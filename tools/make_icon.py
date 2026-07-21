"""Render the tray microphone into assets/SuperDictate.ico.

The tray glyph is drawn at runtime so it can recolour per state; the
executable needs a static file, so this renders the same path at the
sizes Windows asks for and packs them into a PNG-compressed ICO.

Run from the repository root::

    python tools/make_icon.py
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QBuffer, QByteArray  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402

SIZES = (16, 24, 32, 48, 64, 128, 256)
# Shell icons sit on unpredictable backgrounds; the light glyph reads on
# both the dark taskbar and a light Explorer window.
COLOR = "#f2f2f7"


def png_bytes(size: int) -> bytes:
    from superdictate.ui.tray import build_icon

    pixmap = build_icon(COLOR, size).pixmap(size, size)
    # The QByteArray must outlive the QBuffer that writes into it.
    storage = QByteArray()
    buffer = QBuffer(storage)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    buffer.close()
    return bytes(storage)


def build_ico(images: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, blobs = b"", b""
    for size, data in images:
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,   # 0 means 256
            0 if size >= 256 else size,
            0, 0, 1, 32, len(data), offset,
        )
        blobs += data
        offset += len(data)
    return header + entries + blobs


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841 — needed for QPixmap
    images = [(size, png_bytes(size)) for size in SIZES]
    target = ROOT / "assets" / "SuperDictate.ico"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(build_ico(images))
    print(f"wrote {target} ({target.stat().st_size} bytes, {len(images)} sizes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
