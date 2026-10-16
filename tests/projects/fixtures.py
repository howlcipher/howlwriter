"""Synthetic project materials. Nothing here comes from a real person's files."""

from __future__ import annotations

import os
from pathlib import Path
import random
import struct
import zipfile
import zlib

# --- PDF -----------------------------------------------------------------------


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(path: Path, pages: list[str | None], title: str = "") -> Path:
    """A valid PDF: one page per item; text pages use Helvetica, None makes an image-only page."""
    objects: list[bytes] = []

    def add(body: bytes) -> int:
        objects.append(body)
        return len(objects)

    font = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    pixels = bytes([200, 30, 30] * 16)
    image = add(
        b"<< /Type /XObject /Subtype /Image /Width 4 /Height 4 /ColorSpace /DeviceRGB "
        b"/BitsPerComponent 8 /Length %d >>\nstream\n" % len(pixels) + pixels + b"\nendstream"
    )
    page_ids = []
    pages_id_placeholder = len(objects) + 1 + 2 * len(pages)  # assigned after pages
    for content in pages:
        if content is None:
            stream = b"q 200 0 0 200 100 400 cm /Im1 Do Q"
            resources = b"<< /XObject << /Im1 %d 0 R >> >>" % image
        else:
            lines = content.split("\n")
            ops = [b"BT /F1 11 Tf 50 760 Td 14 TL"]
            for line in lines:
                ops.append(b"(" + _pdf_escape(line).encode("latin-1") + b") Tj T*")
            ops.append(b"ET")
            stream = b"\n".join(ops)
            resources = b"<< /Font << /F1 %d 0 R >> >>" % font
        content_id = add(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        page_ids.append(
            add(
                b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] /Resources " % pages_id_placeholder
                + resources
                + b" /Contents %d 0 R >>" % content_id
            )
        )
    kids = b" ".join(b"%d 0 R" % p for p in page_ids)
    pages_id = add(b"<< /Type /Pages /Kids [" + kids + b"] /Count %d >>" % len(page_ids))
    assert pages_id == pages_id_placeholder
    info = add(b"<< /Title (" + _pdf_escape(title).encode("latin-1") + b") >>")
    catalog = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        catalog,
        info,
        xref,
    )
    path.write_bytes(bytes(out))
    return path


# --- DOCX ----------------------------------------------------------------------


def make_docx(path: Path, blocks: list[tuple[str, str]]) -> Path:
    """blocks: (style, text) where style is '' or 'Heading1'/'Heading2'."""

    def para(style: str, text: str) -> str:
        ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
        return f'<w:p>{ppr}<w:r><w:t xml:space="preserve">{text}</w:t></w:r></w:p>'

    body = "".join(para(s, t) for s, t in blocks)
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body>{body}</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/'
            'package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/'
            'vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        )
        archive.writestr("word/document.xml", document)
    return path


# --- PNG -----------------------------------------------------------------------


