# WSL Linker (AnyLink)

High-performance workspace bridges for WSL 2 and isolated Docker containers on Windows.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%2F%2011%20%7C%20WSL%202-blue.svg)]()
[![Speedup](https://img.shields.io/badge/I%2FO%20Speedup-106x--254x-emerald.svg)](PERFORMANCE_BENCHMARK_REPORT.md)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)]()

---

## Concept and Architecture Flow

Developing on Windows with Linux tools usually forces an unacceptable trade-off:

* **Host storage (`/mnt/c` or Docker bind-mounts):**
  `Windows NTFS -> Hyper-V 9P -> Linux/Container`
  Slow. File operations suffer a 100x+ virtualization penalty. Package managers (`npm`, `cargo`) stall, and file locks block directory cleanup.
* **Internal Linux storage (`\\wsl.localhost\...` or container volumes):**
  `Container/WSL ext4 -> Windows UNC path`
  Fast execution, but breaks host tools. Windows IDEs and AI agent harnesses mis-parse UNC paths, drop file-watching events, or cannot access files trapped in container volumes.

### The AnyLink Bridge Flow

AnyLink combines in-kernel NTFS directory junctions, WSL 9P, and reverse SSHFS tunnels:

```
[Windows Host IDE / AI Agent]
            |
            | Reads/writes local path: D:\code\<project> (DRIVE_FIXED)
            v
[NTFS Directory Junction]
            |
            | In-kernel reparse: \\wsl.localhost\<distro>\...
            v
[WSL 2 Linux ext4] ---------------------------------------------+
            |                                                   |
            | Mode 1: Direct native ext4 workspace              | Mode 2: FUSE SSHFS tunnel
            v                                                   v
   [/home/user/code/project]                           [Isolated Docker Container]
   - 180x-254x faster file I/O                         - Zero host bind mounts
   - Full Linux toolchain speed                        - Zero Windows host pollution
                                                       - Resource capped (CPU/RAM/PIDs)
```

The Windows kernel resolves the junction locally. Every Windows tool (Cursor, VS Code, Antigravity, terminal) treats the folder as a native local directory, while execution runs at native Linux ext4 speeds.

---

## Empirical Performance Benchmarks

Measured on Windows 11 Home (Build 26200), WSL 2 (Ubuntu 24.04 LTS), and Docker Engine 29.9.2 across 1,500 file operations (writes, reads, stat traversals, and deletions).

Full reproducible benchmark script: [`scripts/run_live_performance_proof.py`](file:///D:/code/sandbox-linker/scripts/run_live_performance_proof.py)  
Raw benchmark data: [`EMPIRICAL_BENCHMARK_DATA.json`](file:///D:/code/sandbox-linker/EMPIRICAL_BENCHMARK_DATA.json)  
Comprehensive report: [`PERFORMANCE_BENCHMARK_REPORT.md`](file:///D:/code/sandbox-linker/PERFORMANCE_BENCHMARK_REPORT.md)

### 1. File I/O Lifecycle (Setup -> Run -> Destroy)

| Lifecycle Phase | Host 9P Storage (`/mnt/c` or Bind Mount) | Native WSL 2 ext4 (`wsl-linker`) | AnyLink Container ext4 (`sandbox_manager`) | Speedup vs Host |
| :--- | :---: | :---: | :---: | :---: |
| **Setup Phase** | `0.0028s` | `0.0003s` | `0.0004s` | **7.0x - 9.3x faster** |
| **File Writes (1,500 files)** | `8.028s` | `0.043s` | `0.069s` | **116x - 186x faster** |
| **File Reads (1,500 files)** | `5.925s` | `0.018s` | `0.024s` | **246x - 329x faster** |
| **Directory Stat / Walk** | `2552.1ms` | `4.5ms` | `6.0ms` | **425x - 567x faster** |
| **Total Run Execution** | **`16.506s`** | **`0.065s`** | **`0.098s`** | **254.6x (WSL) / 168.2x (Container)** |
| **Destroy Phase** | `2.144s` | `0.024s` | `0.019s` | **88x - 111x faster** |
| **Residual Host Disk Clutter** | **1,500 files left on host** | **0 files on host** | **0 files on host** | **Zero host pollution** |
| **Host File Lock Hazards** | High (Explorer locks) | None | None (1-click dissolve) | Safe teardown |

### 2. Autonomous AI Agent Benchmark (`agy` Multi-Turn Project Build)

Multi-turn software build executed autonomously by Google Antigravity CLI (`agy`) scaffolding modules, generating test suites, running pytest, and committing to Git:

| Storage Environment | Multi-Turn Agent Task | Tests Pass | Git Commit | Wall-Clock Time | Time Saved |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Windows Host Storage** (`/mnt/c/`) | Full calculator suite | Yes | Yes | `659.57s` (~11.0 min) | Baseline |
| **AnyLink ext4 Target** (`/home/...`) | Full calculator suite | Yes | Yes | `71.60s` (~1.2 min) | **588.0s faster (9.2x speedup)** |

---

## Pragmatic Q&A

### Volumes work?
**Yes.**  
Use `-v` or `--volume <name>:/workspace` with `sandbox_manager.py create`. Docker named volumes store project files and build caches (`node_modules`, `.venv`) entirely inside Docker's virtual storage driver. When containers are stopped or recreated, volume data persists intact without writing any files to the Windows host drive. Standard host directory binds (`-v D:\proj:/workspace`) are also supported when host mirroring is required.

### Space limiting?
**Yes.**  
Container storage footprint can be bounded using `--storage-opt size=10G` on supported Docker storage drivers (overlay2 on xfs/btrfs). Furthermore, container files reside inside the WSL virtual disk (`ext4.vhdx`), preventing uncontrolled file growth from fragmenting the Windows host filesystem. Ephemeral workloads can also use `--tmpfs /tmp` or loopback images.

### Performance throttling?
**Yes.**  
Resource controls map directly to Docker and Linux cgroups v2:
* `--cpus 2.0`: Caps CPU core allocation, preventing compile tasks or runaway loops from freezing the Windows host.
* `-m` / `--memory 2g`: Enforces a hard memory ceiling to protect host RAM.
* `--pids-limit 200`: Caps maximum process IDs, preventing fork bombs and runaway background processes.

### Is this a breakthrough, or did people already have better solutions?
**Honest answer: No, this is not a fundamental OS breakthrough.**  
Virtual filesystems (SSHFS/FUSE), containerization (Docker), and NTFS reparse points have existed for decades. Established tools like VS Code Remote Containers and DevPod already provide containerized environments.

However, existing Windows solutions force an awkward compromise:
1. *Host bind mounts* (`docker run -v C:\project:/workspace`) cross the Hyper-V / 9P virtualization boundary, resulting in a 100x+ I/O penalty.
2. *Internal container volumes* keep files trapped inside the container VM, making them inaccessible to local Windows tools, file watchers, and non-VSCode AI agent harnesses.
3. *Direct WSL UNC paths* (`\\wsl.localhost\...`) trigger path-normalizer bugs in Windows applications and AI harnesses.

AnyLink is pragmatic architectural glue: it connects NTFS junctions, WSL 9P, and reverse SSHFS to deliver native Linux ext4 speed, zero host pollution, and 100% Windows IDE compatibility.

### Why not just open `\\wsl.localhost\...` directly?
Opening UNC paths directly fails in many Windows applications and AI harnesses:
* **Path normalization bugs:** URI parsers frequently strip the `wsl.localhost` authority, turning `\\wsl.localhost\Ubuntu\home\...` into `C:\Ubuntu\...`, which fails immediately.
* **Network drive limitations:** Mapped network drives (`DRIVE_REMOTE`) frequently drop filesystem change events (`ReadDirectoryChangesW`).
* **The fix:** AnyLink creates a local NTFS junction on a fixed drive (`DRIVE_FIXED`, e.g. `D:\code\app`). The Windows kernel handles reparse resolution internally, ensuring full compatibility with file watchers and local path parsers.

---

## Real-World Use Cases

### Use Case 1: Autonomous AI Coding Agents

```
[Agent Prompt] 
      |
      v
[sandbox_manager.py create --name agent-task --cpus 2 --memory 2g]
      |
      +---> [Isolated Container Provisioned]
      |     - Native ext4 file system
      |     - Fast package installs and builds (106x speed)
      |
      +---> [Reverse SSHFS Mount in WSL]
      |
      +---> [NTFS Junction Created at D:\code\agent-task]
      |
      v
[Agent & Developer Work on D:\code\agent-task]
      | - Agent writes code directly to D:\code\agent-task
      | - Host IDE displays syntax highlighting and live diffs
      | - Agent runs commands: sandbox_manager.py exec agent-task -- npm test
      |
      v
[Task Complete -> Clean Teardown]
      |
      v
[sandbox_manager.py teardown agent-task]
      - Container stopped, FUSE unmounted, junction removed
      - Residual files on Windows host: ZERO
```

### Use Case 2: Native WSL 2 Toolchain Acceleration

```
[Windows Host IDE] -> Opens D:\code\my-app (Local NTFS Junction)
       |
       v  (In-kernel reparse: zero virtualization penalty)
[WSL 2 Linux ext4] -> Physical path: /home/user/code/my-app
       |
       v  (Native Linux in-memory VFS)
[Toolchains Execute Inside WSL 2]
       - cargo build / gcc / clang
       - npm / pnpm / yarn install
       - git status / commit / diff
       -> 180x - 254x faster than Windows host /mnt/c/ mounts
```

### Use Case 3: Safe Untrusted Code Auditing

```
[Untrusted Repository / PR]
       |
       v
[Provision Disposable Sandbox] -> docker run (isolated network, cgroup limits)
       |
       v
[Clone & Audit Inside Container]
       - Malicious install scripts cannot access Windows host (C:\, D:\)
       - Host credentials, SSH keys, and system files remain protected
       |
       v
[Review Code from Windows IDE] -> Read-only inspection via D:\code\audit-repo
       |
       v
[1-Click Dissolve] -> Container dropped, zero lingering artifacts
```

---

## Capability Comparison Matrix

| Capability / Feature | Host Mounts (`/mnt/c`) | Plain WSL 2 | Plain Docker | AnyLink (WSL Linker) |
| :--- | :---: | :---: | :---: | :---: |
| **Linux Build Speed** (`npm`, `cargo`, `gcc`) | `[FAIL]` (100x+ slower) | `[OK]` (Native ext4) | `[OK]` (Native ext4) | `[OK]` **Native ext4 (106x-254x)** |
| **Host IDE Compatibility** (Cursor, VS Code) | `[OK]` (Native NTFS) | `[WARN]` (UNC path bugs) | `[FAIL]` (Files trapped in VM) | `[OK]` **Native (`DRIVE_FIXED`)** |
| **File Watchers & Language Servers** | `[WARN]` (Drops events) | `[WARN]` (UNC normalizer issues) | `[FAIL]` (No host access) | `[OK]` **Full event support** |
| **Disposable Agent Sandboxing** | `[FAIL]` (Can damage host) | `[FAIL]` (Shared environment) | `[OK]` (Isolated) | `[OK]` **Isolated + resource limits** |
| **Zero Host Drive Clutter** | `[FAIL]` (Pollutes Windows) | `[OK]` (Inside WSL disk) | `[OK]` (Inside container) | `[OK]` **Zero host pollution** |
| **Multi-Version Dependency Isolation** | `[FAIL]` (Host conflicts) | `[WARN]` (Single distro) | `[OK]` (Containerized) | `[OK]` **Container per project** |
| **Survives Reboots & Sleep Cycles** | `[OK]` | `[OK]` | `[FAIL]` (Mounts drop) | `[OK]` **Self-healing daemon (20s)** |
| **Safe Teardown (Zero Data Loss)** | `[WARN]` (Lock hazards) | `[WARN]` (Manual unlinking) | `[WARN]` (Manual cleanup) | `[OK]` **Guaranteed (`os.rmdir`)** |

---

## Installation & Prerequisites

### Prerequisites
1. **Windows 10 (Build 19041+) or Windows 11** with **WSL 2** enabled.
2. **Windows Developer Mode Enabled:**
   * Settings -> System -> For Developers -> Toggle **Developer Mode** to **ON**.
   * *Reason:* Allows Windows to create directory symbolic links without requiring administrative elevation prompts.

### Installation

```bash
# Clone the repository
git clone https://github.com/fauzulkc/AnyLink.git
cd AnyLink

# Install GUI dependencies (optional, for desktop dashboards)
pip install customtkinter

# Run the standard WSL Linker GUI
python wsl_linker_gui.py

# Or run the Experimental Reverse Sandbox GUI
python experimental_linker_gui.py
```

Standalone precompiled executables (`WSL Linker.exe` and `WSL Linker Experimental.exe`) are available in the [Releases](https://github.com/fauzulkc/AnyLink/releases) section.

---

## CLI Reference

### 1. Standard WSL Linker CLI (`wsl_linker.py`)

```bash
# List all active mappings
python wsl_linker.py list

# Add a link: Windows path -> Linux WSL path
python wsl_linker.py add "D:\code\web-app" "/home/user/code/web-app" --distro Ubuntu-24.04

# Run a Linux command directly inside the linked directory
python wsl_linker.py run npm test
python wsl_linker.py run cargo build --release

# Safely remove a link (does not delete Linux files)
python wsl_linker.py remove web-app
```

### 2. Headless Sandbox Manager CLI (`scripts/sandbox_manager.py`)

Designed for AI agent harnesses and automated scripts. Supports `--json` on all commands.

```bash
# Provision an isolated container sandbox mapped to Windows
python scripts/sandbox_manager.py create --name agent-task --image node:20-alpine --cpus 2.0 --memory 2g --json

# Execute commands inside container workspace at native ext4 speed
python scripts/sandbox_manager.py exec agent-task -- npm install
python scripts/sandbox_manager.py exec agent-task -- npm test

# List active sandboxes and WSL links
python scripts/sandbox_manager.py list --json

# Inspect sandbox health, container state, and mount status
python scripts/sandbox_manager.py status agent-task --json

# Auto-reconnect stale mounts or restart stopped containers
python scripts/sandbox_manager.py heal agent-task

# Dissolve sandbox (unmounts FUSE, removes junction, stops container)
python scripts/sandbox_manager.py teardown agent-task --json
```

#### Available Flags for `sandbox_manager.py create`

| Flag | Description | Example |
| :--- | :--- | :--- |
| `-n`, `--name` | Unique alias name for the sandbox (required) | `--name test-env` |
| `-i`, `--image` | Docker base image (default: `alpine:latest`) | `--image python:3.11-slim` |
| `-p`, `--parent` | Windows parent folder for symlink (default: current dir) | `--parent D:\code` |
| `-d`, `--distro` | WSL 2 distro for SSHFS bridge (default: autodetected) | `--distro Ubuntu-24.04` |
| `--cpus` | CPU core allocation limit | `--cpus 1.5` |
| `-m`, `--memory` | Memory ceiling limit | `--memory 2g` |
| `--pids-limit` | Maximum process limit (prevents fork bombs) | `--pids-limit 200` |
| `-v`, `--volume` | Docker volume mount (named or host bind) | `-v my_cache:/workspace/.cache` |
| `--storage-opt` | Storage driver option (disk size cap) | `--storage-opt size=10G` |
| `--json` | Output machine-readable JSON | `--json` |

#### Machine-Readable JSON Output

When called with `--json`, `create` outputs structured connection details for immediate agent consumption:

```json
{
  "status": "success",
  "name": "agent-task",
  "container_name": "devlink_container_agent-task",
  "image": "node:20-alpine",
  "ssh_port": 2222,
  "windows_path": "\\\\wsl.localhost\\Ubuntu-24.04\\home\\user\\.devlinker-mounts\\agent-task\\workspace",
  "wsl_unc_path": "\\\\wsl.localhost\\Ubuntu-24.04\\home\\user\\.devlinker-mounts\\agent-task\\workspace",
  "wsl_distro": "Ubuntu-24.04",
  "wsl_mount_path": "/home/user/.devlinker-mounts/agent-task",
  "symlink_created": false,
  "link_type": "reverse"
}
```

---

## Security, Safety, and Compliance

* **Localhost-Only Network Binding:** Container SSH ports bind strictly to `127.0.0.1` (never `0.0.0.0`), preventing external network access to the sandbox bridge.
* **Safe Unlink Guarantee:** Symlink removal strictly uses `os.rmdir()` on verified directory junctions. It never recurses into directories and cannot delete files inside WSL or container filesystems.
* **Drive Type Validation:** Queries Windows `GetDriveTypeW` to prevent creating links on remote network drives (`DRIVE_REMOTE`), avoiding silent path failures.
* **Atomic Registry Writes:** Registry configurations are written via atomic temporary file swaps with automatic backup creation (`.corrupt.bak`) on parse failures.
* **Telemetry Free:** Runs 100% locally on your machine. Zero telemetry, zero external network calls.

---

## License

This project is licensed under the [MIT License](LICENSE).
