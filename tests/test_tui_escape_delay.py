from __future__ import annotations

import os

from kanjitui.tui import app as tui_app


def test_configure_curses_escape_delay_uses_setter(monkeypatch) -> None:
    called: dict[str, int] = {}

    def _set_escdelay(value: int) -> None:
        called["value"] = value

    monkeypatch.setattr(tui_app.curses, "set_escdelay", _set_escdelay)
    monkeypatch.delenv("ESCDELAY", raising=False)

    tui_app._configure_curses_escape_delay(17)

    assert called["value"] == 17
    assert "ESCDELAY" not in os.environ


def test_configure_curses_escape_delay_falls_back_to_env(monkeypatch) -> None:
    monkeypatch.delattr(tui_app.curses, "set_escdelay", raising=False)
    monkeypatch.delenv("ESCDELAY", raising=False)

    tui_app._configure_curses_escape_delay(33)

    assert os.environ.get("ESCDELAY") == "33"
