#!/usr/bin/env python3
"""
WSL Linker - Experimental Suite (Docker-Native Sidecar & Workspace Bridge)

This experimental module operates 100% via Docker to bypass the host Windows OS layer
completely. It eliminates any need for administrator permissions, Developer Mode,
local symlinking, or host SSHFS-Win installations.

All mounts, SFTP tunnels, and volume syncs happen inside a Docker Sidecar Bridge.
"""

import os
import sys
import json
import subprocess
from pathlib import Path
import uuid
import datetime

# Registry config location
def get_experimental_dir():
    path = Path.home() / ".wsl-linker-experimental"
    path.mkdir(parents=True, exist_ok=True)
    return path

def get_config_path():
    return get_experimental_dir() / "config.json"

def load_config():
    path = get_config_path()
    if not path.exists():
        return {"credentials": {}, "environments": [], "dev_containers": [], "bridge_active": False}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"credentials": {}, "environments": [], "dev_containers": [], "bridge_active": False}

def save_config(config):
    path = get_config_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"[ERROR] Failed to save config: {e}")

# =====================================================================
# DOCKER SIDECAR BRIDGE ORCHESTRATION
# =====================================================================
def build_and_start_bridge(host_projects_dir):
    """
    Builds the Docker Sidecar Bridge and launches it.
    Binds the host projects directory directly so all mounts inside Docker
    reflect back to the host automatically.
    """
    print(f"\n[DOCKER-BRIDGE] Bootstrapping Sidecar Bridge Container...")
    
    # 1. Create a lightweight Dockerfile for the bridge dynamically
    dockerfile_content = """FROM alpine:latest
RUN apk add --no-cache openssh-client sshfs rsync bash curl shadow
# Configure SSHFS permissions
RUN mkdir -p /projects /root/.ssh && \
    echo "user_allow_other" >> /etc/fuse.conf
WORKDIR /bridge
COPY . .
CMD ["tail", "-f", "/dev/null"]
"""
    bridge_dir = get_experimental_dir() / "bridge_build"
    bridge_dir.mkdir(parents=True, exist_ok=True)
    
    with open(bridge_dir / "Dockerfile", "w") as f:
        f.write(dockerfile_content)

    # 2. Build the Bridge Image
    print(" -> Building 'devlinker-bridge' Docker image...")
    try:
        subprocess.run(["docker", "build", "-t", "devlinker-bridge", str(bridge_dir)], check=True, capture_output=True)
    except Exception as e:
        print(f"[ERROR] Docker build failed. Ensure Docker is running: {e}")
        return

    # 3. Spin up the Bridge Sidecar
    # Binds docker.sock so the bridge can orchestrate other containers
    # Binds host_projects_dir so files are reflected on Windows
    host_projects_dir = os.path.abspath(host_projects_dir)
    print(f" -> Launching sidecar container 'devlinker-bridge'...")
    print(f"    Mounting host workspace: '{host_projects_dir}' ---> '/projects'")
    
    try:
        # Kill previous bridge instance if running
        subprocess.run(["docker", "rm", "-f", "devlinker-bridge"], capture_output=True)
        
        bridge_cmd = [
            "docker", "run", "-d",
            "--name", "devlinker-bridge",
            "--privileged",  # Required for fuse/sshfs mounting inside the container
            "-v", "/var/run/docker.sock:/var/run/docker.sock",
            "-v", f"{host_projects_dir}:/projects:shared",
            "devlinker-bridge"
        ]
        subprocess.run(bridge_cmd, check=True, capture_output=True)
        print(f"[SUCCESS] Docker Sidecar Bridge is active and running!")
    except Exception as e:
        print(f"[ERROR] Failed to start Docker Bridge container: {e}")
        return

    config = load_config()
    config["bridge_active"] = True
    config["host_projects_dir"] = host_projects_dir
    save_config(config)

