from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote_plus


@dataclass(frozen=True)
class ImageLink:
    label: str
    url: str
    source: str
    license_note: str


def cc_image_links(ch: str, cp: int) -> list[ImageLink]:
    token = quote_plus(ch)
    code = f"U+{cp:04X}"
    return [
        ImageLink(
            label="Wikimedia Commons search",
            url=f"https://commons.wikimedia.org/w/index.php?search={token}&title=Special:MediaSearch&go=Go&type=image",
            source="Wikimedia Commons",
            license_note="Mixed licenses; filter to CC in source UI as needed",
        ),
        ImageLink(
            label="Wikimedia Category",
            url=f"https://commons.wikimedia.org/wiki/Category:{quote_plus(ch)}",
            source="Wikimedia Commons",
            license_note="Mixed licenses; verify file-specific license",
        ),
        ImageLink(
            label="Openverse image search",
            url=f"https://openverse.org/search/image?q={token}%20{quote_plus(code)}",
            source="Openverse",
            license_note="CC results with license filters",
        ),
    ]
