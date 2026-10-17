"""Present Panasonic modes with valid icon keys while retaining native commands."""

from __future__ import annotations

PANASONIC_MODE_VALUES = frozenset({
    "Auto", "Low", "LowMid", "Mid", "HighMid", "High",
    "Up", "UpMid", "DownMid", "Down", "Swing",
    "Left", "LeftMid", "RightMid", "Right",
})


def display_mode(value: str | None, modes: list[str] | None) -> str | None:
    """Use lowercase icon keys unless two native options would become identical."""
    normalized = [mode.lower() if mode in PANASONIC_MODE_VALUES else mode for mode in modes or []]
    if len(set(normalized)) != len(set(modes or [])):
        return value
    return value.lower() if value in PANASONIC_MODE_VALUES else value


def display_modes(modes: list[str] | None) -> list[str] | None:
    """Keep the advertised options consistent with the displayed current mode."""
    if modes is None:
        return None
    return [display_mode(mode, modes) or mode for mode in modes]


def native_mode(value: str, modes: list[str] | None) -> str:
    """Resolve a displayed selection to the exact value accepted by members."""
    if value in (modes or []):
        return value
    return next((mode for mode in modes or [] if display_mode(mode, modes) == value), value)
