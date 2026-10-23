# 🚀 WSL Linker (`wsl-linker`)

### Zero-Latency Native Windows Workspace Manager for WSL 2
**Make any WSL folder look like a normal local Windows folder, so every IDE and AI agent harness can open it.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011%20%7C%20WSL%202-blue.svg)]()
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)]()

---

## 📖 Overview

`wsl-linker` is an open-source Windows application and CLI utility that creates virtual directory symbolic links on your **local Windows host drives** pointing directly into your **WSL 2 Linux ext4 filesystem**.

It eliminates the classic dilemma of Windows + WSL development:
* **The Problem:** Storing repositories on Windows (`/mnt/c/`) causes Git, Docker, and `npm`/`pnpm` operations to run **up to 10x slower** inside Linux. Storing files inside Linux (`/home/...`) means Windows-based IDEs and AI agent harnesses (Antigravity, Cursor, Windsurf, Claude Code, Codex, VS Code, ...) have to open `\\wsl.localhost\...` UNC paths, which many of them mis-parse, block, or can't watch.
* **The Solution:** `wsl-linker` establishes an in-kernel NTFS directory junction on a local fixed drive (e.g. `D:\code\my-app` ➔ `\\wsl.localhost\Ubuntu-24.04\home\user\code\my-app`). Your code stays 100% on native Linux ext4 for maximum build performance, while every Windows tool sees it as a native local folder without disk duplication or network latency.

---

## ✨ Key Features

* ⚡ **100% Native Linux Performance:** Source code stays physically inside WSL's ext4 partition. Full speed for Git, Docker, Rust/Cargo, npm, and compiler toolchains.
* 🤖 **Works With Any Agent Harness / IDE:** The link is a plain local-drive path (`D:\code\my-app`), so there is nothing tool-specific to configure. Verified with Google Antigravity 2.x.
* 🛡️ **Drive Safety Check:** Warns you if you try to create a link on a network/mapped drive, which breaks path handling and file watching in many tools.
* 🖥️ **Modern Fluent Dark GUI:** Ultra-crisp CustomTkinter dashboard with live path preview, auto-wrapping responsive cards, and dynamic WSL distribution detection.
* ⌨️ **Scriptable CLI:** Comprehensive command-line interface for automation, terminal workflows, and CI scripting.
* 📋 **One-Click Copy Path:** Copy the local Windows path of any workspace to paste into any tool's "Open Folder" dialog.
* 💻 **Instant Context Terminal:** One-click launcher that spawns Windows Terminal logged directly into your Linux workspace directory.
* 🛡️ **Zero Data Loss Guarantee:** Safe unlinking via Windows `os.rmdir` untethers the symlink junction itself, leaving your Linux files 100% untouched and safe.

---

## ⚙️ Prerequisites

1. **Windows 10 (Build 19041+) or Windows 11** with **WSL 2** enabled.
2. **Windows Developer Mode Enabled:**
   * Go to **Windows Settings** ➔ **System** (or **Update & Security**) ➔ **For Developers**.
   * Toggle **Developer Mode** to **ON**.
   * *Why?* Windows requires administrator elevation to create directory symlinks unless Developer Mode is enabled. With Developer Mode on, `wsl-linker` can create links instantly without UAC administrator prompts.

---

## 🚀 Quick Start & Installation

