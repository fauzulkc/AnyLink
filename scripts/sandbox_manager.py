#!/usr/bin/env python3
"""
WSL Linker - Headless Sandbox Manager CLI

A standalone, zero-GUI CLI tool designed for AI agents (Antigravity, Claude Code,
Cursor, OpenHands, Codex) and headless automation to provision, execute inside,
inspect, heal, and tear down isolated Docker reverse sandboxes and WSL 2 symlinks.

Architecture:
  Docker Container (Isolated ext4 storage, zero host bind-mount)
       │ (internal sshd tunnel over port 2222+)
       ▼
  WSL 2 ext4 (FUSE SSHFS mount at ~/.devlinker-mounts/<alias>)
       │ (Windows 9P UNC link: \\wsl.localhost\<distro>\...)
       ▼
  Windows Host Path (Directory Symlink directly accessible by Windows IDEs / agents)
"""

import os
import sys
import json
import re
import shlex
import socket
import time
import datetime
import argparse
import subprocess
import tempfile
import shutil
import atexit
import signal
from pathlib import Path
from typing import Optional, Dict, Any, List

SSH_KEY_NAME = "devlinker_ed25519"

# Strict Alias Validation
ALIAS_REGEX = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$")

def validate_alias(alias: str) -> bool:
    """
    Validates alias to prevent command injection, traversal, and invalid Docker names.
    Format required: ^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$
    """
    if not isinstance(alias, str):
        return False
    return bool(ALIAS_REGEX.fullmatch(alias))

# Resilience: In-flight container cleanup hook
_pending_containers: set = set()

def _cleanup_pending_containers():
    for cname in list(_pending_containers):
        try:
            subprocess.run(["docker", "rm", "-f", cname], capture_output=True, timeout=10)
        except Exception:
            pass
    _pending_containers.clear()

atexit.register(_cleanup_pending_containers)

def _sig_handler(signum, frame):
    _cleanup_pending_containers()
    sys.exit(128 + signum)

try:
    signal.signal(signal.SIGINT, _sig_handler)
    signal.signal(signal.SIGTERM, _sig_handler)
except Exception:
    pass

# Configuration Paths
def get_experimental_dir() -> Path:
    env_dir = os.environ.get("WSL_LINKER_EXPERIMENTAL_DIR")
    p = Path(env_dir) if env_dir else Path.home() / ".wsl-linker-experimental"
    p.mkdir(parents=True, exist_ok=True)
    return p

def get_config_path() -> Path:
    return get_experimental_dir() / "config.json"

def get_canonical_registry_path() -> Path:
    env_dir = os.environ.get("WSL_LINKER_CONFIG_DIR")
    p = Path(env_dir) if env_dir else Path.home() / ".wsl-linker"
    p.mkdir(parents=True, exist_ok=True)
    return p / "links.json"

def _atomic_write_json(file_path: Path, data: Any) -> None:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    dir_path = file_path.parent
    temp_file = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=dir_path, delete=False, encoding="utf-8") as f:
            temp_file = f.name
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, file_path)
        temp_file = None
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass

def load_registry() -> Dict[str, Any]:
    path = get_config_path()
    data: Dict[str, Any] = {
        "wsl_mappings": [],
        "docker_mappings": [],
        "ssh_mappings": [],
        "credentials": {},
        "env_vars": {},
        "bridge_active": False,
    }
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                if isinstance(loaded, dict):
                    data.update(loaded)
                else:
                    raise ValueError(f"Root JSON entity in '{path}' must be an object")
        except Exception as e:
            bak_path = path.with_name(path.name + ".corrupt.bak")
            try:
                shutil.copy2(path, bak_path)
            except Exception:
                pass
            raise RuntimeError(f"Corrupt registry at '{path}': {e}. Backup created at '{bak_path}'") from e

    for key in ["wsl_mappings", "docker_mappings", "ssh_mappings"]:
        if key not in data:
            data[key] = []
    if "credentials" not in data:
        data["credentials"] = {}
    if "env_vars" not in data:
        data["env_vars"] = {}

    # Sync canonical WSL mappings
    canonical_path = get_canonical_registry_path()
    if canonical_path.exists():
        try:
            with open(canonical_path, "r", encoding="utf-8") as f:
                cdata = json.load(f)
                if isinstance(cdata, dict):
                    c_mappings = cdata.get("mappings", [])
                    existing_names = {m.get("name", "").lower() for m in data["wsl_mappings"]}
                    for cm in c_mappings:
                        if cm.get("name", "").lower() not in existing_names:
                            data["wsl_mappings"].append(cm)
                            existing_names.add(cm.get("name", "").lower())
                else:
                    raise ValueError(f"Root JSON entity in '{canonical_path}' must be an object")
        except Exception as e:
            bak_path = canonical_path.with_name(canonical_path.name + ".corrupt.bak")
            try:
                shutil.copy2(canonical_path, bak_path)
            except Exception:
                pass
            raise RuntimeError(f"Corrupt canonical registry at '{canonical_path}': {e}. Backup created at '{bak_path}'") from e

    return data

