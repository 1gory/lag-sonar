"""Отрисовка иконки во всех комбинациях состояний.

Проверяется главное: каждая комбинация рисуется без исключений, даёт картинку
нужного размера и непустую — то есть на панели что-то видно.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

AppKit = pytest.importorskip("AppKit", reason="нужен PyObjC")

from lag_sonar import icon
from lag_sonar.model import CoreState, RingState

ALL_COMBOS = [(r, c) for r in RingState for c in CoreState]


@pytest.mark.parametrize("ring,core", ALL_COMBOS)
def test_every_combination_renders(ring, core):
    image = icon.render(ring, core)
    assert image is not None
    assert image.size().width == icon.SIZE
    assert image.size().height == icon.SIZE


def test_every_state_has_its_own_colour():
    assert set(icon.RING_COLORS) == set(RingState)
    assert set(icon.CORE_COLORS) == set(CoreState)


@pytest.mark.parametrize("ring,core", ALL_COMBOS)
def test_rendered_image_is_not_blank(ring, core):
    """Пустая иконка — худший исход: пользователь решит, что приложение умерло."""
    data = icon.render_png(ring, core, scale=4)
    assert len(data) > 200

    rep = AppKit.NSBitmapImageRep.imageRepWithData_(
        AppKit.NSData.dataWithBytes_length_(data, len(data))
    )
    opaque = 0
    step = 3
    for x in range(0, rep.pixelsWide(), step):
        for y in range(0, rep.pixelsHigh(), step):
            if rep.colorAtX_y_(x, y).alphaComponent() > 0.1:
                opaque += 1
    assert opaque > 20, "на иконке почти ничего не нарисовано"


def test_ring_states_differ_visually():
    """Разные состояния сети должны давать разные картинки, иначе кодирование бессмысленно."""
    renders = {
        ring: icon.render_png(ring, CoreState.OK, scale=4) for ring in RingState
    }
    assert len(set(renders.values())) == len(RingState)


def test_core_states_differ_visually():
    renders = {
        core: icon.render_png(RingState.OK, core, scale=4) for core in CoreState
    }
    assert len(set(renders.values())) == len(CoreState)
