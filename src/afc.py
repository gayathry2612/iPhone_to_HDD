"""AFC (Apple File Conduit) filesystem wrapper.

AFC gives access to the iPhone media partition which includes:
  /DCIM/         – Camera roll photos and videos
  /PhotoData/    – Thumbnails and metadata
  /Books/        – iBooks / Apple Books files
  /iTunes_Control/ – Synced media

In pymobiledevice3 v4+, *all* AfcService I/O methods (listdir, stat,
get_file_contents, …) are async coroutines.  Every public method on
AfcBrowser is therefore async.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import AsyncIterator

CHUNK_SIZE = 256 * 1024  # 256 KB per read chunk

_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".gif", ".webp", ".tiff", ".bmp", ".raw"}
_VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".3gp", ".mts"}
_AUDIO_EXTS = {".mp3", ".m4a", ".aac", ".flac", ".wav", ".ogg"}


def file_icon(name: str, is_dir: bool) -> str:
    if is_dir:
        return "📁"
    ext = Path(name).suffix.lower()
    if ext in _IMAGE_EXTS:
        return "🖼 "
    if ext in _VIDEO_EXTS:
        return "🎬"
    if ext in _AUDIO_EXTS:
        return "🎵"
    if ext == ".pdf":
        return "📄"
    return "📎"


@dataclass
class AfcEntry:
    path: str       # full path on the iPhone (e.g. /DCIM/100APPLE/IMG_001.JPG)
    name: str       # filename only
    is_dir: bool
    size: int = 0   # 0 for directories


class AfcBrowser:
    """Async wrapper around AfcService.

    All I/O methods are async — use ``await`` everywhere.

    Create instances via the factory methods:

        afc = await AfcBrowser.create(lockdown)       # inside an event loop
        afc = AfcBrowser.create_sync(lockdown)         # no event loop running
    """

    def __init__(self, svc: object) -> None:
        """Private — pass an already-connected AfcService instance."""
        self._svc = svc

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    async def create(cls, lockdown: object) -> "AfcBrowser":
        """Async factory: create and connect the AFC service."""
        from pymobiledevice3.services.afc import AfcService
        svc = AfcService(lockdown)  # type: ignore[arg-type]
        await svc.connect()
        return cls(svc)

    @classmethod
    def create_sync(cls, lockdown: object) -> "AfcBrowser":
        """Sync factory: safe to call when no event loop is running (CLI)."""
        import asyncio
        return asyncio.run(cls.create(lockdown))

    # ------------------------------------------------------------------
    # Directory listing
    # ------------------------------------------------------------------

    async def listdir(self, path: str) -> list[AfcEntry]:
        """Return sorted entries (dirs first, then files) for *path*."""
        try:
            names: list[str] = await self._svc.listdir(path)
        except Exception:
            return []

        entries: list[AfcEntry] = []
        for name in names:
            if name in (".", ".."):
                continue
            full = str(PurePosixPath(path) / name)
            try:
                info = await self._svc.stat(full)
                is_dir = info.get("st_ifmt") == "S_IFDIR"
                size = int(info.get("st_size", 0))
            except Exception:
                is_dir = False
                size = 0
            entries.append(AfcEntry(path=full, name=name, is_dir=is_dir, size=size))

        return sorted(entries, key=lambda e: (not e.is_dir, e.name.lower()))

    # ------------------------------------------------------------------
    # Walking
    # ------------------------------------------------------------------

    async def walk(self, path: str) -> AsyncIterator[tuple[str, list[AfcEntry], list[AfcEntry]]]:
        """Async-yield (dirpath, subdirs, files) recursively, like os.walk."""
        entries = await self.listdir(path)
        subdirs = [e for e in entries if e.is_dir]
        files = [e for e in entries if not e.is_dir]
        yield path, subdirs, files
        for d in subdirs:
            async for item in self.walk(d.path):
                yield item

    async def collect_files(self, path: str) -> list[AfcEntry]:
        """Recursively collect all files under *path*."""
        result: list[AfcEntry] = []
        async for _, _, files in self.walk(path):
            result.extend(files)
        return result

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    async def read_chunks(self, path: str) -> AsyncIterator[bytes]:
        """Async-yield file data in chunks — avoids loading large videos into RAM."""
        data: bytes = await self._svc.get_file_contents(path)
        for i in range(0, len(data), CHUNK_SIZE):
            yield data[i : i + CHUNK_SIZE]

    async def file_size(self, path: str) -> int:
        try:
            info = await self._svc.stat(path)
            return int(info.get("st_size", 0))
        except Exception:
            return 0