def save_registry(data: Dict[str, Any]) -> None:
    # 1. Experimental config
    _atomic_write_json(get_config_path(), data)

    # 2. Canonical WSL registry
    try:
        canonical_path = get_canonical_registry_path()
        cdata = {"mappings": data.get("wsl_mappings", [])}
        _atomic_write_json(canonical_path, cdata)
    except Exception:
        pass

def get_wsl_distros() -> List[str]:
    try:
        result = subprocess.run(["wsl", "--list", "--quiet"], capture_output=True, text=True, encoding="utf-16le")
        output = result.stdout
        if not output:
            result = subprocess.run(["wsl", "--list", "--quiet"], capture_output=True, text=True, encoding="utf-8")
            output = result.stdout
        distros = [line.strip().replace("\x00", "") for line in output.split("\n") if line.strip() and line.strip().replace("\x00", "")]
        distros = [d for d in distros if not d.lower().startswith("docker-desktop")]
        return distros if distros else ["Ubuntu-24.04"]
    except Exception:
        return ["Ubuntu-24.04"]

def detect_default_distro() -> str:
    distros = get_wsl_distros()
    for d in distros:
        if "ubuntu" in d.lower():
            return d
    return distros[0] if distros else "Ubuntu-24.04"

def wsl_run(distro: str, script: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["wsl", "-d", distro, "--cd", "~", "-e", "bash", "-c", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
    )

def get_wsl_home(distro: str) -> str:
    try:
        r = wsl_run(distro, 'printf %s "$HOME"', timeout=30)
        home = r.stdout.strip()
        if r.returncode == 0 and home.startswith("/"):
            return home
    except Exception:
        pass
    return "/root"

def ensure_wsl_ssh_key(distro: str) -> str:
    key = f"$HOME/.ssh/{SSH_KEY_NAME}"
    script = (
        f'mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh" && '
        f'[ -f "{key}" ] || ssh-keygen -q -t ed25519 -N "" -f "{key}" >/dev/null; '
        f'cat "{key}.pub"'
    )
    r = wsl_run(distro, script, timeout=60)
    pub = r.stdout.strip()
    if r.returncode != 0 or not pub.startswith("ssh-"):
        raise RuntimeError(f"Could not create WSL SSH key: {r.stderr.strip() or r.stdout.strip()}")
    return pub

def find_free_port(db: Dict[str, Any]) -> int:
    used = set()
    for m in db.get("docker_mappings", []):
        p = m.get("ssh_port")
        if p is not None:
            try:
                used.add(int(p))
            except (ValueError, TypeError):
                pass
    for port in range(2222, 2322):
        if port in used:
            continue
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue
        return port
    raise RuntimeError("No free port available in range 2222-2321")

def setup_container_ssh(container_name: str, distro: str) -> bool:
    pub = ensure_wsl_ssh_key(distro)
    script = r'''
set -e
if ! command -v sshd >/dev/null 2>&1 && [ ! -x /usr/sbin/sshd ]; then
  if command -v apk >/dev/null 2>&1; then apk add --no-cache openssh >/dev/null
  elif command -v apt-get >/dev/null 2>&1; then apt-get update >/dev/null && DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server >/dev/null
  else echo "Unsupported base image (need apk or apt-get)" >&2; exit 3; fi
fi
ssh-keygen -A >/dev/null
mkdir -p /run/sshd /root/.ssh /workspace
chmod 777 /workspace
chmod 700 /root/.ssh
printf '%s\n' "$PUBKEY" > /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
# Unlock root (Alpine root is locked by default)
sed -i 's/^root:![^:]*:/root:*:/' /etc/shadow 2>/dev/null || true
sed -i -E 's/^#?PermitRootLogin.*/PermitRootLogin prohibit-password/; s/^#?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
grep -q '^PermitRootLogin' /etc/ssh/sshd_config || echo 'PermitRootLogin prohibit-password' >> /etc/ssh/sshd_config
grep -q '^Subsystem.*sftp' /etc/ssh/sshd_config || echo 'Subsystem sftp internal-sftp' >> /etc/ssh/sshd_config
/usr/sbin/sshd 2>/dev/null || true
'''
    r = subprocess.run(
        ["docker", "exec", "-e", f"PUBKEY={pub}", container_name, "sh", "-c", script],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300
    )
    return r.returncode == 0

def sshfs_mount_script(port: int, mount_path: str) -> str:
    key = f"$HOME/.ssh/{SSH_KEY_NAME}"
    opts = (
        f"IdentityFile={key},port={port},StrictHostKeyChecking=no,UserKnownHostsFile=/dev/null,"
        "reconnect,ServerAliveInterval=10,ServerAliveCountMax=3,idmap=user,allow_other,BatchMode=yes,"
        "kernel_cache,auto_cache,entry_timeout=60,attr_timeout=60,big_writes,max_read=131072,max_write=131072,compression=no"
    )
    # FUSE 3 (Ubuntu 22.04+) deprecated/removed 'big_writes'; fall back if rejected
    opts_compat = opts.replace("big_writes,", "").replace(",big_writes", "")
    q_mount = shlex.quote(mount_path)
    return (
        f'M={q_mount}; mkdir -p "$M"; '
        f'(fusermount3 -uz "$M" || fusermount -uz "$M") >/dev/null 2>&1; '
        f'sshfs -o {opts} root@127.0.0.1:/ "$M" 2>/dev/null || '
        f'sshfs -o {opts_compat} root@127.0.0.1:/ "$M"'
    )

def setup_wsl_sshfs_mount(distro: str, port: int, wsl_mount_path: str) -> bool:
    # Ensure sshfs is available in WSL
    if wsl_run(distro, "command -v sshfs >/dev/null 2>&1").returncode != 0:
        r = wsl_run(distro, "sudo -n apt-get update >/dev/null && sudo -n apt-get install -y sshfs >/dev/null", timeout=300)
        if r.returncode != 0:
            raise RuntimeError(f"sshfs is missing in WSL distro {distro}. Please run 'sudo apt install sshfs'.")
    # Ensure user_allow_other in /etc/fuse.conf
    wsl_run(distro, "grep -q '^user_allow_other' /etc/fuse.conf 2>/dev/null || echo user_allow_other | sudo -n tee -a /etc/fuse.conf >/dev/null 2>&1; true")

    for _ in range(5):
        r = wsl_run(distro, sshfs_mount_script(port, wsl_mount_path), timeout=60)
        if r.returncode == 0:
            break
        time.sleep(2)
    else:
        return False

    q_ws = shlex.quote(f"{wsl_mount_path}/workspace")
    v = wsl_run(distro, f'ls {q_ws} >/dev/null', timeout=30)
    return v.returncode == 0

def unmount_wsl_sshfs(distro: str, wsl_mount_path: str) -> None:
    try:
        q_mount = shlex.quote(wsl_mount_path)
        wsl_run(
            distro,
            f'M={q_mount}; (fusermount3 -uz "$M" || fusermount -uz "$M") >/dev/null 2>&1; rmdir "$M" 2>/dev/null; true',
            timeout=30
        )
    except Exception:
        pass

# =====================================================================
# COMMAND IMPLEMENTATIONS
# =====================================================================
def cmd_create(args: argparse.Namespace) -> int:
    alias = args.name.strip()
    image = args.image.strip()
    parent = os.path.abspath(args.parent) if args.parent else os.getcwd()
    distro = args.distro.strip() if args.distro else detect_default_distro()

    if not alias:
        print("[ERROR] Sandbox name (--name / -n) is required.", file=sys.stderr)
        return 1

    if not validate_alias(alias):
        err = f"Invalid sandbox alias '{alias}'. Must match ^[a-zA-Z0-9][a-zA-Z0-9_.-]{{0,62}}$ (alphanumeric start, allowed: letters, digits, _, ., -, max 63 chars)."
        if args.json:
            print(json.dumps({"status": "error", "message": err}))
        else:
            print(f"[ERROR] {err}", file=sys.stderr)
        return 1

    win_path = os.path.join(parent, alias)
    if os.path.exists(win_path) and not os.path.islink(win_path):
        err = f"A regular directory or file already exists at '{win_path}'. Please use a different name or remove it first."
        if args.json:
            print(json.dumps({"status": "error", "message": err}))
        else:
            print(f"[ERROR] {err}", file=sys.stderr)
        return 1

    db = load_registry()
    container_name = f"devlink_container_{alias}"

    # Allocate port
    try:
        port = find_free_port(db)
    except RuntimeError as e:
        if args.json:
            print(json.dumps({"status": "error", "message": str(e)}))
        else:
            print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    wsl_home = get_wsl_home(distro)
    wsl_mount_path = f"{wsl_home}/.devlinker-mounts/{alias}"

    if not args.json:
        print(f"[*] Provisioning sandbox '{alias}'...")
        print(f"    - Base Image      : {image}")
        print(f"    - Container Name  : {container_name}")
        print(f"    - SSH Tunnel Port : {port}")
        print(f"    - WSL Distro      : {distro}")
        print(f"    - Windows Target  : {win_path}")
        if getattr(args, "cpus", None):
            print(f"    - CPU Limit       : {args.cpus} cores")
        if getattr(args, "memory", None):
            print(f"    - Memory Limit    : {args.memory}")
        if getattr(args, "pids_limit", None):
            print(f"    - Max Processes   : {args.pids_limit} PIDs")
        if getattr(args, "volume", None):
            print(f"    - Volumes Mounted : {', '.join(args.volume)}")

    # Track in-flight container for signal/atexit cleanup
    _pending_containers.add(container_name)

    # Launch Container
    subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
    docker_cmd = [
        "docker", "run", "-d",
        "--name", container_name,
        "--restart", "unless-stopped",
        "-p", f"127.0.0.1:{port}:22",
        "-w", "/workspace",
    ]

    # Resource throttling & cgroup limits
    if getattr(args, "cpus", None) is not None:
        try:
            c = float(args.cpus)
            if c <= 0:
                raise ValueError("Must be positive")
            docker_cmd.extend(["--cpus", str(args.cpus)])
        except ValueError:
            err = f"Invalid --cpus value '{args.cpus}'. Must be a positive number (e.g. 1.5, 2.0)."
            if args.json:
                print(json.dumps({"status": "error", "message": err}))
            else:
                print(f"[ERROR] {err}", file=sys.stderr)
            return 1

    if getattr(args, "memory", None) is not None:
        mem_str = str(args.memory).strip()
        if not re.match(r"^[1-9][0-9]*[bkmgBKMG]$", mem_str):
            err = f"Invalid --memory value '{args.memory}'. Format must be <num>[b|k|m|g] (e.g. 512m, 2g)."
            if args.json:
                print(json.dumps({"status": "error", "message": err}))
            else:
                print(f"[ERROR] {err}", file=sys.stderr)
            return 1
        docker_cmd.extend(["--memory", mem_str.lower(), "--memory-swap", mem_str.lower()])

    if getattr(args, "pids_limit", None) is not None:
        try:
            p = int(args.pids_limit)
            if p <= 0:
                raise ValueError("Must be positive")
            docker_cmd.extend(["--pids-limit", str(p)])
        except ValueError:
            err = f"Invalid --pids-limit value '{args.pids_limit}'. Must be a positive integer."
            if args.json:
                print(json.dumps({"status": "error", "message": err}))
            else:
                print(f"[ERROR] {err}", file=sys.stderr)
            return 1

    # Volume mounting (named volumes or container paths)
    if getattr(args, "volume", None):
        for vol in args.volume:
            vol = str(vol).strip()
            if not vol:
                continue
            docker_cmd.extend(["-v", vol])

    # Storage options (disk quotas)
    if getattr(args, "storage_opt", None):
        for sopt in args.storage_opt:
            sopt = str(sopt).strip()
            if not sopt:
                continue
            docker_cmd.extend(["--storage-opt", sopt])

    # Environment variables
    if args.env:
        for ev in args.env:
            docker_cmd.extend(["-e", ev])

    # Start sshd on launch
    docker_cmd.extend([
        image,
        "sh", "-c", "mkdir -p /workspace && chmod 777 /workspace && /usr/sbin/sshd 2>/dev/null; exec tail -f /dev/null"
    ])

    res = subprocess.run(docker_cmd, capture_output=True, text=True)
    if res.returncode != 0:
        _pending_containers.discard(container_name)
        err = f"Docker container run failed: {res.stderr.strip()}"
        if args.json:
            print(json.dumps({"status": "error", "message": err}))
        else:
            print(f"[ERROR] {err}", file=sys.stderr)
        return 1

    # Container SSH setup
    if not setup_container_ssh(container_name, distro):
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
        _pending_containers.discard(container_name)
        err = "Failed to configure SSH and authorized_keys inside container."
        if args.json:
            print(json.dumps({"status": "error", "message": err}))
        else:
            print(f"[ERROR] {err}", file=sys.stderr)
        return 1

    # SSHFS reverse mount inside WSL
    try:
        if not setup_wsl_sshfs_mount(distro, port, wsl_mount_path):
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
            _pending_containers.discard(container_name)
            err = "Failed to establish SSHFS mount from WSL."
            if args.json:
                print(json.dumps({"status": "error", "message": err}))
            else:
                print(f"[ERROR] {err}", file=sys.stderr)
            return 1
    except Exception as e:
        subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)
        _pending_containers.discard(container_name)
        if args.json:
            print(json.dumps({"status": "error", "message": str(e)}))
        else:
            print(f"[ERROR] {e}", file=sys.stderr)
        return 1

    # Windows symlink with normalized UNC path
    normalized_mnt = "/" + f"{wsl_mount_path}/workspace".replace('\\', '/').lstrip('/')
    wsl_unc = f"\\\\wsl.localhost\\{distro}" + normalized_mnt.replace("/", "\\")
    symlink_ok = False
    try:
        if win_path and os.path.islink(win_path):
            os.rmdir(win_path)
        os.symlink(wsl_unc, win_path, target_is_directory=True)
        symlink_ok = True
    except Exception as e:
        if not args.json:
            print(f"[WARN] Windows symlink creation failed ({e}). Falling back to direct WSL UNC path.")
        win_path = wsl_unc

    # Save to registry
    # Remove any existing record for this name
    db["docker_mappings"] = [m for m in db["docker_mappings"] if m.get("name", "").lower() != alias.lower()]
    resource_info = {
        "cpus": getattr(args, "cpus", None),
        "memory": getattr(args, "memory", None),
        "pids_limit": getattr(args, "pids_limit", None),
        "volumes": getattr(args, "volume", None) or [],
        "storage_opt": getattr(args, "storage_opt", None) or [],
    }
    mapping = {
        "name": alias,
        "container_name": container_name,
        "image": image,
        "link_type": "reverse",
        "ssh_port": port,
        "wsl_distro": distro,
        "wsl_mount_path": wsl_mount_path,
        "wsl_unc_path": wsl_unc,
        "windows_path": win_path,
        "symlink_created": symlink_ok,
        "resources": resource_info,
        "created_at": datetime.datetime.now().isoformat()
    }
    db["docker_mappings"].append(mapping)
    save_registry(db)
    _pending_containers.discard(container_name)

    result_data = {
        "status": "success",
        "name": alias,
        "container_name": container_name,
        "image": image,
        "ssh_port": port,
        "windows_path": win_path,
        "wsl_unc_path": wsl_unc,
        "wsl_distro": distro,
        "wsl_mount_path": wsl_mount_path,
        "symlink_created": symlink_ok,
        "resources": resource_info,
        "link_type": "reverse"
    }

    if args.json:
        print(json.dumps(result_data, indent=2))
    else:
        print(f"\n[SUCCESS] Sandbox '{alias}' is active and ready!")
        print(f" -> Windows Workspace Path : {win_path}")
        print(f" -> Docker Container Target: {container_name}:/workspace")
        print(f" -> SSH Tunnel Port        : {port}")
        print(f"\nAI agents and IDEs can now edit files directly at: {win_path}")
        print(f"Run commands inside sandbox with: python scripts/sandbox_manager.py exec {alias} -- <cmd>")

    return 0

