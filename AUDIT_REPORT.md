# Comprehensive Multi-Angle Audit Report: `sandbox-linker` (AnyLink)

**Project:** `sandbox-linker` (AnyLink)  
**Date:** 2026-10-23  
**Auditor:** Teamwork Project Audit Team  
**Scope:** `scripts/sandbox_manager.py`, `experimental_linker.py`, `experimental_linker_gui.py`, `wsl_linker.py`, `wsl_linker_gui.py`, documentation, and licensing artifacts.

---

## Executive Summary

`sandbox-linker` provides an architecture designed to solve the chronic Windows-WSL-Docker cross-filesystem I/O performance bottleneck. By combining reverse SSHFS tunneling with native Windows NTFS directory junctions pointing to WSL 9P network paths (`\\wsl.localhost\<distro>`), the system eliminates 9P protocol translation overhead across NTFS mounts and unlocks near-native ext4 disk throughput (demonstrating up to 182x speedups in git and build operations).

However, an exhaustive multi-angle audit across **Security, Compliance & Licensing, Performance, and Engineering Quality** has uncovered critical vulnerabilities and reliability gaps:
1. **Critical Security Weaknesses:** Arbitrary bash command injection in container mount scripts, container escape attack vectors via unconstrained privileged bridge containers, global network exposure of container root SSH servers (`0.0.0.0`), and Windows command injection in desktop GUI launchers.
2. **Data Integrity Hazards:** Fragile registry loading that catches generic exceptions and silently returns empty dictionaries, risking instantaneous loss of all workspace mappings upon subsequent saves.
3. **Performance Inefficiencies:** Missing SSHFS cache and buffer tuning flags that incur unnecessary round-trip latency on file metadata operations, and heavy polling loops.
4. **Resilience & Safe Teardown Deficiencies:** Absence of SIGINT/termination handlers leading to orphaned containers and blocked ports, and teardown logic capable of removing regular empty host directories.

---

## 1. Pillar 1: Security Audit

### 1.1 Command Injection Attack Surfaces in Shell Interpolations
- **Citations:**
  - `scripts/sandbox_manager.py:194-205, 216, 228`
  - `experimental_linker.py:198-201`
  - `experimental_linker_gui.py:815-816`
  - `wsl_linker.py:262`
- **Analysis:**
  In `scripts/sandbox_manager.py:194-205`, `sshfs_mount_script()` constructs a multi-command bash script using raw Python f-strings:
  ```python
  def sshfs_mount_script(port: int, mount_path: str) -> str:
      key = f"$HOME/.ssh/{SSH_KEY_NAME}"
      opts = (...)
      return (
          f'M="{mount_path}"; mkdir -p "$M"; '
          f'(fusermount3 -uz "$M" || fusermount -uz "$M") >/dev/null 2>&1; '
          f'sshfs -o {opts} root@127.0.0.1:/ "$M"'
      )
  ```
  `mount_path` is derived directly from user-supplied `alias` (`wsl_mount_path = f"{wsl_home}/.devlinker-mounts/{alias}"`). It is passed to `wsl_run()` which invokes `wsl.exe -d <distro> -e bash -c "<script>"`. An alias containing shell metacharacters (e.g. `test"; touch /tmp/pwned; #`) breaks out of the double quotes and executes arbitrary commands inside the WSL Linux guest.
  Similarly, in `experimental_linker.py:198-201` and `experimental_linker_gui.py:815-816`:
  ```python
  mount_cmd = f"sshfs {user}@{host}:{remote_path} /projects/{mount_dir_name} -o allow_other,default_permissions,cache=yes {sshfs_opt}"
  result = subprocess.run(["docker", "exec", "devlinker-bridge", "bash", "-c", mount_cmd], capture_output=True, text=True)
  ```
  Any parameter containing `;`, `&&`, or `$()` executes arbitrary commands within the `devlinker-bridge` container.
- **Risk Severity:** P0 Critical (Remote Code Execution / Guest Compromise).

