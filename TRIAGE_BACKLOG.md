# Prioritized Triage Backlog: `sandbox-linker` (AnyLink)

**Classification System:**
- **P0 Critical:** Data loss, remote/guest arbitrary code execution, container breakout / full host compromise.
- **P1 High:** Local network exposure, host command execution via GUI, silent automation failures, process leaks, path traversal, missing performance caching flags.
- **P2 Medium:** Host key verification bypass, unencrypted credentials, broad mount scope, polling inefficiency.
- **P3 Low:** Non-interactive sudo diagnostics, enterprise Developer Mode fallback UX.

---

## P0 — Critical Severity

### [P0-01] Silent JSON Read Exceptions Risk Registry Destruction
- **Component:** `scripts/sandbox_manager.py:57-63, 85-86`, `wsl_linker.py:42-46`
- **Description:** `load_registry()` catches generic `Exception` and silently returns an empty dictionary. If the registry file is temporarily unreadable or syntactically invalid, a subsequent `save_registry()` overwrites the file on disk, permanently wiping all user workspace links.
- **Reproduction Steps:**
  1. Write invalid JSON to `$HOME/.wsl-linker-experimental/config.json`: `echo { broken json > ~/.wsl-linker-experimental/config.json`.
  2. Run `python scripts/sandbox_manager.py list`.
  3. Inspect file: file is read as `{}`. Next update writes `{}` back to disk, losing all previous entries.
- **Impact:** Total loss of user workspace configuration and mount metadata.
- **Remediation:**
  - Create an automatic backup (`.corrupt.bak`) on decode failure.
  - Fail fast by raising a descriptive `RuntimeError` rather than silently continuing with an empty registry.
  - Implement atomic writes via `tempfile.NamedTemporaryFile` and `os.replace`.

### [P0-02] Arbitrary Command Injection in `mount_cmd` via `bash -c`
- **Component:** `experimental_linker.py:198-201`, `experimental_linker_gui.py:815-816`
- **Description:** `mount_cmd` formats user parameters (`remote_path`, `user`, `host`, `mount_dir_name`) into an unquoted bash string executed via `docker exec devlinker-bridge bash -c <mount_cmd>`.
- **Reproduction Steps:**
  1. Supply `remote_path` containing `"; touch /tmp/pwned; #"` or `$(id)`.
  2. Execute mount command.
  3. Observe arbitrary command execution inside the container.
- **Impact:** Complete compromise of the bridge sidecar container.
- **Remediation:** Sanitize arguments, apply `shlex.quote`, or invoke `sshfs` directly with arguments array without shell interpolation.

### [P0-03] Container Escape and Host Compromise via `--privileged` and Docker Socket
- **Component:** `experimental_linker.py:96-97`, `experimental_linker_gui.py:438-439`
- **Description:** `devlinker-bridge` container is launched with `--privileged` and bind-mounts `/var/run/docker.sock:/var/run/docker.sock`.
- **Reproduction Steps:**
  1. Inspect `devlinker-bridge` run arguments.
  2. Execute `docker exec devlinker-bridge docker run -v /:/host-root alpine chroot /host-root cat /etc/shadow`.
- **Impact:** Full host compromise from within the bridge container.
- **Remediation:** Remove `-v /var/run/docker.sock:/var/run/docker.sock` and `--privileged`. Replace with minimal FUSE capabilities: `--cap-add=SYS_ADMIN --device /dev/fuse`.

---

## P1 — High Severity

### [P1-01] Container OpenSSH Server Exposed to `0.0.0.0`
- **Component:** `scripts/sandbox_manager.py:284`, `experimental_linker_gui.py:707`
- **Description:** Container creation uses `-p {port}:22` without specifying `127.0.0.1`, causing Docker to bind the container's SSH port to all external network interfaces on the host.
- **Reproduction Steps:**
  1. Create sandbox: `python scripts/sandbox_manager.py create --name audit_test_01 --image ubuntu:latest`.
  2. Run `docker inspect -f '{{json .NetworkSettings.Ports}}' devlink_container_audit_test_01`.
  3. Observe `HostIp: "0.0.0.0"`.
- **Impact:** Container SSH daemon is accessible to any device on the local network or internet.
- **Remediation:** Change port argument to `"-p", f"127.0.0.1:{port}:22"`.

### [P1-02] Bash Command Injection via `alias` and `wsl_mount_path` in `wsl_run`
- **Component:** `scripts/sandbox_manager.py:201-204, 216, 228`, `wsl_linker.py:262`
- **Description:** `alias` and `wsl_mount_path` are interpolated directly into shell script strings executed by `wsl.exe -e bash -c`.
- **Reproduction Steps:**
  1. Call `cmd_create` with alias `"demo;id>/tmp/id;#"`.
  2. Observe shell execution inside WSL guest.
- **Impact:** Arbitrary command execution inside WSL 2 guest filesystem.
- **Remediation:** Validate `alias` with strict regex `^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$`. Apply `shlex.quote` to all path variables.

### [P1-03] Windows Host Command Injection via GUI `shell=True`
- **Component:** `experimental_linker_gui.py:958, 973`, `wsl_linker_gui.py:554, 567`
- **Description:** Desktop GUI launchers invoke `subprocess.Popen(f'start wsl.exe ...', shell=True)` and `subprocess.run(fallback_cmd, shell=True)`.
- **Reproduction Steps:**
  1. Trigger terminal launcher with a path containing `& calc.exe &`.
  2. Windows `cmd.exe` executes `calc.exe`.
- **Impact:** Arbitrary command execution on Windows host.
- **Remediation:** Remove `shell=True`. Execute commands as tokenized argument lists (`["cmd.exe", "/c", "start", "wsl.exe", ...]`).

