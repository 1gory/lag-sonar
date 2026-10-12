#!/usr/bin/env python3
"""Иконка приложения (.icns) из того же рисунка, что и значок в menu bar.

Зелёное кольцо с зелёным ядром на тёмной подложке — «всё работает».
Нужна только Finder и «Объектам входа»: в menu bar рисуется `icon.render`.

    python3 scripts/make_app_icon.py build/LagSonar.icns
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from AppKit import (
    NSAffineTransform,
    NSBezierPath,
    NSBitmapImageRep,
    NSColor,
    NSGraphicsContext,
    NSMakeRect,
    NSPNGFileType,
)

from lag_sonar import icon
from lag_sonar.model import CoreState, RingState

# Размеры, которые iconutil ждёт в .iconset: базовый и @2x.
SIZES = (16, 32, 128, 256, 512)


def render(pixels: int) -> bytes:
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, pixels, pixels, 8, 4, True, False, "NSCalibratedRGBColorSpace", 0, 0
    )
    context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(context)

    # Подложка по сетке иконок macOS: скруглённый квадрат с полями ~10%.
    inset = pixels * 0.1
    side = pixels - 2 * inset
    NSColor.colorWithSRGBRed_green_blue_alpha_(0.13, 0.13, 0.15, 1).set()
    NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
        NSMakeRect(inset, inset, side, side), side * 0.225, side * 0.225
    ).fill()

    # Сам знак занимает ~70% подложки.
    scale = side * 0.7 / icon.SIZE
    offset = inset + (side - icon.SIZE * scale) / 2
    transform = NSAffineTransform.transform()
    transform.translateXBy_yBy_(offset, offset)
    transform.scaleBy_(scale)
    transform.concat()
    icon._draw(RingState.OK, CoreState.OK)

    NSGraphicsContext.restoreGraphicsState()
    return bytes(rep.representationUsingType_properties_(NSPNGFileType, None))


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "build/LagSonar.icns")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "LagSonar.iconset"
        iconset.mkdir()
        for size in SIZES:
            (iconset / f"icon_{size}x{size}.png").write_bytes(render(size))
            (iconset / f"icon_{size}x{size}@2x.png").write_bytes(render(size * 2))
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(target)], check=True)
    print(f"записано: {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
