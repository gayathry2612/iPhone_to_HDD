"""File transfer engine: iPhone (AFC) → local destination.

``run_transfer`` is an async coroutine — all AFC reads are async in
pymobiledevice3 v4+.  Disk writes are synchronous (fast) and stay on
the calling event loop thread.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path, PurePosixPath
from typing import Callable

from .afc import AfcBrowser, AfcEntry


class ConflictPolicy(Enum):
    SKIP = auto()       # skip if destination file already exists
    OVERWRITE = auto()  # always overwrite
    RENAME = auto()     # rename new file (append _1, _2, …)


@dataclass
class TransferJob:
    """A single file to transfer."""
    src_path: str       # full AFC path on iPhone
    src_size: int       # bytes
    dst_path: Path      # full local destination path


@dataclass
class TransferProgress:
    total_files: int = 0
    done_files: int = 0
    total_bytes: int = 0
    done_bytes: int = 0
    current_file: str = ""
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    finished: bool = False
    cancelled: bool = False

    @property
    def file_pct(self) -> float:
        return (self.done_files / self.total_files * 100) if self.total_files else 0.0

    @property
    def byte_pct(self) -> float:
        return (self.done_bytes / self.total_bytes * 100) if self.total_bytes else 0.0


ProgressCallback = Callable[["TransferProgress"], None]


def _unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    counter = 1
    while True:
        candidate = path.with_name(f"{stem}_{counter}{suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


def build_jobs(
    selected: dict[str, int],   # afc_path → size
    destination: Path,
    strip_prefix: str = "/",
) -> list[TransferJob]:
    """Convert a selection dict into a list of TransferJob objects."""
    jobs: list[TransferJob] = []
    for afc_path, size in selected.items():
        rel = PurePosixPath(afc_path)
        try:
            rel = rel.relative_to(strip_prefix.rstrip("/"))
        except ValueError:
            rel = PurePosixPath(*rel.parts[1:]) if rel.parts else rel
        local_path = destination / Path(*rel.parts) if rel.parts else destination / rel.name
        jobs.append(TransferJob(src_path=afc_path, src_size=size, dst_path=local_path))
    return jobs


async def run_transfer(
    afc: AfcBrowser,
    jobs: list[TransferJob],
    conflict: ConflictPolicy = ConflictPolicy.SKIP,
    on_progress: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> TransferProgress:
    """Transfer *jobs* from the iPhone to local disk.

    All AFC I/O is async.  Call with ``await`` inside an asyncio event loop.
    The ``on_progress`` callback is called synchronously from the event loop —
    keep it fast (no blocking I/O).
    """
    progress = TransferProgress(
        total_files=len(jobs),
        total_bytes=sum(j.src_size for j in jobs),
    )

    def _notify() -> None:
        if on_progress:
            on_progress(progress)

    for job in jobs:
        if cancel_event and cancel_event.is_set():
            progress.cancelled = True
            break

        progress.current_file = Path(job.src_path).name
        _notify()

        dst = job.dst_path
        if dst.exists():
            if conflict == ConflictPolicy.SKIP:
                progress.skipped += 1
                progress.done_files += 1
                progress.done_bytes += job.src_size
                _notify()
                continue
            elif conflict == ConflictPolicy.RENAME:
                dst = _unique_path(dst)

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            progress.errors.append(f"{job.src_path}: cannot create dir — {exc}")
            progress.done_files += 1
            _notify()
            continue

        try:
            with open(dst, "wb") as fout:
                async for chunk in afc.read_chunks(job.src_path):
                    if cancel_event and cancel_event.is_set():
                        progress.cancelled = True
                        break
                    fout.write(chunk)
                    progress.done_bytes += len(chunk)
                    _notify()
        except Exception as exc:
            progress.errors.append(f"{job.src_path}: {exc}")
            try:
                dst.unlink(missing_ok=True)
            except OSError:
                pass

        if progress.cancelled:
            break

        progress.done_files += 1
        _notify()

    progress.finished = True
    _notify()
    return progress
