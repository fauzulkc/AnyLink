# 🚀 WSL Linker (`wsl-linker`) - Modern GUI Workspace Manager

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20WSL2-blue.svg)]()

`wsl-linker` is an open-source, lightweight Windows desktop application and CLI manager designed to link your **Windows Host** workspace directories directly to your **WSL 2 Linux filesystem** using native Windows directory symbolic links.

It provides a premium **Fluent Dark Mode** GUI, enabling developers to build, edit, and manage cross-platform projects with zero disk duplication, maximum execution speed, and absolute convenience.

---

## 🌟 The Origin Story: The Antigravity IDE 2.0 Dilemma

`wsl-linker` was born out of an urgent development need. 

When **Google's Antigravity IDE upgraded to 2.0**, the traditional Editor interface was completely restructured, resulting in the loss of the standard **WSL Remote Plugin** workflow. Developers who depended on the WSL Remote Plugin to bridge host-side editors to Linux containers were suddenly stranded, unable to easily access and edit files locked inside their WSL 2 filesystem.

We needed a solution immediately. We did not want to compromise by moving code out of the WSL filesystem back onto the slow Windows host, because cross-operating-system disk operations (accessing `/mnt/c/` from WSL) degrade Git, Docker, and npm performance by up to **10x**.

**The Solution**: `wsl-linker` bridges the gap. By establishing a zero-latency, virtual Directory Symbolic Link on Windows pointing straight to WSL (`\\wsl.localhost\Ubuntu-24.04\home\user\project`), developers can:
1. Keep their source files physically on the native Linux ext4 partition (maintaining 100% build performance).
2. Open, search, and edit their files directly using native Windows host editors (VS Code, Sublime Text, PyCharm, Notepad++) on the host side.
3. Drop instantly into WSL Linux terminals to run test suites or compile binaries.

This tool restored developer workflows instantly, turning a breaking IDE update into a highly optimized, lag-free development paradigm.

---

## 💡 Powerful Use Cases

`wsl-linker` solves critical friction points for Windows and WSL developers:

### 1. High-Performance Web Development (npm, Git, Docker)
Running `npm install` or `git status` from a WSL environment on files stored in Windows (`/mnt/c/`) is notoriously slow due to operating system translation layers. By keeping your repositories entirely on the Linux filesystem and using `wsl-linker`, your builds run at **100% native Linux speed**, while you still edit them locally on Windows.

### 2. Standalone Zero-Dependency GUI for Cross-Functional Teams
Often, designers, QA engineers, or junior developers need to run or preview a project on their Windows machines without spending hours installing Python, PyInstaller, or configuring WSL path shares. The single-file compiled binary `WSL Linker.exe` gives them a simple, zero-setup dashboard to manage paths instantly.

### 3. Native Windows File Explorer Management
Browse, preview, rename, drag-and-drop, and manage files physically located deep inside WSL directly from the native Windows File Explorer (`explorer.exe`) as if they were standard Windows folders.

### 4. Direct Terminal Context-Dropping
Spawn a terminal logged into any WSL 2 distribution inside your specific workspace context with a single click. No more opening a shell, typing `wsl`, and hunting down complex path directories.

### 5. Seamless CLI Proxy Runner (`wsl-linker run`)
If you are working inside your Windows shell (CMD or PowerShell) in the linked folder, you can run Linux commands on your project natively:
```powershell
# Instantly runs npm install inside the corresponding WSL Linux directory
wsl-linker run npm install
```

---

## 🖥️ Desktop GUI Highlights & Latest Upgrades

The GUI features a state-of-the-art **Fluent Dark theme** styled with CustomTkinter, built with precision and responsiveness:

*   **Sleek Parent Directory Onboarding**: The app no longer forces you to choose a path that *must not exist*. You simply browse and select your **Local Parent Windows Directory** (e.g. `D:\AI Stuff\projects\fauzul`). The application automatically appends your **Alias Name** and creates the virtual link folder inside it!
*   **Live Path Preview Widget**: Watch your target path build in real-time as you type your Alias or select your parent folder. The preview shows in a clean, italicized typography and turns **emerald green** when all details are ready.
*   **Auto-Wrapping Card Mappings**: Squeezing the window horizontally will never cut off or squish your action buttons. Mappings cards utilize a prioritized pack layout, dynamic vertical constraints, and real-time `<Configure>` event listeners to calculate and wrap long path strings onto new lines automatically.

---

## 🛠️ Developer Makefile

We have introduced a dedicated developer **`Makefile`** in the repository root to automate common tasks for both Windows (via Git Bash, MSYS2, Chocolatey) and Unix-like shells:

| Command | Action |
| :--- | :--- |
| `make run` | Launches the WSL Linker GUI locally in Python |
| `make build-docker` | Compiles the GUI script into `dist/WSL Linker.exe` inside an isolated Wine Docker container (keeps host system 100% clean) |
| `make build-local` | Compiles the EXE locally using host-installed Python/PyInstaller |
| `make clean` | Flushes out PyInstaller build caches, specs, and outputs |
| `make status` | Quick proxy to check Git version status |

---

## 🔒 Security & Best Practices

*   **Enable Developer Mode**: Creating symbolic links in Windows normally requires administrator elevation. To run WSL Linker and create direct links instantly without administrator popups, enable **Developer Mode** in Windows (Settings > Update & Security > For Developers).
*   **Safe Unlinking**: Deleting directory symbolic links manually inside older versions of Windows File Explorer can occasionally result in recursive deletions inside the target WSL folder. **Always use the "Safe Remove" button or CLI command**. Our unlinker safely runs `os.rmdir` on Windows which untethers the symlink junction itself, leaving your WSL files 100% safe and untouched.

---

## 📜 Open Source & Distribution

`wsl-linker` is proud to be **100% open-source software**! 

*   **Free to Replicate & Distribute**: You are completely free to clone this repository, modify the code, build your own versions, and distribute the standalone `WSL Linker.exe` executable anywhere.
*   **Permissive Licensing**: The project is published under the highly permissive **MIT License**, permitting unrestricted commercial use, private modification, distribution, and sublicensing.

Feel free to fork, customize the stylesheet, package it for your development team, or distribute it as an independent tool. Let's make cross-platform WSL development seamless and ultra-fast for everyone! 🚀

