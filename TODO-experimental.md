# TODO: WSL Linker Experimental Dev Suite (Reverse Docker Link)

This todo list outlines the next steps to implement the self-healing reverse Docker linking features in `experimental_linker_gui.py`.

## 📋 Task List

- [x] **Phase 1: Dynamic Port Allocation & WSL Detection**
    - [x] Implement `_find_free_port(self, db)` in `experimental_linker_gui.py` to scan host ports dynamically starting from `2222` and avoid collisions.
    - [x] Implement `_detect_wsl_distro(self)` to resolve which WSL distribution is selected or active.
    - [x] Implement `_get_wsl_home(self, wsl_distro)` using a `wsl -d <distro> --cd ~ -e` command to locate the Linux home folder path.

- [x] **Phase 2: Container SSH Provisioning & WSL key injection**
    - [x] Implement `_setup_container_ssh(self, container_name, wsl_distro)` to detect Alpine vs Debian, install `openssh-server`, generate host keys, and configure PermitRootLogin.
    - [x] Generate `devlinker_ed25519` inside WSL if not already present, read the public key, and append it to the container's `/root/.ssh/authorized_keys`.
    - [x] Start the SSH daemon manually inside the container with unlocked root access.

- [x] **Phase 3: FUSE SSHFS Mount Configuration**
    - [x] Implement `_setup_wsl_sshfs_mount(self, wsl_distro, alias, port, wsl_mount_path)`.
    - [x] Ensure FUSE `user_allow_other` option is configured in WSL `/etc/fuse.conf`.
    - [x] Establish robust `sshfs` mount with automatic reconnection options, `idmap=user`, and `allow_other`.
    - [x] Verify mount status by attempting to list `/workspace` within WSL.

- [x] **Phase 4: Self-Healing & Persistence Daemon**
    - [x] Implement `_start_auto_reconnect(self)` and `_auto_reconnect_loop(self)` running as a background thread.
    - [x] Periodically (every 20 seconds) poll the active reverse docker mappings:
        - If container stopped ➔ Run `docker start`.
        - If `sshd` inside container is dead ➔ Relaunch `sshd`.
        - If FUSE mount is stale/unmounted ➔ Perform safe unmount and remount.

- [x] **Phase 5: Graceful Environment Teardown**
    - [x] Update `delete_mapping(self, env_type, name)` in `experimental_linker_gui.py`:
        - Safely unmount the SSHFS volume from WSL (`fusermount3 -uz`).
        - Remove the Windows symbolic link path using `os.unlink` or `os.rmdir`.
        - Force-remove the Docker container (`docker rm -f`).

- [x] **Phase 6: Verification & End-to-End Testing**
    - [x] Spin up a reverse sandbox, verify directories appear on Windows.
    - [x] Verify bidirectional editing is lag-free and correct.
    - [x] Simulate Windows reboot (restart container) and verify self-healing remounts.

---

## 🔬 Technical Deep Dive: How the Reverse Docker Sandbox Pipeline Works

### 1. Architectural Philosophy
Traditional dev containers mount a folder from the host into the container (`-v D:\project:/workspace`). On Windows, this incurs severe virtualization overhead crossing the 9P/Hyper-V bridge, leads to file-lock conflicts, and leaves gigabytes of container build caches polluting the host.

**The Reverse Link reverses the data flow:**
The files reside **exclusively inside the container's isolated Linux filesystem**. They are projected outwards to WSL via SSHFS, and then projected to the Windows host through an in-kernel NTFS Directory Symlink / UNC reparse point.

### 2. Step-by-Step Data Flow

```
[Docker Container :22]
        ▲
        │  SSHFS Tunnel (SSH key authentication, port 2222+)
        ▼
[WSL 2 Linux: ~/.devlinker-mounts/<alias>]
        ▲
        │  WSL Plan9 (P9) Driver (\\wsl.localhost\<distro>\...)
        ▼
[Windows Host: D:\code\<alias> (NTFS Directory Symlink)]
        ▲
        │  Local File I/O
        ▼
[IDEs & AI Agents (Antigravity, Cursor, Claude Code, VS Code)]
```

#### Step 1: Port Allocation & Distro Resolution
* Scans host ports dynamically between `2222` and `2321` using a probe socket to avoid port conflicts with other containers or host services.
* Identifies the primary user WSL distribution (filtering out Docker Desktop's internal distros).
* Resolves the user's home folder path inside WSL via `wsl -d <distro> --cd ~ -e bash -c 'printf %s "$HOME"'`.

#### Step 2: Container Provisioning & In-Container SSH Setup
* Launches the Docker container with published SSH port `-p <port>:22`, working directory `-w /workspace`, and keep-alive process (`exec tail -f /dev/null`). **No host directory is bind-mounted.**
* The setup script auto-detects the container distribution package manager:
  * Alpine Linux: `apk add --no-cache openssh`
  * Debian / Ubuntu: `DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server`
* Generates an ED25519 keypair inside WSL (`~/.ssh/devlinker_ed25519`) if not already present.
* Injects the public key into the container's `/root/.ssh/authorized_keys`, unlocks root login (`sed -i 's/^root:![^:]*:/root:*:/' /etc/shadow`), enables `PermitRootLogin prohibit-password`, enables the `sftp` subsystem, and starts `/usr/sbin/sshd`.
* Grants full read/write permissions on `/workspace` (`chmod 777 /workspace`).

#### Step 3: FUSE SSHFS Mount in WSL
* Mounts the container filesystem into WSL at `~/.devlinker-mounts/<alias>` using:
  ```bash
  sshfs -o IdentityFile=~/.ssh/devlinker_ed25519,port=<port>,StrictHostKeyChecking=no,UserKnownHostsFile=/dev/null,reconnect,ServerAliveInterval=10,ServerAliveCountMax=3,idmap=user,allow_other,BatchMode=yes root@127.0.0.1:/ "$MOUNT_PATH"
  ```
* **Critical Flags:**
  * `idmap=user`: Maps the connecting WSL user (`uid=1000`) to `root` inside the container, preventing Linux permission mismatches.
  * `allow_other`: Enables the WSL 9P / Windows Plan9 server to access the mount point without `Permission Denied` errors.
  * `reconnect`: Instructs FUSE to re-establish the connection if temporarily severed.

#### Step 4: Windows Symlink & UNC Projection
* Computes the WSL UNC target: `\\wsl.localhost\<distro>\home\<user>\.devlinker-mounts\<alias>\workspace`.
* Creates an in-kernel directory symlink on Windows: `os.symlink(wsl_unc, win_path, target_is_directory=True)`.
* If Developer Mode is disabled or unprivileged, it logs a warning and provides the UNC path directly, which modern IDEs can open immediately.

#### Step 5: Background Self-Healing Daemon
* Runs as a daemon thread every 20 seconds.
* Inspects running container state. If stopped, executes `docker start`.
* Checks whether `ls "$MOUNT_PATH/workspace"` responds. If stale:
  1. Relaunches `sshd` inside the container: `docker exec <cname> /usr/sbin/sshd`.
  2. Unmounts stale FUSE handles safely: `fusermount3 -uz "$MOUNT_PATH"`.
  3. Re-executes the SSHFS mount script.
* Ensures transparent recovery after Windows sleep cycles or Docker daemon restarts.

#### Step 6: Graceful Teardown
* Safely unmounts the FUSE mount inside WSL: `fusermount3 -uz ~/.devlinker-mounts/<alias>`.
* Removes the Windows symbolic link using `os.rmdir()` (which deletes the NTFS junction pointer without traversing or deleting container files).
* Dissolves the container with `docker rm -f`.
