from __future__ import annotations

import gzip
import io
import os
from dataclasses import dataclass
from pathlib import Path
import shutil
import tempfile
from typing import Callable
import urllib.request
import zipfile

from kanjitui.db.user import UserStore
from kanjitui.providers.tatoeba import BuildSentencesConfig, build_sentences_tsv, download_if_missing


SOURCE_ORDER = ("unihan", "cedict", "kanjidic2", "jmdict", "sentences", "strokeorder")


@dataclass(frozen=True)
class SourceSpec:
    key: str
    label: str


SOURCES: dict[str, SourceSpec] = {
    "unihan": SourceSpec("unihan", "Unicode Unihan"),
    "cedict": SourceSpec("cedict", "CC-CEDICT"),
    "kanjidic2": SourceSpec("kanjidic2", "EDRDG KANJIDIC2"),
    "jmdict": SourceSpec("jmdict", "EDRDG JMdict"),
    "sentences": SourceSpec("sentences", "Tatoeba sentences.tsv"),
    "strokeorder": SourceSpec("strokeorder", "StrokeOrder/KanjiVG stroke data"),
}


@dataclass(frozen=True)
class RuntimePaths:
    data_dir: Path
    strokeorder_dir: Path
    tatoeba_dir: Path


def resolve_runtime_paths(user_store: UserStore | None) -> RuntimePaths:
    env_data = os.environ.get("KANJITUI_DATA_DIR", "").strip()
    if env_data:
        data_dir = Path(env_data).expanduser()
    elif user_store is not None:
        data_dir = user_store.db_path.parent / "raw"
    else:
        data_dir = Path("data/raw")

    env_stroke = os.environ.get("KANJITUI_STROKEORDER_DIR", "").strip()
    if env_stroke:
        strokeorder_dir = Path(env_stroke).expanduser()
    else:
        strokeorder_dir = data_dir.parent / "strokeorder"

    return RuntimePaths(
        data_dir=data_dir,
        strokeorder_dir=strokeorder_dir,
        tatoeba_dir=data_dir / "tatoeba",
    )


def _path_exists(path: Path) -> bool:
    try:
        return path.exists()
    except OSError:
        return False


def detect_available_sources(paths: RuntimePaths) -> dict[str, bool]:
    unihan_dir = paths.data_dir / "unihan"
    unihan_ok = False
    if _path_exists(unihan_dir):
        unihan_ok = any(unihan_dir.glob("Unihan*.txt"))
    if not unihan_ok:
        unihan_ok = any(paths.data_dir.glob("Unihan*.txt"))

    return {
        "unihan": unihan_ok,
        "cedict": _path_exists(paths.data_dir / "cedict_ts.u8"),
        "kanjidic2": _path_exists(paths.data_dir / "kanjidic2.xml"),
        "jmdict": _path_exists(paths.data_dir / "jmdict.xml"),
        "sentences": _path_exists(paths.data_dir / "sentences.tsv"),
        "strokeorder": _path_exists(paths.strokeorder_dir / "kanji"),
    }


def default_setup_selection(presence: dict[str, bool]) -> list[str]:
    out = [key for key in SOURCE_ORDER if not presence.get(key, False)]
    return out


def acknowledgements_for_sources(presence: dict[str, bool]) -> list[str]:
    lines = ["Acknowledgements", ""]
    if presence.get("unihan"):
        lines.append(
            "This package uses Unicode Unihan data under the Unicode Terms of Use."
        )
    if presence.get("cedict"):
        lines.append(
            "This package uses CC-CEDICT under CC BY-SA; attribution and share-alike terms apply."
        )
    if presence.get("kanjidic2") or presence.get("jmdict"):
        lines.append(
            "This package uses the JMdict/EDICT and KANJIDIC dictionary files. These files are the property of the Electronic Dictionary Research and Development Group, and are used in conformance with the Group's licence."
        )
    if presence.get("sentences"):
        lines.append(
            "This package uses Tatoeba sentence data; licensing is source-dependent (CC BY / CC0 subsets)."
        )
    if presence.get("strokeorder"):
        lines.append(
            "This package uses StrokeOrder/KanjiVG stroke assets (KanjiVG: CC BY-SA 3.0)."
        )
    if len(lines) <= 2:
        lines.append("No optional external datasets detected yet.")
    lines.append("")
    lines.append("See THIRD_PARTY_NOTICES.md and data/licenses/ for full notices.")
    return lines


def _download_to(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "kanjitui/0.1"})
    with urllib.request.urlopen(req) as resp, dest.open("wb") as out:
        shutil.copyfileobj(resp, out)


