---
name: sandbox-linker
description: Provisions and manages isolated Docker reverse sandboxes and WSL 2 workspace bridges on Windows. Use when an agent needs a fast, isolated Linux development environment with zero host pollution that is directly editable from Windows host IDEs.
---

# Sandbox Linker: Agent Skill

## Overview

`sandbox-linker` enables any AI agent (Antigravity, Claude Code, Cursor, OpenHands, Codex) to programmatically spin up, execute inside, edit, and teardown isolated Linux Docker sandboxes and WSL 2 workspace links on Windows.

### The Problem It Solves
Traditional Docker on Windows uses host volume bind mounts (`-v C:\project:/workspace`), which forces all disk I/O through Windows 9P/SMB virtualization. This causes severe bottlenecks:
- **10x to 182x slower I/O** on file-intensive operations (`npm install`, `cargo build`, `pytest`, `git status`).
- **Host pollution**: `node_modules/`, `.venv/`, temporary caches, and platform-specific `.so`/`.bin` artifacts clutter the Windows filesystem.
- **File locking**: Windows indexers, antivirus engines, and open handles frequently lock files, breaking hot reloads and builds.

### The Reverse Sandbox Architecture
Instead of bind-mounting the slow Windows host into Docker, `sandbox-linker` reverses the relationship:
1. The project lives on **pure Linux ext4 filesystem** inside an isolated Docker container.
2. The container publishes an internal SSH tunnel port (`2222+`).
3. WSL 2 mounts the container via **FUSE SSHFS** (`~/.devlinker-mounts/<alias>`).
4. Windows accesses the workspace via a direct **symlink or UNC path** (`\\wsl.localhost\<distro>\...`).
5. AI agents and Windows IDEs (Cursor, VS Code, Antigravity) edit files directly at the Windows path with zero friction, while all compilation, dependencies, and test executions run at native ext4 speed inside the sandbox.

Benchmark proof: Multi-turn agent project builds run in **71.6s vs 659.6s** on host storage — a **9.2x (821%) speedup**.

---

## When to Use This Skill

Activate this skill whenever:
- The user requests to **"run in a sandbox"**, **"create an isolated dev environment"**, **"test this in docker"**, or **"link a WSL workspace"**.
- The task requires installing dependencies (`npm install`, `pip install`, `cargo`, `gem`) or running compilers on Windows without cluttering the user's host drives.
- The project needs high-performance Linux ext4 disk I/O for heavy testing, benchmarking, or multi-turn agent iterations.
- Running untrusted scripts or foreign code that should not have access to host Windows files.

---

## Headless CLI Tool (`sandbox_manager.py`)

The skill is driven by the headless Python CLI script `scripts/sandbox_manager.py` (zero GUI dependencies, standard Python library only).

### Script Resolution Order
To find `sandbox_manager.py`, look in:
1. Current workspace: `scripts/sandbox_manager.py` or `D:\code\sandbox-linker\scripts\sandbox_manager.py`
2. Skill bundled directory: `<skill_dir>/scripts/sandbox_manager.py`
3. Fallback path: `C:\Users\fauzu\.gemini\config\skills\sandbox-linker\scripts\sandbox_manager.py`

---

## Agent Step-by-Step Workflow

### Step 1: List Existing Environments
Check currently active sandboxes and WSL links before creating a new one:

```bash
python scripts/sandbox_manager.py list --json
```

Output:
```json
[
  {
    "name": "my-existing-app",
    "type": "docker-reverse",
    "status": "running",
    "image": "node:20-alpine",
    "container": "devlink_container_my-existing-app",
    "ssh_port": 2222,
    "windows_path": "\\\\wsl.localhost\\Ubuntu-24.04\\home\\fauzul\\.devlinker-mounts\\my-existing-app\\workspace",
    "wsl_distro": "Ubuntu-24.04"
  }
]
```

### Step 2: Provision a New Isolated Sandbox
Spin up a new isolated container and establish the reverse mount:

```bash
python scripts/sandbox_manager.py create --name <alias> --image <docker_image> --json
```

