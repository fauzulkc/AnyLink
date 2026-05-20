# 🚀 WSL Linker (`wsl-linker`) - Desktop GUI Manager

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%20%7C%20WSL2-blue.svg)]()

`wsl-linker` is a lightweight, open-source Windows desktop manager designed to connect your **Windows Host** workspace directories directly to your **WSL 2 Linux filesystem** via directory symbolic links.

It provides a state-of-the-art **Fluent Dark Mode** UI, enabling developers and teams to configure direct-reference folders with zero duplication, compile code at native speeds, and drop straight into dynamic Linux shells inside their current workspaces.

---

## 💡 Desktop GUI Highlights

*   **⚡ Zero-Lag Filesystem Links**: Employs native Windows directory symbolic links to reference WSL folders directly. No file syncing, duplication, or CPU-hogging watchers.
*   **📂 Native Folder Dialogs**: Click "Browse" to select Windows project directories via the operating system's native folder dialogs instead of copy-pasting paths.
*   **🐋 Auto WSL Distro Discovery**: Automatically queries your active WSL distros (e.g. `Ubuntu-24.04`, `Debian`, etc.) on start and populates them into an easy dropdown list.
*   **💻 Direct Bash Terminal Spawner**: Select a linked workspace in the table and click "Open Linux Bash Terminal" to instantly launch a terminal window already logged in and context-mapped to that WSL directory!
*   **🛡️ Safely Remove Links**: Cleans up symbolic link folder junctions safely via native unlinking (`os.rmdir`), leaving actual repositories inside WSL completely untouched.
*   **💾 Standalone Executable (`.exe`)**: Can be compiled into a single self-contained binary file containing the GUI libraries, allowing other developers to download and run it instantly with zero prerequisites.

---

## 📦 How to Compile the Standalone `.exe`

We support two ways to compile your standalone binary executable. Using the **Docker compilation** method is highly recommended as it keeps your host system completely clean.

### Option A: Isolated Compile via Docker (Recommended)
This uses a lightweight, pre-configured Wine/PyInstaller container to package your Windows executable, meaning you do not need Python or packaging libraries on your host system:

1. Ensure **Docker Desktop** is running.
2. Double-click **`compile-docker.bat`** in your project folder.
3. Once completed, your executable is ready at:
   ```text
   D:\AI Stuff\projects\fauzul\dist\WSL Linker.exe
   ```

---

### Option B: Local Compile via Python
If you already have Python installed on your host and prefer a local build:

1. Double-click **`compile.bat`** in your project folder.
2. The script will automatically install `pyinstaller` locally.
3. It compiles the `wsl_linker_gui.py` application into a single, self-contained file.
4. Once completed, your executable is ready at:
   ```text
   D:\AI Stuff\projects\fauzul\dist\WSL Linker.exe
   ```

You can now copy **`WSL Linker.exe`** to any Windows machine and run it with zero dependencies!

---

## 📖 GUI Features Breakdown

### 1. The Mapping Registry Table (The Map)
The center grid acts as a real-time list of all active links mapped on your PC. Selecting any row unlocks quick action buttons.

### 2. Create Direct Link (Form Inputs)
*   **Alias Name**: Give your linked folder a simple shortname (e.g., `my-project`).
*   **Windows Folder Path**: Click the `Browse` button and select an empty folder on Windows where the symlink will live.
*   **WSL Target Path**: Supply the remote Linux path inside WSL (e.g. `/home/user/code/my-project`).
*   **Target WSL Distribution**: Select your active distro from the dropdown.

### 3. Open Linux Bash Terminal
Click this to spawn a new, native interactive Bash session logged inside WSL inside your context-mapped folder directory.

### 4. Activity Console Logs
A scrolling console feed at the bottom of the window displays error outputs, success logs, permission issues, and OS system calls in real-time.

---

## 🔒 Security & Safety Best Practices

*   **Developer Mode / Admin Elevation**: Creating directory symbolic links on Windows requires administrator privileges. Turn on **Developer Mode** inside Windows Settings (Update & Security > For Developers) to allow standard users to create symlinks without administrator prompts.
*   **Safe Unlinking**: Always use the **Safely Remove Symlink** button or command to delete mappings. Manual folder deletion in older File Explorer versions can sometimes lead to recursive deletions inside WSL; our script isolates mapping deletions safely.
