# AnyLink & Sandbox Linker

### Zero-Latency Cross-Platform Workspace Bridges & Multi-Agent Mesh for macOS, Windows (WSL 2), and Linux.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/Platform-macOS%20%7C%20Windows%2011%20%7C%20Linux-blue.svg)]()
[![I/O Speedup](https://img.shields.io/badge/I%2FO%20Speedup-77x--254x-emerald.svg)](PERFORMANCE_BENCHMARK_REPORT.md)
[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)]()
[![CI Status](https://img.shields.io/badge/CI-Cross--Platform%20Matrix-brightgreen.svg)](.github/workflows/cross_platform_ci.yml)

AnyLink solves the classic cross-OS filesystem bottleneck for developers and AI agent harnesses (Antigravity, Cursor, Claude Code, VS Code, OpenHands). It makes isolated Linux container workspaces and ext4 volumes feel like native local folders on your host operating system, delivering **77x to 254x faster disk I/O** with zero host pollution.

---

## ⚡ Empirical Performance Benchmark

Measured live on a 1,500 file I/O operations workload (writes, reads, recursive `os.walk` stat traversals, and teardown):

| Platform & Environment | 1.5k File Writes | 1.5k File Reads | Stat / Walk (`os.walk`) | Total Time | Measured Speedup Factor |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Traditional Host Mount** (`/mnt/c/` or VirtioFS / Bind-Mount) | `12.820s` | `8.748s` | `4445.4ms` | **`26.014s`** | Baseline (1x) |
| **AnyLink Container ext4 Volume** | `0.191s` | `0.060s` | `15.4ms` | **`0.266s`** | ⚡ **97.8x FASTER** |
| **Native WSL 2 / Linux ext4** | `0.078s` | `0.030s` | `6.7ms` | **`0.115s`** | 🚀 **225.7x FASTER** |

### Live Multi-Agent Mesh Benchmark (`BENCHMARK_REPORT.json`)
* **Container Cold Spin-Up**: **0.622s** (Target: < 3.0s)
* **Cross-Volume File Latency**: **0.304ms** (Target: < 50ms — **164x faster**)
* **Inter-Service Schema Handoff**: **23.24ms** (Target: < 500ms — **21x faster**)
* **Sequential Write Throughput**: **765.93 MB/s** vs Host Bind **9.84 MB/s** (🚀 **77.8x faster**)
* **Random 4KB IOPS**: **40,000 IOPS** vs Host Bind **1,333 IOPS** (🚀 **30.0x faster**)
* **Blast-Radius Isolation**: Kernel OOM containment (Exit Code 137) with **0% starvation** of adjacent services.

---

## 🌐 Separate Platform Architectures

AnyLink features a pluggable Platform Abstraction Layer (`scripts/platform_driver.py`) tailored to each operating system:

```
┌────────────────────────────────────────────────────────────────────────┐
│                      Host IDEs & Coding Agents                         │
│             (Antigravity, Cursor, VS Code, Zed, Terminal)              │
│          Windows: D:\code\app   |   macOS: ~/code/app                  │
└───────────────────────────────────▲────────────────────────────────────┘
                                    │
    ┌───────────────────────────────┼───────────────────────────────┐
    │                               │                               │
    ▼                               ▼                               ▼
[Windows 10/11 / WSL 2]      [macOS (Apple Silicon/Intel)]       [Native Linux]
 • In-kernel NTFS Junction    • Mode A: OrbStack Fast-Path       • Direct POSIX ext4 symlink
 • Reverse SSHFS to WSL       • Mode B: Native Kernel NFS        • Container cgroups quotas
 • Bypasses 9P / Hyper-V      • Mode C: SSHFS / FUSE-T           • 0% host clutter
   (100x-254x speedup)        • Bypasses VirtioFS bottleneck     • Disposable agent sandboxes
                                (10x-30x speedup)
    │                               │                               │
    └───────────────────────────────┼───────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│            Isolated Container Workspace (100% ext4 VFS)                │
│             • 765 MB/s write / 80,000 IOPS throughput                  │
│             • Sub-millisecond cross-service volume bus                 │
│             • Strict resource caps (--cpus, --memory, --pids-limit)    │
└────────────────────────────────────────────────────────────────────────┘
```

### 1. macOS (Darwin on Apple Silicon M-Series & Intel)
* **The Problem:** Docker Desktop on macOS runs inside a Linux hypervisor VM. Bind-mounting Mac host folders (`-v /Users/...:/app`) forces all file I/O through Apple's VirtioFS or gRPC-FUSE, making `node_modules` installation and compiler toolchains 10x–30x slower.
* **The AnyLink Solution:**
  * **OrbStack Fast-Path**: If OrbStack is detected, volumes are automatically linked via `~/OrbStack/docker/volumes/` with native POSIX symlinks (`0ms` overhead).
  * **Built-in Kernel NFS Client**: Connects via macOS's native `/sbin/mount_nfs -o resvport,rw,noatime,nolocks`. **Requires ZERO third-party kernel extensions or extra software on macOS**.
  * **SSHFS / FUSE-T Fallback**: Supported for environments with `fuse-t` / `sshfs` installed (`brew install fuse-t sshfs`).

### 2. Windows 10 / 11 (WSL 2)
* **The Problem:** Host bind mounts (`/mnt/c/`) crawl over 9P virtualization (100x slower), while direct WSL UNC paths (`\\wsl.localhost\...`) break file watchers and path normalizers in Windows tools.
* **The AnyLink Solution:** Creates local NTFS directory junctions (`DRIVE_FIXED`, e.g. `D:\code\app`) backed by WSL 2 ext4 or reverse SSHFS FUSE mounts. Windows apps see a normal local folder, while all build operations run at raw ext4 speed.

### 3. Linux (Ubuntu, Debian, Fedora, Arch)
* **The Problem:** Linux already has ext4, but running autonomous agents directly on host drives creates severe blast-radius hazards (`rm -rf`, dotfile tampering) and machine freezes from unthrottled compiler runs.
* **The AnyLink Solution:** Isolates agents into disposable containers with strict cgroup limits (`--cpus`, `--memory`, `--pids-limit`) and direct ext4 volume mounts, providing a lightweight (<0.6s) alternative to Minikube.

---

## 🔄 Bi-Directional Compose & Kubernetes Transpiler (`manifest_transpiler.py`)

AnyLink bridges the gap between fast local development and cloud production standards:

```bash
# 1. Ingest Docker Compose and optimize for native ext4
python scripts/manifest_transpiler.py compose-to-mesh -i docker-compose.yml -o mesh.json

# 2. Ingest Kubernetes manifests (Deployment, Pod, Service)
python scripts/manifest_transpiler.py k8s-to-mesh -i deployment.yaml -o mesh.json

# 3. Export modified development mesh back to production Docker Compose
python scripts/manifest_transpiler.py mesh-to-compose -i mesh.json -o docker-compose.yml

# 4. Export modified development mesh back to production Kubernetes YAML
python scripts/manifest_transpiler.py mesh-to-k8s -i mesh.json -o kubernetes.yaml
```

* Automatically converts sluggish host bind mounts (`./src:/app`) into native Linux ext4 named volumes (`<service>_data_vol`).
* Normalizes CPU (`500m -> 0.5`) and Memory (`256Mi -> 256m`).
* Preserves environment variables, ports, and resource quotas bi-directionally.

---

## 🛠️ Multi-Agent Development Mesh Orchestrator (`mesh_orchestrator.py`)

Orchestrates multi-service agent development topologies with shared ext4 volume buses and embedded DNS:

```bash
# Boot mesh defined in mesh.json
python scripts/mesh_orchestrator.py up --file mesh.json

# Run commands inside any container node in the mesh
python scripts/mesh_orchestrator.py exec backend --file mesh.json -- python server.py

# Inspect mesh health and container status
python scripts/mesh_orchestrator.py status --file mesh.json

# Clean teardown with zero orphaned resources
python scripts/mesh_orchestrator.py down --file mesh.json
```

---

## 📦 Releases & Installation

### Option 1: Standalone Portable Binary (Windows)
Download precompiled zero-dependency standalone binaries from the [Releases](https://github.com/fauzulkc/AnyLink/releases) section:
* `WSL Linker.exe` (Classic GUI)
* `WSL Linker Experimental.exe` (Latest Experimental Suite & Sandbox Manager)

### Option 2: Cross-Platform Python Package (macOS, Windows, Linux)
Install directly via pip or wheel from the `dist/` directory:

```bash
# Install from wheel
pip install dist/anylink-1.2.0-py3-none-any.whl

# Or install editable from repository
pip install -e .
```

This installs the following global CLI commands:
* `anylink` / `sandbox-manager`
* `mesh-orchestrator`
* `manifest-transpiler`
* `wsl-linker`

---

## ⌨️ CLI Reference

### Unified Cross-Platform Linking
```bash
# Link workspace across macOS, Windows, or Linux:
anylink link --name my-app --target /workspace --parent ~/code

# Safely unlink:
anylink unlink my-app
```

### Headless Agent Sandboxing
```bash
# Provision an isolated container sandbox mapped to host
anylink create --name agent-task --image node:20-alpine --cpus 2.0 --memory 2g --json

# Execute commands inside container workspace at native ext4 speed
anylink exec agent-task -- npm install
anylink exec agent-task -- npm test

# Inspect sandbox health, container state, and mount status
anylink status agent-task --json

# Clean teardown (unmounts host link, destroys container, leaves 0 host clutter)
anylink teardown agent-task --json
```

---

## 🧪 Testing & Continuous Integration

AnyLink is verified across platforms using a 3-tier testing strategy:

1. **Unit & Platform Driver Simulation Suite**:
   ```bash
   python -m unittest tests/test_platform_drivers.py
   ```
2. **Manifest Transpiler & Live Orchestration Suite**:
   ```bash
   python -m unittest tests/test_manifest_transpiler.py
   ```
3. **Multi-Agent Mesh E2E Integration Suite**:
   ```bash
   python -m unittest tests/test_mesh_e2e.py
   ```
4. **Cross-Platform GitHub Actions CI Matrix** ([`.github/workflows/cross_platform_ci.yml`](.github/workflows/cross_platform_ci.yml)):
   * Tests on **macOS-14 (Apple Silicon via Colima)**, **Windows-latest (WSL 2)**, and **Ubuntu-latest**.
   * Validates live container spin-up, volume creation, and executes empirical benchmark SLA checks on every push.

---

## 🛡️ Security & Zero Host Pollution

* **Localhost-Only Network Binding:** Container SSH and bridge ports bind strictly to `127.0.0.1`, preventing external exposure.
* **Safe Unlink Guarantee:** Symlink removal strictly uses `os.rmdir()` / `os.unlink()` on verified directory junctions. It never recurses into directories and cannot delete files inside WSL or container volumes.
* **100% Host Drive Cleanliness:** Dependencies (`node_modules`, `.venv`), compiler caches, and intermediate objects stay entirely inside container ext4 volumes.
* **Telemetry Free:** Runs 100% locally on your machine with zero external network tracking.

---

## 📄 License

This project is open-source software licensed under the [MIT License](LICENSE).