# =====================================================================
# DOCKER-NATIVE DEV CONTAINER LINKER (VIA SIDECAR)
# =====================================================================
def create_docker_native_dev(name, image):
    """
    Spins up an isolated Dev Container and mirrors it to the host projects
    folder via a Docker-to-Docker bind mount, involving zero host OS commands.
    """
    config = load_config()
    if not config.get("bridge_active"):
        print("[ERROR] Docker Bridge is not active. Run 'bridge-start' first!")
        return

    print(f"\n[DOCKER-NATIVE] Provisioning isolated dev container '{name}'...")
    container_name = f"devlink_container_{name}"
    
    # 1. Create a workspace folder inside our mapped host projects directory
    host_path = os.path.join(config["host_projects_dir"], name)
    os.makedirs(host_path, exist_ok=True)
    print(f" -> Created host directory: '{host_path}'")

    # 2. Spin up the container with the workspace folder bind-mounted directly by Docker
    print(f" -> Spinning up isolated dev container '{container_name}' using image '{image}'...")
    try:
        # Resolve path inside the Docker Bridge
        container_mount_cmd = [
            "docker", "run", "-d",
            "--name", container_name,
            "-v", f"{host_path}:/workspace",
            "-w", "/workspace",
            image,
            "tail", "-f", "/dev/null"
        ]
        subprocess.run(container_mount_cmd, check=True, capture_output=True)
        print(f"\n[SUCCESS] Dev Container is online and mapped cleanly!")
        print(f" -> Windows workspace location: '{host_path}'")
        print(f" -> Isolated Container target   : '{container_name}:/workspace'")
        print(f" -> Open in Cursor, Antigravity 2, or Claude to edit natively with ZERO host OS dependencies!")
    except Exception as e:
        print(f"[ERROR] Failed to spin up native Dev Container: {e}")