**Common Images:**
- `alpine:latest` (Ultra-lightweight Linux)
- `node:20-alpine` (Node.js & JavaScript/TypeScript)
- `python:3.11-slim` (Python backend)
- `mcr.microsoft.com/devcontainers/base:ubuntu` (Full Debian/Ubuntu environment with build tools)

**Optional Flags:**
- `-p`, `--parent`: Windows parent folder (e.g. `-p "D:\code"`). Defaults to current working directory.
- `-d`, `--distro`: WSL 2 distribution for SSHFS bridge (defaults to autodetected `Ubuntu-24.04`).
- `-e`, `--env`: Inject environment variables into the container (e.g. `-e API_KEY=xyz -e NODE_ENV=development`).
- `--cpus`: Limit CPU cores available to container (e.g. `--cpus 2.0`). Protects host from runaway compilation/infinite loops.
- `-m`, `--memory`: Hard-caps container RAM ceiling (e.g. `-m 512m`, `-m 2g`). Triggers in-container OOM-killer if exceeded, preventing Windows host freezes.
- `--pids-limit`: Maximum active container processes (e.g. `--pids-limit 100`). Protects against fork bombs or recursive script explosions.
- `-v`, `--volume`: Mount named Docker volumes (e.g. `-v my_vol:/workspace`) or secondary container volumes (`-v cache:/cache`).
- `--storage-opt`: Enforce disk quotas via Docker storage options (e.g. `--storage-opt size=10G`).

**Example:**
```bash
python scripts/sandbox_manager.py create --name agent-node-api --image node:20-alpine --json
```

**Response:**
```json
{
  "status": "success",
  "name": "agent-node-api",
  "container_name": "devlink_container_agent-node-api",
  "image": "node:20-alpine",
  "ssh_port": 2222,
  "windows_path": "\\\\wsl.localhost\\Ubuntu-24.04\\home\\fauzul\\.devlinker-mounts\\agent-node-api\\workspace",
  "wsl_unc_path": "\\\\wsl.localhost\\Ubuntu-24.04\\home\\fauzul\\.devlinker-mounts\\agent-node-api\\workspace",
  "wsl_distro": "Ubuntu-24.04",
  "wsl_mount_path": "/home/fauzul/.devlinker-mounts/agent-node-api",
  "symlink_created": false,
  "link_type": "reverse"
}
```

> [!IMPORTANT]
> Always parse the `windows_path` from the JSON response. This is the exact Windows file path where the agent and user can view and edit files.

### Step 3: Edit and Inspect Workspace Files
Agents and host IDEs read and write directly to `windows_path` using standard file tools (`read_file`, `write_file`, `edit_file`):

- **Windows Path**: `<windows_path>\package.json`
- **Inside Container**: `/workspace/package.json`

File writes reflect inside the container instantaneously with zero sync latency.

### Step 4: Execute Commands Inside the Container
Run tests, install packages, and execute builds inside the isolated container using `exec`:

```bash
python scripts/sandbox_manager.py exec <alias> -- <command>
```

**Examples:**
```bash
# Initialize Node project and install express
python scripts/sandbox_manager.py exec agent-node-api -- npm init -y
python scripts/sandbox_manager.py exec agent-node-api -- npm install express

# Run test suite
python scripts/sandbox_manager.py exec agent-node-api -- npm test

# Python pip installation and pytest
python scripts/sandbox_manager.py exec agent-python-app -- pip install -r requirements.txt
python scripts/sandbox_manager.py exec agent-python-app -- pytest -v
```

> [!TIP]
> Complex shell commands (pipes, redirects, environment chains) can be passed wrapped in quotes or via `sh -c`:
> ```bash
> python scripts/sandbox_manager.py exec agent-node-api -- sh -c "cat package.json | grep express"
> ```

### Step 5: Check Health & Self-Healing
If the host machine sleeps, Docker restarts, or a mount becomes stale:

```bash
# Check sandbox health (container running, SSHFS mount alive, Windows path valid)
python scripts/sandbox_manager.py status <alias> --json

# Automatically heal and remount stale sandboxes
python scripts/sandbox_manager.py heal <alias>
```

### Step 6: Safe Teardown and Cleanup
When the agent finishes its task or the user requests cleanup:

