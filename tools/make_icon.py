"""Draw the Pete's Vinyl icons (static/vinyl.ico and static/update.ico). Pure Python, no extra packages.

Run:  python tools/make_icon.py
The .ico holds several sizes so Windows can show it sharply on the desktop, taskbar and in Alt-Tab.
"""
from __future__ import annotations

import math
import struct
import zlib
from pathlib import Path

SIZES = [16, 24, 32, 48, 64, 128, 256]
SS = 3  # supersampling (SS x SS samples per pixel) for smooth edges


def _in_arrow(px: float, py: float) -> bool:
    """A white 'up' arrow, in coordinates relative to the badge centre (y grows downwards)."""
    if -0.04 <= px <= 0.04 and -0.01 <= py <= 0.12:        # stem
        return True
    if -0.13 <= py <= -0.01:                              # head: a triangle pointing up
        return abs(px) <= (py + 0.13) / 0.12 * 0.11
    return False


def shade(x: float, y: float, update: bool = False) -> tuple[int, int, int, int]:
    """Colour at a point of the unit square (0..1), RGBA. Alpha 0 outside the disc.
    With update=True a green badge with an up-arrow is drawn in the bottom-right corner."""
    if update:
        bx, by = x - 0.74, y - 0.74
        br = math.hypot(bx, by)
        if br <= 0.25:
            if br > 0.215:
                return (255, 255, 255, 255)                # white ring
            return (255, 255, 255, 255) if _in_arrow(bx, by) else (46, 168, 84, 255)
    dx, dy = x - 0.5, y - 0.5
    r = math.hypot(dx, dy)
    if r > 0.49:
        return (0, 0, 0, 0)
    if r < 0.022:                       # spindle hole
        return (245, 245, 245, 255)
    if r < 0.19:                        # red label
        t = r / 0.19
        return (int(236 - 30 * t), int(60 - 25 * t), int(46 - 20 * t), 255)
    if r < 0.205:                       # ring around the label
        return (60, 30, 25, 255)
    base = 22
    groove = 14 if int((r - 0.205) / 0.012) % 2 == 0 else 0     # fine concentric grooves
    ang = math.atan2(dy, dx)
    gloss = int(26 * max(0.0, math.cos(2 * ang - 0.9)) ** 6)   # two soft highlights across the disc
    v = base + groove + gloss
    return (v, v, v + 2, 255)


def render(size: int, update: bool = False) -> bytes:
    rows = []
    for py in range(size):
        row = bytearray([0])  # PNG filter byte: none
        for px in range(size):
            rs = gs = bs = a_sum = 0
            for sy in range(SS):
                for sx in range(SS):
                    r, g, b, a = shade((px + (sx + 0.5) / SS) / size, (py + (sy + 0.5) / SS) / size, update)
                    rs += r * a; gs += g * a; bs += b * a; a_sum += a
            if a_sum:
                row += bytes([rs // a_sum, gs // a_sum, bs // a_sum, a_sum // (SS * SS)])
            else:
                row += bytes(4)
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")


def write_ico(name: str, update: bool) -> None:
    images = [(sz, render(sz, update)) for sz in SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    directory, blobs = b"", b""
    for size, png in images:
        directory += struct.pack("<BBBBHHII", size % 256, size % 256, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    out = Path(__file__).resolve().parent.parent / "static" / name
    out.write_bytes(header + directory + blobs)
    print(f"Wrote {out} ({out.stat().st_size // 1024} KB, sizes {SIZES})")


def main() -> None:
    write_ico("vinyl.ico", update=False)
    write_ico("update.ico", update=True)


if __name__ == "__main__":
    main()
