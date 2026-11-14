"""Draw the 1200x630 card that social sites fetch for the scoreboard.

The card is generated from the scoreboard for this run, so the figure on it
matches the page that was just written. It prefers Inter, then DejaVu, then
any other face the machine already has.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1200
HEIGHT = 630

_BG = (247, 247, 247)
_SURFACE = (255, 255, 255)
_INK = (25, 28, 31)
_MUTED = (107, 111, 118)
_SUBTLE = (154, 158, 166)
_ACCENT = (6, 102, 235)
_PASS = (26, 127, 75)
_GAP = (198, 40, 40)
_DIVERGE = (179, 107, 0)
_BLOCKED = (107, 111, 118)
_CHIP = (240, 241, 243)

_OUTCOME = {
    "pass": _PASS,
    "not_implemented": _GAP,
    "divergent": _DIVERGE,
    "blocked": _BLOCKED,
}

# (regular, semibold, bold). The first family that exists on disk wins.
_FAMILIES = (
    (
        "/usr/share/fonts/truetype/macos/Inter-Regular.ttf",
        "/usr/share/fonts/truetype/macos/Inter-SemiBold.ttf",
        "/usr/share/fonts/truetype/macos/Inter-Bold.ttf",
    ),
    (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    (
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ),
    (
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ),
    (
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ),
    (
        "/Library/Fonts/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
    ),
    (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    ),
    (
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/seguisb.ttf",
        "C:/Windows/Fonts/segoeuib.ttf",
    ),
    (
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
        "C:/Windows/Fonts/arialbd.ttf",
    ),
)


def write_og_image(scoreboard: dict, path: Path) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), _BG)
    draw = ImageDraw.Draw(image)
    summary = scoreboard.get("summary") or {}
    emulator = scoreboard.get("emulator") or {}
    regular = _face("regular")
    semibold = _face("semibold")
    bold = _face("bold")

    _header(draw, emulator.get("version"), regular, semibold)
    _hero(draw, summary, regular, bold, semibold)
    _genome(draw, scoreboard, regular)
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, "PNG", optimize=True)


def _header(draw: ImageDraw.ImageDraw, version, regular, semibold) -> None:
    draw.ellipse((64, 58, 76, 70), fill=_ACCENT)
    draw.text((88, 46), "AWS Emulator Arena", font=semibold(26), fill=_INK)
    draw.text((88, 80), "Local fidelity board", font=regular(16), fill=_MUTED)
    if not version:
        return
    label = f"emulator {version}"
    font = semibold(15)
    text_w = font.getlength(label)
    pad_x = 14
    box_w = text_w + pad_x * 2
    box_h = 32
    x = WIDTH - 64 - box_w
    y = 52
    draw.rounded_rectangle((x, y, x + box_w, y + box_h), radius=16, fill=_CHIP)
    draw.text((x + pad_x, y + 7), label, font=font, fill=_INK)


def _hero(draw: ImageDraw.ImageDraw, summary: dict, regular, bold, semibold) -> None:
    passed = int(summary.get("pass") or 0)
    gaps = int(summary.get("not_implemented") or 0)
    divergent = int(summary.get("divergent") or 0)
    scenarios = int(summary.get("scenarios") or 0)
    scored = passed + gaps + divergent
    fidelity = summary.get("fidelity_pct")
    score_text = "-" if fidelity is None else str(fidelity)
    tone = _score_tone(fidelity)

    draw.rounded_rectangle((56, 132, 732, 444), radius=22, fill=_SURFACE)
    _tracked(draw, (88, 156), "FIDELITY", regular(13), _MUTED, 1.1)
    score_font = bold(104)
    draw.text((88, 180), score_text, font=score_font, fill=tone)
    score_w = score_font.getlength(score_text)
    draw.text((88 + score_w + 6, 200), "%", font=semibold(32), fill=_SUBTLE)
    draw.text(
        (88, 320),
        f"{passed} of {scored} steps behaved like AWS",
        font=regular(18),
        fill=_INK,
    )
    draw.text(
        (88, 348),
        f"across {scenarios} workflows. {gaps} came back 501. {divergent} diverged.",
        font=regular(16),
        fill=_MUTED,
    )

    latency = (summary.get("latency_ms") or {}).get("p50")
    calls = (summary.get("latency_ms") or {}).get("n")
    p50 = "-" if latency is None else _ms(latency)
    p50_label = "p50" if not calls else f"p50 over {calls} calls"
    cards = (
        (str(passed), "passed", _PASS),
        (str(gaps), "501 not implemented", _GAP),
        (str(divergent), "divergent", _DIVERGE),
        (p50, p50_label, _INK),
    )
    origin_x, origin_y = 756, 132
    card_w, card_h, gap = 188, 148, 16
    for index, (value, label, colour) in enumerate(cards):
        col, row = index % 2, index // 2
        x = origin_x + col * (card_w + gap)
        y = origin_y + row * (card_h + gap)
        draw.rounded_rectangle((x, y, x + card_w, y + card_h), radius=22, fill=_SURFACE)
        value_font = _fit(bold, value, 36, card_w - 40)
        draw.text((x + 20, y + 36), value, font=value_font, fill=colour)
        draw.text((x + 20, y + 94), label, font=regular(13), fill=_MUTED)


def _genome(draw: ImageDraw.ImageDraw, scoreboard: dict, regular) -> None:
    steps = [
        step.get("outcome") or "blocked"
        for scenario in scoreboard.get("scenarios") or []
        for step in scenario.get("steps") or []
    ]
    legend = (("pass", _PASS), ("501", _GAP), ("divergent", _DIVERGE), ("blocked", _BLOCKED))
    x = 56
    y = 468
    for name, colour in legend:
        draw.ellipse((x, y + 4, x + 8, y + 12), fill=colour)
        label_font = regular(14)
        draw.text((x + 14, y), name, font=label_font, fill=_MUTED)
        x += 14 + label_font.getlength(name) + 22
    if not steps:
        return
    bar_x, bar_y, bar_w, bar_h = 56, 498, WIDTH - 112, 64
    draw.rounded_rectangle((bar_x, bar_y, bar_x + bar_w, bar_y + bar_h), radius=16, fill=_SURFACE)
    inner_x = bar_x + 14
    inner_w = bar_w - 28
    inner_h = 28
    inner_y = bar_y + (bar_h - inner_h) / 2
    count = len(steps)
    gap = 3 if count > 1 else 0
    mark_w = (inner_w - gap * (count - 1)) / count
    if mark_w < 1.5 and count > 1:
        gap = 1
        mark_w = (inner_w - gap * (count - 1)) / count
    if mark_w < 1:
        return
    for index, outcome in enumerate(steps):
        left = inner_x + index * (mark_w + gap)
        colour = _OUTCOME.get(outcome, _BLOCKED)
        draw.rounded_rectangle((left, inner_y, left + mark_w, inner_y + inner_h), radius=3, fill=colour)


def _score_tone(fidelity) -> tuple[int, int, int]:
    if fidelity is None:
        return _INK
    if fidelity >= 80:
        return _PASS
    if fidelity >= 50:
        return _INK
    return _GAP


def _ms(value: float) -> str:
    number = float(value)
    if number >= 100:
        return f"{round(number)} ms"
    if number >= 10:
        return f"{number:.1f} ms"
    return f"{number:.2f} ms"


def _tracked(draw, origin, text: str, font, fill, extra: float) -> None:
    x, y = origin
    for char in text:
        draw.text((x, y), char, font=font, fill=fill)
        x += font.getlength(char) + extra


def _fit(factory, text: str, size: int, max_width: float):
    while size > 16:
        font = factory(size)
        if font.getlength(text) <= max_width:
            return font
        size -= 2
    return factory(size)


def _face(weight: str):
    path = _family().get(weight)

    def load(size: int):
        if path is None:
            return _default(size)
        return ImageFont.truetype(path, size=size)

    return load


@lru_cache(maxsize=1)
def _family() -> dict[str, str | None]:
    for regular, semibold, bold in _FAMILIES:
        if Path(regular).is_file():
            return {
                "regular": regular,
                "semibold": semibold if Path(semibold).is_file() else regular,
                "bold": bold if Path(bold).is_file() else regular,
            }
    return {"regular": None, "semibold": None, "bold": None}


def _default(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()
