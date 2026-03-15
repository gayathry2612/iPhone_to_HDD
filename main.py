#!/usr/bin/env python3
"""iPhone → Mac / HDD File Transfer Tool.

Usage
-----
    python main.py                   # launch interactive TUI
    python main.py list              # list connected device info
    python main.py transfer /DCIM /Volumes/MyHDD/iPhone  # headless transfer
"""
from __future__ import annotations

import asyncio
import sys

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


# ──────────────────────────────────────────────────────────────────────────────
# CLI entry points
# ──────────────────────────────────────────────────────────────────────────────

@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """Transfer files from a connected iPhone to Mac or external HDD."""
    if ctx.invoked_subcommand is None:
        _run_tui()


@cli.command(name="list")
def list_cmd() -> None:
    """Show connected device information."""
    from src.device import connect_device

    console.print(Panel("[bold]Detecting iPhone…[/bold]", expand=False))
    try:
        device = connect_device()
    except RuntimeError as exc:
        console.print(f"[red]✗[/red] {exc}")
        sys.exit(1)

    t = Table(show_header=False, box=None, padding=(0, 2))
    t.add_row("[dim]Name[/dim]", f"[bold]{device.name}[/bold]")
    t.add_row("[dim]Model[/dim]", device.model)
    t.add_row("[dim]iOS[/dim]", device.ios_version)
    t.add_row("[dim]UDID[/dim]", f"[dim]{device.udid}[/dim]")
    console.print(Panel(t, title="[green]✓ Device Connected[/green]", expand=False))


@cli.command()
@click.argument("src_path", default="/DCIM")
@click.argument("destination")
@click.option(
    "--conflict",
    type=click.Choice(["skip", "overwrite", "rename"], case_sensitive=False),
    default="skip",
    show_default=True,
    help="How to handle files that already exist at the destination.",
)
def transfer(src_path: str, destination: str, conflict: str) -> None:
    """Non-interactive transfer of SRC_PATH on iPhone to DESTINATION on Mac.

    \b
    Examples:
      python main.py transfer /DCIM ~/Desktop/iPhone_Photos
      python main.py transfer /DCIM /Volumes/MyHDD/Backup --conflict=rename
    """
    asyncio.run(_transfer_async(src_path, destination, conflict))


async def _transfer_async(src_path: str, destination: str, conflict: str) -> None:
    from pathlib import Path

    import humanize
    from rich.progress import (
        BarColumn, DownloadColumn, Progress, TaskProgressColumn,
        TextColumn, TimeRemainingColumn, TransferSpeedColumn,
    )

    from src.afc import AfcBrowser
    from src.device import connect_device_async
    from src.transfer import ConflictPolicy, TransferProgress, build_jobs, run_transfer

    policy_map = {
        "skip": ConflictPolicy.SKIP,
        "overwrite": ConflictPolicy.OVERWRITE,
        "rename": ConflictPolicy.RENAME,
    }

    dst = Path(destination).expanduser().resolve()

    console.print(Panel("[bold]Connecting to iPhone…[/bold]", expand=False))
    try:
        device = await connect_device_async()
        afc = await AfcBrowser.create(device.lockdown)
    except RuntimeError as exc:
        console.print(f"[red]✗[/red] {exc}")
        sys.exit(1)

    console.print(f"[green]✓[/green] Connected: [bold]{device.name}[/bold] (iOS {device.ios_version})")

    console.print(f"[dim]Scanning {src_path} …[/dim]")
    files = await afc.collect_files(src_path)
    if not files:
        console.print(f"[yellow]No files found under {src_path}[/yellow]")
        return

    selected = {f.path: f.size for f in files}
    jobs = build_jobs(selected, dst)

    total_bytes = sum(f.size for f in files)
    console.print(
        f"[bold]{len(files)} files[/bold]  "
        f"({humanize.naturalsize(total_bytes, binary=True)})  "
        f"→  [cyan]{dst}[/cyan]"
    )

    with Progress(
        TextColumn("[bold blue]{task.fields[filename]}", justify="right"),
        BarColumn(bar_width=None),
        TaskProgressColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        console=console,
        expand=True,
    ) as progress_ui:
        overall = progress_ui.add_task("[cyan]Overall", total=len(files), filename="")
        current = progress_ui.add_task("[green]Current file", total=100, filename="")

        def on_progress(p: TransferProgress) -> None:
            progress_ui.update(overall, completed=p.done_files, filename=f"{p.done_files}/{p.total_files} files")
            if p.total_bytes:
                progress_ui.update(current, completed=int(p.byte_pct), filename=p.current_file)
            if p.finished:
                progress_ui.update(overall, completed=p.total_files)

        await run_transfer(afc, jobs, conflict=policy_map[conflict], on_progress=on_progress)

    console.print("[bold green]✓ Transfer complete![/bold green]")


# ──────────────────────────────────────────────────────────────────────────────
# Interactive TUI
# ──────────────────────────────────────────────────────────────────────────────

def _run_tui() -> None:
    """Launch the interactive TUI.  Runs a single asyncio event loop shared
    by both the pymobiledevice3 async connect and Textual's async runtime."""
    asyncio.run(_run_tui_async())


async def _run_tui_async() -> None:
    from src.afc import AfcBrowser
    from src.device import connect_device_async
    from src.tui import TransferApp

    console.print(
        Panel(
            "[bold cyan]iPhone → Mac File Transfer[/bold cyan]\n"
            "[dim]Connecting to device…[/dim]",
            expand=False,
        )
    )

    try:
        device = await connect_device_async()
        afc = await AfcBrowser.create(device.lockdown)
    except RuntimeError as exc:
        console.print(
            Panel(
                f"[red]✗  Connection failed[/red]\n\n{exc}",
                title="Error",
                border_style="red",
                expand=False,
            )
        )
        sys.exit(1)

    console.print(
        f"[green]✓[/green] Connected: [bold]{device.name}[/bold]  "
        f"(iOS [bold]{device.ios_version}[/bold])\n"
    )
    console.print(
        "[dim]Keybindings inside the TUI:\n"
        "  SPACE     — select / deselect file or directory\n"
        "  A         — select all files in current directory\n"
        "  T         — start transfer\n"
        "  TAB       — switch between iPhone / Destination panels\n"
        "  ← / →     — collapse / expand tree node\n"
        "  ESC       — cancel active transfer\n"
        "  Q         — quit[/dim]\n"
    )

    app = TransferApp(device=device, afc=afc)
    # run_async shares our existing event loop — no nested asyncio.run() needed
    await app.run_async()


# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()
