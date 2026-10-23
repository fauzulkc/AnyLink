# Engineering Case Study: Making WSL 2 Workspaces Work in Agent Harnesses (Antigravity as the Reference Case)

## 1. Executive Summary

When developing inside Windows Subsystem for Linux (WSL 2), developers often face a fundamental trade-off:
* **Option A:** Store files on the Windows host (`/mnt/c/` or `/mnt/d/`) to allow Windows IDEs to open them natively, sacrificing up to **10x build and Git performance** due to WSL 2 9P filesystem translation overhead.
* **Option B:** Store files natively on the Linux ext4 filesystem for maximum performance, but lose native integration with Windows-based IDEs and agentic tools that expect local Windows drive paths.

With the release of **Google Antigravity 2.x**, users attempting to open WSL 2 repositories in **Agent Mode** encountered a blocking issue: workspaces displayed a yellow folder warning sign (`⚠️`), marked the directory as "missing", or failed to index and watch files.

This document details the investigative process, the hypotheses tested, the technical post-mortem of failed approaches, and the reverse-engineered solution that powers `wsl-linker`.

---

## 2. Problem Statement & Symptoms

### The Symptom
When opening a WSL 2 workspace directly (e.g. `\\wsl.localhost\<distro>\<path>` or `file://wsl.localhost/<distro>/<path>`), Antigravity Agent Mode:
1. Displayed a warning icon (`⚠️`) next to the workspace name.
2. Displayed `Path does not exist on disk` or failed file discovery during agent tool execution.
3. Disabled file watchers, preventing the language server from tracking changes made by subagents or background tasks.

---

## 3. Investigation & Root Cause Analysis

### 3.1 Reverse Engineering the Antigravity URI Normalizer
By inspecting the client bundle (`main.js` / `workbench.desktop.main.js`), we analyzed how workspace URIs are sanitized before being passed to the backend language server:

```javascript
// Internal Antigravity URI normalizer:
function normalizeProjectUri(rawUri) {
    const parsed = typeof rawUri === "string" ? URI.parse(rawUri) : rawUri;
    return parsed.with({ scheme: "file", authority: null });
}
```

#### What happens to Direct WSL UNC Paths:
1. Input URI: `file://wsl.localhost/Ubuntu-24.04/home/user/project`
2. Component breakdown:
   - `scheme`: `file`
   - `authority`: `wsl.localhost`
   - `path`: `/Ubuntu-24.04/home/user/project`
3. The normalizer enforces `{ authority: null }`:
   - Output URI: `file:///Ubuntu-24.04/home/user/project`
4. On Windows, `file:///Ubuntu-24.04/...` is resolved by the OS filesystem API as:
   - `C:\Ubuntu-24.04\home\user\project`
5. Since `C:\Ubuntu-24.04` does not exist on the host, the IDE flags the folder as missing (`⚠️`).

#### What happens to Raw Windows Paths:
When passing raw paths like `D:\code\my-project` without a URI scheme:
1. `URI.parse("D:\\code\\my-project")` treats `D:` as a custom URI scheme (`scheme: "d"`).
2. The normalizer enforces `scheme: "file"` but discards the drive letter, producing malformed URIs like `file:///%5Ccode%5Cmy-project`, which fail to resolve.

### 3.2 Inspecting the Antigravity LanguageServer Process
Antigravity runs an internal backend process named `language_server.exe`. 
Through process inspection and network analysis:
* The process communicates over localhost using **Connect-RPC** (gRPC-compatible HTTP/JSON).
* It requires an authentication header: `x-codeium-csrf-token: <csrf_token>`.
* Key endpoints exposed:
  - `StatUri`: Checks whether a file/directory URI exists and returns metadata.
  - `ReadProject`: Fetches project configuration and registered resource URIs.
  - `UpdateProject`: Updates workspace folders and Git tracking configuration.
  - `ReadDir`: Lists directory contents via the language server.