def cmd_exec(args: argparse.Namespace) -> int:
    name = args.name.strip()
    cmd = args.cmd

    if not cmd:
        print("[ERROR] No command specified to execute.", file=sys.stderr)
        return 1

    db = load_registry()
    target = next((m for m in db["docker_mappings"] if m.get("name", "").lower() == name.lower()), None)
    container_name = target.get("container_name") if target else f"devlink_container_{name}"

    # Verify container exists
    chk = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", container_name], capture_output=True, text=True)
    if chk.returncode != 0:
        print(f"[ERROR] Container '{container_name}' does not exist.", file=sys.stderr)
        return 1

    if "true" not in chk.stdout:
        print(f"[*] Container '{container_name}' is stopped. Starting container...")
        subprocess.run(["docker", "start", container_name], check=True)

    exec_cmd = ["docker", "exec"]
    if args.user:
        exec_cmd.extend(["-u", args.user])
    if args.workdir:
        exec_cmd.extend(["-w", args.workdir])
    else:
        exec_cmd.extend(["-w", "/workspace"])

    exec_cmd.append(container_name)

    # If command is passed as list of arguments, join or invoke via sh -c
    if len(cmd) == 1 and (" " in cmd[0] or "|" in cmd[0] or "&" in cmd[0]):
        exec_cmd.extend(["sh", "-c", cmd[0]])
    else:
        exec_cmd.extend(cmd)

    proc = subprocess.run(exec_cmd)
    return proc.returncode

