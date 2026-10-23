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
