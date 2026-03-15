# iPhone → Mac File Transfer

A terminal-based file transfer tool that lets you browse and copy files from your iPhone to your Mac or any external HDD — no iTunes, no Finder, no GUI required.

---

## Features

- **Interactive TUI** — two-panel browser (iPhone on the left, destination on the right)
- **Checkbox selection** — select individual files, whole folders, or everything at once
- **Live progress bar** — per-file and overall transfer progress
- **Conflict handling** — skip, overwrite, or auto-rename existing files
- **Headless CLI mode** — scriptable one-liner transfers for automation
- **No jailbreak needed** — communicates over USB using the same protocol as Finder/iTunes

---

## What's accessible on a stock iPhone

| Path | Contents |
|------|----------|
| `/DCIM/` | Camera roll — photos, videos, screenshots |
| `/PhotoData/` | Album metadata, thumbnails |
| `/Books/` | ePub / PDF files from Apple Books |
| App documents | Files from apps with **iTunes File Sharing** enabled |

> App documents live under the app's own sandbox. Enable file sharing per-app via **Files → On My iPhone → [App Name]**.

---

## Requirements

| Requirement | Notes |
|-------------|-------|
| macOS 12+ | |
| Python 3.10+ | `brew install python` |
| Homebrew | [brew.sh](https://brew.sh) |
| `libimobiledevice` | installed automatically by `install.sh` |
| iPhone cable | Lightning or USB-C |

---

## Installation

```bash
git clone <this-repo>
cd Photo_transfer

# One-time setup: Homebrew libs + Python venv + pip packages
./install.sh

# Activate the virtual environment
source .venv/bin/activate
```

---

## Usage

### Interactive TUI (recommended)

```bash
python main.py
```

Connect your iPhone, unlock it, and tap **"Trust This Computer"** when prompted.

```
┌─ iPhone Transfer · Gayathry's iPhone · iOS 17.4 ──────────────────────────────┐
│┌─ 📱 iPhone ──────────────────────────┐┌─ 💻 Destination ────────────────────┐│
││ ▶ 📁 DCIM/                           ││ /Volumes/                            ││
││   ☑ 📁 100APPLE/                     ││   ▶ 📁 MyHDD/                       ││
││     ☑ 🖼  IMG_0042.HEIC   4.1 MiB    ││     ▶ 📁 iPhone_Backup/             ││
││     ☑ 🎬 VID_0043.MOV   231.4 MiB   ││                                      ││
││     ☐ 🖼  IMG_0044.JPG    3.2 MiB    ││                                      ││
││   ☐ 📁 101APPLE/                     ││                                      ││
│└──────────────────────────────────────┘└─────────────────────────────────────┘│
│ ✓ 2 files  (235.5 MiB)  →  /Volumes/MyHDD/iPhone_Backup/                      │
│ [SPACE] Select  [A] All in dir  [T] Transfer  [TAB] Switch panel  [Q] Quit     │
└────────────────────────────────────────────────────────────────────────────────┘
```

#### Keybindings

| Key | Action |
|-----|--------|
| `↑ ↓` | Navigate files |
| `→` / `←` | Expand / collapse folder |
| `Space` | Select / deselect file or folder (recursive) |
| `A` | Select all files in the current directory |
| `Tab` | Switch focus between iPhone and Destination panels |
| `T` | Start transfer |
| `Esc` | Cancel an active transfer |
| `Q` | Quit |

**Choosing a destination:** Switch to the right panel with `Tab`, navigate to your target folder, and click or press `Enter` to select it. The status bar updates immediately.

---

### Headless CLI mode

#### Check device info

```bash
python main.py list
```

```
╭─ ✓ Device Connected ──╮
│  Name    Gayathry's iPhone
│  Model   iPhone17,2
│  iOS     17.4
│  UDID    0000000-…
╰───────────────────────╯
```

#### Transfer a folder

```bash
# Transfer all photos/videos to an external HDD
python main.py transfer /DCIM /Volumes/MyHDD/iPhone_Backup

# Transfer with rename on conflict (keeps both old and new file)
python main.py transfer /DCIM /Volumes/MyHDD --conflict=rename

# Transfer Books to Desktop
python main.py transfer /Books ~/Desktop/iPhone_Books
```

| `--conflict` | Behaviour |
|---|---|
| `skip` *(default)* | Skip the file if it already exists at the destination |
| `overwrite` | Replace the existing file |
| `rename` | Keep both — appends `_1`, `_2`, … to the new file |

---

## Project Structure

```
Photo_transfer/
├── main.py             # CLI entry point (click commands + TUI launcher)
├── requirements.txt
├── install.sh          # One-time setup script
└── src/
    ├── device.py       # iPhone USB connection (pymobiledevice3 async API)
    ├── afc.py          # AFC filesystem: list, walk, chunked file reads
    ├── transfer.py     # Transfer engine with progress callbacks
    └── tui.py          # Textual two-panel TUI
```

---

## Troubleshooting

**"No iPhone detected"**
- Make sure the cable is firmly connected
- Unlock your iPhone before running the app
- Try a different USB port or cable

**"iPhone not trusted"**
- A "Trust This Computer?" dialog should appear on your iPhone — tap **Trust**
- If the dialog never appeared, go to **Settings → General → Transfer or Reset iPhone → Reset → Reset Location & Privacy**, then reconnect

**AFC returns no files under `/DCIM`**
- Some iOS versions require the Photos app to be opened at least once after unlock before AFC exposes DCIM
- Open the Photos app on your iPhone, then rerun the transfer

**"pymobiledevice3 is not installed"**
- Run `source .venv/bin/activate` first, or rerun `./install.sh`

**Permission error writing to external HDD**
- Ensure the drive is formatted as **exFAT** or **APFS** (not NTFS — macOS can't write to NTFS by default)
- Check the drive isn't locked: `ls -la /Volumes/MyHDD`

---

## Dependencies

| Package | Purpose |
|---------|---------|
| [pymobiledevice3](https://github.com/doronz88/pymobiledevice3) | USB communication with iPhone via AFC protocol |
| [textual](https://github.com/Textualize/textual) | Terminal UI framework |
| [rich](https://github.com/Textualize/rich) | Styled terminal output and progress bars |
| [click](https://click.palletsprojects.com) | CLI argument parsing |
| [humanize](https://github.com/python-humanize/humanize) | Human-readable file sizes |
