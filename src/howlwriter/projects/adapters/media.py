"""Video and audio, processed locally with timestamps.

* Probe: duration and streams (PyAV when present, else ``ffmpeg -i``).
* Audio: decoded to 16 kHz mono and transcribed by faster-whisper on the CPU.
  Segments keep their start and end times and the model's no-speech
  probability. Model weights are downloaded once from the model hub; no
  private media ever leaves the machine.
* Frames: sampled at a fixed interval (bounded count) and read by the local
  OCR engine, so on-screen text -- terminal output, slides, dashboards -- is
  evidence with a timestamp.
* Silence: a video without an audio stream, or whose transcript is empty,
  is reported as such. A transcript is never presented as understanding of a
  video's visual content; frames that were not read are listed.

Results are cached under the project's cache directory by the file's SHA-256,
so a rescan or a resumed session does not re-transcribe an unchanged video.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import subprocess

from howlwriter.projects.adapters import AdapterResult
from howlwriter.projects.resources import governed_run
from howlwriter.voice.identity import privacy

FRAME_INTERVAL_SECONDS = 30
MAX_FRAMES = 40
MAX_TRANSCRIBE_SECONDS = 3 * 3600
SEGMENT_GROUP_SECONDS = 45
WHISPER_MODEL = "base.en"
CPU_THREADS = 4
_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def ffmpeg_exe() -> str | None:
    import shutil

    if shutil.which("ffmpeg"):
        return "ffmpeg"
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def timestamp(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def probe(path: Path) -> dict:
    try:
        import av

        with av.open(str(path)) as container:
            duration = float(container.duration / 1_000_000) if container.duration else 0.0
            return {
                "duration_seconds": round(duration, 2),
                "has_audio": any(s.type == "audio" for s in container.streams),
                "has_video": any(s.type == "video" for s in container.streams),
                "probe": "pyav",
            }
    except ImportError:
        pass
    except Exception as error:
        return {"error": f"unreadable media ({type(error).__name__})"}
    exe = ffmpeg_exe()
    if not exe:
        return {"error": "no media probe available (install ffmpeg or pip install av)"}
    completed = governed_run(
        [exe, "-hide_banner", "-i", str(path)], capture_output=True, text=True, timeout=60
    )
    match = _DURATION.search(completed.stderr)
    if not match:
        return {"error": "unreadable media"}
    h, m, s = match.groups()
    return {
        "duration_seconds": round(int(h) * 3600 + int(m) * 60 + float(s), 2),
        "has_audio": "Audio:" in completed.stderr,
        "has_video": "Video:" in completed.stderr,
        "probe": "ffmpeg",
    }


class Transcriber:
    """faster-whisper in the governed worker; `available` is False when not installed."""

    def __init__(self, model: str = WHISPER_MODEL, worker=None, policy=None) -> None:
        import importlib.util

        self.model_name = model
        self.available = importlib.util.find_spec("faster_whisper") is not None
        self._worker = worker
        self.policy = policy

    @property
    def name(self) -> str:
        return f"faster-whisper-{self.model_name}"

    @property
    def worker(self):
        if self._worker is None:
            from howlwriter.projects.resources import HeavyWorker

            self._worker = HeavyWorker(self.policy)
        return self._worker

    def transcribe(self, audio: Path, *, timeout: float | None = None) -> list[dict]:
        return self.worker.run("transcribe", str(audio), self.model_name, timeout=timeout)

    def close(self) -> None:
        if self._worker is not None:
            self._worker.close()


def _threads(engine) -> int:
    policy = getattr(engine, "policy", None)
    return getattr(policy, "threads", 2) or 2


def _group(segments: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    for segment in segments:
        if groups and segment["start"] - groups[-1][0]["start"] < SEGMENT_GROUP_SECONDS:
            groups[-1].append(segment)
        else:
            groups.append([segment])
    return groups


def extract_media(
    path: Path,
    *,
    sha256: str,
    cache_dir: Path,
    transcriber: Transcriber | None = None,
    ocr=None,
    frames: bool = True,
    kind: str = "video",
) -> AdapterResult:
    info = probe(path)
    if "error" in info:
        return AdapterResult(status="failed", reason=info["error"])
    result = AdapterResult(method="local-media", metadata=dict(info))
    duration = info.get("duration_seconds", 0.0)
    exe = ffmpeg_exe()
    if not exe:
        return AdapterResult(status="unavailable", reason="ffmpeg is not available", metadata=info)
    cache = cache_dir / sha256[:16]
    privacy.ensure_private_dir(cache)
    methods: list[str] = []

    # --- transcript -------------------------------------------------------
    transcript_file = cache / "transcript.json"
    segments: list[dict] | None = None
    if transcript_file.is_file():
        cached = json.loads(transcript_file.read_text(encoding="utf-8"))
        segments = cached.get("segments", [])
        methods.append(cached.get("method", "transcript-cache"))
        result.metadata["transcript_cached"] = True
    elif not info.get("has_audio"):
        result.warnings.append("no audio stream: there is no speech to transcribe")
    elif duration > MAX_TRANSCRIBE_SECONDS:
        result.warnings.append(f"longer than {MAX_TRANSCRIBE_SECONDS // 3600} h; not transcribed")
    else:
        engine = transcriber or Transcriber()
        if not engine.available:
            result.warnings.append(
                "no local speech model installed (pip install 'howlwriter[sources]'); not transcribed"
            )
        else:
            audio = cache / "audio.wav"
            try:
                governed_run(
                    [
                        exe,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-threads",
                        str(_threads(engine)),
                        "-i",
                        str(path),
                        "-vn",
                        "-ac",
                        "1",
                        "-ar",
                        "16000",
                        "-f",
                        "wav",
                        str(audio),
                    ],
                    policy=getattr(engine, "policy", None),
                    check=True,
                    capture_output=True,
                    timeout=max(120, int(duration)),
                )
                budget = getattr(getattr(engine, "policy", None), "media_timeout", None)
                segments = engine.transcribe(audio, timeout=max(budget or 0, duration * 2) or None)
                privacy.write_private_json(transcript_file, {"method": engine.name, "segments": segments})
                methods.append(engine.name)
            except (subprocess.SubprocessError, OSError, RuntimeError) as error:
                result.warnings.append(f"transcription stopped ({type(error).__name__}: {str(error)[:80]})")
            finally:
                audio.unlink(missing_ok=True)
    if segments is not None:
        if not segments:
            result.warnings.append("the audio contains no recognisable speech")
        for group in _group(segments):
            start, end = group[0]["start"], group[-1]["end"]
            uncertain = sum(1 for s in group if s["no_speech_prob"] > 0.5 or s["avg_logprob"] < -1.0)
            result.items.append(
                {
                    "kind": "transcript",
                    "source_type": kind,
                    "method": methods[-1],
                    "status": "extracted_from_source",
                    "location": f"{timestamp(start)}–{timestamp(end)}",
                    "locator": {"start": start, "end": end},
                    "excerpt": " ".join(s["text"] for s in group)[:900],
                    "observation": {"segments": group},
                    "confidence": "low" if uncertain > len(group) / 2 else "medium",
                    "limitations": ["automatic speech recognition; names and numbers may be misheard"]
                    + ([f"{uncertain} uncertain segment(s)"] if uncertain else []),
                }
            )
        result.text += "\n".join(s["text"] for s in segments)

    # --- frames -----------------------------------------------------------
    if frames and info.get("has_video") and kind == "video":
        frame_dir = cache / "frames"
        privacy.ensure_private_dir(frame_dir)
        interval = max(FRAME_INTERVAL_SECONDS, duration / MAX_FRAMES if duration else FRAME_INTERVAL_SECONDS)
        if not any(frame_dir.glob("*.png")):
            try:
                governed_run(
                    [
                        exe,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-threads",
                        "2",
                        "-i",
                        str(path),
                        "-vf",
                        f"fps=1/{interval:.3f},scale='min(1280,iw)':-2",
                        "-frames:v",
                        str(MAX_FRAMES),
                        str(frame_dir / "frame-%04d.png"),
                    ],
                    check=True,
                    capture_output=True,
                    timeout=max(300, int(duration)),
                )
            except (subprocess.SubprocessError, OSError) as error:
                result.warnings.append(f"frame extraction failed ({type(error).__name__})")
        frame_files = sorted(frame_dir.glob("frame-*.png"))
        result.metadata["frames_sampled"] = len(frame_files)
        result.metadata["frame_interval_seconds"] = round(interval, 1)
        if frame_files and (ocr is None or not ocr.available):
            result.warnings.append(f"{len(frame_files)} frames sampled but not read (no OCR engine)")
        unread = 0
        for index, frame in enumerate(frame_files):
            at = index * interval
            if ocr is None or not ocr.available:
                unread += 1
                continue
            cached = frame.with_suffix(".ocr.json")
            if cached.is_file():
                lines = json.loads(cached.read_text(encoding="utf-8"))
            else:
                try:
                    lines = ocr.read(frame)
                except Exception:
                    unread += 1
                    continue
                privacy.write_private_json(cached, lines)
            certain = [line for line in lines if not line["uncertain"]]
            if len(certain) < 3:
                unread += 1
                continue
            result.items.append(
                {
                    "kind": "frame",
                    "source_type": kind,
                    "method": f"ffmpeg-frame+{ocr.name}",
                    "status": "extracted_from_source",
                    "location": f"frame at {timestamp(at)}",
                    "locator": {"at": round(at, 2), "frame_file": frame.name},
                    "excerpt": " ".join(line["text"] for line in certain)[:900],
                    "observation": {"lines": lines[:150]},
                    "confidence": "medium",
                    "limitations": [
                        "on-screen text read by OCR from one sampled frame; timing is approximate "
                        f"to the {interval:.0f}-second sampling interval"
                    ],
                }
            )
        if frame_files:
            methods.append(f"ffmpeg-frames+{getattr(ocr, 'name', 'none')}")
            if unread:
                result.warnings.append(
                    f"{unread} of {len(frame_files)} sampled frames had no readable text; "
                    "their visual content "
                    "is not described"
                )
    if not result.items:
        result.status = "partial"
        result.reason = "nothing readable was extracted (see warnings)"
    elif kind == "video" and segments is None:
        result.status = "partial"
    result.method = "+".join(dict.fromkeys(methods)) or "local-media"
    return result