### [P1-04] Teardown Deletion Hazard on Non-Symlink Directories
- **Component:** `scripts/sandbox_manager.py:638, 723`, `experimental_linker_gui.py:989, 1002`
- **Description:** Teardown logic checks `if win_path and (os.path.islink(win_path) or os.path.isdir(win_path)): os.rmdir(win_path)`. If `win_path` is an empty normal directory, `os.rmdir` deletes it.
- **Reproduction Steps:**
  1. Register a directory that is not a symlink.
  2. Teardown or unlink: the host directory is deleted.
- **Impact:** Unintended host directory deletion.
- **Remediation:** Remove `or os.path.isdir(win_path)`. Strictly require `os.path.islink(win_path)` before calling `os.rmdir()`.

### [P1-05] Missing SSHFS Caching & Buffer Optimization Flags
- **Component:** `scripts/sandbox_manager.py:197-200`, `experimental_linker_gui.py:561-564`
- **Description:** SSHFS mount options omit caching and buffer tuning, causing severe metadata latency and suboptimal throughput.
- **Reproduction Steps:** Benchmark repeated `stat()` or `git status` calls on an SSHFS mount without `kernel_cache`.
- **Impact:** Degraded I/O throughput and high latency in IDE file watchers.
- **Remediation:** Add `kernel_cache,auto_cache,entry_timeout=60,attr_timeout=60,big_writes,max_read=131072,max_write=131072,compression=no` to SSHFS options.

### [P1-06] Silent Zero Exit Codes on Fatal Errors in `wsl_linker.py`
- **Component:** `wsl_linker.py:88-90, 96, 99, 125, 131, 148, 151, 183, 192, 203, 246, 256`
- **Description:** Fatal errors print to stdout and return `None` (exit code `0`).
- **Reproduction Steps:**
  1. Run `python wsl_linker.py add`.
  2. Check `$LASTEXITCODE`: returns `0`.
- **Impact:** Automated scripts and pipelines cannot detect failures.
- **Remediation:** Route error messages to `sys.stderr.write` and terminate with `sys.exit(1)`.

### [P1-07] Dangling Containers and Port Leaks on Process Interruption
- **Component:** `scripts/sandbox_manager.py:278-366`
- **Description:** Lack of `signal.SIGINT` and `atexit` handlers leaves Docker containers and bound ports orphaned if provisioning is interrupted before registry update.
- **Reproduction Steps:** Hit Ctrl+C during OpenSSH installation; container continues running untracked.
- **Impact:** Port collisions and resource exhaustion.
- **Remediation:** Implement in-memory provisioning rollback hook registered with `atexit` and `signal.signal`.

### [P1-08] Malformed UNC Paths and Fragile String Slicing
- **Component:** `scripts/sandbox_manager.py:337, 684`, `wsl_linker.py:111, 249-250`
- **Description:** String concatenation `f"\\\\wsl.localhost\\{distro}" + target.replace('/', '\\')` produces invalid UNC paths when `target` lacks a leading slash. In `wsl_linker.py:249-250`, `current_dir[len(win_root):]` fails on short 8.3 paths.
- **Reproduction Steps:** Supply `home/user/workspace` without leading slash. Result: `\\wsl.localhost\Ubuntu-24.04home\user\workspace`.
- **Impact:** Symlink creation fails or points to non-existent path.
- **Remediation:** Normalize target path with leading slash: `target = "/" + target.lstrip("/\\")`. Use `os.path.relpath(current_dir, win_root)`.

---

## P2 — Medium Severity

### [P2-01] Global Disabling of Host Key Verification
- **Component:** `scripts/sandbox_manager.py:197`, `experimental_linker_gui.py:561`
- **Description:** SSH options include `StrictHostKeyChecking=no,UserKnownHostsFile=/dev/null`.
- **Impact:** Disables host key validation completely. While acceptable for ephemeral localhost containers, should be isolated to private ephemeral known_hosts files.

### [P2-02] Plaintext Credential Storage in Experimental Config
- **Component:** `experimental_linker.py:229`, `experimental_linker_gui.py:1146, 1224`
- **Description:** Passwords, tokens, and SSH key paths are stored in plaintext JSON.
- **Impact:** Information disclosure if config files are shared or committed.

### [P2-03] Full Container Root Filesystem Mounted via SSHFS
- **Component:** `scripts/sandbox_manager.py:203`, `experimental_linker_gui.py:567`
- **Description:** Mounts container root `root@127.0.0.1:/` instead of targeting `/workspace`.
- **Impact:** Unnecessary exposure of `/proc`, `/sys`, `/dev` to IDE indexers.

### [P2-04] GUI 20-Second Polling Loop CPU/Battery Drain
- **Component:** `experimental_linker_gui.py:616-654`
- **Description:** Tight loop executes external `docker` and `wsl` commands every 20s.
- **Impact:** Prevents CPU low-power sleep states on laptops and blocks up to 80s on hanging mounts.

---

## P3 — Low Severity

### [P3-01] Non-Interactive Sudo Failure Diagnostics
- **Component:** `scripts/sandbox_manager.py:209-214`
- **Description:** Silent failure of `sudo -n` when configuring `/etc/fuse.conf`.
- **Impact:** Poor user experience if passwordless sudo is disabled.

### [P3-02] Enterprise Developer Mode Fallback
- **Component:** `wsl_linker.py:143-152`
- **Description:** Fails hard when Windows Developer Mode is disabled.
- **Impact:** Cannot be used directly on locked-down enterprise machines without Administrator rights.