### Option 1: Standalone Portable Binary (No Python Required)
1. Download `WSL Linker.exe` from the latest [Releases](https://github.com/fauzulkc/AnyLink/releases) page.
2. Double-click to launch the GUI dashboard immediately.

### Option 2: Running via Python
Clone the repository and install the minimal dependencies:

```bash
git clone https://github.com/fauzulkc/AnyLink.git
cd AnyLink

# Install required dependencies
pip install customtkinter

# Launch the desktop GUI
python wsl_linker_gui.py

# Or use the CLI directly
python wsl_linker.py list
```

### Option 3: Setting Up a Global CLI Alias
To use `wsl-linker` from anywhere in PowerShell or CMD, add a wrapper to your `PATH` or add an alias to your PowerShell `$PROFILE`:

```powershell
# Add to Microsoft.PowerShell_profile.ps1:
function wsl-linker { python "C:\path\to\wsl-linker\wsl_linker.py" $args }
```

---

## 🖥️ How to Use: Desktop GUI

Launch the GUI by running `WSL Linker.exe` or `python wsl_linker_gui.py`.

```
+-----------------------------------------------------------------------------------+
|  WSL LINKER | Zero-Latency Native Workspace Mappings     [✕ Close Form] |
+-----------------------------------------------------------------------------------+
| Active Registry Mappings (3)               | Link New Workspace                   |
|                                            |                                      |
| [my-web-app]                               | ALIAS NAME                           |
| D:\code\my-web-app ➔ [Ubuntu] /home/...   | [ my-project                     ]   |
| [📋 Copy Path] [💻 Open Terminal] [🗑 Remove]| LOCAL PARENT WINDOWS DIRECTORY       |
|                                            | [ D:\code           ] [ Browse ]     |
| [backend-api]                              |                                      |
| D:\code\backend-api ➔ [Ubuntu] /home/...  | WSL TARGET DIRECTORY PATH            |
| [📋 Copy Path] [💻 Open Terminal] [🗑 Remove]|                                      |
|                                            | TARGET WSL DISTRIBUTION              |
|                                            | [ Ubuntu-24.04                 v ]   |
|                                            |                                      |
|                                            | Preview: D:\code\my-project          |
|                                            | [ Create Direct Link 🔗          ]   |
+-----------------------------------------------------------------------------------+
```

### 1. Linking a New Workspace
1. **Alias Name:** Enter the folder name for your project (e.g. `my-project`).
2. **Local Parent Windows Directory:** Choose an existing folder on a local fixed drive (e.g. `D:\code`). Your virtual link folder will be created inside this directory (`D:\code\my-project`).
3. **WSL Target Directory Path:** Enter the path inside Linux (e.g. `/home/user/code/my-project`). If the directory does not exist yet, `wsl-linker` will create it inside Linux automatically.
4. **Distribution:** Select your installed WSL distribution from the dropdown.
5. Click **"Create Direct Link 🔗"**.

### 2. Copying the Workspace Path
* Click **"📋 Copy Path"** on any card to copy the local Windows path (e.g. `D:\code\my-project`) and paste it into any IDE or agent harness's "Open Folder" / "Add Workspace" dialog.

### 3. Opening the Workspace in Any Tool
* Open `D:\code\my-project` (the link) in your tool of choice. Always open the **link path**, never the `\\wsl.localhost\...` path.

### 4. Spawning a Linux Shell
* Click **"💻 Open Terminal"** on any card. `wsl-linker` launches Windows Terminal (or fallback console) already logged into the exact Linux directory and distribution.

### 5. Safe Unlinking
* Click **"🗑 Safe Remove"** to delete the Windows symlink. `wsl-linker` safely runs `os.rmdir` on the junction, ensuring **zero file deletions** inside your WSL Linux filesystem.

---

## ⌨️ How to Use: Command Line Interface (CLI)

The CLI provides full scriptability for developers who live in the terminal:

### View Active Mappings
```bash
wsl-linker list
```
Displays all registered mappings, their local Windows path, target WSL distribution, and Linux path.

### Add a New Workspace Mapping
```bash
wsl-linker add <windows_path> <wsl_linux_path> [-d <distro>] [-n <alias>]
```
* **Example:**
  ```bash
  wsl-linker add "D:\code\web-app" "/home/user/code/web-app" --distro Ubuntu-24.04
  ```
  Creates the link folder `D:\code\web-app` (must not already exist) pointing to the Linux directory.

### Run Commands in WSL Context from Windows Shell
Run any Linux command on your project directly from PowerShell or CMD without manual `cd` navigation:
```bash
# Run npm test inside the linked WSL folder:
wsl-linker run npm test

# Run a cargo build:
wsl-linker run cargo build --release
```

### Safely Unlink a Workspace
```bash
wsl-linker remove web-app
```

---

## 🤖 Why Direct WSL Paths Break Agent Harnesses (and Why the Link Fixes It)

This is **not specific to any one tool** - it is about how a path is understood once it leaves the OS.

| Path you open | What tools see | Result |
| :--- | :--- | :--- |
| `\\wsl.localhost\Ubuntu\home\user\app` | UNC network path | Many URI/path normalizers strip the host (`wsl.localhost`) leaving `/Ubuntu/home/...`, which Windows resolves to a non-existent `C:\Ubuntu\...`. Others block UNC for sandboxing or can't watch files. |
| `X:\app` (SSHFS / WebDAV mapped drive) | `DRIVE_REMOTE` network drive | File watchers and reparse handling are unreliable. |
| `D:\code\app` -> link into WSL | Normal folder on a local fixed drive (`DRIVE_FIXED`) | Works everywhere. The Windows kernel transparently forwards I/O into WSL ext4. |

Because the link is resolved by Windows itself, **no tool needs special support** - open the link path and it behaves like any local folder.

> 📖 **Deep Dive**: Full investigation, failed experiments (SSHFS/WebDAV mounts), and the Antigravity URI-normalizer analysis are in the [Integration Case Study](docs/ANTIGRAVITY_INTEGRATION_CASE_STUDY.md).

---

## 🏗️ Architecture

```
+--------------------------------------------------------------------+
|                        WINDOWS HOST (C: / D:)                      |
|                                                                    |
|  +--------------------+     +-----------------------------------+  |
|  | AI Agent Harness   |     | Windows File Explorer / Editors   |  |
|  | (any IDE / agent)  |     | (VS Code, Sublime Text, PyCharm)  |  |
|  +---------+----------+     +-----------------+-----------------+  |
|            |                                  |                    |
|            | Opens D:\code\project            |                    |
|            v                                  v                    |
|  +--------------------------------------------------------------+  |
|  |           Local NTFS Directory Junction (Symlink)            |  |
|  |           Path: D:\code\project (DRIVE_FIXED)                |  |
|  +------------------------------+-------------------------------+  |
+---------------------------------|----------------------------------+
                                  | In-Kernel NTFS Reparse Point
                                  | \\wsl.localhost\Ubuntu-24.04\...
                                  v
+--------------------------------------------------------------------+
|                         WSL 2 LINUX VM                             |
|                                                                    |
|  +--------------------------------------------------------------+  |
|  |               Native ext4 Linux Filesystem                   |  |
|  |               Path: /home/user/code/project                  |  |
|  +--------------------------------------------------------------+  |
|  |                                                              |  |
|  |   ⚡ Native Build Speed (npm, cargo, git, docker, compilers) |  |
|  +--------------------------------------------------------------+  |
+--------------------------------------------------------------------+
```

---

## 🛠️ Developer & Build Guide

The repository includes a developer `Makefile` for building and testing:

| Command | Action |
| :--- | :--- |
| `make run` | Runs the GUI locally in Python (`python wsl_linker_gui.py`) |
| `make build-local` | Compiles the standalone executable `dist/WSL Linker.exe` using local PyInstaller |
| `make build-docker` | Compiles the standalone EXE inside an isolated Wine Docker container |
| `make clean` | Cleans PyInstaller caches, build specs, and output folders |
| `make status` | Checks Git status |

### Building the Executable Manually:
```bash
pip install customtkinter pyinstaller
pyinstaller --onefile --noconsole --collect-all customtkinter --name "WSL Linker" wsl_linker_gui.py
```
The compiled binary will be placed in `dist/WSL Linker.exe`.

---

## 🔒 Security & Data Safety

* **Safe Unlink Guarantee:** When unlinking workspaces, `wsl-linker` strictly uses `os.rmdir()` on the local junction. It verifies that the path is an NTFS symbolic link before unlinking. It **never recurses** into the directory, ensuring your Linux files inside WSL are 100% protected.
* **Drive Validation:** `wsl-linker` queries `GetDriveTypeW` to prevent creating symlinks on network-mapped drives, saving you from path resolution bugs and broken file watchers.
* **Zero Telemetry:** `wsl-linker` runs 100% locally on your machine. No telemetry, no remote servers, no analytics.

---

## 📜 License

This project is licensed under the **MIT License** — feel free to use, modify, distribute, and package it for your personal workflows or team infrastructure.

Contributions, issues, and feature requests are welcome! 🚀
