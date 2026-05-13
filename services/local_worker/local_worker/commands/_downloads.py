"""
Title: _downloads.py — BT4 network and Syzygy tablebase download helpers
Description:
    Stream-download utilities used by the ``setup`` wizard.  Split out so
    that ``commands/setup.py`` itself stays under the Halstead-effort
    quality-gate threshold.

Changelog:
    2026-05-12: Extracted from commands/setup.py (issue #43 follow-up).
"""
from __future__ import annotations

from pathlib import Path

import httpx
import questionary
from rich.progress import BarColumn, DownloadColumn, Progress, TextColumn, TransferSpeedColumn

from local_worker._shared import console, data_dir

_BT4_URL = (
    "https://storage.lczero.org/files/networks-contrib/"
    "BT4-1024x15x32h-swa-6147500-policytune-332.pb.gz"
)
_BT4_FILENAME = "BT4-1024x15x32h-swa-6147500-policytune-332.pb.gz"

_SYZYGY_BASE_URL = "https://tablebase.lichess.ovh/tables/standard/"
_SYZYGY_SUBDIRS = {"rtbw": "3-4-5-wdl", "rtbz": "3-4-5-dtz"}
_SYZYGY_345_POSITIONS = [
    "KBBvK", "KBNvK", "KBPvK", "KBvK", "KBvKB",
    "KBvKN", "KBvKP", "KNNvK", "KNPvK", "KNvK",
    "KNvKN", "KNvKP", "KPPvK", "KPvK", "KPvKP",
    "KQBvK", "KQNvK", "KQPvK", "KQQvK",
    "KQRvK", "KQvK", "KQvKB", "KQvKN", "KQvKP",
    "KQvKQ", "KQvKR", "KRBvK", "KRNvK", "KRPvK",
    "KRRvK", "KRvK", "KRvKB", "KRvKN", "KRvKP",
    "KRvKR",
]
_SYZYGY_345_FILES = [
    f"{position}.{ext}" for position in _SYZYGY_345_POSITIONS for ext in ("rtbw", "rtbz")
]


def _download_file(url: str, dest: Path, label: str) -> bool:
    """Stream-download ``url`` to ``dest``, showing a Rich progress bar.

    Args:
        url: HTTP(S) URL to download.
        dest: Destination file path.
        label: Short label shown in the progress bar.

    Returns:
        True on success, False on any error.
    """
    try:
        with httpx.stream("GET", url, follow_redirects=True, timeout=30) as resp:
            resp.raise_for_status()
            total = int(resp.headers.get("content-length", 0)) or None
            with Progress(
                TextColumn(label),
                BarColumn(),
                DownloadColumn(),
                TransferSpeedColumn(),
            ) as progress:
                task = progress.add_task("", total=total)
                dest.parent.mkdir(parents=True, exist_ok=True)
                with dest.open("wb") as fh:
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        fh.write(chunk)
                        progress.advance(task, len(chunk))
        return True
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]Download failed: {exc}")
        if dest.exists():
            dest.unlink()
        return False


def offer_download_bt4(current_path: str) -> str:
    """Offer to download the BT4 network if no weights are configured.

    Args:
        current_path: Currently configured ``lc0_weights_path``.

    Returns:
        Path string to the weights file (existing, newly downloaded, or empty).
    """
    if current_path and Path(current_path).exists():
        return current_path

    dest = data_dir() / "networks" / _BT4_FILENAME
    if dest.exists():
        console.print(f"  BT4 network: [green]{dest}")
        return str(dest)

    console.print("\n[yellow]No Lc0 network weights found.")
    console.print("  BT4-it332 (~200 MB) will be downloaded from storage.lczero.org")
    if not questionary.confirm("Download BT4-it332 network now?", default=True).ask():
        return questionary.text("Enter path to existing weights file (or leave blank):").ask() or ""

    if _download_file(_BT4_URL, dest, "BT4-it332"):
        console.print(f"[green]Saved to {dest}")
        return str(dest)
    return ""


def offer_download_syzygy(current_path: str) -> str:
    """Offer to download 3-4-5 piece Syzygy tablebases if none are configured.

    Args:
        current_path: Currently configured ``syzygy_path``.

    Returns:
        Path string to the Syzygy directory, or empty string.
    """
    if current_path and Path(current_path).exists():
        return current_path

    console.print("\n[yellow]No Syzygy tablebase path configured.")
    console.print("  3-4-5 piece WDL+DTZ files (~290 MB) will be downloaded from tablebase.lichess.ovh")
    if not questionary.confirm("Download 3-4-5 piece Syzygy tablebases now?", default=False).ask():
        return questionary.text("Enter path to existing Syzygy directory (or leave blank):").ask() or ""

    dest_dir = data_dir() / "syzygy"
    dest_dir.mkdir(parents=True, exist_ok=True)
    failed = 0
    for filename in _SYZYGY_345_FILES:
        ext = filename.rsplit(".", 1)[1]
        url = f"{_SYZYGY_BASE_URL}{_SYZYGY_SUBDIRS[ext]}/{filename}"
        dest = dest_dir / filename
        if dest.exists():
            continue
        if not _download_file(url, dest, filename):
            failed += 1

    if failed:
        console.print(f"[yellow]{failed} files failed — partial tablebase at {dest_dir}")
    else:
        console.print(f"[green]Syzygy tablebases saved to {dest_dir}")
    return str(dest_dir)


__all__ = ["offer_download_bt4", "offer_download_syzygy"]
