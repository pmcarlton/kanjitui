# Landing Page

Academic-style static landing page for `kanjitui` / `kanjigui`.

The page links to `/docs/` for the MkDocs user manual.

## Files

- `index.html`
- `styles.css`
- `wsgi.py` (optional, for Gunicorn static serving)
- `assets/kanjiTUI.png` (featured UI screenshot)

## Serve with Caddy (recommended for static)

Build docs into this static root first:

```bash
cd /absolute/path/to/kanjitui
make build-web-docs
```

Example `Caddyfile` block:

```caddyfile
kanji.example.com {
    root * /absolute/path/to/kanjitui/web/landing
    encode zstd gzip
    file_server
}
```

## Serve with Gunicorn (optional)

From this directory:

```bash
cd /absolute/path/to/kanjitui/web/landing
gunicorn --bind 127.0.0.1:8080 wsgi:app
```

Then reverse-proxy from Caddy/Nginx if desired.

To expose docs with Gunicorn, also run:

```bash
cd /absolute/path/to/kanjitui
make build-web-docs
```