def cmd_list(args: argparse.Namespace) -> int:
    db = load_registry()
    docker_sandboxes = db.get("docker_mappings", [])
    wsl_mappings = db.get("wsl_mappings", [])

    results = []

    for d in docker_sandboxes:
        cname = d.get("container_name", "")
        # Inspect state
        chk = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", cname], capture_output=True, text=True)
        running = (chk.returncode == 0 and "true" in chk.stdout)
        results.append({
            "name": d.get("name"),
            "type": "docker-reverse",
            "status": "running" if running else "stopped",
            "image": d.get("image", "unknown"),
            "container": cname,
            "ssh_port": d.get("ssh_port"),
            "windows_path": d.get("windows_path"),
            "wsl_distro": d.get("wsl_distro"),
        })

    for w in wsl_mappings:
        results.append({
            "name": w.get("name"),
            "type": "wsl",
            "status": "active",
            "image": None,
            "container": None,
            "ssh_port": None,
            "windows_path": w.get("windows_path"),
            "wsl_distro": w.get("wsl_distro"),
            "wsl_path": w.get("wsl_path"),
        })

    if args.json:
        print(json.dumps(results, indent=2))
        return 0

    print(f"\nRegistered Workspaces & Sandboxes ({len(results)}):")
    print("-" * 80)
    fmt = "{:<16} {:<15} {:<10} {:<18} {:<20}"
    print(fmt.format("ALIAS", "TYPE", "STATUS", "DETAILS", "WINDOWS PATH"))
    print("-" * 80)
    for r in results:
        details = r.get("image") or r.get("wsl_distro") or ""
        if r.get("ssh_port"):
            details += f" (:{r['ssh_port']})"
        print(fmt.format(
            r["name"][:15],
            r["type"][:14],
            r["status"],
            details[:17],
            r["windows_path"] or ""
        ))
    print("-" * 80)
    return 0