### 1.2 Container Escape and Host Compromise via `--privileged` and Docker Socket
- **Citations:**
  - `experimental_linker.py:96-97`
  - `experimental_linker_gui.py:438-439`
- **Analysis:**
  `devlinker-bridge` is created with:
  ```python
  bridge_cmd = [
      "docker", "run", "-d",
      "--name", "devlinker-bridge",
      "--privileged",
      "-v", "/var/run/docker.sock:/var/run/docker.sock",
      "-v", f"{host_projects_dir}:/projects:shared",
      "devlinker-bridge"
  ]
  ```
  Mounting the host Docker socket (`/var/run/docker.sock`) into a `--privileged` container grants any code inside the container full, unrestricted control of the host Docker daemon. An attacker who compromises the container (or exploits the command injection in `mount_cmd`) can issue API calls to spawn sibling containers that mount the root host filesystem (`-v /:/host`), resulting in instant and total host compromise.
- **Risk Severity:** P0 Critical.

### 1.3 Unrestricted Network Exposure (0.0.0.0 Bindings)
- **Citations:**
  - `scripts/sandbox_manager.py:284`
  - `experimental_linker_gui.py:707`
  - `scripts/sandbox_manager.py:160`
  - `experimental_linker_gui.py:470`
- **Analysis:**
  When provisioning containers, Docker is invoked with `-p {port}:22`. In Docker's networking architecture, publishing a port without an explicit interface IP defaults to `0.0.0.0:{port}:22` (and `[::]:{port}:22`). This exposes the container's OpenSSH server across all network interfaces, including local Wi-Fi, Ethernet, and any public IP addresses assigned to the host.
  Furthermore, socket availability checks in `find_free_port()` bind to `("0.0.0.0", port)` rather than `("127.0.0.1", port)`.
- **Risk Severity:** P1 High (Network Service Exposure).

### 1.4 Windows Host Command Injection via GUI `shell=True`
- **Citations:**
  - `experimental_linker_gui.py:958, 973`
  - `wsl_linker_gui.py:554, 567`
- **Analysis:**
  When launching terminal windows or shells, the GUI modules invoke:
  ```python
  subprocess.Popen(f'start wsl.exe -d {distro} --cd "{wsl_path}"', shell=True)
  subprocess.Popen(f'start cmd.exe /k docker exec -it {container_name} sh', shell=True)
  ```
  In Windows `cmd.exe`, `&`, `|`, and `^` act as command chaining delimiters. If `wsl_path` or `container_name` contains quotes and command separators, `cmd.exe` executes arbitrary host Windows commands with the privileges of the active user.
- **Risk Severity:** P1 High.

### 1.5 FUSE `allow_other` Permission Boundaries
- **Citations:**
  - `scripts/sandbox_manager.py:200`
  - `experimental_linker.py:198`
  - `experimental_linker_gui.py:564, 815`
- **Analysis:**
  The SSHFS mount specifies `allow_other`, which allows non-root users and the WSL 9P server to access the FUSE mount. While required for the Windows host to read files via `\\wsl.localhost`, this requires `user_allow_other` in `/etc/fuse.conf`. In shared or multi-user WSL environments, all local users can read and write files within the mounted container.
- **Risk Severity:** P2 Medium.

### 1.6 Elevated Privilege Requirements & Sudo Behavior
- **Citations:**
  - `scripts/sandbox_manager.py:209-214`
- **Analysis:**
  `ensure_wsl_sshfs()` attempts non-interactive `sudo -n sed -i ... /etc/fuse.conf` and `sudo -n apt-get install -y sshfs`. If passwordless sudo is not configured for the default WSL user, the command fails silently without actionable diagnostic guidance for the user.
- **Risk Severity:** P3 Low.

---

## 2. Pillar 2: Compliance & Licensing Audit

### 2.1 Open-Source Licensing (MIT)
- **Citations:**
  - `LICENSE:1-22`
  - `pyproject.toml:13`
- **Analysis:**
  The project is licensed under the standard MIT License, Copyright (c) 2026 Fauzul. The license text is standard and permissive.