def _gunzip_to(src_gz: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(src_gz, "rb") as gz, dest.open("wb") as out:
        shutil.copyfileobj(gz, out)


def _download_unihan(paths: RuntimePaths, log: Callable[[str], None]) -> None:
    zip_path = paths.data_dir / "Unihan.zip"
    log("Downloading Unihan.zip ...")
    _download_to("https://www.unicode.org/Public/UCD/latest/ucd/Unihan.zip", zip_path)
    log("Extracting Unihan*.txt ...")
    unihan_out = paths.data_dir / "unihan"
    unihan_out.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.startswith("Unihan") and name.endswith(".txt"):
                zf.extract(name, path=unihan_out)


def _download_cedict(paths: RuntimePaths, log: Callable[[str], None]) -> None:
    gz_path = paths.data_dir / "cedict_ts.u8.gz"
    out_path = paths.data_dir / "cedict_ts.u8"
    log("Downloading CC-CEDICT ...")
    _download_to(
        "https://www.mdbg.net/chinese/export/cedict/cedict_1_0_ts_utf-8_mdbg.txt.gz",
        gz_path,
    )
    log("Decompressing CC-CEDICT ...")
    _gunzip_to(gz_path, out_path)


def _download_edrdg(paths: RuntimePaths, log: Callable[[str], None], key: str) -> None:
    if key == "kanjidic2":
        urls = [
            "ftp://ftp.edrdg.org/pub/Nihongo/kanjidic2.xml.gz",
            "https://ftp.edrdg.org/pub/Nihongo/kanjidic2.xml.gz",
        ]
        gz_path = paths.data_dir / "kanjidic2.xml.gz"
        out_path = paths.data_dir / "kanjidic2.xml"
    else:
        urls = [
            "ftp://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz",
            "https://ftp.edrdg.org/pub/Nihongo/JMdict_e.gz",
        ]
        gz_path = paths.data_dir / "jmdict.xml.gz"
        out_path = paths.data_dir / "jmdict.xml"

    last_err: Exception | None = None
    for url in urls:
        try:
            log(f"Downloading {key} ({url}) ...")
            _download_to(url, gz_path)
            last_err = None
            break
        except Exception as exc:  # noqa: BLE001
            last_err = exc
    if last_err is not None:
        raise last_err

    log(f"Decompressing {key} ...")
    _gunzip_to(gz_path, out_path)


def _download_sentences(paths: RuntimePaths, log: Callable[[str], None]) -> None:
    base = "https://downloads.tatoeba.org/exports/per_language"
    urls = {
        "jpn_sentences": f"{base}/jpn/jpn_sentences.tsv.bz2",
        "cmn_sentences": f"{base}/cmn/cmn_sentences.tsv.bz2",
        "eng_sentences": f"{base}/eng/eng_sentences.tsv.bz2",
        "jpn_eng_links": f"{base}/jpn/jpn-eng_links.tsv.bz2",
        "cmn_eng_links": f"{base}/cmn/cmn-eng_links.tsv.bz2",
    }
    paths.tatoeba_dir.mkdir(parents=True, exist_ok=True)
    downloaded: dict[str, Path] = {}
    for key, url in urls.items():
        dest = paths.tatoeba_dir / Path(url).name
        log(f"Downloading {dest.name} ...")
        downloaded[key] = download_if_missing(url, dest, force=False)

    cfg = BuildSentencesConfig(
        jpn_sentences=downloaded["jpn_sentences"],
        cmn_sentences=downloaded["cmn_sentences"],
        eng_sentences=downloaded["eng_sentences"],
        jpn_eng_links=downloaded["jpn_eng_links"],
        cmn_eng_links=downloaded["cmn_eng_links"],
        out_path=paths.data_dir / "sentences.tsv",
        max_per_cp_per_lang=3,
        require_translation=False,
    )
    log("Building sentences.tsv ...")
    stats = build_sentences_tsv(cfg)
    log(f"sentences.tsv rows={stats['rows_total']} cp={stats['distinct_cp']}")


def _download_strokeorder(paths: RuntimePaths, log: Callable[[str], None]) -> None:
    url = "https://codeload.github.com/Svampis/StrokeOrder/zip/refs/heads/master"
    log("Downloading StrokeOrder archive ...")
    req = urllib.request.Request(url, headers={"User-Agent": "kanjitui/0.1"})
    with urllib.request.urlopen(req) as resp:
        content = resp.read()
    with tempfile.TemporaryDirectory(prefix="kanjitui-strokeorder-") as td:
        tmp = Path(td)
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            zf.extractall(tmp)
        extracted = None
        for child in tmp.iterdir():
            if child.is_dir() and (child / "kanji").exists():
                extracted = child
                break
        if extracted is None:
            raise FileNotFoundError("StrokeOrder archive missing kanji/ directory")
        dest = paths.strokeorder_dir
        dest.mkdir(parents=True, exist_ok=True)
        src_kanji = extracted / "kanji"
        dst_kanji = dest / "kanji"
        if dst_kanji.exists():
            shutil.rmtree(dst_kanji)
        shutil.copytree(src_kanji, dst_kanji)
        src_readme = extracted / "README.md"
        if src_readme.exists():
            shutil.copy2(src_readme, dest / "README.md")
    log(f"Installed StrokeOrder data to {paths.strokeorder_dir}")


def download_selected_sources(
    selected: list[str],
    paths: RuntimePaths,
    progress: Callable[[str], None] | None = None,
) -> dict[str, str]:
    results: dict[str, str] = {}

    def log(msg: str) -> None:
        if progress is not None:
            progress(msg)

    for key in selected:
        if key not in SOURCES:
            results[key] = "unknown source"
            continue
        try:
            if key == "unihan":
                _download_unihan(paths, log)
            elif key == "cedict":
                _download_cedict(paths, log)
            elif key in ("kanjidic2", "jmdict"):
                _download_edrdg(paths, log, key)
            elif key == "sentences":
                _download_sentences(paths, log)
            elif key == "strokeorder":
                _download_strokeorder(paths, log)
            results[key] = "ok"
        except Exception as exc:  # noqa: BLE001
            results[key] = f"error: {exc}"
            log(f"{key} failed: {exc}")
    return results
