"""Textual TUI for the iPhone → Mac/HDD file transfer tool.

Layout
------
┌─ iPhone Transfer ─────────────── device: iPhone 14  iOS 17  ──────────────────┐
│┌─ 📱 iPhone ─────────────────────┐┌─ 💻 Destination ──────────────────────────┐│
││ ▶ 📁 DCIM/                      ││ /Volumes/                                  ││
││   ☑ 📁 100APPLE/                ││   ▶ 📁 MyHDD/                             ││
││     ☑ 🖼  IMG_001.JPG  4.2 MB   ││     ▶ 📁 iPhone_Backup/                  ││
││     ☐ 🖼  IMG_002.JPG  3.1 MB   ││                                            ││
││   ☐ 📁 101APPLE/                ││                                            ││
│└─────────────────────────────────┘└────────────────────────────────────────────┘│
│ Selected: 23 files  (156 MB)   →  /Volumes/MyHDD/iPhone_Backup/                │
│ [SPACE] Select  [A] All in dir  [T] Transfer  [TAB] Switch panel  [Q] Quit      │
└────────────────────────────────────────────────────────────────────────────────┘
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import humanize
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.reactive import reactive
from textual.widgets import (
    DirectoryTree,
    Footer,
    Header,
    Label,
    ProgressBar,
    Static,
    Tree,
)
from textual.widgets._tree import TreeNode

from .afc import AfcBrowser, AfcEntry, file_icon
from .device import DeviceInfo
from .transfer import ConflictPolicy, TransferProgress, build_jobs, run_transfer

# ──────────────────────────────────────────────────────────────────────────────
# Helper data attached to every tree node
# ──────────────────────────────────────────────────────────────────────────────

class _NodeData:
    """Payload stored in each iPhone tree node."""
    __slots__ = ("entry", "selected", "loaded")

    def __init__(self, entry: AfcEntry) -> None:
        self.entry = entry
        self.selected: bool = False
        self.loaded: bool = False   # children loaded?


# ──────────────────────────────────────────────────────────────────────────────
# iPhone file-tree widget
# ──────────────────────────────────────────────────────────────────────────────

class IPhoneTree(Tree):
    """Lazy-loading tree that displays iPhone AFC file system."""

    BORDER_TITLE = "📱 iPhone"

    class SelectionChanged(Message):
        """Fired when the file selection changes."""
        def __init__(self, selected: dict[str, int]) -> None:
            super().__init__()
            self.selected = selected   # afc_path → size

    def __init__(self, afc: AfcBrowser, **kwargs: Any) -> None:
        super().__init__("/ (root)", **kwargs)
        self._afc = afc
        self._selected: dict[str, int] = {}   # afc_path → size

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    async def on_mount(self) -> None:
        self.root.expand()
        await self._load_children(self.root, "/")

    async def _load_children(self, node: TreeNode, path: str) -> None:
        """Populate *node* with the children of *path*."""
        data: _NodeData | None = node.data
        if data and data.loaded:
            return
        if data:
            data.loaded = True

        entries = await self._afc.listdir(path)
        for entry in entries:
            icon = file_icon(entry.name, entry.is_dir)
            size_str = f"  {humanize.naturalsize(entry.size, binary=True)}" if not entry.is_dir else ""
            label = f"☐ {icon} {entry.name}{size_str}"
            child = node.add(label, data=_NodeData(entry), expand=False)

    # ------------------------------------------------------------------
    # Interaction
    # ------------------------------------------------------------------

    async def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        nd: _NodeData | None = event.node.data
        if nd and nd.entry.is_dir and not nd.loaded:
            await self._load_children(event.node, nd.entry.path)

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """SPACE / click on a file node toggles its selection."""
        nd: _NodeData | None = event.node.data
        if nd is None or nd.entry.is_dir:
            return
        self._toggle_node(event.node, nd)

    def action_toggle_selected(self) -> None:
        """Bound to SPACE — toggle the currently highlighted node."""
        cursor = self.cursor_node
        if cursor is None:
            return
        nd: _NodeData | None = cursor.data
        if nd is None:
            return
        if nd.entry.is_dir:
            self._toggle_dir(cursor, nd)
        else:
            self._toggle_node(cursor, nd)

    def action_select_all(self) -> None:
        """Select all files under the currently highlighted directory."""
        cursor = self.cursor_node
        if cursor is None:
            return
        nd: _NodeData | None = cursor.data
        if nd and nd.entry.is_dir:
            self._toggle_dir(cursor, nd, force_select=True)
        elif cursor.parent:
            self._toggle_dir(cursor.parent, cursor.parent.data, force_select=True)

    def _toggle_node(self, node: TreeNode, nd: _NodeData) -> None:
        nd.selected = not nd.selected
        self._update_label(node, nd)
        if nd.selected:
            self._selected[nd.entry.path] = nd.entry.size
        else:
            self._selected.pop(nd.entry.path, None)
        self.post_message(self.SelectionChanged(dict(self._selected)))

    def _toggle_dir(
        self,
        node: TreeNode,
        nd: _NodeData | None,
        force_select: bool = False,
    ) -> None:
        """Recursively toggle / select all files under already-loaded tree nodes.

        Note: only operates on nodes already loaded in the tree (no lazy fetch
        here — use action_select_all which is async for the full recursive case).
        """
        if nd is None:
            return

        changed = False
        for child in node.children:
            cnd: _NodeData | None = child.data
            if cnd is None:
                continue
            if cnd.entry.is_dir:
                self._toggle_dir(child, cnd, force_select=force_select)
            else:
                want = force_select if force_select else (not cnd.selected)
                if cnd.selected != want:
                    cnd.selected = want
                    self._update_label(child, cnd)
                    if want:
                        self._selected[cnd.entry.path] = cnd.entry.size
                    else:
                        self._selected.pop(cnd.entry.path, None)
                    changed = True

        if changed:
            self.post_message(self.SelectionChanged(dict(self._selected)))

    @staticmethod
    def _update_label(node: TreeNode, nd: _NodeData) -> None:
        icon = file_icon(nd.entry.name, nd.entry.is_dir)
        size_str = f"  {humanize.naturalsize(nd.entry.size, binary=True)}" if not nd.entry.is_dir else ""
        checkbox = "☑" if nd.selected else "☐"
        node.set_label(f"{checkbox} {icon} {nd.entry.name}{size_str}")

    @property
    def selected(self) -> dict[str, int]:
        return dict(self._selected)


# ──────────────────────────────────────────────────────────────────────────────
# Status / transfer bar at the bottom
# ──────────────────────────────────────────────────────────────────────────────

class StatusBar(Static):
    """One-line status: selection summary + current destination."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        padding: 0 1;
        background: $panel;
        color: $text;
    }
    """

    selected_count: reactive[int] = reactive(0)
    selected_bytes: reactive[int] = reactive(0)
    destination: reactive[str] = reactive("")

    def render(self) -> str:  # type: ignore[override]
        if self.selected_count == 0:
            sel = "[dim]No files selected[/dim]"
        else:
            sel = (
                f"[bold green]✓ {self.selected_count} file"
                f"{'s' if self.selected_count != 1 else ''}"
                f"  ({humanize.naturalsize(self.selected_bytes, binary=True)})[/bold green]"
            )
        dst = f"  →  [cyan]{self.destination}[/cyan]" if self.destination else "  [dim](no destination)[/dim]"
        return sel + dst


class TransferBar(Static):
    """Progress display shown during an active transfer."""

    DEFAULT_CSS = """
    TransferBar {
        height: 3;
        padding: 0 1;
        background: $panel;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("", id="xfr-file-label")
        yield ProgressBar(total=100, show_eta=False, id="xfr-progress")

    def update_progress(self, p: TransferProgress) -> None:
        label = self.query_one("#xfr-file-label", Label)
        bar = self.query_one("#xfr-progress", ProgressBar)
        if p.finished:
            errs = f"  [red]{len(p.errors)} error(s)[/red]" if p.errors else ""
            label.update(
                f"[bold green]✓ Transfer complete[/bold green]  "
                f"{p.done_files} files  "
                f"({humanize.naturalsize(p.done_bytes, binary=True)})"
                f"{errs}"
            )
            bar.update(progress=100)
        elif p.cancelled:
            label.update("[bold yellow]⚠ Transfer cancelled[/bold yellow]")
        else:
            label.update(
                f"[cyan]{p.current_file}[/cyan]"
                f"  {p.done_files}/{p.total_files} files"
                f"  ({humanize.naturalsize(p.done_bytes, binary=True)}"
                f" / {humanize.naturalsize(p.total_bytes, binary=True)})"
            )
            bar.update(progress=int(p.byte_pct))


# ──────────────────────────────────────────────────────────────────────────────
# Main application
# ──────────────────────────────────────────────────────────────────────────────

class TransferApp(App):
    """Two-panel file transfer application."""

    TITLE = "iPhone Transfer"

    CSS = """
    Screen {
        layout: vertical;
    }
    #panels {
        height: 1fr;
    }
    #iphone-panel {
        width: 1fr;
        border: solid $accent;
        border-title-align: left;
    }
    #dest-panel {
        width: 1fr;
        border: solid $primary;
        border-title-align: left;
    }
    IPhoneTree {
        height: 1fr;
    }
    #dest-tree {
        height: 1fr;
    }
    #transfer-bar {
        display: none;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("t", "start_transfer", "Transfer", priority=True),
        Binding("space", "toggle_select", "Select", show=False),
        Binding("a", "select_all", "Select all in dir", show=False),
        Binding("tab", "switch_panel", "Switch panel", show=False),
        Binding("escape", "cancel_transfer", "Cancel", show=False),
    ]

    def __init__(self, device: DeviceInfo, afc: AfcBrowser, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._device = device
        self._afc = afc  # pre-connected via AfcBrowser.create()
        self._selected: dict[str, int] = {}
        self._destination: Path | None = None
        self._cancel_event = threading.Event()
        self._transferring = False

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="panels"):
            with Vertical(id="iphone-panel", classes="panel"):
                yield IPhoneTree(self._afc, id="iphone-tree")
            with Vertical(id="dest-panel", classes="panel"):
                yield DirectoryTree("/", id="dest-tree")
        yield StatusBar(id="status-bar")
        yield TransferBar(id="transfer-bar")
        yield Footer()

    def on_mount(self) -> None:
        self.title = f"iPhone Transfer  •  {self._device.name}  iOS {self._device.ios_version}"
        iphone_panel = self.query_one("#iphone-panel")
        iphone_panel.border_title = "📱 iPhone"
        dest_panel = self.query_one("#dest-panel")
        dest_panel.border_title = "💻 Destination  (navigate to choose folder)"
        # Default destination = home Downloads
        default_dst = Path.home() / "Downloads"
        self._destination = default_dst
        self._refresh_status()
        # Focus the iPhone tree
        self.query_one("#iphone-tree").focus()

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    def on_iphone_tree_selection_changed(self, msg: IPhoneTree.SelectionChanged) -> None:
        self._selected = msg.selected
        self._refresh_status()

    def on_directory_tree_directory_selected(
        self, event: DirectoryTree.DirectorySelected
    ) -> None:
        """User clicked a folder in the destination tree — use it as destination."""
        self._destination = Path(event.path)
        self._refresh_status()
        dest_panel = self.query_one("#dest-panel")
        dest_panel.border_title = f"💻 Destination: {self._destination}"

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def action_toggle_select(self) -> None:
        focused = self.focused
        if isinstance(focused, IPhoneTree):
            focused.action_toggle_selected()

    def action_select_all(self) -> None:
        focused = self.focused
        if isinstance(focused, IPhoneTree):
            focused.action_select_all()

    def action_switch_panel(self) -> None:
        iphone = self.query_one("#iphone-tree")
        dest = self.query_one("#dest-tree")
        if self.focused is iphone:
            dest.focus()
        else:
            iphone.focus()

    def action_start_transfer(self) -> None:
        if self._transferring:
            return
        if not self._selected:
            self.notify("No files selected. Press SPACE to select files.", severity="warning")
            return
        if self._destination is None:
            self.notify("No destination chosen. Browse the right panel and click a folder.", severity="warning")
            return
        self._start_transfer()

    def action_cancel_transfer(self) -> None:
        if self._transferring:
            self._cancel_event.set()
            self.notify("Cancelling transfer…", severity="warning")

    # ------------------------------------------------------------------
    # Transfer worker
    # ------------------------------------------------------------------

    def _start_transfer(self) -> None:
        self._transferring = True
        self._cancel_event.clear()

        # Show progress bar, hide status bar
        self.query_one("#transfer-bar").display = True
        self.query_one("#status-bar").display = False

        jobs = build_jobs(self._selected, self._destination)  # type: ignore[arg-type]
        self._do_transfer(jobs)

    @work(exclusive=True)
    async def _do_transfer(self, jobs: list) -> None:
        # run_transfer is async — drive it directly in Textual's event loop.
        def on_progress(p: TransferProgress) -> None:
            # Called synchronously from run_transfer; already on the event loop.
            self._update_transfer_ui(p)

        await run_transfer(
            self._afc,
            jobs,
            conflict=ConflictPolicy.SKIP,
            on_progress=on_progress,
            cancel_event=self._cancel_event,
        )

    def _update_transfer_ui(self, p: TransferProgress) -> None:
        bar = self.query_one("#transfer-bar", TransferBar)
        bar.update_progress(p)

        if p.finished or p.cancelled:
            self._transferring = False
            if p.errors:
                for err in p.errors[:5]:
                    self.notify(f"Error: {err}", severity="error")
            if p.finished and not p.cancelled:
                self.notify(
                    f"Done!  {p.done_files} file(s) transferred to {self._destination}",
                    severity="information",
                    timeout=8,
                )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _refresh_status(self) -> None:
        bar = self.query_one("#status-bar", StatusBar)
        bar.selected_count = len(self._selected)
        bar.selected_bytes = sum(self._selected.values())
        bar.destination = str(self._destination) if self._destination else ""
