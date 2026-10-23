#!/usr/bin/env python3
"""
Automated Verification Test Suite for sandbox-linker Audit Remediation.

Test Coverage:
- TC-SEC-01: Localhost port binding verification (127.0.0.1:{port}:22 and find_free_port)
- TC-SEC-02: Input sanitization on alias, rejecting shell injection payloads, spaces, quotes, traversal
- TC-SEC-03: Safe teardown verification (directory junctions unlinked, regular directories NEVER deleted)
- TC-SEC-04: UNC path construction and leading slash normalization
- TC-SEC-05: Non-zero exit code verification on wsl_linker.py fatal errors
- TC-SEC-06: Atomic registry loading, saving, and corruption backup
- TC-SEC-07: SSHFS performance flags presence (kernel_cache, auto_cache, big_writes, etc.)
- TC-R5: Complete isolation verification ensuring existing user workspaces are NEVER modified or touched

Standard Library: unittest
"""

import os
import sys
import json
import hashlib
import tempfile
import shutil
import socket
import argparse
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Paths to real user workspaces for R5 invariant checking
REAL_USER_WSL_DIR = Path.home() / ".wsl-linker"
REAL_USER_LINKS = REAL_USER_WSL_DIR / "links.json"
REAL_USER_EXP_DIR = Path.home() / ".wsl-linker-experimental"
REAL_USER_CONFIG = REAL_USER_EXP_DIR / "config.json"


def _hash_file(path: Path) -> str:
    """Calculates SHA-256 hash of a file if it exists."""
    if not path.exists():
        return "NON_EXISTENT"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class BaseIsolatedTestCase(unittest.TestCase):
    """
    Base test case ensuring 100% isolation from host user workspaces (Requirement R5).
    Redirects WSL_LINKER_CONFIG_DIR and WSL_LINKER_EXPERIMENTAL_DIR to ephemeral temp dirs.
    """

    @classmethod
    def setUpClass(cls):
        # Capture baseline state of real host files
        cls.real_links_hash = _hash_file(REAL_USER_LINKS)
        cls.real_links_mtime = REAL_USER_LINKS.stat().st_mtime if REAL_USER_LINKS.exists() else None
        cls.real_config_hash = _hash_file(REAL_USER_CONFIG)
        cls.real_config_mtime = REAL_USER_CONFIG.stat().st_mtime if REAL_USER_CONFIG.exists() else None

    def setUp(self):
        # Create dedicated isolated temp dirs for this test instance
        self.temp_dir = tempfile.mkdtemp(prefix="audit_test_iso_")
        self.iso_config_dir = Path(self.temp_dir) / ".wsl-linker"
        self.iso_exp_dir = Path(self.temp_dir) / ".wsl-linker-experimental"
        self.iso_config_dir.mkdir(parents=True, exist_ok=True)
        self.iso_exp_dir.mkdir(parents=True, exist_ok=True)

        self._orig_env = os.environ.copy()
        os.environ["WSL_LINKER_CONFIG_DIR"] = str(self.iso_config_dir)
        os.environ["WSL_LINKER_EXPERIMENTAL_DIR"] = str(self.iso_exp_dir)

    def tearDown(self):
        # Restore environment
        os.environ.clear()
        os.environ.update(self._orig_env)
        # Clean up temporary test files
        if os.path.exists(self.temp_dir):
            try:
                shutil.rmtree(self.temp_dir)
            except Exception:
                pass

        # Invariant check: real host files must NOT have been modified
        curr_links_hash = _hash_file(REAL_USER_LINKS)
        curr_config_hash = _hash_file(REAL_USER_CONFIG)
        if self.real_links_hash != curr_links_hash:
            raise AssertionError(f"[R5 VIOLATION] Real user links.json was modified during test: {self.id()}")
        if self.real_config_hash != curr_config_hash:
            raise AssertionError(f"[R5 VIOLATION] Real user config.json was modified during test: {self.id()}")