```bash
python scripts/sandbox_manager.py teardown <alias> --json
```

**What Teardown Does:**
1. Safely unmounts the WSL FUSE SSHFS tunnel (`fusermount3 -uz`).
2. Safely removes the Windows symlink/junction via `os.rmdir` (**never** recursive file deletion).
3. Stops and dissolves the Docker container (`docker rm -f`).
4. Cleans up the registry entry.

**Preserving the Container:**
If the user wants to detach the Windows mount but keep the Docker container alive:
```bash
python scripts/sandbox_manager.py teardown <alias> --keep-container
```

---

## WSL 2 Native Workspace Linking

For existing Linux codebases that already live inside WSL 2 (e.g. in `/home/fauzul/code/...`):

```bash
# Unified cross-platform link (Windows WSL, macOS, Linux)
python scripts/sandbox_manager.py link --name my-project --target /home/user/code/my-project --parent D:\code

# Safely unlink
python scripts/sandbox_manager.py unlink my-project

# Legacy WSL link/unlink (Windows only)
python scripts/sandbox_manager.py wsl-link --name my-project --target /home/fauzul/code/my-project --parent D:\code
python scripts/sandbox_manager.py wsl-unlink my-project
`

---

## Bi-Directional Compose & Kubernetes Transpiler (manifest_transpiler.py)

Transform existing production manifests into high-performance ext4 development meshes:

`ash
# 1. Transpile Docker Compose to AnyLink Mesh
python scripts/manifest_transpiler.py compose-to-mesh -i docker-compose.yml -o mesh.json

# 2. Transpile Kubernetes manifests to AnyLink Mesh
python scripts/manifest_transpiler.py k8s-to-mesh -i deployment.yaml -o mesh.json

# 3. Export modified mesh back to production Docker Compose
python scripts/manifest_transpiler.py mesh-to-compose -i mesh.json -o docker-compose.yml

# 4. Export modified mesh back to production Kubernetes manifests
python scripts/manifest_transpiler.py mesh-to-k8s -i mesh.json -o kubernetes.yaml
`

---

## Multi-Agent Development Mesh Orchestrator (mesh_orchestrator.py)

Orchestrate multi-service agent development topologies with shared ext4 volume buses:

`ash
# Boot mesh defined in mesh.json
python scripts/mesh_orchestrator.py up --file mesh.json

# Run commands inside any container node in the mesh
python scripts/mesh_orchestrator.py exec backend --file mesh.json -- python server.py

# Inspect mesh status and container health
python scripts/mesh_orchestrator.py status --file mesh.json

# Clean teardown with zero orphaned resources
python scripts/mesh_orchestrator.py down --file mesh.json
```

---

## Multi-Agent Compatibility Reference

| Agent Harness | Execution Method | File Tool Target |
| :--- | :--- | :--- |
| **Antigravity** | `run_command` (`python scripts/sandbox_manager.py ...`) | `write_file` / `edit_file` on `windows_path` |
| **Claude Code** | `Bash` (`python scripts/sandbox_manager.py ...`) | Read/Write on `windows_path` |
| **Cursor / Windsurf** | Integrated Terminal execution | Direct editor editing at `windows_path` |
| **OpenHands / SWE-agent** | Terminal execution tool | Local workspace path |
| **Python Scripts** | `subprocess.run(["python", "scripts/sandbox_manager.py", ...])` | Standard `open()` on `windows_path` |

---

## Best Practices & Safety Rules

1. **Never recursively delete Windows symlink targets**: Always use `sandbox_manager.py teardown` or `os.rmdir()`. Standard recursive deletions (`rm -rf` / `shutil.rmtree`) from Windows Explorer or CMD may attempt to delete underlying container files across the mount.
2. **Drive Selection**: When specifying `--parent`, prefer local fixed SSD drives (`C:`, `D:`) over network drives or cloud-synced folders (OneDrive, Google Drive).
3. **Port Collisions**: `sandbox_manager.py` automatically scans ports `2222-2321` and selects an unused port. Do not manually assign ports unless necessary.
4. **Environment Secrets**: Use `--env KEY=VALUE` to pass API keys and tokens directly into the container during creation, avoiding hardcoding secrets in files.
