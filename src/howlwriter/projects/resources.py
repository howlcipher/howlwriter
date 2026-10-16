"""Keep heavy extraction from taking over the machine.

OCR, speech recognition, and frame decoding are the only expensive work in a
project scan. Left alone, ONNX Runtime and CTranslate2 start one thread per
core and spin; a pathological image can then pin the CPU indefinitely. So
heavy work never runs in the scanning process. It runs in one worker
process that is

* scheduled ``SCHED_IDLE`` (Linux) and ``nice 19`` -- it only gets CPU time
  nothing else wants, so the desktop and other work stay responsive;
* capped at ``threads`` compute threads (2 by default) through the usual
  environment variables and the engines' own options;
* memory-limited (``RLIMIT_AS``);
* given a wall-clock deadline per job. A job past its deadline is killed
  with the worker, recorded as ``timed out``, and a fresh worker starts for
  the next job -- one bad file costs one deadline, never the whole scan.

Before each job the governor also checks the load average and, while the
machine is busy (load above ``busy_load`` per core), waits in short sleeps
up to ``max_wait`` seconds before proceeding.

Settings come from the project's ``resources`` block (``project.json``) or
the defaults below; the CLI exposes ``--threads`` and ``--job-timeout``.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import os
import time
from typing import Any, Callable

DEFAULT_THREADS = 2
DEFAULT_JOB_TIMEOUT = 90.0  # seconds per image / frame batch
DEFAULT_MEDIA_TIMEOUT = 3600.0  # seconds per transcription
DEFAULT_MEMORY_MB = 4096
BUSY_LOAD_PER_CORE = 0.8
MAX_WAIT_SECONDS = 120.0
OCR_MAX_SIDE = 1600


@dataclass
class ResourcePolicy:
    threads: int = DEFAULT_THREADS
    job_timeout: float = DEFAULT_JOB_TIMEOUT
    media_timeout: float = DEFAULT_MEDIA_TIMEOUT
    memory_mb: int = DEFAULT_MEMORY_MB
    idle_priority: bool = True
    busy_load: float = BUSY_LOAD_PER_CORE
    max_wait: float = MAX_WAIT_SECONDS

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> "ResourcePolicy":
        data = data or {}
        fields = cls.__dataclass_fields__
        policy = cls(**{k: data[k] for k in data if k in fields})
        policy.threads = max(1, min(int(policy.threads), os.cpu_count() or 1))
        return policy


def thread_env(threads: int) -> dict[str, str]:
    value = str(max(1, threads))
    return {
        name: value
        for name in (
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "NUMEXPR_NUM_THREADS",
            "CT2_INTER_THREADS",
            "ORT_NUM_THREADS",
        )
    }


def _lower_priority(policy: ResourcePolicy) -> None:
    if not policy.idle_priority:
        return
    try:
        os.nice(19)
    except OSError:
        pass
    sched_idle = getattr(os, "SCHED_IDLE", None)
    if sched_idle is not None:
        try:
            os.sched_setscheduler(0, sched_idle, os.sched_param(0))
        except OSError:
            pass


def _limit_memory(policy: ResourcePolicy) -> None:
    try:
        import resource

        limit = int(policy.memory_mb) * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, ValueError, OSError):
        pass


def _worker_main() -> int:
    """Worker loop: one JSON request per stdin line, one JSON reply per stdout line."""
    import json
    import sys

    policy = ResourcePolicy.from_dict(json.loads(os.environ.get("HOWLWRITER_WORKER_POLICY", "{}")))
    _lower_priority(policy)
    _limit_memory(policy)
    state: dict[str, Any] = {}
    out = sys.stdout
    sys.stdout = sys.stderr  # stray library prints must not corrupt the protocol
    for line in sys.stdin:
        if not line.strip():
            continue
        name, args = json.loads(line)
        try:
            reply = ["ok", JOBS[name](state, policy, *args)]
        except MemoryError:
            reply = ["error", "MemoryError: over the worker memory limit"]
        except Exception as error:  # reported to the parent, never raised there
            reply = ["error", f"{type(error).__name__}: {str(error)[:200]}"]
        out.write(json.dumps(reply) + "\n")
        out.flush()
    return 0


# --- jobs (run inside the worker) -------------------------------------------


def _job_ocr(state: dict, policy: ResourcePolicy, image_path: str) -> list[dict]:
    from howlwriter.projects.adapters.images import LOW_CONFIDENCE

    engine = state.get("ocr")
    if engine is None:
        from rapidocr_onnxruntime import RapidOCR

        engine = RapidOCR(intra_op_num_threads=policy.threads, inter_op_num_threads=1)
        state["ocr"] = engine
    source = image_path
    scale = 1.0
    try:
        from PIL import Image

        with Image.open(image_path) as image:
            width, height = image.size
            longest = max(width, height)
            if longest > OCR_MAX_SIDE:
                scale = OCR_MAX_SIDE / longest
                import numpy as np

                source = np.asarray(image.convert("RGB").resize((int(width * scale), int(height * scale))))
    except ImportError:
        pass
    result, _ = engine(source)
    lines = []
    for box, text, score in result or []:
        text = str(text).strip()
        if not text:
            continue
        xs = [float(p[0]) / scale for p in box]
        ys = [float(p[1]) / scale for p in box]
        lines.append(
            {
                "text": text,
                "score": round(float(score), 3),
                "box": [round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))],
                "uncertain": float(score) < LOW_CONFIDENCE,
            }
        )
    return lines


def _read_wav(path: str):
    """16-bit PCM WAV -> float32 samples in [-1, 1]."""
    import wave

    import numpy as np

    with wave.open(path, "rb") as handle:
        if handle.getsampwidth() != 2:
            raise ValueError("expected 16-bit PCM audio")
        frames = handle.readframes(handle.getnframes())
        channels = handle.getnchannels()
    samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    return samples.reshape(-1, channels).mean(axis=1) if channels > 1 else samples


def _job_transcribe(state: dict, policy: ResourcePolicy, audio_path: str, model: str) -> list[dict]:
    key = f"whisper:{model}"
    engine = state.get(key)
    if engine is None:
        from faster_whisper import WhisperModel

        engine = WhisperModel(
            model, device="cpu", compute_type="int8", cpu_threads=policy.threads, num_workers=1
        )
        state[key] = engine
    # Pass decoded samples, not a path: the audio is already 16 kHz mono PCM from ffmpeg, and
    # faster-whisper's own file decoding depends on a PyAV API that changes between releases.
    segments, _info = engine.transcribe(_read_wav(audio_path), vad_filter=True, beam_size=1)
    out = []
    for segment in segments:
        text = segment.text.strip()
        if text:
            out.append(
                {
                    "start": round(segment.start, 2),
                    "end": round(segment.end, 2),
                    "text": text,
                    "no_speech_prob": round(float(segment.no_speech_prob), 3),
                    "avg_logprob": round(float(segment.avg_logprob), 3),
                }
            )
    return out


def _job_sleep(state: dict, policy: ResourcePolicy, seconds: float) -> float:  # for tests
    time.sleep(seconds)
    return seconds


JOBS: dict[str, Callable] = {"ocr": _job_ocr, "transcribe": _job_transcribe, "sleep": _job_sleep}


class JobTimeout(RuntimeError):
    pass


class HeavyWorker:
    """One governed worker process, restarted after a timeout or crash."""

    def __init__(self, policy: ResourcePolicy | None = None) -> None:
        self.policy = policy or ResourcePolicy()
        self._process = None
        self._killed = False
        self.stats = {"jobs": 0, "timeouts": 0, "errors": 0, "restarts": 0, "waited_seconds": 0.0}

    def _start(self) -> None:
        import json
        import subprocess
        import sys

        env = dict(os.environ)
        env.update(thread_env(self.policy.threads))
        env["HOWLWRITER_WORKER_POLICY"] = json.dumps(self.policy.to_dict())
        self._process = subprocess.Popen(
            [sys.executable, "-I", "-m", "howlwriter.projects.resources", "--worker"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            text=True,
            bufsize=1,
            close_fds=True,
        )

    def _stop(self, kill: bool = False) -> None:
        if self._process is None:
            return
        process, self._process = self._process, None
        self._killed = kill
        try:
            if kill:
                process.kill()
            else:
                process.stdin.close()
            process.wait(timeout=5)
        except Exception:
            process.kill()
            try:
                process.wait(timeout=5)
            except Exception:
                pass

    def close(self) -> None:
        self._stop()

    def wait_for_quiet(self) -> float:
        """Sleep while the machine is busy (bounded). Returns seconds waited."""
        try:
            cores = os.cpu_count() or 1
            waited = 0.0
            while os.getloadavg()[0] > self.policy.busy_load * cores and waited < self.policy.max_wait:
                time.sleep(2.0)
                waited += 2.0
        except (OSError, AttributeError):
            return 0.0
        self.stats["waited_seconds"] += waited
        return waited

    def run(self, name: str, *args, timeout: float | None = None):
        import json
        import select

        if self._process is None or self._process.poll() is not None:
            if self._process is not None or self._killed:
                self.stats["restarts"] += 1
            self._killed = False
            self._start()
        self.wait_for_quiet()
        deadline = timeout or self.policy.job_timeout
        self.stats["jobs"] += 1
        try:
            self._process.stdin.write(json.dumps([name, list(args)]) + "\n")
            self._process.stdin.flush()
        except (OSError, ValueError):
            self.stats["errors"] += 1
            self._stop(kill=True)
            raise RuntimeError(f"{name} worker is not accepting jobs")
        ready, _, _ = select.select([self._process.stdout], [], [], deadline)
        if not ready:
            self.stats["timeouts"] += 1
            self._stop(kill=True)
            raise JobTimeout(f"{name} exceeded {deadline:.0f} s and was stopped")
        line = self._process.stdout.readline()
        if not line:
            self.stats["errors"] += 1
            self._stop(kill=True)
            raise RuntimeError(f"{name} worker exited unexpectedly (possibly the memory limit)")
        status, payload = json.loads(line)
        if status != "ok":
            self.stats["errors"] += 1
            raise RuntimeError(payload)
        return payload


if __name__ == "__main__":
    import sys

    if "--worker" in sys.argv:
        raise SystemExit(_worker_main())


def governed_run(command: list[str], *, policy: ResourcePolicy | None = None, timeout: float, **kwargs):
    """subprocess.run for external tools (ffmpeg, pdftoppm, tshark) under the same policy."""
    import subprocess

    policy = policy or ResourcePolicy()
    env = dict(kwargs.pop("env", None) or os.environ)
    env.update(thread_env(policy.threads))

    def _prepare() -> None:
        _lower_priority(policy)

    return subprocess.run(command, env=env, timeout=timeout, preexec_fn=_prepare, **kwargs)