# =====================================================================
# TC-SEC-01: Localhost Port Binding & Container Capability Hardening
# =====================================================================
class TestPortBindingSecurity(BaseIsolatedTestCase):

    def test_tc_sec_01_sandbox_manager_find_free_port_binds_localhost(self):
        """Verifies find_free_port tests availability strictly on 127.0.0.1, not 0.0.0.0."""
        from scripts.sandbox_manager import find_free_port

        bound_addresses = []

        def mock_bind(*args, **kwargs):
            if args:
                bound_addresses.append(args[0])
            return None

        with patch.object(socket.socket, "bind", side_effect=mock_bind):
            port = find_free_port({"docker_mappings": []})
            self.assertGreaterEqual(port, 2222)
            self.assertTrue(len(bound_addresses) > 0)
            for addr in bound_addresses:
                host, p = addr
                self.assertEqual(host, "127.0.0.1", f"Expected bind to 127.0.0.1 but found '{host}'")

    def test_tc_sec_01_sandbox_manager_cmd_create_docker_port_arg(self):
        """Verifies docker run in cmd_create explicitly binds container SSH port to 127.0.0.1."""
        from scripts.sandbox_manager import cmd_create

        captured_docker_cmds = []

        def mock_subprocess_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and len(cmd) > 1 and cmd[0] == "docker" and cmd[1] == "run":
                captured_docker_cmds.append(cmd)
                # Return failure to avoid continuing into SSH setup in this mock test
                return subprocess.CompletedProcess(cmd, returncode=1, stdout="", stderr="Mock abort after docker run")
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_subprocess_run):
            with patch("scripts.sandbox_manager.detect_default_distro", return_value="Ubuntu-24.04"):
                args = argparse.Namespace(
                    name="audit_test_port01",
                    image="alpine:latest",
                    parent=self.temp_dir,
                    distro="Ubuntu-24.04",
                    env=None,
                    json=True
                )
                cmd_create(args)

        self.assertTrue(len(captured_docker_cmds) > 0, "docker run was not called")
        run_cmd = captured_docker_cmds[0]
        # Verify that -p is followed by 127.0.0.1:{port}:22
        self.assertIn("-p", run_cmd)
        p_index = run_cmd.index("-p")
        port_binding = run_cmd[p_index + 1]
        self.assertTrue(
            port_binding.startswith("127.0.0.1:"),
            f"Expected port binding to start with '127.0.0.1:', but got '{port_binding}'"
        )
        self.assertFalse(
            port_binding.startswith("0.0.0.0:"),
            f"Found insecure 0.0.0.0 binding: '{port_binding}'"
        )

    def test_tc_sec_01_experimental_bridge_capabilities_unprivileged(self):
        """Verifies devlinker-bridge does NOT use --privileged or docker.sock, and uses SYS_ADMIN + /dev/fuse."""
        from experimental_linker import build_and_start_bridge

        captured_bridge_cmds = []

        def mock_subprocess_run(cmd, *args, **kwargs):
            if isinstance(cmd, list) and "devlinker-bridge" in cmd:
                captured_bridge_cmds.append(cmd)
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        with patch("subprocess.run", side_effect=mock_subprocess_run):
            build_and_start_bridge(self.temp_dir)

        run_cmds = [c for c in captured_bridge_cmds if "run" in c]
        self.assertTrue(len(run_cmds) > 0, "docker run for devlinker-bridge was not executed")
        bridge_cmd = run_cmds[0]

        self.assertNotIn("--privileged", bridge_cmd, "devlinker-bridge must NOT run with --privileged")
        self.assertNotIn("/var/run/docker.sock:/var/run/docker.sock", bridge_cmd, "docker.sock must NOT be bind mounted")
        self.assertIn("--cap-add=SYS_ADMIN", bridge_cmd, "devlinker-bridge must use --cap-add=SYS_ADMIN")
        self.assertIn("--device", bridge_cmd, "devlinker-bridge must specify --device")
        self.assertIn("/dev/fuse", bridge_cmd, "devlinker-bridge must mount /dev/fuse")