def cmd_status(args: argparse.Namespace) -> int:
    name = args.name.strip()
    db = load_registry()
    target = next((m for m in db["docker_mappings"] if m.get("name", "").lower() == name.lower()), None)

    if not target:
        wsl_target = next((m for m in db["wsl_mappings"] if m.get("name", "").lower() == name.lower()), None)
        if wsl_target:
            path_exists = os.path.exists(wsl_target.get("windows_path", ""))
            data = {
                "name": name,
                "type": "wsl",
                "status": "healthy" if path_exists else "unreachable",
                "windows_path": wsl_target.get("windows_path"),
                "wsl_path": wsl_target.get("wsl_path"),
                "wsl_distro": wsl_target.get("wsl_distro")
            }
            if args.json:
                print(json.dumps(data, indent=2))
            else:
                print(f"WSL Link '{name}': {data['status']}")
                print(f"Path: {data['windows_path']} -> {data['wsl_path']}")
            return 0 if path_exists else 1

        err = f"No sandbox or workspace registered with name '{name}'."
        if args.json:
            print(json.dumps({"status": "error", "message": err}))
        else:
            print(f"[ERROR] {err}", file=sys.stderr)
        return 1

    cname = target.get("container_name", "")
    distro = target.get("wsl_distro", "Ubuntu-24.04")
    mnt = target.get("wsl_mount_path", "")
    win_path = target.get("windows_path", "")

    # 1. Container check
    chk = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", cname], capture_output=True, text=True)
    c_running = (chk.returncode == 0 and "true" in chk.stdout)

    # 2. Mount check
    m_healthy = False
    if c_running:
        m_chk = wsl_run(distro, f'timeout 5 ls "{mnt}/workspace" >/dev/null 2>&1', timeout=10)
        m_healthy = (m_chk.returncode == 0)

    # 3. Windows path check
    w_accessible = os.path.exists(win_path)

    overall = "healthy" if (c_running and m_healthy and w_accessible) else "degraded"

    data = {
        "name": name,
        "type": "docker-reverse",
        "overall_status": overall,
        "container_running": c_running,
        "mount_healthy": m_healthy,
        "windows_path_accessible": w_accessible,
        "container_name": cname,
        "ssh_port": target.get("ssh_port"),
        "windows_path": win_path,
        "wsl_mount_path": mnt,
        "wsl_distro": distro
    }

    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(f"\nSandbox Status: {name} ({overall.upper()})")
        print(f" - Container Running : {c_running} ({cname})")
        print(f" - WSL SSHFS Mount   : {m_healthy} ({mnt})")
        print(f" - Windows Symlink   : {w_accessible} ({win_path})")

    return 0 if overall == "healthy" else 1