### 2.2 Third-Party Dependencies and Redistribution
- **Dependencies:**
  - `customtkinter` (MIT / CC0-1.0)
  - `pyinstaller` (GPL with runtime exception permitting proprietary/MIT distribution)
  - `sshfs` (GPLv2, invoked exclusively via external process execution)
- **Compliance Assessment:**
  Invoking `sshfs` and `docker` via CLI subprocesses qualifies as independent process invocation ("mere aggregation") under GPL interpretation rather than static or dynamic linking. This creates no licensing incompatibility with MIT.

### 2.3 Platform Compliance: Windows Developer Mode & WSL 2
- **Citations:**
  - `scripts/sandbox_manager.py:341-352`
  - `wsl_linker.py:137-152`
- **Analysis:**
  Creating directory symbolic links on Windows NTFS fixed drives requires either Windows Developer Mode enabled or Administrator privileges (`SeCreateSymbolicLinkPrivilege`). While `sandbox_manager.py` provides a fallback to display UNC paths, `wsl_linker.py` aborts with an error if link creation fails. Supporting corporate/enterprise environments where Group Policy disables Developer Mode requires seamless fallback to direct UNC path mapping.
- **Compliance Severity:** P3 Low.

---

## 3. Pillar 3: Performance Audit

### 3.1 SSHFS Mount Options & Throughput Tuning
- **Citations:**
  - `scripts/sandbox_manager.py:197-200`
  - `experimental_linker_gui.py:561-564`
- **Analysis:**
  The current mount configuration:
  `opts = "IdentityFile=...,port=...,StrictHostKeyChecking=no,UserKnownHostsFile=/dev/null,reconnect,ServerAliveInterval=10,ServerAliveCountMax=3,idmap=user,allow_other,BatchMode=yes"`
  Omits critical FUSE performance flags:
  1. `kernel_cache` / `auto_cache`: Without kernel caching, every `stat()`, `lstat()`, and `access()` call triggers synchronous network RPCs over the SSH connection. High-frequency IDE operations (language server indexers, git status checks) suffer excessive latency.
  2. `entry_timeout=60,attr_timeout=60`: Caches directory entries and file attributes.
  3. `big_writes`, `max_read=131072`, `max_write=131072`: Enables 128KB buffer transfers instead of default 4KB chunks, substantially increasing sequential read/write throughput.
  4. `compression=no`: Eliminates CPU compression/decompression overhead on loopback (`127.0.0.1`) connections.
- **Risk Severity:** P1 High.

### 3.2 20-Second Daemon Polling Overhead
- **Citations:**
  - `experimental_linker_gui.py:616-654`
- **Analysis:**
  `_auto_reconnect_loop` polls all active links every 20 seconds, executing multiple `docker inspect` and `wsl.exe` subprocesses sequentially. Spawning external Windows and WSL processes every 20 seconds wakes the CPU from low-power C-states, degrading laptop battery life. Furthermore, sequential timeouts (`timeout=20`, `timeout=60`) mean a single hanging mount blocks the health thread for over 80 seconds.
- **Risk Severity:** P2 Medium.

### 3.3 Disk I/O Caching & Whole-Root Mount Overhead
- **Citations:**
  - `scripts/sandbox_manager.py:203`
  - `experimental_linker_gui.py:567`
- **Analysis:**
  `sshfs -o {opts} root@127.0.0.1:/ "$M"` mounts the entire container root filesystem (`/`) rather than targeting `/workspace`. This exposes container internal pseudo-filesystems (`/proc`, `/sys`, `/dev`) to the WSL 9P server and Windows IDE file indexers, increasing memory consumption and indexing time.
- **Risk Severity:** P2 Medium.

---

## 4. Pillar 4: Engineering Quality Audit

### 4.1 Silent Exception Swallowing and Registry Destruction
- **Citations:**
  - `scripts/sandbox_manager.py:57-63, 85-86`
  - `wsl_linker.py:42-46`