# =====================================================================
# TC-SEC-02: Strict Input Sanitization on Alias & Paths
# =====================================================================
class TestInputSanitization(BaseIsolatedTestCase):

    def test_tc_sec_02_alias_validation_regex(self):
        """Validates validate_alias against valid identifiers and attack payloads."""
        from scripts.sandbox_manager import validate_alias

        # Legitimate aliases
        valid_aliases = [
            "sandbox1",
            "audit_test_01",
            "my-project-dev",
            "app.prod",
            "A",
            "Z123-abc.def_ghi",
            "a" * 63  # Max 63 characters
        ]
        for val in valid_aliases:
            self.assertTrue(validate_alias(val), f"Expected valid alias for '{val}'")

        # Attack vectors & invalid formats
        invalid_aliases = [
            'audit_test_$(id)',                   # Command substitution
            'audit_test"; touch /tmp/pwned; #',   # Quote breakout & command chaining
            'audit test space',                   # Space
            '../../audit_test_escape',            # Path traversal
            'test;rm -rf /',                      # Semicolon injection
            'test&calc.exe',                      # Windows cmd chaining
            'test|calc.exe',                      # Pipe chaining
            '-invalid_leading_dash',              # Must start with alphanumeric
            '.invalid_leading_dot',               # Must start with alphanumeric
            '_invalid_leading_underscore',        # Must start with alphanumeric
            '',                                   # Empty
            'a' * 64,                             # Exceeds max length of 63
            'test\nnewline',                      # Newline injection
            'test`id`',                           # Backtick expansion
            'test>out'                            # Redirect
        ]
        for inval in invalid_aliases:
            self.assertFalse(validate_alias(inval), f"Expected invalid alias for injection vector '{inval}'")

    def test_tc_sec_02_cmd_create_rejects_malicious_alias_immediately(self):
        """Verifies cmd_create aborts with exit code 1 when given a malicious alias without launching Docker."""
        from scripts.sandbox_manager import cmd_create

        docker_invoked = []

        def mock_subprocess_run(cmd, *args, **kwargs):
            docker_invoked.append(cmd)
            return subprocess.CompletedProcess(cmd, returncode=0)

        with patch("subprocess.run", side_effect=mock_subprocess_run):
            args = argparse.Namespace(
                name='test"; touch /tmp/pwned; #',
                image="alpine:latest",
                parent=self.temp_dir,
                distro="Ubuntu-24.04",
                env=None,
                json=False
            )
            ret = cmd_create(args)
            self.assertEqual(ret, 1, "cmd_create must return 1 on invalid alias")
            self.assertEqual(len(docker_invoked), 0, "No subprocesses should be launched when alias is invalid")


# =====================================================================
# TC-SEC-03: Safe Teardown Guarantees (NEVER delete normal directories)
# =====================================================================
class TestSafeTeardown(BaseIsolatedTestCase):

    def test_tc_sec_03_sandbox_manager_teardown_never_deletes_regular_dir(self):
        """Verifies cmd_teardown NEVER deletes physical host directories, even if registered or empty."""
        from scripts.sandbox_manager import cmd_teardown, load_registry, save_registry

        # Create a real, physical folder with a file
        real_folder = Path(self.temp_dir) / "real_project_folder"
        real_folder.mkdir(parents=True, exist_ok=True)
        canary_file = real_folder / "precious_data.txt"
        canary_file.write_text("critical source code")

        # Register this folder as a sandbox mapping
        db = load_registry()
        db["docker_mappings"].append({
            "name": "audit_safe_teardown_test",
            "container_name": "mock_container",
            "image": "alpine:latest",
            "link_type": "reverse",
            "ssh_port": 2222,
            "wsl_distro": "Ubuntu-24.04",
            "wsl_mount_path": "/root/.devlinker-mounts/audit_safe_teardown_test",
            "wsl_unc_path": "\\\\wsl.localhost\\Ubuntu-24.04\\...",
            "windows_path": str(real_folder),
            "symlink_created": False
        })
        save_registry(db)

        # Run teardown
        args = argparse.Namespace(
            name="audit_safe_teardown_test",
            keep_container=True,
            json=True
        )
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], returncode=0)):
            ret = cmd_teardown(args)

        self.assertEqual(ret, 0)
        # Verify physical directory and file were NOT deleted
        self.assertTrue(real_folder.exists(), "Teardown erroneously deleted a real host folder!")
        self.assertTrue(canary_file.exists(), "Teardown deleted files inside a real host folder!")

    def test_tc_sec_03_sandbox_manager_wsl_unlink_never_deletes_regular_dir(self):
        """Verifies cmd_wsl_unlink NEVER deletes physical host directories."""
        from scripts.sandbox_manager import cmd_wsl_unlink, load_registry, save_registry

        real_folder = Path(self.temp_dir) / "wsl_real_folder"
        real_folder.mkdir(parents=True, exist_ok=True)
        canary_file = real_folder / "file.txt"
        canary_file.write_text("do not delete")

        db = load_registry()
        db["wsl_mappings"].append({
            "name": "audit_wsl_test",
            "windows_path": str(real_folder),
            "wsl_distro": "Ubuntu-24.04",
            "wsl_path": "/home/user/project"
        })
        save_registry(db)

        args = argparse.Namespace(name="audit_wsl_test")
        ret = cmd_wsl_unlink(args)
        self.assertEqual(ret, 0)
        self.assertTrue(real_folder.exists(), "cmd_wsl_unlink deleted a physical folder!")

    def test_tc_sec_03_wsl_linker_remove_aborts_on_regular_dir(self):
        """Verifies wsl_linker.remove_link raises SystemExit(1) and refuses to delete a regular directory."""
        from wsl_linker import remove_link, load_registry, save_registry

        real_folder = Path(self.temp_dir) / "wsl_linker_real_folder"
        real_folder.mkdir(parents=True, exist_ok=True)
        canary_file = real_folder / "keep_me.txt"
        canary_file.write_text("must survive")

        reg = load_registry()
        reg["mappings"].append({
            "name": "safe_unlink_test",
            "windows_path": str(real_folder),
            "wsl_distro": "Ubuntu-24.04",
            "wsl_path": "/home/user/app"
        })
        save_registry(reg)

        args = argparse.Namespace(name_or_path="safe_unlink_test")
        with self.assertRaises(SystemExit) as ctx:
            remove_link(args)

        self.assertEqual(ctx.exception.code, 1)
        self.assertTrue(real_folder.exists(), "wsl_linker.remove_link deleted a physical directory!")
        self.assertTrue(canary_file.exists(), "wsl_linker.remove_link deleted files inside a physical directory!")


