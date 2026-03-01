from kanjitui.tui.router import KeyRouter


def test_router_prefers_mode_handler() -> None:
    seen: list[str] = []

    def mode_resolver() -> str:
        return "search"

    def default_handler(_: int) -> bool:
        seen.append("default")
        return True

    def search_handler(_: int) -> bool:
        seen.append("search")
        return False

    router = KeyRouter(mode_resolver, default_handler)
    router.register("search", search_handler)

    assert router.dispatch(10) is False
    assert seen == ["search"]


def test_router_falls_back_when_mode_handler_returns_none() -> None:
    seen: list[str] = []

    def mode_resolver() -> str:
        return "radical"

    def default_handler(_: int) -> bool:
        seen.append("default")
        return True

    def radical_handler(_: int) -> bool | None:
        seen.append("radical")
        return None

    router = KeyRouter(mode_resolver, default_handler)
    router.register("radical", radical_handler)

    assert router.dispatch(9) is True
    assert seen == ["radical", "default"]
