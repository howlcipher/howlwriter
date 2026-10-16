"""Packet captures, analysed offline and read-only.

TShark is the primary engine (from PATH, or the Wireshark flatpak run with a
read-only grant on the capture's folder only). Pure-Python dpkt is the
fallback when TShark is absent; it produces a smaller set of findings and
says so.

What is extracted, each with frame numbers:

* capture summary: frames, bytes, duration, protocol distribution;
* conversations and TCP streams;
* TLS handshakes: client and server hellos, SNI, offered and negotiated
  versions, selected cipher suite, whether certificates are visible;
* DNS queries and answers; HTTP requests (query strings redacted);
* payload visibility per stream: byte entropy and printable share, so
  "encrypted payload" and "cleartext payload" are measured, not assumed.

What is never claimed: decrypted content. Without key material the payload
of a TLS stream is reported as not observable, however the handshake looks.

Privacy: captures can hold credentials and tokens. Payload bytes are never
stored -- only entropy and printable share -- and URL query strings are
dropped. Raw captures are never uploaded anywhere.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import math
from pathlib import Path
import shutil
import subprocess

from howlwriter.projects.adapters import AdapterResult
from howlwriter.projects.resources import governed_run

MAX_PAYLOAD_FRAMES = 20_000
TIMEOUT_SECONDS = 180
_STANDARD_TLS_PORTS = {443, 8443, 465, 993, 995, 636, 853, 5061}

TLS_VERSIONS = {
    "0x0300": "SSL 3.0",
    "0x0301": "TLS 1.0",
    "0x0302": "TLS 1.1",
    "0x0303": "TLS 1.2",
    "0x0304": "TLS 1.3",
}


class TShark:
    """Locates TShark and runs it without a shell, read-only."""

    def __init__(self, policy=None) -> None:
        self.policy = policy
        self.command: list[str] | None = None
        self.flatpak = False
        if shutil.which("tshark"):
            self.command = ["tshark"]
        elif shutil.which("flatpak"):
            try:
                probe = subprocess.run(
                    ["flatpak", "info", "org.wireshark.Wireshark"],
                    capture_output=True,
                    timeout=20,
                )
                if probe.returncode == 0:
                    self.command = ["flatpak", "run", "--command=tshark", "org.wireshark.Wireshark"]
                    self.flatpak = True
            except (OSError, subprocess.SubprocessError):
                pass
        self.version = ""
        if self.command:
            try:
                out = subprocess.run([*self.command, "--version"], capture_output=True, text=True, timeout=30)
                self.version = (
                    (out.stdout.splitlines() or [""])[0].replace("TShark (Wireshark) ", "").split(" ")[0]
                )
            except (OSError, subprocess.SubprocessError):
                self.command = None

    @property
    def available(self) -> bool:
        return self.command is not None

    def run(self, capture: Path, args: list[str]) -> list[list[str]]:
        command = list(self.command or [])
        if self.flatpak:
            # Grant the sandbox read-only access to this capture's folder only.
            command.insert(2, f"--filesystem={capture.parent}:ro")
        command += ["-r", str(capture), "-n", *args]
        completed = governed_run(
            command, policy=self.policy, capture_output=True, text=True, timeout=TIMEOUT_SECONDS
        )
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or "tshark failed").strip().splitlines()[-1][:200])
        return [line.split("\t") for line in completed.stdout.splitlines() if line.strip()]


def _fields(*names: str) -> list[str]:
    out = ["-T", "fields", "-E", "separator=/t", "-E", "occurrence=a", "-E", "aggregator=,"]
    for name in names:
        out += ["-e", name]
    return out


def _entropy(data: bytes) -> float:
    if not data:
        return 0.0
    counts = Counter(data)
    total = len(data)
    return -sum((c / total) * math.log2(c / total) for c in counts.values())


def _visibility(payload: bytes) -> tuple[float, float, str]:
    entropy = _entropy(payload)
    printable = (
        sum(1 for b in payload if 32 <= b < 127 or b in (9, 10, 13)) / len(payload) if payload else 0.0
    )
    if not payload:
        label = "no payload"
    elif printable >= 0.85 and entropy < 6.0:
        label = "cleartext-like payload"
    elif entropy >= 7.2:
        label = "high-entropy payload (encrypted or compressed)"
    else:
        label = "binary or mixed payload"
    return round(entropy, 3), round(printable, 3), label


def _frames(frames: list[int]) -> str:
    frames = sorted(set(frames))
    if not frames:
        return ""
    return f"frame {frames[0]}" if len(frames) == 1 else f"frames {frames[0]}–{frames[-1]}"


def _redact_uri(uri: str) -> str:
    return uri.split("?", 1)[0] + ("?[query redacted]" if "?" in uri else "")


def analyze(path: Path, *, tshark: TShark | None = None) -> AdapterResult:
    engine = tshark or TShark()
    if engine.available:
        try:
            return _analyze_tshark(path, engine)
        except (RuntimeError, OSError, subprocess.SubprocessError) as error:
            fallback = _analyze_dpkt(path)
            fallback.warnings.insert(0, f"TShark failed ({error}); fell back to dpkt")
            return fallback
    return _analyze_dpkt(path)


def _item(
    kind: str,
    method: str,
    location: str,
    locator: dict,
    observation: dict,
    excerpt: str,
    limitations: list[str] | None = None,
    status: str = "directly_observed",
) -> dict:
    return {
        "kind": kind,
        "source_type": "pcap",
        "method": method,
        "status": status,
        "location": location,
        "locator": locator,
        "observation": observation,
        "excerpt": excerpt,
        "confidence": "high",
        "limitations": limitations or [],
    }


def _analyze_tshark(path: Path, engine: TShark) -> AdapterResult:
    method = f"tshark-{engine.version or 'unknown'}"
    result = AdapterResult(method=method)
    rows = engine.run(
        path,
        _fields(
            "frame.number",
            "frame.time_relative",
            "frame.len",
            "ip.src",
            "ip.dst",
            "ipv6.src",
            "ipv6.dst",
            "tcp.srcport",
            "tcp.dstport",
            "udp.srcport",
            "udp.dstport",
            "tcp.stream",
            "_ws.col.Protocol",
            "tcp.len",
        ),
    )
    if not rows:
        return AdapterResult(status="failed", reason="capture contains no readable frames", method=method)
    protocols: Counter = Counter()
    conversations: dict[tuple, dict] = {}
    streams: dict[str, list[int]] = defaultdict(list)
    candidate_ports: Counter = Counter()
    total_bytes = 0
    last_time = 0.0
    for row in rows:
        row += [""] * (14 - len(row))
        number = int(row[0])
        total_bytes += int(row[2] or 0)
        last_time = max(last_time, float(row[1] or 0))
        protocol = row[12] or "?"
        protocols[protocol] += 1
        src = row[3] or row[5]
        dst = row[4] or row[6]
        sport = row[7] or row[9]
        dport = row[8] or row[10]
        transport = "tcp" if row[7] else "udp" if row[9] else "other"
        key = (src, dst, dport, transport) if src else ("?", "?", "", transport)
        entry = conversations.setdefault(key, {"frames": [], "bytes": 0, "src_port": sport})
        entry["frames"].append(number)
        entry["bytes"] += int(row[2] or 0)
        if row[11]:
            streams[row[11]].append(number)
        if protocol in ("TCP", "Data", "Unknown") and (row[13] or "0") not in ("", "0") and dport:
            if int(dport) not in _STANDARD_TLS_PORTS:
                candidate_ports[int(dport)] += 1
    result.metadata = {
        "frames": len(rows),
        "bytes": total_bytes,
        "duration_seconds": round(last_time, 3),
        "protocols": dict(protocols.most_common()),
        "tcp_streams": len(streams),
        "engine": method,
    }
    result.items.append(
        _item(
            "packet_summary",
            method,
            f"frames 1–{len(rows)}",
            {"frames": [1, len(rows)]},
            dict(result.metadata),
            f"{len(rows)} frames, {total_bytes} bytes over {last_time:.3f} s; protocols: "
            + ", ".join(f"{k} {v}" for k, v in protocols.most_common(6)),
        )
    )
    for (src, dst, dport, transport), info in sorted(
        conversations.items(), key=lambda kv: -len(kv[1]["frames"])
    )[:10]:
        result.items.append(
            _item(
                "conversation",
                method,
                _frames(info["frames"]),
                {"frames": [min(info["frames"]), max(info["frames"])]},
                {
                    "src": src,
                    "dst": dst,
                    "dst_port": dport,
                    "src_port": info["src_port"],
                    "transport": transport,
                    "frames": len(info["frames"]),
                    "bytes": info["bytes"],
                },
                f"{src} → {dst}:{dport}/{transport}: {len(info['frames'])} frames, {info['bytes']} bytes",
            )
        )

    # TLS, decoding likely non-standard TLS ports explicitly.
    decode = []
    for port, _count in candidate_ports.most_common(3):
        decode += ["-d", f"tcp.port=={port},tls"]
    tls_rows = engine.run(
        path,
        decode
        + ["-Y", "tls.handshake.type"]
        + _fields(
            "frame.number",
            "tcp.stream",
            "tls.handshake.type",
            "tls.handshake.extensions_server_name",
            "tls.handshake.version",
            "tls.handshake.extensions.supported_version",
            "tls.handshake.ciphersuite",
            "tcp.dstport",
        ),
    )
    by_stream: dict[str, dict] = defaultdict(lambda: {"frames": [], "types": set()})
    for row in tls_rows:
        row += [""] * (8 - len(row))
        number, stream, types = int(row[0]), row[1], set(row[2].split(",")) if row[2] else set()
        info = by_stream[stream]
        info["frames"].append(number)
        info["types"] |= types
        info["port"] = row[7] or info.get("port", "")
        if "1" in types:
            info["client_hello_frame"] = number
            info["sni"] = row[3] or info.get("sni", "")
            offered = [TLS_VERSIONS.get(v, v) for v in row[5].split(",") if v]
            info["offered_versions"] = offered or [TLS_VERSIONS.get(row[4], row[4])]
        if "2" in types:
            info["server_hello_frame"] = number
            negotiated = row[5].split(",")[-1] if row[5] else row[4]
            info["negotiated_version"] = TLS_VERSIONS.get(negotiated, negotiated)
            info["cipher_suite"] = row[6].split(",")[0] if row[6] else ""
        if "11" in types:
            info["certificate_frame"] = number
    decoded_ports = [p for p, _ in candidate_ports.most_common(3)]
    for stream, info in sorted(by_stream.items(), key=lambda kv: min(kv[1]["frames"])):
        limitations = ["handshake metadata is visible; application data is encrypted and was not decrypted"]
        if info.get("port") and int(info["port"] or 0) in decoded_ports:
            limitations.append(f"decoded as TLS on non-standard port {info['port']} (tshark decode-as)")
        version = info.get("negotiated_version", "")
        cert = (
            "certificate visible in cleartext"
            if "certificate_frame" in info
            else (
                "certificate not visible (encrypted in TLS 1.3)"
                if version == "TLS 1.3"
                else "no certificate frame seen"
            )
        )
        result.items.append(
            _item(
                "tls_handshake",
                method,
                _frames(info["frames"]),
                {"frames": [min(info["frames"]), max(info["frames"])], "tcp_stream": stream},
                {
                    "tcp_stream": stream,
                    "sni": info.get("sni", ""),
                    "offered_versions": info.get("offered_versions", []),
                    "negotiated_version": version,
                    "cipher_suite": info.get("cipher_suite", ""),
                    "client_hello_frame": info.get("client_hello_frame"),
                    "server_hello_frame": info.get("server_hello_frame"),
                    "certificate": cert,
                    "port": info.get("port", ""),
                },
                f"TCP stream {stream}: TLS handshake"
                + (f", SNI {info['sni']}" if info.get("sni") else ", no SNI")
                + (f", negotiated {version}" if version else "")
                + (f", cipher {info['cipher_suite']}" if info.get("cipher_suite") else "")
                + f"; {cert}",
                limitations,
            )
        )

    dns_rows = engine.run(
        path,
        ["-Y", "dns"] + _fields("frame.number", "dns.flags.response", "dns.qry.name", "dns.a", "dns.aaaa"),
    )
    names: dict[str, dict] = defaultdict(lambda: {"frames": [], "answers": set()})
    for row in dns_rows:
        row += [""] * (5 - len(row))
        for name in [n for n in row[2].split(",") if n]:
            names[name]["frames"].append(int(row[0]))
            names[name]["answers"] |= {a for a in (row[3] + "," + row[4]).split(",") if a}
    for name, info in sorted(names.items()):
        result.items.append(
            _item(
                "dns",
                method,
                _frames(info["frames"]),
                {"frames": [min(info["frames"]), max(info["frames"])]},
                {"query": name, "answers": sorted(info["answers"])[:20], "frames": len(info["frames"])},
                f"DNS {name}"
                + (
                    f" → {', '.join(sorted(info['answers'])[:5])}" if info["answers"] else " (no answer seen)"
                ),
            )
        )

    http_rows = engine.run(
        path,
        decode
        + ["-Y", "http.request"]
        + _fields("frame.number", "http.host", "http.request.method", "http.request.uri"),
    )
    for row in http_rows[:200]:
        row += [""] * (4 - len(row))
        result.items.append(
            _item(
                "http_request",
                method,
                f"frame {row[0]}",
                {"frames": [int(row[0]), int(row[0])]},
                {"host": row[1], "method": row[2], "uri": _redact_uri(row[3])},
                f"HTTP {row[2]} {row[1]}{_redact_uri(row[3])}",
                ["cleartext HTTP request visible on the wire"],
            )
        )

    payload_rows = engine.run(
        path,
        ["-Y", "tcp.len > 0", "-c", str(MAX_PAYLOAD_FRAMES * 4)]
        + _fields("frame.number", "tcp.stream", "tcp.payload"),
    )
    per_stream: dict[str, dict] = defaultdict(lambda: {"frames": [], "data": bytearray()})
    for row in payload_rows[:MAX_PAYLOAD_FRAMES]:
        row += [""] * (3 - len(row))
        try:
            chunk = bytes.fromhex(row[2].replace(":", ""))
        except ValueError:
            continue
        info = per_stream[row[1]]
        info["frames"].append(int(row[0]))
        if len(info["data"]) < 1_000_000:
            info["data"] += chunk
    tls_streams = set(by_stream)
    for stream, info in sorted(per_stream.items(), key=lambda kv: min(kv[1]["frames"])):
        entropy, printable, label = _visibility(bytes(info["data"]))
        info["data"] = bytearray()  # payload bytes are never kept
        result.items.append(
            _item(
                "payload_visibility",
                method,
                _frames(info["frames"]),
                {"frames": [min(info["frames"]), max(info["frames"])], "tcp_stream": stream},
                {
                    "tcp_stream": stream,
                    "payload_frames": len(info["frames"]),
                    "entropy_bits_per_byte": entropy,
                    "printable_share": printable,
                    "assessment": label,
                    "tls_handshake_seen": stream in tls_streams,
                },
                f"TCP stream {stream}: {label} (entropy {entropy} bits/byte, printable {printable:.0%})",
                ["measured from payload bytes; the bytes themselves are not stored"],
                status="derived_by_calculation",
            )
        )
    return result


def _analyze_dpkt(path: Path) -> AdapterResult:
    try:
        import dpkt
    except ImportError:
        return AdapterResult(
            status="unavailable",
            reason="neither TShark nor dpkt is available (install Wireshark/TShark or pip install dpkt)",
        )
    method = f"dpkt-{dpkt.__version__}"
    result = AdapterResult(method=method)
    result.warnings.append("dpkt fallback: protocol dissection is limited compared with TShark")
    try:
        with open(path, "rb") as handle:
            try:
                reader = dpkt.pcap.Reader(handle)
            except ValueError:
                handle.seek(0)
                reader = dpkt.pcapng.Reader(handle)
            frames = 0
            total = 0
            first = last = None
            transports: Counter = Counter()
            conversations: dict[tuple, list[int]] = defaultdict(list)
            dns_names: dict[str, list[int]] = defaultdict(list)
            for ts, buf in reader:
                frames += 1
                total += len(buf)
                first = ts if first is None else first
                last = ts
                try:
                    eth = dpkt.ethernet.Ethernet(buf)
                    ip = eth.data
                    if not isinstance(ip, (dpkt.ip.IP, dpkt.ip6.IP6)):
                        transports["non-IP"] += 1
                        continue
                    seg = ip.data
                    src = _addr(ip.src)
                    dst = _addr(ip.dst)
                    if isinstance(seg, dpkt.tcp.TCP):
                        transports["TCP"] += 1
                        conversations[(src, dst, seg.dport, "tcp")].append(frames)
                    elif isinstance(seg, dpkt.udp.UDP):
                        transports["UDP"] += 1
                        conversations[(src, dst, seg.dport, "udp")].append(frames)
                        if 53 in (seg.sport, seg.dport):
                            try:
                                for q in dpkt.dns.DNS(seg.data).qd:
                                    dns_names[q.name].append(frames)
                            except Exception:
                                pass
                    else:
                        transports["other IP"] += 1
                except Exception:
                    transports["undecoded"] += 1
    except (ValueError, OSError, dpkt.dpkt.NeedData) as error:
        return AdapterResult(
            status="failed", reason=f"not a readable capture ({type(error).__name__})", method=method
        )
    if not frames:
        return AdapterResult(status="failed", reason="capture contains no frames", method=method)
    duration = round((last or 0) - (first or 0), 3)
    result.metadata = {
        "frames": frames,
        "bytes": total,
        "duration_seconds": duration,
        "protocols": dict(transports),
        "engine": method,
    }
    result.items.append(
        _item(
            "packet_summary",
            method,
            f"frames 1–{frames}",
            {"frames": [1, frames]},
            dict(result.metadata),
            f"{frames} frames, {total} bytes over {duration} s; "
            + ", ".join(f"{k} {v}" for k, v in transports.items()),
        )
    )
    for (src, dst, port, transport), numbers in sorted(conversations.items(), key=lambda kv: -len(kv[1]))[
        :10
    ]:
        result.items.append(
            _item(
                "conversation",
                method,
                _frames(numbers),
                {"frames": [min(numbers), max(numbers)]},
                {
                    "src": src,
                    "dst": dst,
                    "dst_port": str(port),
                    "transport": transport,
                    "frames": len(numbers),
                },
                f"{src} → {dst}:{port}/{transport}: {len(numbers)} frames",
            )
        )
    for name, numbers in sorted(dns_names.items()):
        result.items.append(
            _item(
                "dns",
                method,
                _frames(numbers),
                {"frames": [min(numbers), max(numbers)]},
                {"query": name, "frames": len(numbers)},
                f"DNS query {name}",
            )
        )
    return result


def _addr(raw: bytes) -> str:
    import socket

    try:
        return socket.inet_ntop(socket.AF_INET6 if len(raw) == 16 else socket.AF_INET, raw)
    except (OSError, ValueError):
        return "?"


def compare(before: list[dict], after: list[dict], *, before_name: str, after_name: str) -> list[dict]:
    """Deterministic differences between two captures' findings."""

    def summary(items):
        return next((i["observation"] for i in items if i["kind"] == "packet_summary"), {})

    def tls(items):
        return [i["observation"] for i in items if i["kind"] == "tls_handshake"]

    def visibility(items):
        return Counter(i["observation"]["assessment"] for i in items if i["kind"] == "payload_visibility")

    def dns(items):
        return {i["observation"]["query"] for i in items if i["kind"] == "dns"}

    a, b = summary(before), summary(after)
    findings = []
    protocols_a, protocols_b = a.get("protocols", {}), b.get("protocols", {})
    changed = {
        p: (protocols_a.get(p, 0), protocols_b.get(p, 0))
        for p in sorted(set(protocols_a) | set(protocols_b))
        if protocols_a.get(p, 0) != protocols_b.get(p, 0)
    }
    findings.append(
        {
            "aspect": "frames and protocols",
            "before": {"frames": a.get("frames"), "protocols": protocols_a},
            "after": {"frames": b.get("frames"), "protocols": protocols_b},
            "changed_protocols": changed,
            "statement": f"{before_name}: {a.get('frames')} frames; {after_name}: {b.get('frames')} frames. "
            + (
                "Protocol counts changed: " + "; ".join(f"{p} {x}→{y}" for p, (x, y) in changed.items())
                if changed
                else "Protocol counts are identical."
            ),
        }
    )
    tls_a, tls_b = tls(before), tls(after)
    versions_a = sorted({t["negotiated_version"] for t in tls_a if t.get("negotiated_version")})
    versions_b = sorted({t["negotiated_version"] for t in tls_b if t.get("negotiated_version")})
    findings.append(
        {
            "aspect": "TLS",
            "before": {
                "handshakes": len(tls_a),
                "versions": versions_a,
                "sni": sorted({t["sni"] for t in tls_a if t["sni"]}),
            },
            "after": {
                "handshakes": len(tls_b),
                "versions": versions_b,
                "sni": sorted({t["sni"] for t in tls_b if t["sni"]}),
            },
            "statement": f"TLS handshakes: {len(tls_a)} in {before_name} "
            f"({', '.join(versions_a) or 'none'}), "
            f"{len(tls_b)} in {after_name} ({', '.join(versions_b) or 'none'}).",
        }
    )
    va, vb = visibility(before), visibility(after)
    findings.append(
        {
            "aspect": "payload visibility",
            "before": dict(va),
            "after": dict(vb),
            "statement": f"Payload streams in {before_name}: "
            + (", ".join(f"{k} ×{v}" for k, v in va.items()) or "none")
            + f"; in {after_name}: "
            + (", ".join(f"{k} ×{v}" for k, v in vb.items()) or "none")
            + ".",
        }
    )
    da, db = dns(before), dns(after)
    if da or db:
        findings.append(
            {
                "aspect": "DNS",
                "only_before": sorted(da - db),
                "only_after": sorted(db - da),
                "statement": f"DNS names only in {before_name}: {len(da - db)}; "
                f"only in {after_name}: {len(db - da)}.",
            }
        )
    return findings