# =====================================================================
# TC-SEC-04: UNC Path Construction & Leading Slash Normalization
# =====================================================================
class TestUNCPathConstruction(BaseIsolatedTestCase):

    def test_tc_sec_04_wsl_linker_unc_leading_slash_normalization(self):
        """Verifies UNC path construction properly normalizes target paths with or without leading slashes."""
        from wsl_linker import add_link, load_registry

        dest_folder = str(Path(self.temp_dir) / "new_symlink_dest")

        # Test various representations of target WSL path
        test_inputs = [
            ("home/user/code/project", "\\\\wsl.localhost\\Ubuntu-24.04\\home\\user\\code\\project"),
            ("/home/user/code/project", "\\\\wsl.localhost\\Ubuntu-24.04\\home\\user\\code\\project"),
            ("home\\user\\code\\project", "\\\\wsl.localhost\\Ubuntu-24.04\\home\\user\\code\\project"),
            ("\\home\\user\\code\\project", "\\\\wsl.localhost\\Ubuntu-24.04\\home\\user\\code\\project")
        ]

        for idx, (raw_target, expected_unc) in enumerate(test_inputs):
            target_uncs_created = []

            def mock_symlink(src, dst, target_is_directory=False):
                target_uncs_created.append(src)

            with patch("os.symlink", side_effect=mock_symlink):
                with patch("subprocess.run", return_value=subprocess.CompletedProcess([], returncode=0)):
                    args = argparse.Namespace(
                        windows_path=dest_folder + f"_{idx}",
                        wsl_path=raw_target,
                        distro="Ubuntu-24.04",
                        name=f"unc_test_{idx}"
                    )
                    add_link(args)

            self.assertEqual(len(target_uncs_created), 1)
            self.assertEqual(
                target_uncs_created[0],
                expected_unc,
                f"For input '{raw_target}', expected '{expected_unc}' but got '{target_uncs_created[0]}'"
            )

    def test_tc_sec_04_wsl_linker_relpath_computation(self):
        """Verifies run_command accurately translates Windows subdirectories to WSL subdirectories."""
        from wsl_linker import run_command, load_registry, save_registry

        root_win = os.path.abspath(str(Path(self.temp_dir) / "workspace_root"))
        sub_win = os.path.join(root_win, "src", "components")

        reg = load_registry()
        reg["mappings"].append({
            "name": "relpath_test",
            "windows_path": root_win,
            "wsl_distro": "Ubuntu-24.04",
            "wsl_path": "/home/user/repo"
        })
        save_registry(reg)

        captured_commands = []

        def mock_run(cmd, *args, **kwargs):
            captured_commands.append(cmd)
            return subprocess.CompletedProcess(cmd, returncode=0)

        with patch("os.getcwd", return_value=sub_win):
            with patch("subprocess.run", side_effect=mock_run):
                args = argparse.Namespace(cmd_args=["git", "status"])
                with self.assertRaises(SystemExit) as ctx:
                    run_command(args)
                self.assertEqual(ctx.exception.code, 0)

        self.assertEqual(len(captured_commands), 1)
        wsl_cmd = captured_commands[0]
        # Should contain --cd /home/user/repo/src/components
        self.assertIn("--cd", wsl_cmd)
        cd_idx = wsl_cmd.index("--cd")
        target_dir = wsl_cmd[cd_idx + 1]
        self.assertEqual(target_dir, "/home/user/repo/src/components")


