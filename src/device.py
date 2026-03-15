"""iPhone device detection and connection management.

In pymobiledevice3 v4+, ``create_using_usbmux`` is an async coroutine.
This module exposes:

  * ``connect_device_async()`` — awaitable, used from within an existing
    asyncio event loop (e.g. when launching the Textual TUI).

  * ``connect_device()`` — synchronous wrapper via ``asyncio.run()``, safe
    to call from plain CLI commands that have no running event loop.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DeviceInfo:
    name: str
    model: str
    ios_version: str
    udid: str
    lockdown: object  # LockdownClient — typed loosely to avoid import at module level


async def connect_device_async() -> DeviceInfo:
    """Async connect — await this inside an existing event loop."""
    try:
        from pymobiledevice3.lockdown import create_using_usbmux
    except ImportError:
        raise RuntimeError(
            "pymobiledevice3 is not installed.  Run:  pip install pymobiledevice3"
        )

    try:
        lockdown = await create_using_usbmux()
    except Exception as exc:
        name = type(exc).__name__
        if any(k in name for k in ("NoDevice", "NotFound", "NotConnected")):
            raise RuntimeError(
                "No iPhone detected.\n"
                "  • Connect your iPhone with a USB cable\n"
                "  • Unlock the screen and tap 'Trust This Computer' if prompted"
            ) from exc
        if any(k in name for k in ("Pairing", "Trust", "InvalidPair")):
            raise RuntimeError(
                "iPhone not trusted.\n"
                "  • Unlock your iPhone and tap 'Trust This Computer'\n"
                "  • Then run this app again"
            ) from exc
        raise RuntimeError(f"Connection failed ({name}): {exc}") from exc

    # short_info is a sync property available after the lockdown is established
    try:
        info = lockdown.short_info          # dict with DeviceName, ProductVersion, …
    except Exception:
        info = {}

    return DeviceInfo(
        name=info.get("DeviceName") or getattr(lockdown, "name", "iPhone"),
        model=info.get("ProductType") or getattr(lockdown, "product_type", "Unknown"),
        ios_version=info.get("ProductVersion") or getattr(lockdown, "product_version", "Unknown"),
        udid=str(info.get("UniqueDeviceID") or getattr(lockdown, "identifier", getattr(lockdown, "udid", "unknown"))),
        lockdown=lockdown,
    )


def connect_device() -> DeviceInfo:
    """Synchronous connect — safe to call from non-async CLI entry points."""
    return asyncio.run(connect_device_async())
