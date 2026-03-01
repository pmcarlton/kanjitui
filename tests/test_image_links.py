from kanjitui.tui.imagelinks import cc_image_links


def test_cc_image_links_are_generated() -> None:
    links = cc_image_links("漢", 0x6F22)
    assert len(links) >= 3
    assert any("openverse" in link.url for link in links)
    assert any("wikimedia.org" in link.url for link in links)