# =====================================================================
# TC-SEC-05: Non-Zero Exit Code Verification on Fatal Errors
# =====================================================================
class TestNonZeroExitCodes(BaseIsolatedTestCase):

    def test_tc_sec_05_wsl_linker_add_missing_name_exits_1(self):
        """Verifies add_link exits with code 1 if name cannot be derived."""
        from wsl_linker import add_link

        args = argparse.Namespace(
            windows_path="\\",
            wsl_path="/home/user/test",
            distro="Ubuntu-24.04",
            name=""
        )
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], returncode=0)):
            with self.assertRaises(SystemExit) as ctx:
                add_link(args)
        self.assertEqual(ctx.exception.code, 1)

    def test_tc_sec_05_wsl_linker_add_existing_destination_exits_1(self):
        """Verifies add_link exits with code 1 when destination already exists."""
        from wsl_linker import add_link

        existing_folder = Path(self.temp_dir) / "already_exists"
        existing_folder.mkdir()

        args = argparse.Namespace(
            windows_path=str(existing_folder),
            wsl_path="/home/user/test",
            distro="Ubuntu-24.04",
            name="existing_test"
        )
        with patch("subprocess.run", return_value=subprocess.CompletedProcess([], returncode=0)):
            with self.assertRaises(SystemExit) as ctx:
                add_link(args)
            self.assertEqual(ctx.exception.code, 1)

    def test_tc_sec_05_wsl_linker_remove_nonexistent_exits_1(self):
        """Verifies remove_link exits with code 1 when target mapping is not found."""
        from wsl_linker import remove_link

        args = argparse.Namespace(name_or_path="non_existent_workspace_9999")
        with self.assertRaises(SystemExit) as ctx:
            remove_link(args)
        self.assertEqual(ctx.exception.code, 1)

    def test_tc_sec_05_wsl_linker_cli_subprocess_returns_nonzero(self):
        """Verifies wsl_linker.py invoked via CLI subprocess returns exit code 1 on fatal error."""
        cmd = [sys.executable, str(REPO_ROOT / "wsl_linker.py"), "remove", "non_existent_workspace_xyz"]
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env={**os.environ, "WSL_LINKER_CONFIG_DIR": str(self.iso_config_dir)}
        )
        self.assertEqual(res.returncode, 1, f"Expected CLI to exit with code 1, but got {res.returncode}")
        self.assertIn("Error:", res.stderr)


# =====================================================================
# TC-SEC-06: Atomic Registry Loading, Saving & Corruption Backup
# =====================================================================
class TestAtomicRegistrySafety(BaseIsolatedTestCase):

    def test_tc_sec_06_sandbox_manager_load_corrupt_creates_backup_and_raises(self):
        """Verifies load_registry in sandbox_manager does NOT silently swallow corrupt JSON, creates .corrupt.bak and raises."""
        from scripts.sandbox_manager import load_registry, get_config_path

        cfg = get_config_path()
        corrupt_content = "{ invalid json content !!!"
        cfg.write_text(corrupt_content, encoding="utf-8")

        with self.assertRaises(RuntimeError) as ctx:
            load_registry()

        self.assertIn("Corrupt registry", str(ctx.exception))
        bak_file = cfg.with_name(cfg.name + ".corrupt.bak")
        self.assertTrue(bak_file.exists(), "Backup .corrupt.bak was not created on decode failure")
        self.assertEqual(bak_file.read_text(encoding="utf-8"), corrupt_content)

    def test_tc_sec_06_sandbox_manager_save_is_atomic_and_valid(self):
        """Verifies save_registry writes valid JSON atomically without corruption."""
        from scripts.sandbox_manager import save_registry, load_registry, get_config_path

        test_data = {
            "docker_mappings": [{"name": "atom_test", "ssh_port": 2225}],
            "wsl_mappings": [{"name": "atom_wsl"}],
            "ssh_mappings": [],
            "credentials": {},
            "env_vars": {"FOO": "BAR"},
            "bridge_active": True
        }
        save_registry(test_data)

        # Reload directly and verify
        loaded = load_registry()
        self.assertEqual(loaded["docker_mappings"][0]["name"], "atom_test")
        self.assertEqual(loaded["env_vars"]["FOO"], "BAR")

    def test_tc_sec_06_wsl_linker_load_corrupt_creates_backup_and_raises(self):
        """Verifies load_registry in wsl_linker creates .corrupt.bak and raises on decode failure."""
        from wsl_linker import load_registry, get_registry_path

        reg_file = get_registry_path()
        corrupt_content = '{"mappings": [ broken syntax ...'
        reg_file.write_text(corrupt_content, encoding="utf-8")

        with self.assertRaises(RuntimeError) as ctx:
            load_registry()

        self.assertIn("Corrupt registry", str(ctx.exception))
        bak_file = reg_file.with_name(reg_file.name + ".corrupt.bak")
        self.assertTrue(bak_file.exists(), "Backup .corrupt.bak was not created for links.json")
        self.assertEqual(bak_file.read_text(encoding="utf-8"), corrupt_content)