def make_png(path: Path, width: int = 64, height: int = 32) -> Path:
    raw = b"".join(b"\x00" + bytes([255, 255, 255] * width) for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")
    path.write_bytes(png)
    return path


# --- PCAP ----------------------------------------------------------------------


def _client_hello(sni: str, tls13: bool) -> bytes:
    name = sni.encode()
    sni_ext = struct.pack(">HH", 0, len(name) + 5) + struct.pack(">HBH", len(name) + 3, 0, len(name)) + name
    exts = sni_ext
    if tls13:
        exts += struct.pack(">HHB", 0x002B, 5, 4) + b"\x03\x04\x03\x03"
    suites = b"\x13\x01\xc0\x2f"
    body = b"\x03\x03" + bytes(32) + b"\x00" + struct.pack(">H", len(suites)) + suites + b"\x01\x00"
    body += struct.pack(">H", len(exts)) + exts
    handshake = b"\x01" + struct.pack(">I", len(body))[1:] + body
    return b"\x16\x03\x01" + struct.pack(">H", len(handshake)) + handshake


def _server_hello(tls13: bool) -> bytes:
    exts = struct.pack(">HHH", 0x002B, 2, 0x0304) if tls13 else b""
    suite = b"\x13\x01" if tls13 else b"\xc0\x2f"
    body = b"\x03\x03" + bytes(32) + b"\x00" + suite + b"\x00" + struct.pack(">H", len(exts)) + exts
    handshake = b"\x02" + struct.pack(">I", len(body))[1:] + body
    if not tls13:
        cert = b"\x0b" + struct.pack(">I", 3)[1:] + b"\x00\x00\x00"
        handshake += cert
    return b"\x16\x03\x03" + struct.pack(">H", len(handshake)) + handshake


def make_pcap(
    path: Path,
    *,
    tls13: bool = True,
    sni: str = "lab.example.test",
    http: bool = True,
    dns: bool = True,
    seed: int = 7,
) -> Path:
    import dpkt

    rng = random.Random(seed)
    client, server = bytes([10, 0, 0, 5]), bytes([10, 0, 0, 9])
    packets: list[bytes] = []
    t = [1_700_000_000.0]

    def tcp(src, dst, sport, dport, seq, ack, flags, payload=b""):
        segment = dpkt.tcp.TCP(
            sport=sport, dport=dport, seq=seq, ack=ack, flags=flags, win=65535, data=payload
        )
        ip = dpkt.ip.IP(src=src, dst=dst, p=dpkt.ip.IP_PROTO_TCP, ttl=64, data=segment)
        ip.len = len(ip)
        return bytes(
            dpkt.ethernet.Ethernet(src=b"\x02" * 6, dst=b"\x04" * 6, type=dpkt.ethernet.ETH_TYPE_IP, data=ip)
        )

    def stream(sport, dport, exchanges):
        cseq, sseq = 1000, 5000
        packets.append(tcp(client, server, sport, dport, cseq, 0, dpkt.tcp.TH_SYN))
        packets.append(tcp(server, client, dport, sport, sseq, cseq + 1, dpkt.tcp.TH_SYN | dpkt.tcp.TH_ACK))
        cseq, sseq = cseq + 1, sseq + 1
        packets.append(tcp(client, server, sport, dport, cseq, sseq, dpkt.tcp.TH_ACK))
        for from_client, payload in exchanges:
            if from_client:
                packets.append(
                    tcp(client, server, sport, dport, cseq, sseq, dpkt.tcp.TH_ACK | dpkt.tcp.TH_PUSH, payload)
                )
                cseq += len(payload)
            else:
                packets.append(
                    tcp(server, client, dport, sport, sseq, cseq, dpkt.tcp.TH_ACK | dpkt.tcp.TH_PUSH, payload)
                )
                sseq += len(payload)

    if dns:
        query = dpkt.dns.DNS(id=1, qd=[dpkt.dns.DNS.Q(name=sni, type=dpkt.dns.DNS_A)])
        answer = dpkt.dns.DNS(
            id=1,
            op=dpkt.dns.DNS_RA,
            rcode=0,
            qd=query.qd,
            an=[dpkt.dns.DNS.RR(name=sni, type=dpkt.dns.DNS_A, ip=server, ttl=60)],
        )
        answer.op = 0x8180
        for src, dst, sport, dport, msg in (
            (client, server, 5353, 53, query),
            (server, client, 53, 5353, answer),
        ):
            udp = dpkt.udp.UDP(sport=sport, dport=dport, data=bytes(msg))
            udp.ulen = len(udp)
            ip = dpkt.ip.IP(src=src, dst=dst, p=dpkt.ip.IP_PROTO_UDP, ttl=64, data=udp)
            ip.len = len(ip)
            packets.append(
                bytes(
                    dpkt.ethernet.Ethernet(
                        src=b"\x02" * 6, dst=b"\x04" * 6, type=dpkt.ethernet.ETH_TYPE_IP, data=ip
                    )
                )
            )
    app_data = bytes(rng.getrandbits(8) for _ in range(900))
    stream(
        40001,
        443,
        [
            (True, _client_hello(sni, tls13)),
            (False, _server_hello(tls13)),
            (True, b"\x17\x03\x03" + struct.pack(">H", len(app_data)) + app_data),
        ],
    )
    if http:
        request = (
            b"GET /search?token=SECRET123&q=alerts HTTP/1.1\r\nHost: plain.example.test\r\n"
            b"User-Agent: test\r\n\r\n"
        )
        stream(40002, 80, [(True, request), (False, b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")])
    with open(path, "wb") as handle:
        writer = dpkt.pcap.Writer(handle)
        for frame in packets:
            t[0] += 0.01
            writer.writepkt(frame, ts=t[0])
    return path


def tree_digest(root: Path) -> dict[str, tuple[int, int]]:
    """(size, mtime_ns) for every file under root; used to prove nothing changed."""
    out = {}
    if not root.exists():
        return out
    for directory, _dirs, files in os.walk(root):
        for name in files:
            path = Path(directory) / name
            info = path.stat()
            out[str(path.relative_to(root))] = (info.st_size, info.st_mtime_ns)
    return out