# =====================================================================
# SSH TUNNELING & MOUNTING INSIDE THE DOCKER SIDECAR
# =====================================================================
def connect_remote_ssh_in_docker(profile_name, remote_path):
    """
    Mounts a remote SSH/EC2 server path entirely INSIDE the Docker Sidecar.
    Docker Desktop's volume bridge instantly propagates the mounted files
    to the host Windows folder with zero host SSHFS utilities required!
    """
    config = load_config()
    if not config.get("bridge_active"):
        print("[ERROR] Docker Bridge is not active. Run 'bridge-start' first!")
        return

    profile = config["credentials"].get(profile_name)
    if not profile:
        print(f"[ERROR] Credential profile '{profile_name}' does not exist.")
        return

    user = profile["user"]
    host = profile["host"]
    secret = profile["secret"]
    auth_type = profile["auth_type"]

    print(f"\n[DOCKER-SSHFS] Tunneling filesystem connection inside Docker Sidecar...")
    
    # Create the mount folder inside the mapped projects directory
    mount_dir_name = f"remote_{profile_name}"
    local_host_path = os.path.join(config["host_projects_dir"], mount_dir_name)
    os.makedirs(local_host_path, exist_ok=True)
    
    # Setup keys inside the Docker Bridge container
    if auth_type == "key":
        print(" -> Injecting SSH Private Key into the Bridge...")
        key_filename = Path(secret).name
        # Copy key to bridge container
        subprocess.run(["docker", "cp", secret, f"devlinker-bridge:/root/.ssh/{key_filename}"], check=True)
        # Fix key permissions inside the container
        subprocess.run(["docker", "exec", "devlinker-bridge", "chmod", "600", f"/root/.ssh/{key_filename}"], check=True)
        sshfs_opt = f"-o IdentityFile=/root/.ssh/{key_filename}"
    else:
        sshfs_opt = ""

    # Execute SSHFS mount inside the Docker container
    print(f" -> Mounting {user}@{host}:{remote_path} to '/projects/{mount_dir_name}' in Docker...")
    mount_cmd = f"sshfs {user}@{host}:{remote_path} /projects/{mount_dir_name} -o allow_other,default_permissions,cache=yes {sshfs_opt}"
    
    try:
        result = subprocess.run(["docker", "exec", "devlinker-bridge", "bash", "-c", mount_cmd], capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(result.stderr)
        
        print(f"\n[SUCCESS] Secure SFTP bridge established perfectly!")
        print(f" -> Windows Workspace Folder  : '{local_host_path}'")
        print(f" -> Remote Target Node Location: '{user}@{host}:{remote_path}'")
        print(f" -> Tunneled inside container with ZERO host OS modifications!")
    except Exception as e:
        print(f"[ERROR] SSHFS mount inside Docker failed: {e}")

# =====================================================================
# INSTANT CLOUD VM PROVISIONER INTEGRATION
# =====================================================================
def provision_docker_cloud(partner_token):
    """Mocks instant Cloud VM provisioning and auto-bridges it via Docker-SSHFS."""
    # 1. Simulate billing and instant spin up
    print(f"\n[CLOUD] Initiating instant Cloud Node Provisioning over Partner API...")
    mock_ip = f"159.203.{os.getpid() % 255}.88"
    print(f" -> Instance booted up instantly in US-East region! IP: {mock_ip}")
    
    # 2. Automatically register connection credential in the database
    config = load_config()
    profile_name = f"partner-vm-{uuid.uuid4().hex[:4]}"
    config["credentials"][profile_name] = {
        "user": "ubuntu",
        "host": mock_ip,
        "auth_type": "key",
        "secret": str(Path.home() / ".ssh" / "id_rsa"), # Using default system key for demo
        "registered_at": datetime.datetime.now().isoformat()
    }
    save_config(config)
    
    # 3. Instruct developer on how to bridge it instantly inside Docker
    print(f"\n[SUCCESS] VM Node online. To bridge it inside Docker instantly, run:")
    print(f"  python experimental_linker.py docker-connect {profile_name} /home/ubuntu/app")

# =====================================================================
# CLI COMMAND ROUTING
# =====================================================================
def show_help():
    print("""
===========================================================================
        DEVLINKER - EXPERIMENTAL ZERO-OS-POLLUTION DOCKER SUITE
===========================================================================
Docker Sidecar Bridge Setup (Run first to isolate the host OS):
  python experimental_linker.py bridge-start <host-projects-parent-dir>

Docker-Native Dev Containers (Zero Host OS dependency):
  python experimental_linker.py docker-create <alias> <docker-image>

Remote SSH Tunnels Bridged inside Docker (Bypasses SSHFS-Win):
  python experimental_linker.py register-cred <profile-name> <user> <host> <key|password> <secret-value-or-key-path>
  python experimental_linker.py docker-connect <profile-name> <remote-path>

Instant One-Click Partner Cloud VMs:
  python experimental_linker.py docker-cloud [partner-token]
===========================================================================
""")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        show_help()
        sys.exit(0)

    cmd = sys.argv[1].lower()

    if cmd == "bridge-start" and len(sys.argv) >= 3:
        build_and_start_bridge(sys.argv[2])
    elif cmd == "docker-create" and len(sys.argv) >= 4:
        create_docker_native_dev(sys.argv[2], sys.argv[3])
    elif cmd == "register-cred" and len(sys.argv) >= 7:
        register_credential = register_credential if 'register_credential' in globals() else None
        if not register_credential:
            # Inline fallback to ensure execution works cleanly
            def register_credential(profile_name, user, host, auth_type, secret_path_or_val):
                config = load_config()
                config["credentials"][profile_name] = {
                    "user": user,
                    "host": host,
                    "auth_type": auth_type,
                    "secret": secret_path_or_val,
                    "registered_at": datetime.datetime.now().isoformat()
                }
                save_config(config)
                print(f"[REGISTRY] Stored Connection Profile '{profile_name}' ({user}@{host}).")
        register_credential(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6])
    elif cmd == "docker-connect" and len(sys.argv) >= 4:
        connect_remote_ssh_in_docker(sys.argv[2], sys.argv[3])
    elif cmd == "docker-cloud":
        provision_docker_cloud("demo-dev-token")
    else:
        show_help()