# =====================================================================
# TC-SEC-07: SSHFS Performance Optimization Flags
# =====================================================================
class TestSSHFSPerformanceFlags(BaseIsolatedTestCase):

    def test_tc_sec_07_sandbox_manager_sshfs_performance_flags(self):
        """Verifies sshfs_mount_script includes all critical caching and throughput flags and shell-quotes path."""
        from scripts.sandbox_manager import sshfs_mount_script

        script = sshfs_mount_script(2225, "/home/user/.devlinker-mounts/my project")

        required_flags = [
            "kernel_cache",
            "auto_cache",
            "entry_timeout=60",
            "attr_timeout=60",
            "big_writes",
            "max_read=131072",
            "max_write=131072",
            "compression=no"
        ]

        for flag in required_flags:
            self.assertIn(flag, script, f"Missing required SSHFS performance flag: '{flag}'")

        # Check that path with space was safely quoted
        self.assertIn("'/home/user/.devlinker-mounts/my project'", script)

    def test_tc_sec_07_experimental_linker_mount_cmd_performance_flags(self):
        """Verifies connect_remote_ssh_in_docker uses performance flags and shlex.quote."""
        import experimental_linker

        captured_docker_cmds = []

        def mock_subprocess_run(cmd, *args, **kwargs):
            captured_docker_cmds.append(cmd)
            return subprocess.CompletedProcess(cmd, returncode=0, stdout="", stderr="")

        # Setup test config in isolated dir
        cfg = experimental_linker.load_config()
        cfg["bridge_active"] = True
        cfg["host_projects_dir"] = self.temp_dir
        cfg["credentials"]["test_prof"] = {
            "user": "ubuntu",
            "host": "1.2.3.4",
            "auth_type": "password",
            "secret": "demo"
        }
        experimental_linker.save_config(cfg)

        with patch("subprocess.run", side_effect=mock_subprocess_run):
            experimental_linker.connect_remote_ssh_in_docker("test_prof", "/var/www/my site")

        self.assertTrue(len(captured_docker_cmds) > 0)
        mount_call = [c for c in captured_docker_cmds if "devlinker-bridge" in c and "sshfs" in " ".join(c)]
        self.assertTrue(len(mount_call) > 0, "sshfs mount command was not executed")

        full_cmd_str = " ".join(mount_call[0])
        self.assertIn("kernel_cache", full_cmd_str)
        self.assertIn("max_read=131072", full_cmd_str)
        self.assertIn("compression=no", full_cmd_str)
        self.assertIn("'/var/www/my site'", full_cmd_str)


# =====================================================================
# TC-R5: Host Infrastructure & Workspace Safety Verification
# =====================================================================
class TestR5WorkspaceIsolation(BaseIsolatedTestCase):

    def test_tc_r5_real_user_workspaces_untouched(self):
        """
        Validates Requirement R5: Ensures the active user's production workspace files
        (~/.wsl-linker/links.json and ~/.wsl-linker-experimental/config.json) are 100% untouched.
        """
        current_links_hash = _hash_file(REAL_USER_LINKS)
        current_config_hash = _hash_file(REAL_USER_CONFIG)

        self.assertEqual(
            self.real_links_hash,
            current_links_hash,
            "R5 VIOLATION: Real user links.json was modified!"
        )
        self.assertEqual(
            self.real_config_hash,
            current_config_hash,
            "R5 VIOLATION: Real user config.json was modified!"
        )

        if REAL_USER_LINKS.exists():
            self.assertEqual(
                self.real_links_mtime,
                REAL_USER_LINKS.stat().st_mtime,
                "R5 VIOLATION: Real user links.json modification timestamp changed!"
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
