from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parent

MIME_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".ico": "image/x-icon",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".txt": "text/plain; charset=utf-8",
}


def _safe_path(path_info: str) -> Path | None:
    raw = unquote(path_info or "/")
    if raw == "/":
        raw = "/index.html"
    candidate = (ROOT / raw.lstrip("/")).resolve()
    try:
        candidate.relative_to(ROOT)
    except ValueError:
        return None
    if not candidate.exists() or not candidate.is_file():
        return None
    return candidate


def app(environ, start_response):  # type: ignore[no-untyped-def]
    candidate = _safe_path(environ.get("PATH_INFO", "/"))
    if candidate is None:
        body = b"404 not found\n"
        start_response(
            "404 Not Found",
            [
                ("Content-Type", "text/plain; charset=utf-8"),
                ("Content-Length", str(len(body))),
            ],
        )
        return [body]

    content = candidate.read_bytes()
    ctype = MIME_TYPES.get(candidate.suffix.lower(), "application/octet-stream")
    headers = [
        ("Content-Type", ctype),
        ("Content-Length", str(len(content))),
    ]
    if candidate.suffix.lower() in {".css", ".js", ".png", ".svg", ".ico"}:
        headers.append(("Cache-Control", "public, max-age=3600"))
    else:
        headers.append(("Cache-Control", "no-cache"))
    start_response("200 OK", headers)
    return [content]