- **Analysis:**
  ```python
  try:
      with open(path, "r", encoding="utf-8") as f:
          loaded = json.load(f)
          if isinstance(loaded, dict):
              data.update(loaded)
  except Exception:
      pass
  ```
  If `config.json` or `links.json` encounters a transient read lock, encoding issue, or minor syntax error, `load_registry()` silently catches the exception and returns an empty dictionary. The very next call to `save_registry()` overwrites the file on disk with the empty state, permanently obliterating all registered workspace links.
- **Risk Severity:** P0 Critical (Data Destruction).

### 4.2 Silent Zero Exit Codes on Fatal Errors
- **Citations:**
  - `wsl_linker.py:88-90, 96, 99, 125, 131, 148, 151, 183, 192, 203, 246, 256`
- **Analysis:**
  In `wsl_linker.py`, all error branches print an error message and return `None` (exiting with code `0`). External scripts, CI pipelines, and orchestrators cannot detect that an operation failed.
- **Risk Severity:** P1 High.

### 4.3 Process Termination & Cleanup Resilience
- **Citations:**
  - `scripts/sandbox_manager.py:278-366`
- **Analysis:**
  There are no `signal.signal` handlers or `atexit.register` hooks. If a user or automated agent cancels container creation with Ctrl+C (SIGINT) while OpenSSH is installing, the running Docker container and its bound port remain orphaned and unrecorded in `config.json`.
- **Risk Severity:** P1 High.

### 4.4 Cross-Platform Path Handling Defects
- **Citations:**
  - `scripts/sandbox_manager.py:337, 684`
  - `wsl_linker.py:111, 249-250`
- **Analysis:**
  `f"\\\\wsl.localhost\\{distro}" + target.replace('/', '\\')`: If `target` does not have a leading slash, the resulting UNC path is malformed (e.g. `\\wsl.localhost\Ubuntu-24.04home\user`).
  In `wsl_linker.py:249-250`, `current_dir[len(win_root):]` slices paths by character length, which breaks when Windows short (8.3) names or drive letter casing discrepancies exist.
- **Risk Severity:** P1 High.

### 4.5 Teardown Directory Deletion Hazard
- **Citations:**
  - `scripts/sandbox_manager.py:638, 723`
  - `experimental_linker_gui.py:989, 1002`
- **Analysis:**
  `if win_path and (os.path.islink(win_path) or os.path.isdir(win_path)): os.rmdir(win_path)`: Calling `os.rmdir` on a non-symlink empty host directory deletes that directory. Teardown should strictly verify `os.path.islink(win_path)` before attempting removal.
- **Risk Severity:** P1 High.

---

## 5. Summary of Audit Recommendations

1. **Input Sanitization & Injection Hardening:** Enforce strict alphanumeric regex validation on `alias` (`^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}$`), apply `shlex.quote` to all path interpolations, eliminate `shell=True` in Windows GUI launchers, and replace `bash -c` string commands with tokenized arrays.
2. **Network Isolation:** Enforce explicit `127.0.0.1:{port}:22` port forwarding in all `docker run` calls and bind localhost in port discovery.
3. **Container Hardening:** Remove `--privileged` and bind mounts of `/var/run/docker.sock` from sidecar containers; use scoped `--cap-add=SYS_ADMIN --device /dev/fuse`.
4. **Atomic Registry Safety:** Implement atomic writes (`tempfile` + `os.replace`), preserve `.corrupt.bak` copies on read errors, and fail fast instead of returning empty dictionaries.
5. **Safe Teardown:** Guard `os.rmdir` with strict `os.path.islink()` checks to ensure host workspaces and project folders are never deleted.
6. **Performance Flags:** Inject `kernel_cache,auto_cache,entry_timeout=60,attr_timeout=60,big_writes,max_read=131072,max_write=131072,compression=no` into all SSHFS options and mount `/workspace`.
7. **Strict CLI Status & Exit Codes:** Ensure all error paths route to `sys.stderr` and exit with non-zero status codes (`sys.exit(1)`).