def cmd_heal(args: argparse.Namespace) -> int:
    alias = args.name.strip() if args.name else None
    db = load_registry()
    sandboxes = db.get("docker_mappings", [])
    if alias:
        sandboxes = [s for s in sandboxes if s.get("name", "").lower() == alias.lower()]
        if not sandboxes:
            print(f"[ERROR] Sandbox '{alias}' not found in registry.", file=sys.stderr)
            return 1

    healed_count = 0
    for s in sandboxes:
        name = s.get("name")
        cname = s.get("container_name")
        distro = s.get("wsl_distro")
        mnt = s.get("wsl_mount_path")
        port = s.get("ssh_port")

        print(f"[*] Checking health of sandbox '{name}'...")
        # Check container
        st = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", cname], capture_output=True, text=True)
        if st.returncode != 0:
            print(f"    [WARN] Container '{cname}' does not exist.")
            continue

        if "true" not in st.stdout:
            print(f"    -> Container stopped. Starting container...")
            subprocess.run(["docker", "start", cname], capture_output=True)
            time.sleep(2)

        # Check mount
        q_ws = shlex.quote(f"{mnt}/workspace")
        healthy = wsl_run(distro, f'timeout 5 ls {q_ws} >/dev/null 2>&1', timeout=10).returncode == 0
        if not healthy:
            print(f"    -> Mount stale. Relaunching container sshd & remounting...")
            subprocess.run(["docker", "exec", cname, "sh", "-c", "/usr/sbin/sshd 2>/dev/null; true"], capture_output=True)
            r = wsl_run(distro, sshfs_mount_script(port, mnt), timeout=60)
            if r.returncode == 0:
                print(f"    [SUCCESS] Mount restored for '{name}'.")
                healed_count += 1
            else:
                print(f"    [ERROR] Could not restore mount: {r.stderr.strip()}", file=sys.stderr)
        else:
            print(f"    -> Mount is healthy.")

    print(f"\n[DONE] Healed {healed_count} sandbox(es).")
    return 0

