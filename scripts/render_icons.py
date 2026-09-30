#!/usr/bin/env python3
"""Контрольный лист иконок: все комбинации кольца и ядра в один PNG.

Нужен, чтобы посмотреть на состояния глазами — автотест проверяет, что картинка
не пустая и что состояния различаются, но не может сказать, читается ли она.

    python3 scripts/render_icons.py [каталог]
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from AppKit import (
    NSAffineTransform,
    NSBitmapImageRep,
    NSColor,
    NSFont,
    NSForegroundColorAttributeName,
    NSFontAttributeName,
    NSGraphicsContext,
    NSMakeRect,
    NSPNGFileType,
    NSString,
)
from Foundation import NSMutableDictionary

from lag_sonar import icon
from lag_sonar.model import CoreState, RingState

SCALE = 4
CELL = int(icon.SIZE * SCALE)
PAD = 14
LABEL_W = 150
HEADER_H = 26


def build_sheet(dark: bool) -> bytes:
    rings = list(RingState)
    cores = list(CoreState)

    width = LABEL_W + PAD + len(cores) * (CELL + PAD)
    height = HEADER_H + PAD + len(rings) * (CELL + PAD)

    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, width, height, 8, 4, True, False, "NSCalibratedRGBColorSpace", 0, 0
    )
    context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(context)

    # Фон имитирует панель меню: тёмную и светлую.
    bg = NSColor.colorWithSRGBRed_green_blue_alpha_(*((0.17, 0.17, 0.19, 1) if dark else (0.93, 0.93, 0.94, 1)))
    bg.set()
    from AppKit import NSBezierPath

    NSBezierPath.bezierPathWithRect_(NSMakeRect(0, 0, width, height)).fill()

    text_color = NSColor.whiteColor() if dark else NSColor.blackColor()
    attrs = NSMutableDictionary.dictionary()
    attrs[NSFontAttributeName] = NSFont.systemFontOfSize_(11)
    attrs[NSForegroundColorAttributeName] = text_color

    for col, core in enumerate(cores):
        x = LABEL_W + PAD + col * (CELL + PAD)
        NSString.stringWithString_(core.value).drawAtPoint_withAttributes_(
            (x, height - HEADER_H + 6), attrs
        )

    for row, ring in enumerate(rings):
        y = height - HEADER_H - PAD - (row + 1) * (CELL + PAD) + PAD
        NSString.stringWithString_(ring.value).drawAtPoint_withAttributes_(
            (PAD, y + CELL / 2 - 7), attrs
        )
        for col, core in enumerate(cores):
            x = LABEL_W + PAD + col * (CELL + PAD)
            NSGraphicsContext.saveGraphicsState()
            transform = NSAffineTransform.transform()
            transform.translateXBy_yBy_(x, y)
            transform.scaleBy_(SCALE)
            transform.concat()
            icon._draw(ring, core)
            NSGraphicsContext.restoreGraphicsState()

    NSGraphicsContext.restoreGraphicsState()
    return bytes(rep.representationUsingType_properties_(NSPNGFileType, None))


def main() -> int:
    out_dir = Path(sys.argv[1] if len(sys.argv) > 1 else "artifacts")
    out_dir.mkdir(parents=True, exist_ok=True)
    for dark in (True, False):
        name = "icons-dark.png" if dark else "icons-light.png"
        path = out_dir / name
        path.write_bytes(build_sheet(dark))
        print(f"записано: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
