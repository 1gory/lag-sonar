"""Отрисовка иконки menu bar.

Кольцо кодирует состояние сети, ядро — состояние Claude. Цвет всегда продублирован
формой: иконка размером 18×18 pt лежит на произвольном фоне (обои просвечивают
сквозь панель), и полагаться на один оттенок ненадёжно.

Модуль ничего не знает о сети: на вход — пара состояний, на выход — NSImage.
"""

from __future__ import annotations

import math

from AppKit import (
    NSBezierPath,
    NSColor,
    NSCompositingOperationSourceOver,
    NSImage,
    NSMakeRect,
)

from .model import CoreState, RingState

SIZE = 18.0
CENTER = SIZE / 2.0

RING_OUTER = 8.0
RING_WIDTH = 2.4
RING_RADIUS = RING_OUTER - RING_WIDTH / 2.0

CORE_RADIUS = 3.1


def _color(red: float, green: float, blue: float, alpha: float = 1.0):
    return NSColor.colorWithSRGBRed_green_blue_alpha_(red, green, blue, alpha)


# Оттенки подобраны так, чтобы читаться и на светлой, и на тёмной панели:
# средняя светлота, высокая насыщенность.
RING_COLORS = {
    RingState.OK: _color(0.20, 0.72, 0.35),  # зелёный
    RingState.DNS_DOWN: _color(0.95, 0.72, 0.10),  # янтарный
    RingState.VPN_DOWN: _color(0.63, 0.36, 0.92),  # фиолетовый
    RingState.ISP_DOWN: _color(0.96, 0.49, 0.12),  # оранжевый
    RingState.NO_LINK: _color(0.60, 0.60, 0.63),  # серый
    RingState.UNKNOWN: _color(0.55, 0.55, 0.58, 0.55),  # тусклый серый
}

CORE_COLORS = {
    CoreState.OK: _color(0.20, 0.72, 0.35),
    CoreState.SLOW: _color(0.95, 0.72, 0.10),
    CoreState.BLOCKED: _color(0.63, 0.36, 0.92),
    CoreState.DOWN: _color(0.90, 0.22, 0.21),
    CoreState.INCIDENT: _color(0.90, 0.22, 0.21),
    CoreState.UNKNOWN: _color(0.55, 0.55, 0.58, 0.5),
}


def _ring_path(state: RingState) -> NSBezierPath:
    path = NSBezierPath.bezierPath()
    path.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(
        (CENTER, CENTER), RING_RADIUS, 0, 360
    )
    path.setLineWidth_(RING_WIDTH)

    if state is RingState.NO_LINK:
        # Пунктир — «связи нет вовсе», видно даже боковым зрением.
        path.setLineDash_count_phase_([2.2, 2.2], 2, 0.0)
    elif state is RingState.DNS_DOWN:
        # Разрыв сверху: связь есть, но цепочка неполная.
        path = NSBezierPath.bezierPath()
        path.appendBezierPathWithArcWithCenter_radius_startAngle_endAngle_(
            (CENTER, CENTER), RING_RADIUS, 75, 425
        )
        path.setLineWidth_(RING_WIDTH)
    return path


def _draw_core(state: CoreState) -> None:
    color = CORE_COLORS[state]
    color.set()

    if state is CoreState.OK:
        NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(
                CENTER - CORE_RADIUS, CENTER - CORE_RADIUS, CORE_RADIUS * 2, CORE_RADIUS * 2
            )
        ).fill()

    elif state is CoreState.UNKNOWN:
        path = NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(
                CENTER - CORE_RADIUS + 0.6,
                CENTER - CORE_RADIUS + 0.6,
                (CORE_RADIUS - 0.6) * 2,
                (CORE_RADIUS - 0.6) * 2,
            )
        )
        path.setLineWidth_(1.2)
        path.stroke()

    elif state is CoreState.SLOW:
        # Треугольник вершиной вверх — привычный знак «внимание».
        path = NSBezierPath.bezierPath()
        r = CORE_RADIUS + 0.5
        path.moveToPoint_((CENTER, CENTER + r))
        path.lineToPoint_((CENTER + r * 0.92, CENTER - r * 0.68))
        path.lineToPoint_((CENTER - r * 0.92, CENTER - r * 0.68))
        path.closePath()
        path.fill()

    elif state is CoreState.BLOCKED:
        side = CORE_RADIUS * 1.7
        NSBezierPath.bezierPathWithRect_(
            NSMakeRect(CENTER - side / 2, CENTER - side / 2, side, side)
        ).fill()

    elif state is CoreState.DOWN:
        path = NSBezierPath.bezierPath()
        arm = CORE_RADIUS * 0.85
        path.moveToPoint_((CENTER - arm, CENTER - arm))
        path.lineToPoint_((CENTER + arm, CENTER + arm))
        path.moveToPoint_((CENTER - arm, CENTER + arm))
        path.lineToPoint_((CENTER + arm, CENTER - arm))
        path.setLineWidth_(1.8)
        path.setLineCapStyle_(1)  # NSLineCapStyleRound
        path.stroke()

    elif state is CoreState.INCIDENT:
        # Восклицательный знак: у них авария, а не просто «не ответили нам».
        bar = NSBezierPath.bezierPathWithRect_(
            NSMakeRect(CENTER - 0.85, CENTER - 0.6, 1.7, CORE_RADIUS * 1.5)
        )
        bar.fill()
        NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect(CENTER - 0.95, CENTER - CORE_RADIUS - 0.2, 1.9, 1.9)
        ).fill()


def _draw(ring: RingState, core: CoreState) -> None:
    RING_COLORS[ring].set()
    _ring_path(ring).stroke()
    _draw_core(core)


def render(ring: RingState, core: CoreState) -> NSImage:
    """Собрать иконку для пары состояний.

    Рисование идёт через drawing handler: система сама перерисует изображение
    под нужный масштаб при переезде на другой монитор.
    """
    image = NSImage.alloc().initWithSize_((SIZE, SIZE))
    image.setTemplate_(False)

    image.lockFocus()
    _draw(ring, core)
    image.unlockFocus()
    return image


def render_png(ring: RingState, core: CoreState, scale: int = 8) -> bytes:
    """Крупный PNG для проверки глазами. В приложении не используется."""
    from AppKit import (
        NSAffineTransform,
        NSBitmapImageRep,
        NSGraphicsContext,
        NSPNGFileType,
    )

    side = int(SIZE * scale)
    rep = NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, side, side, 8, 4, True, False, "NSCalibratedRGBColorSpace", 0, 0
    )
    context = NSGraphicsContext.graphicsContextWithBitmapImageRep_(rep)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.setCurrentContext_(context)

    # Масштабируем через NSAffineTransform: модуль Quartz в системе не установлен,
    # а CGContext без него из PyObjC недоступен.
    transform = NSAffineTransform.transform()
    transform.scaleBy_(scale)
    transform.concat()

    _draw(ring, core)

    NSGraphicsContext.restoreGraphicsState()
    return bytes(rep.representationUsingType_properties_(NSPNGFileType, None))