def cmd_teardown(args: argparse.Namespace) -> int:
    alias = args.name.strip()
    db = load_registry()
    target = next((m for m in db["docker_mappings"] if m.get("name", "").lower() == alias.lower()), None)

    if not target:
        err = f"No Docker sandbox registered under name '{alias}'."
        if args.json:
            print(json.dumps({"status": "error", "message": err}))
        else:
            print(f"[ERROR] {err}", file=sys.stderr)
        return 1

    win_path = target.get("windows_path", "")
    distro = target.get("wsl_distro", "")
    mnt = target.get("wsl_mount_path", "")
    cname = target.get("container_name", "")

    if not args.json:
        print(f"[*] Tearing down sandbox '{alias}'...")

    # 1. Remove Windows Symlink safely (ONLY remove if islink, NEVER regular directories)
    if win_path and os.path.islink(win_path):
        try:
            os.rmdir(win_path)
            if not args.json:
                print(f"    -> Windows symlink removed: {win_path}")
        except Exception as e:
            if not args.json:
                print(f"    [WARN] Symlink removal failed: {e}")
    elif win_path and os.path.exists(win_path):
        if not args.json:
            print(f"    [WARN] Target '{win_path}' is a regular directory/file, skipping removal for safety.", file=sys.stderr)

    # 2. Unmount SSHFS in WSL
    if distro and mnt:
        unmount_wsl_sshfs(distro, mnt)
        if not args.json:
            print(f"    -> WSL SSHFS unmounted: {mnt}")

    # 3. Stop and remove container (unless --keep-container)
    if not args.keep_container and cname:
        subprocess.run(["docker", "rm", "-f", cname], capture_output=True)
        if not args.json:
            print(f"    -> Docker container destroyed: {cname}")

    # 4. Remove from registry
    db["docker_mappings"] = [m for m in db["docker_mappings"] if m.get("name", "").lower() != alias.lower()]
    save_registry(db)

    res = {
        "status": "success",
        "message": f"Sandbox '{alias}' successfully torn down.",
        "name": alias,
        "container_destroyed": not args.keep_container
    }

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"[SUCCESS] Sandbox '{alias}' torn down cleanly.")

    return 0

def cmd_wsl_link(args: argparse.Namespace) -> int:
    alias = args.name.strip()
    target = args.target.strip()
    parent = os.path.abspath(args.parent) if args.parent else os.getcwd()
    distro = args.distro.strip() if args.distro else detect_default_distro()

    if not validate_alias(alias):
        print(f"[ERROR] Invalid alias '{alias}'. Must match ^[a-zA-Z0-9][a-zA-Z0-9_.-]{{0,62}}$.", file=sys.stderr)
        return 1

    target = "/" + target.replace('\\', '/').lstrip('/')
    win_path = os.path.join(parent, alias)
    wsl_unc = f"\\\\wsl.localhost\\{distro}" + target.replace('/', '\\')

    if os.path.exists(win_path):
        if os.path.islink(win_path):
            try:
                os.rmdir(win_path)
            except Exception:
                pass
        else:
            print(f"[ERROR] Directory '{win_path}' already exists and is not a symlink.", file=sys.stderr)
            return 1

    try:
        os.symlink(wsl_unc, win_path, target_is_directory=True)
        db = load_registry()
        db["wsl_mappings"] = [m for m in db["wsl_mappings"] if m.get("name", "").lower() != alias.lower()]
        db["wsl_mappings"].append({
            "name": alias,
            "windows_path": win_path,
            "wsl_distro": distro,
            "wsl_path": target,
            "created_at": datetime.datetime.now().isoformat()
        })
        save_registry(db)
        print(f"[SUCCESS] WSL Link established: {win_path} -> {wsl_unc}")
        return 0
    except Exception as e:
        print(f"[ERROR] Failed to create symlink: {e}", file=sys.stderr)
        return 1

def cmd_wsl_unlink(args: argparse.Namespace) -> int:
    alias = args.name.strip()
    db = load_registry()
    target = next((m for m in db["wsl_mappings"] if m.get("name", "").lower() == alias.lower()), None)
    if not target:
        print(f"[ERROR] WSL mapping '{alias}' not found.", file=sys.stderr)
        return 1

    win_path = target.get("windows_path", "")
    if win_path and os.path.islink(win_path):
        try:
            os.rmdir(win_path)
        except Exception as e:
            print(f"[WARN] Failed to remove link: {e}")
    elif win_path and os.path.exists(win_path):
        print(f"[WARN] Target '{win_path}' is a regular directory, skipping removal for safety.", file=sys.stderr)

    db["wsl_mappings"] = [m for m in db["wsl_mappings"] if m.get("name", "").lower() != alias.lower()]
    save_registry(db)
    print(f"[SUCCESS] WSL Link '{alias}' unlinked.")
    return 0

