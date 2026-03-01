from __future__ import annotations

from typing import Callable


KeyHandler = Callable[[int], bool | None]
ModeResolver = Callable[[], str]


class KeyRouter:
    def __init__(self, mode_resolver: ModeResolver, default_handler: Callable[[int], bool]) -> None:
        self._mode_resolver = mode_resolver
        self._default_handler = default_handler
        self._mode_handlers: dict[str, KeyHandler] = {}

    def register(self, mode: str, handler: KeyHandler) -> None:
        self._mode_handlers[mode] = handler

    def dispatch(self, key: int) -> bool:
        mode = self._mode_resolver()
        handler = self._mode_handlers.get(mode)
        if handler is not None:
            result = handler(key)
            if result is not None:
                return result
        return self._default_handler(key)
