"""FastAPI web server for iPhone Transfer.

Endpoints
---------
POST /api/connect               — pair & connect to USB iPhone
GET  /api/device                — device info / connection status
GET  /api/iphone/files?path=    — list one directory via AFC
GET  /api/iphone/collect?path=  — recursive file list (for select-all)
GET  /api/local/files?path=     — list a local directory
GET  /api/local/shortcuts       — home / desktop / downloads / volumes
POST /api/transfer              — start transfer, responds with SSE stream
POST /api/transfer/cancel       — cancel active transfer
POST /api/open-folder           — open destination in Finder
GET  /                          — serves web/static/index.html
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import threading
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── project root on path ─────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.device import connect_device_async, DeviceInfo
from src.afc import AfcBrowser
from src.transfer import ConflictPolicy, TransferProgress, build_jobs, run_transfer

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="iPhone Transfer", docs_url=None, redoc_url=None)

# ── Mutable state (single server process, single user) ───────────────────────
_device: Optional[DeviceInfo] = None
_afc: Optional[AfcBrowser] = None
_cancel_event = threading.Event()


def _need_afc() -> AfcBrowser:
    if _afc is None:
        raise HTTPException(503, detail="iPhone not connected. POST /api/connect first.")
    return _afc


# ── Device ────────────────────────────────────────────────────────────────────

@app.post("/api/connect")
async def connect():
    global _device, _afc
    try:
        _device = await connect_device_async()
        _afc = await AfcBrowser.create(_device.lockdown)
    except RuntimeError as exc:
        raise HTTPException(503, detail=str(exc))
    return _device_dict()


@app.get("/api/device")
def device_status():
    if _device is None:
        return {"connected": False}
    return _device_dict()


def _device_dict() -> dict:
    return {
        "connected": True,
        "name": _device.name,
        "model": _device.model,
        "ios_version": _device.ios_version,
        "udid": _device.udid,
    }


# ── iPhone files ──────────────────────────────────────────────────────────────

@app.get("/api/iphone/files")
async def iphone_files(path: str = "/"):
    afc = _need_afc()
    entries = await afc.listdir(path)
    return [
        {"path": e.path, "name": e.name, "is_dir": e.is_dir, "size": e.size}
        for e in entries
    ]


@app.get("/api/iphone/collect")
async def iphone_collect(path: str = "/DCIM"):
    """Return all files recursively — used for folder-level select-all."""
    afc = _need_afc()
    files = await afc.collect_files(path)
    return [{"path": f.path, "name": f.name, "size": f.size} for f in files]


# ── Local filesystem ──────────────────────────────────────────────────────────

@app.get("/api/local/files")
def local_files(path: str = "/"):
    p = Path(path).expanduser()
    if not p.exists():
        return []
    result = []
    try:
        items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
        for item in items:
            if item.name.startswith("."):
                continue
            try:
                result.append({
                    "path": str(item),
                    "name": item.name,
                    "is_dir": item.is_dir(),
                    "size": item.stat().st_size if item.is_file() else 0,
                })
            except (PermissionError, OSError):
                pass
    except (PermissionError, OSError):
        pass
    return result


@app.get("/api/local/shortcuts")
def local_shortcuts():
    home = Path.home()
    shortcuts = [
        {"path": str(home),               "name": "Home",      "icon": "🏠"},
        {"path": str(home / "Desktop"),   "name": "Desktop",   "icon": "🖥"},
        {"path": str(home / "Downloads"), "name": "Downloads", "icon": "⬇️"},
        {"path": str(home / "Pictures"),  "name": "Pictures",  "icon": "🖼"},
    ]
    volumes = Path("/Volumes")
    if volumes.exists():
        for v in sorted(volumes.iterdir()):
            try:
                if v.is_dir() and not v.name.startswith("."):
                    icon = "💿" if v.name == "Macintosh HD" else "💾"
                    shortcuts.append({"path": str(v), "name": v.name, "icon": icon})
            except OSError:
                pass
    return shortcuts


# ── Open in Finder ────────────────────────────────────────────────────────────

class OpenFolderBody(BaseModel):
    path: str


@app.post("/api/open-folder")
def open_folder(body: OpenFolderBody):
    try:
        subprocess.Popen(["open", body.path])
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


# ── Transfer (SSE stream over POST) ──────────────────────────────────────────

class TransferRequest(BaseModel):
    selected: dict   # { afc_path: size_int }
    destination: str
    conflict: str = "skip"


@app.post("/api/transfer")
async def transfer_sse(req: TransferRequest):
    afc = _need_afc()

    policy_map = {
        "skip":      ConflictPolicy.SKIP,
        "overwrite": ConflictPolicy.OVERWRITE,
        "rename":    ConflictPolicy.RENAME,
    }
    policy = policy_map.get(req.conflict, ConflictPolicy.SKIP)

    dst = Path(req.destination).expanduser().resolve()
    selected = {k: int(v) for k, v in req.selected.items()}
    jobs = build_jobs(selected, dst)

    _cancel_event.clear()
    # run_transfer is now async — drive it directly in the event loop.
    # We buffer each progress event into an asyncio.Queue so the SSE
    # generator can yield them without blocking.
    queue: asyncio.Queue = asyncio.Queue()

    def on_progress(p: TransferProgress) -> None:
        # Called synchronously from run_transfer (same event loop thread).
        queue.put_nowait({
            "total_files":  p.total_files,
            "done_files":   p.done_files,
            "total_bytes":  p.total_bytes,
            "done_bytes":   p.done_bytes,
            "current_file": p.current_file,
            "skipped":      p.skipped,
            "errors":       p.errors[-3:],
            "finished":     p.finished,
            "cancelled":    p.cancelled,
            "file_pct":     round(p.file_pct, 1),
            "byte_pct":     round(p.byte_pct, 1),
        })

    async def stream():
        yield f"data: {json.dumps({'status': 'started', 'total_files': len(jobs)})}\n\n"
        # Start the transfer as a background task so the SSE generator
        # can drain the queue while transfer is running.
        task = asyncio.create_task(
            run_transfer(afc, jobs, conflict=policy,
                         on_progress=on_progress, cancel_event=_cancel_event)
        )
        while True:
            try:
                data = await asyncio.wait_for(queue.get(), timeout=60.0)
                yield f"data: {json.dumps(data)}\n\n"
                if data.get("finished") or data.get("cancelled"):
                    break
            except asyncio.TimeoutError:
                if task.done():
                    break
                yield 'data: {"ping":true}\n\n'
        await task   # surface any exception

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/transfer/cancel")
def cancel_transfer():
    _cancel_event.set()
    return {"cancelled": True}


# ── Static files (must be last) ───────────────────────────────────────────────
_static = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=str(_static), html=True), name="static")


# ── Dev entry point ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    uvicorn.run("web.server:app", host="127.0.0.1", port=8765, reload=True)