# =====================================================================
# CLI PARSER
# =====================================================================
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sandbox_manager.py",
        description="Headless Reverse Docker Sandbox & WSL Linker CLI for AI Agents and Developers."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # create
    p_create = sub.add_parser("create", help="Provision an isolated reverse Docker sandbox mapped to Windows.")
    p_create.add_argument("-n", "--name", "--alias", required=True, help="Unique sandbox alias/name")
    p_create.add_argument("-i", "--image", default="alpine:latest", help="Docker base image (default: alpine:latest)")
    p_create.add_argument("-p", "--parent", default=None, help="Windows parent folder to project symlink (default: current working directory)")
    p_create.add_argument("-d", "--distro", default=None, help="WSL 2 distribution for SSHFS bridge (default: autodetected Ubuntu)")
    p_create.add_argument("-e", "--env", action="append", help="Environment variables (KEY=VALUE), can repeat")
    p_create.add_argument("--cpus", default=None, help="Limit CPU cores available to container (e.g. 1.5, 2.0)")
    p_create.add_argument("-m", "--memory", default=None, help="Limit container RAM ceiling (e.g. 512m, 2g, 4g)")
    p_create.add_argument("--pids-limit", type=int, default=None, help="Limit maximum container process IDs to prevent fork bombs")
    p_create.add_argument("-v", "--volume", action="append", help="Mount Docker volume (e.g. my_vol:/workspace or named_vol:/data), can repeat")
    p_create.add_argument("--storage-opt", action="append", help="Storage driver options (e.g. size=10G), can repeat")
    p_create.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_create.set_defaults(func=cmd_create)

    # exec
    p_exec = sub.add_parser("exec", help="Execute a command inside the isolated container workspace.")
    p_exec.add_argument("name", help="Sandbox alias")
    p_exec.add_argument("-u", "--user", default=None, help="User inside container (default: root)")
    p_exec.add_argument("-w", "--workdir", default="/workspace", help="Working directory inside container (default: /workspace)")
    p_exec.add_argument("cmd", nargs=argparse.REMAINDER, help="Command and arguments to execute")
    p_exec.set_defaults(func=cmd_exec)

    # list
    p_list = sub.add_parser("list", help="List all registered sandboxes and WSL links.")
    p_list.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_list.set_defaults(func=cmd_list)

    # status
    p_status = sub.add_parser("status", help="Inspect health of container, SSHFS mount, and Windows symlink.")
    p_status.add_argument("name", help="Sandbox alias")
    p_status.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_status.set_defaults(func=cmd_status)

    # heal
    p_heal = sub.add_parser("heal", help="Auto-reconnect stale SSHFS mounts and restart stopped containers.")
    p_heal.add_argument("name", nargs="?", default=None, help="Optional sandbox alias to heal (default: all)")
    p_heal.set_defaults(func=cmd_heal)

    # teardown
    p_tear = sub.add_parser("teardown", help="Cleanly unmount, remove Windows symlink, and destroy container.")
    p_tear.add_argument("name", help="Sandbox alias")
    p_tear.add_argument("--keep-container", action="store_true", help="Keep the Docker container alive, only remove bridge & symlink")
    p_tear.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    p_tear.set_defaults(func=cmd_teardown)

    # wsl-link
    p_wlink = sub.add_parser("wsl-link", help="Create a direct Windows symlink to a WSL 2 directory.")
    p_wlink.add_argument("-n", "--name", required=True, help="Workspace alias")
    p_wlink.add_argument("-t", "--target", required=True, help="Target path inside WSL (e.g. /home/user/code/my-app)")
    p_wlink.add_argument("-p", "--parent", default=None, help="Windows parent directory")
    p_wlink.add_argument("-d", "--distro", default=None, help="WSL distribution")
    p_wlink.set_defaults(func=cmd_wsl_link)

    # wsl-unlink
    p_wunlink = sub.add_parser("wsl-unlink", help="Safely unlink a WSL 2 directory symlink.")
    p_wunlink.add_argument("name", help="Workspace alias")
    p_wunlink.set_defaults(func=cmd_wsl_unlink)

    return parser

def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    # Handle cmd remainder if leading '--' was parsed
    if hasattr(args, "cmd") and args.cmd and args.cmd[0] == "--":
        args.cmd = args.cmd[1:]

    return args.func(args)

if __name__ == "__main__":
    sys.exit(main())