Testing `StatUri` across different URI variations revealed the exact resolution rules:
* `file://wsl.localhost/...` ➔ **Fails** (authority stripped by client before RPC).
* `file:///Ubuntu-24.04/...` ➔ **Fails** (maps to host root `C:\`).
* `vscode-remote://...` ➔ **Fails** (unsupported in standalone Agent Mode).
* `file:///D:/code/my-project` ➔ **Succeeds (200 OK)** with valid file metadata, provided `D:\code\my-project` exists on a local fixed drive.

---

## 4. Exploration of Approaches & Post-Mortem

### Approach 1: Mapped Network Drive via SSHFS / WebDAV
* **Hypothesis:** Expose the WSL 2 Linux filesystem to Windows as a mapped drive letter (e.g. `X:\`) using an SSHFS-Win or WebDAV bridge. This would give the project a standard drive letter (`file:///X:/...`).
* **Experiment:**
  1. Configured an internal SSH daemon inside WSL 2 bound to localhost.
  2. Mounted the WSL filesystem to Windows drive `X:` using WinFsp / SSHFS-Win.
  3. Added `file:///X:/project` to Antigravity.
* **Findings & Failure Modes:**
  1. **Drive Type Mismatch:** Windows identifies mapped network drives as `DRIVE_REMOTE` (Type 4) via `GetDriveTypeW`.
  2. **Reparse & Watcher Failures:** Antigravity's `language_server.exe` uses Windows `ReadDirectoryChangesW` and local NTFS reparse point APIs. Network-backed filesystems (WinFsp/SSHFS) do not implement the requisite NTFS reparse semantics, resulting in dropped file watcher events and intermittent indexing hangs.
  3. **Operational Fragility:** Required running persistent background SSH daemons, managing local keys, and handling network reconnect drops after Windows sleep/wake cycles.
* **Verdict:** **Rejected & Rolled Back.** Mapped network drives introduce unnecessary complexity, network overhead, and fundamental file-watcher incompatibilities.

---

### Approach 2: Windows ReFS Dev Drive
* **Hypothesis:** Format a dedicated virtual disk as a Windows Dev Drive (ReFS) and locate the codebase there.
* **Findings & Failure Modes:**
  1. While Dev Drive provides improved I/O on the Windows host, Linux tools inside WSL 2 still access it via `/mnt/`, which incurs the same 9P virtualization translation overhead.
  2. Running package managers (`npm`, `pnpm`, `cargo`) or Git commands inside WSL on `/mnt/` remains significantly slower than native Linux ext4.
* **Verdict:** **Rejected.** Moving source files out of WSL ext4 violates the requirement of maintaining native Linux build performance.

---

### Approach 3: Local NTFS Directory Symbolic Links on Fixed Drives (The Winning Solution)
* **Hypothesis:** Keep all source files physically inside WSL 2 (`/home/<user>/code/<project>`), but create a local directory symbolic link on an existing local fixed NTFS drive (such as `D:\code\<project>` or `C:\Users\<user>\...`), pointing to `\\wsl.localhost\<distro>\<path>`.
* **Technical Validation:**
  1. **Drive Type:** A path on `D:\` evaluates to `DRIVE_FIXED` (Type 3).
  2. **URI Normalization Immunity:** 
     - Canonical file URI: `file:///D:/code/my-project`
     - When processed by `parsed.with({ authority: null })`, the authority is already empty. The URI remains `file:///D:/code/my-project` without modification.
  3. **OS-Level Reparse:** When `language_server.exe` queries `file:///D:/code/my-project`, the Windows NTFS driver encounters the directory reparse point and routes the I/O request directly to the WSL 2 Plan9 / P9 driver.
  4. **Performance:** Read/write operations from Windows host tools occur at native speed, while all compilation, Git operations, and terminal workflows remain 100% inside Linux ext4.
* **Verdict:** **Selected as the canonical architecture.**

---

## 5. Technical Comparison Matrix

| Path Format | Example | Drive Type | Antigravity URI | Agent Mode Status | Why? |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Direct WSL UNC** | `\\wsl.localhost\Ubuntu\home\user\app` | UNC (`\\`) | `file:///Ubuntu/home/user/app` | ❌ Broken (`⚠️`) | Authority stripped by normalizer; maps to `C:\Ubuntu` |
| **Raw Windows Path** | `D:\code\app` | `DRIVE_FIXED` | `file:///%5Ccode%5Capp` | ❌ Broken (`⚠️`) | Malformed parsing without `file:///` scheme |
| **Mapped Network Drive** | `X:\app` (SSHFS / WebDAV) | `DRIVE_REMOTE` | `file:///X:/app` | ⚠️ Unreliable | Missing NTFS reparse points; file watchers fail |
| **Fixed Drive Symlink** | `D:\code\app` ➔ `\\wsl.localhost\...` | `DRIVE_FIXED` | `file:///D:/code/app` | ✅ **Healthy (100%)** | Canonical URI intact; native NTFS reparse resolution |

---

## 6. Implementation Architecture in `wsl-linker`

With the solution proven, `wsl-linker` was updated to automate this pipeline end-to-end:

### 1. Drive Validation Guard (`check_windows_drive_type`)
```python
def check_windows_drive_type(win_path):
    root = os.path.splitdrive(os.path.abspath(win_path))[0] + "\\"
    drive_type = ctypes.windll.kernel32.GetDriveTypeW(root)
    # DRIVE_FIXED = 3, DRIVE_REMOTE = 4
    if drive_type == 4:
        return False, "remote_network"
    elif drive_type == 3:
        return True, "local_fixed"
    return True, f"type_{drive_type}"
```
Both the CLI and GUI now intercept attempts to create links on network drives, warning the user before invalid configurations are created.

### 2. Why There Is No Tool-Specific Integration
An earlier iteration of `wsl-linker` shipped an Antigravity-specific "sync" feature that rewrote project entries through the editor's local language-server RPC. It was removed: the fix is entirely in how Windows presents the path, so a plain local-drive link works for **every** IDE and agent harness (Antigravity, Cursor, Windsurf, Claude Code, Codex, VS Code, ...) with no per-tool code. Projects previously registered with a `\\wsl.localhost\...` path simply need to be re-opened once via the link path (e.g. `D:\code\app`).

## 7. Lessons Learned & Reference Notes

1. **Never Mount Network Drives for Host-Guest Tooling:** Mapped network drives (`DRIVE_REMOTE`) break assumptions made by modern language servers that rely on native NTFS file notifications (`ReadDirectoryChangesW`).
2. **Authority Stripping is Common in Web-Based IDEs:** Many Electron-based IDEs use URL normalization routines that assume local `file://` URIs never have authorities. Tools bridging WSL must always present drive-letter-based paths with empty authorities.
3. **NTFS Directory Symlinks are Zero-Cost Bridges:** A directory symbolic link created via `os.symlink(target, link, target_is_directory=True)` acts as an in-kernel junction. It introduces no background services, no persistent memory footprint, and no network overhead.

---

## 8. Extending the Architecture: Isolated Docker Reverse Sandboxes

### 8.1 The Need for Agentic Execution Sandboxing
While the direct WSL 2 link solved host IDE integration for developers' primary repositories, the rise of autonomous AI coding agents (such as Antigravity Agent Mode, Claude Code, and autonomous test runners) introduces a new challenge: **sandboxing**.

Running autonomous agents directly against the host or primary WSL distro carries risks:
* Dependency conflicts and unintended package installations.
* Background daemon spawns and port collisions.
* Accidental file modifications outside the workspace.

Developers want disposable, isolated container sandboxes. However, traditional Docker dev containers on Windows rely on **host bind mounts** (`-v D:\code\project:/workspace`), which:
1. Re-introduce the same Hyper-V 9P translation overhead, making agent build runs **8–10x slower**.
2. Cause file-lock contention between host file watchers and container processes.
3. Pollute the host drive with container-generated build caches and temporary files.

### 8.2 The Reverse Docker Sandbox Architecture
To eliminate host bind mounts while maintaining full compatibility with Windows IDEs and AI agent harnesses, `wsl-linker` implements a **Reverse Docker Linking** architecture:

```
+-------------------------------------------------------------------------+
|                          WINDOWS HOST (DRIVE_FIXED)                     |
|                                                                         |
|  +--------------------+     +----------------------------------------+  |
|  | AI Agent Harness   |     | Windows File Explorer / Editors        |  |
|  | (Antigravity 2.x,  |     | (Cursor, VS Code, JetBrains)           |  |
|  |  Claude Desktop)   |     |                                        |  |
|  +---------+----------+     +-------------------+--------------------+  |
|            |                                    |                       |
|            | Opens file:///D:/code/sandbox      |                       |
|            v                                    v                       |
|  +-------------------------------------------------------------------+  |
|  |             Local NTFS Directory Symlink (Reparse Point)          |  |
|  |             Path: D:\code\sandbox (DRIVE_FIXED)                   |  |
|  +--------------------------------+----------------------------------+  |
+-----------------------------------|-------------------------------------+
                                    | In-Kernel Reparse to WSL UNC Path:
                                    | \\wsl.localhost\<distro>\home\<user>\.devlinker-mounts\<alias>\workspace
                                    v
+-------------------------------------------------------------------------+
|                           WSL 2 LINUX GUEST                             |
|                                                                         |
|  +-------------------------------------------------------------------+  |
|  |  FUSE SSHFS Mount: ~/.devlinker-mounts/<alias>                    |  |
|  |  Options: idmap=user, allow_other, reconnect, port=2222           |  |
|  |  Daemon: 🔄 Background Reconnection Daemon (polls every 20s)      |  |
|  +--------------------------------+----------------------------------+  |
+-----------------------------------|-------------------------------------+
                                    | SSHFS Tunnel (SSH key authentication)
                                    | 127.0.0.1:2222 -> Container :22
                                    v
+-------------------------------------------------------------------------+
|                     ISOLATED DOCKER DEV CONTAINER                       |
|                                                                         |
|  +-------------------------------------------------------------------+  |
|  |  Container Linux Ext4 Filesystem                                  |  |
|  |  Workspace Directory: /workspace (chmod 777)                      |  |
|  |  Daemon: openssh-server (sshd on port 22)                         |  |
|  |                                                                   |  |
|  |  🐳 100% Isolated: Zero Host Bind Mounts, Zero Host OS Pollution  |  |
|  +-------------------------------------------------------------------+  |
+-------------------------------------------------------------------------+
```

### 8.3 Key Technical Innovations in the Reverse Bridge
1. **Zero Host Bind Mounts:** The container runs purely in Docker storage (`/workspace`). No files are stored or duplicated on the Windows host.
2. **`idmap=user` & `allow_other` FUSE Configuration:** Normal FUSE mounts restrict access strictly to the mounting user ID. By configuring `/etc/fuse.conf` with `user_allow_other` and mounting via `sshfs -o idmap=user,allow_other`, the WSL 9P kernel driver can project the mount point over Windows UNC (`\\wsl.localhost\...`) with full read and write permissions.
3. **Self-Healing Persistence Daemon:** Docker containers can be paused, stopped, or restarted during host sleep cycles. A background monitor thread regularly checks mount health. If a mount drops, it restarts the container, restarts `sshd`, and re-attaches FUSE with zero developer intervention.
4. **Instant Shell Integration:** A single click on the GUI dashboard launches an interactive terminal directly inside the container via `docker exec -it <container> sh` or into WSL.
5. **Safe Teardown:** Unlinking untethers the Windows directory symlink via `os.rmdir`, safely unmounts the FUSE volume (`fusermount3 -uz`), and stops the container, ensuring persistent data is never accidentally wiped.
