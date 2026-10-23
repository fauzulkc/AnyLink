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
* 🐳 **Isolated Docker Reverse Sandboxes (Zero Host Pollution):** Spin up isolated Docker containers without host bind mounts. Container files are reverse-mounted into WSL via SSHFS and exposed to Windows as local symlinked paths with real-time bidirectional sync and background self-healing.
* 🤖 **Works With Any Agent Harness / IDE:** The link is a plain local-drive path (`D:\code\my-app`), so there is nothing tool-specific to configure. Verified with Google Antigravity 2.x, Claude Desktop, Cursor, and VS Code.
* 🛡️ **Drive Safety Check:** Warns you if you try to create a link on a network/mapped drive, which breaks path handling and file watching in many tools.
* 🖥️ **Modern Fluent Dark GUI:** Ultra-crisp CustomTkinter dashboard with live path preview, auto-wrapping responsive cards, and dynamic WSL distribution detection.
* 🔄 **Self-Healing Persistence Daemon:** Background engine monitors reverse Docker mounts every 20 seconds, automatically reviving SSH daemons and healing stale mounts after container restarts or sleep cycles.
* ⌨️ **Scriptable CLI:** Comprehensive command-line interface for automation, terminal workflows, and CI scripting.
* 📋 **One-Click Copy Path:** Copy the local Windows path of any workspace to paste into any tool's "Open Folder" dialog.
* 💻 **Instant Context Terminal:** One-click launcher that spawns Windows Terminal logged directly into your Linux workspace directory or container shell.
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

## 🐳 Isolated Docker Reverse Sandboxes (Experimental Dev Suite)

For tasks requiring fully sandboxed agentic execution, clean reproducible development environments, or zero host file pollution, `wsl-linker` provides **Docker Reverse Sandbox Linking** via `experimental_linker_gui.py`.

### The Problem with Traditional Dev Containers on Windows
* **Host Bind Mounts Suffer Heavy I/O Penalties:** Traditional `docker run -v D:\project:/workspace` maps a Windows NTFS path across the Hyper-V virtualization boundary into Docker. File I/O drops by up to **8–10x**, file watching frequently drops events, and Windows file locks regularly prevent tools from cleaning up.
* **Host OS Pollution:** All dependencies (`node_modules`, build artifacts, cache files) are written onto your Windows host drive.
* **Volume Isolation Dilemma:** If you keep files entirely inside an isolated Docker volume for maximum Linux speed, Windows IDEs and AI agent harnesses cannot easily browse, edit, or watch the files natively.

### The Reverse Docker Link Solution
`wsl-linker` flips the dev container model inside out:
1. **Container Runs in Complete Isolation:** A Docker container is launched with **zero host bind mounts**. All source code and dependencies live 100% inside the container's isolated Linux filesystem (`/workspace`).
2. **Automated SSH Provisioning:** An SSH server (`sshd`) is dynamically configured inside the container, unlocked for root key authentication, with key injection (`devlinker_ed25519` generated inside WSL).
3. **WSL FUSE Reverse Mount:** WSL mounts the container root using `sshfs` with `idmap=user,allow_other,reconnect` into `~/.devlinker-mounts/<alias>`.
4. **Windows NTFS Symlink:** Windows creates a directory symlink `D:\code\<alias>` pointing to `\\wsl.localhost\<distro>\home\<user>\.devlinker-mounts\<alias>\workspace` (with automatic fallback to the UNC path if running unprivileged).
5. **Real-Time Bidirectional Sync:** Windows IDEs, Cursor, and AI agents read and write directly to `D:\code\<alias>`. Changes reflect inside the running container instantaneously without host bind mounts.
6. **Self-Healing Persistence Daemon:** A background watcher monitors the reverse mount every 20 seconds. If Docker restarts or the system wakes from sleep, it restarts the container, revives `sshd`, and heals stale FUSE mounts automatically.

### Running the Experimental Dashboard
Launch the unified tabbed dashboard:
```bash
python experimental_linker_gui.py
```
* **WSL Tab:** Link native WSL 2 directories to Windows fixed drives.
* **Docker Tab:** Enter an alias name (e.g. `node-sandbox`), image name (e.g. `node:20-alpine`), and Windows parent directory (`D:\code`). Click **"Create Reverse Docker Sandbox"**.
* **One-Click Shell:** Click **"💻 Open Shell"** on any Docker card to jump directly into `docker exec -it <container> sh`.
* **Safe Teardown:** Click **"🗑 Safe Remove"** to safely unmount the FUSE volume, remove the Windows symlink, and dissolve the container without data loss.

---

## 🏗️ Architecture

### Mode 1: WSL 2 Direct Native Workspace Link
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

### Mode 2: Isolated Docker Reverse Sandbox Bridge
```
+--------------------------------------------------------------------+
|                        WINDOWS HOST (C: / D:)                      |
|                                                                    |
|  +--------------------+     +-----------------------------------+  |
|  | AI Agent Harness   |     | Windows File Explorer / Editors   |  |
|  | (any IDE / agent)  |     | (VS Code, Cursor, Antigravity)    |  |
|  +---------+----------+     +-----------------+-----------------+  |
|            |                                  |                    |
|            | Opens D:\code\sandbox            |                    |
|            v                                  v                    |
|  +--------------------------------------------------------------+  |
|  |           Local NTFS Directory Junction (Symlink)            |  |
|  |           Path: D:\code\sandbox (DRIVE_FIXED)                |  |
|  +------------------------------+-------------------------------+  |
+---------------------------------|----------------------------------+
                                  | In-Kernel NTFS Reparse Point
                                  | \\wsl.localhost\Ubuntu-24.04\home\user\.devlinker-mounts\sandbox\workspace
                                  v
+--------------------------------------------------------------------+
|                         WSL 2 LINUX VM                             |
|                                                                    |
|  +--------------------------------------------------------------+  |
|  |  FUSE SSHFS Mount Point: ~/.devlinker-mounts/sandbox         |  |
|  |  Options: idmap=user, allow_other, reconnect, port=2222     |  |
|  |  Managed by: 🔄 Self-Healing Persistence Daemon (every 20s)   |  |
|  +------------------------------+-------------------------------+  |
+---------------------------------|----------------------------------+
                                  | SSHFS Tunnel (SSH Key Authenticated)
                                  | localhost:2222 -> Container :22
                                  v
+--------------------------------------------------------------------+
|                  ISOLATED DOCKER DEV CONTAINER                     |
|                                                                    |
|  +--------------------------------------------------------------+  |
|  |  Container Filesystem (e.g. alpine, node, python, debian)    |  |
|  |  Workspace Path: /workspace (chmod 777)                      |  |
|  |  Daemon: openssh-server (sshd on port 22)                    |  |
|  |                                                              |  |
|  |  🐳 100% Isolated: Zero Host Bind Mounts, Zero Host Pollution|  |
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
