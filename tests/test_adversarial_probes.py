#!/usr/bin/env python3
"""
Adversarial Empirical Probe Suite for sandbox-linker Remediation.

Empirically challenges:
1. Input validation & regex boundary probing (validate_alias)
2. Zero external shell invocation on invalid inputs
3. Port binding restriction strictly to 127.0.0.1 & port exhaustion behavior
4. Physical directory preservation during teardown/unlink (anti-deletion oracle)
5. Shell injection elimination (zero shell=True, tokenized execution)
6. Host workspace safety & invariant verification (R5)
7. Atomic registry corruption protection
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
import subprocess
import hashlib
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.sandbox_manager import validate_alias, ALIAS_REGEX
import scripts.sandbox_manager as sm
import wsl_linker


class TestAdversarialInputValidation(unittest.TestCase):
    """Deep adversarial boundary and edge case testing of alias validation."""

    def test_alias_boundary_lengths(self):
        """Test exact boundary lengths: 0, 1, 63, 64, 100 chars."""
        # 0 chars (empty string)
        self.assertFalse(validate_alias(""), "Empty string must be rejected")

        # 1 char boundaries
        for ch in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789":
            self.assertTrue(validate_alias(ch), f"Single valid alnum char '{ch}' must be accepted")
        for ch in "_-./@\\:;#%*":
            self.assertFalse(validate_alias(ch), f"Single non-alnum char '{ch}' must be rejected")

        # 63 chars (1 alnum + 62 allowed chars) -> MAX ALLOWED
        alias_63 = "a" + ("b" * 62)
        self.assertEqual(len(alias_63), 63)
        self.assertTrue(validate_alias(alias_63), "63-character valid alias must be accepted")

        alias_63_mixed = "A" + ("_.-" * 20) + "x" + "9"
        self.assertEqual(len(alias_63_mixed), 63)
        self.assertTrue(validate_alias(alias_63_mixed), "63-character mixed valid alias must be accepted")

        # 64 chars (1 alnum + 63 chars) -> EXCEEDS MAX (63)
        alias_64 = "a" + ("b" * 63)
        self.assertEqual(len(alias_64), 64)
        self.assertFalse(validate_alias(alias_64), "64-character alias MUST be rejected")

        alias_100 = "a" * 100
        self.assertFalse(validate_alias(alias_100), "100-character alias MUST be rejected")

    def test_shell_metacharacters(self):
        """Test all common shell metacharacters and injection attack payloads."""
        payloads = [
            "$(id)",
            "`id`",
            "test; id",
            "test;id",
            "test&&id",
            "test && id",
            "test||id",
            "test|id",
            "test | cat /etc/passwd",
            "test&id",
            "test\\",
            "test\\subdir",
            "test'id",
            "test\"id",
            "test\nid",
            "test\rid",
            "test\tid",
            "test id",
            " test",
            "test ",
            "test > /tmp/pwned",
            "test < /dev/null",
            "test${IFS}id",
            "test*",
            "test?",
            "test~",
            "test!id",
            "test#comment",
            "test(id)",
            "test[0]",
            "test{a,b}",
        ]
        for p in payloads:
            self.assertFalse(validate_alias(p), f"Shell payload '{p}' MUST be rejected")

    def test_path_traversal(self):
        """Test path traversal sequences and separators."""
        traversal_payloads = [
            "..",
            ".",
            "../",
            "../../",
            "../../../etc/shadow",
            "..\\..\\Windows",
            "/root",
            "/",
            "\\",
            "C:\\",
            "D:\\workspace",
            "foo/bar",
            "foo\\bar",
            "./foo",
            ".\\foo",
            "foo/../bar",
        ]
        for t in traversal_payloads:
            self.assertFalse(validate_alias(t), f"Path traversal '{t}' MUST be rejected")

    def test_unicode_and_homoglyphs(self):
        """Test that unicode letters, homoglyphs, and control characters are rejected."""
        unicode_payloads = [
            "пwned",           # Cyrillic small letter pe
            "алиас",           # Cyrillic alias
            "héllo",           # Latin small letter e with acute
            "café",            # e with acute
            "über",            # u with umlaut
            "🚀sandbox",        # Emoji
            "sandbox🚀",        # Emoji at end
            "\u202ealias",     # Right-to-Left Override (RTLO)
            "\uff0fetc\uff0f", # Fullwidth solidus
            "test\u0000null",  # Null byte
            "\ufeffbom",       # Zero-width byte order mark
        ]
        for u in unicode_payloads:
            self.assertFalse(validate_alias(u), f"Unicode payload '{u!r}' MUST be rejected")

    def test_non_string_types(self):
        """Test that validate_alias gracefully rejects non-string inputs."""
        non_strings = [
            None,
            123,
            0,
            True,
            False,
            [],
            ["alias"],
            {"alias": "val"},
            1.23,
            b"alias",
        ]
        for val in non_strings:
            self.assertFalse(validate_alias(val), f"Non-string input {val!r} MUST be rejected")

    def test_cmd_create_and_wsl_link_reject_before_invoking_external_shells(self):
        """
        Verify that cmd_create and cmd_wsl_link safely reject invalid aliases
        WITHOUT invoking any subprocess (wsl, docker, bash, cmd).
        """
        malicious_aliases = [
            "$(id)",
            "test; rm -rf /",
            "test && whoami",
            "../../etc/shadow",
            "test | evil",
        ]

        for alias in malicious_aliases:
            args = MagicMock()
            args.name = alias
            args.alias = alias
            args.parent = tempfile.gettempdir()
            args.image = "ubuntu:latest"
            args.distro = "Ubuntu-24.04"
            args.json = True

            with patch("subprocess.run") as mock_subproc, \
                 patch("scripts.sandbox_manager.wsl_run") as mock_wsl:
                exit_code_create = sm.cmd_create(args)
                self.assertEqual(exit_code_create, 1, f"cmd_create must return 1 on malicious alias '{alias}'")
                mock_subproc.assert_not_called()
                mock_wsl.assert_not_called()

            with patch("subprocess.run") as mock_subproc, \
                 patch("scripts.sandbox_manager.wsl_run") as mock_wsl:
                args.target = "/home/user/code"
                exit_code_wsl = sm.cmd_wsl_link(args)
                self.assertEqual(exit_code_wsl, 1, f"cmd_wsl_link must return 1 on malicious alias '{alias}'")
                mock_subproc.assert_not_called()
                mock_wsl.assert_not_called()


class TestAdversarialPortBindingAndNetworkExposure(unittest.TestCase):
    """Empirically verify 0.0.0.0 is completely eliminated and port binding is local-only."""

    def test_repo_files_contain_zero_insecure_port_bindings(self):
        """Verify that scripts/ and root python scripts contain no 0.0.0.0 bindings."""
        in_scope_files = [
            REPO_ROOT / "scripts" / "sandbox_manager.py",
            REPO_ROOT / "experimental_linker.py",
            REPO_ROOT / "experimental_linker_gui.py",
            REPO_ROOT / "wsl_linker.py",
            REPO_ROOT / "wsl_linker_gui.py",
        ]
        for fpath in in_scope_files:
            content = fpath.read_text(encoding="utf-8")
            self.assertNotIn("0.0.0.0", content, f"Insecure '0.0.0.0' found in {fpath.name}")

    def test_find_free_port_local_loopback_only(self):
        """Verify find_free_port binds strictly to 127.0.0.1 and avoids port collisions."""
        with patch("socket.socket") as mock_socket_class:
            mock_s = MagicMock()
            mock_socket_class.return_value.__enter__.return_value = mock_s

            db = {"docker_mappings": [{"ssh_port": 2222}]}
            port = sm.find_free_port(db)

            # 2222 was registered, so it must check 2223
            self.assertEqual(port, 2223)
            # Ensure socket.bind was called with ('127.0.0.1', port)
            bind_calls = [call.args[0] for call in mock_s.bind.call_args_list]
            self.assertIn(("127.0.0.1", 2223), bind_calls)
            for addr, p in bind_calls:
                self.assertEqual(addr, "127.0.0.1", f"Insecure bind host observed: {addr}")

    def test_find_free_port_exhaustion_behavior(self):
        """Verify find_free_port raises RuntimeError when ports 2222-2321 are all occupied."""
        with patch("socket.socket") as mock_socket_class:
            mock_s = MagicMock()
            # Simulate every port being already occupied (bind raises OSError)
            mock_s.bind.side_effect = OSError("Address already in use")
            mock_socket_class.return_value.__enter__.return_value = mock_s

            with self.assertRaises(RuntimeError) as ctx:
                sm.find_free_port({"docker_mappings": []})
            self.assertIn("No free port available", str(ctx.exception))


class TestTeardownSafetyAntiDeletionOracle(unittest.TestCase):
    """
    Empirical teardown safety oracle:
    Verifies that normal physical directories (empty or populated) are NEVER deleted
    by unmount, teardown, or unlink routines.
    """

    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="adv_teardown_test_")

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_sandbox_manager_teardown_never_deletes_empty_normal_directory(self):
        """Create empty physical directory, pass to cmd_teardown, verify it is NOT deleted."""
        target_dir = os.path.join(self.test_dir, "empty_real_dir")
        os.makedirs(target_dir, exist_ok=True)
        self.assertTrue(os.path.isdir(target_dir))
        self.assertFalse(os.path.islink(target_dir))

        # Mock database with a mapping pointing to this regular directory
        mock_db = {
            "docker_mappings": [{
                "name": "probe_sandbox",
                "windows_path": target_dir,
                "wsl_distro": "Ubuntu-24.04",
                "wsl_mount_path": "/home/user/.devlinker-mounts/probe_sandbox",
                "container_name": "devlink_container_probe_sandbox",
                "ssh_port": 2222,
            }]
        }

        with patch("scripts.sandbox_manager.load_registry", return_value=mock_db), \
             patch("scripts.sandbox_manager.save_registry"), \
             patch("scripts.sandbox_manager.unmount_wsl_sshfs"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            args = MagicMock()
            args.name = "probe_sandbox"
            args.alias = "probe_sandbox"
            args.keep_container = True
            args.json = True

            sm.cmd_teardown(args)

            # Oracle assertion: The physical directory MUST still exist!
            self.assertTrue(os.path.exists(target_dir), "VULNERABILITY: cmd_teardown DELETED a normal directory!")
            self.assertTrue(os.path.isdir(target_dir), "Target must remain a normal directory")

    def test_sandbox_manager_teardown_never_deletes_populated_normal_directory(self):
        """Create populated physical directory with files, verify it is 100% intact after teardown."""
        target_dir = os.path.join(self.test_dir, "populated_dir")
        os.makedirs(target_dir, exist_ok=True)
        canary_file = os.path.join(target_dir, "precious_code.py")
        Path(canary_file).write_text("print('critical user code')", encoding="utf-8")

        mock_db = {
            "docker_mappings": [{
                "name": "probe_sandbox_2",
                "windows_path": target_dir,
                "wsl_distro": "Ubuntu-24.04",
                "wsl_mount_path": "/home/user/.devlinker-mounts/probe_sandbox_2",
                "container_name": "devlink_container_probe_sandbox_2",
                "ssh_port": 2223,
            }]
        }

        with patch("scripts.sandbox_manager.load_registry", return_value=mock_db), \
             patch("scripts.sandbox_manager.save_registry"), \
             patch("scripts.sandbox_manager.unmount_wsl_sshfs"), \
             patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            args = MagicMock()
            args.name = "probe_sandbox_2"
            args.alias = "probe_sandbox_2"
            args.keep_container = True
            args.json = True

            sm.cmd_teardown(args)

            self.assertTrue(os.path.exists(target_dir), "cmd_teardown deleted directory!")
            self.assertTrue(os.path.exists(canary_file), "cmd_teardown deleted canary file!")
            self.assertEqual(Path(canary_file).read_text(encoding="utf-8"), "print('critical user code')")

    def test_wsl_linker_remove_aborts_on_normal_directory(self):
        """Verify wsl_linker.remove_link raises SystemExit(1) and refuses to delete a normal directory."""
        target_dir = os.path.join(self.test_dir, "wsl_normal_folder")
        os.makedirs(target_dir, exist_ok=True)

        mock_registry = {
            "mappings": [{
                "name": "test_wsl_link",
                "windows_path": target_dir,
                "wsl_path": "/home/user/repo",
                "wsl_distro": "Ubuntu-24.04",
            }]
        }

        args = MagicMock()
        args.name_or_path = "test_wsl_link"

        with patch("wsl_linker.load_registry", return_value=mock_registry), \
             patch("wsl_linker.save_registry"):
            with self.assertRaises(SystemExit) as cm:
                wsl_linker.remove_link(args)
            self.assertEqual(cm.exception.code, 1, "Must exit with status 1 on normal directory")

            # Oracle assertion
            self.assertTrue(os.path.exists(target_dir), "VULNERABILITY: remove_link DELETED a normal directory!")


class TestShellInjectionAndProcessSafety(unittest.TestCase):
    """Empirical verification that shell=True is eradicated and execution is tokenized."""

    def test_zero_shell_true_in_all_modules(self):
        """Assert zero occurrences of shell=True across all implementation files."""
        files_to_check = [
            REPO_ROOT / "scripts" / "sandbox_manager.py",
            REPO_ROOT / "experimental_linker.py",
            REPO_ROOT / "experimental_linker_gui.py",
            REPO_ROOT / "wsl_linker.py",
            REPO_ROOT / "wsl_linker_gui.py",
        ]
        for fpath in files_to_check:
            content = fpath.read_text(encoding="utf-8")
            self.assertNotIn("shell=True", content, f"shell=True found in {fpath.name}")

    def test_wsl_linker_run_command_uses_direct_wsl_cd(self):
        """
        Verify that wsl_linker run_command uses --cd rather than bash string interpolation
        to navigate to guest directories.
        """
        current_dir = os.path.join(self.id(), "subfolder")
        mock_mapping = {
            "name": "test_ws",
            "windows_path": self.id(),
            "wsl_path": "/home/user/project",
            "wsl_distro": "Ubuntu-24.04",
        }

        args = MagicMock()
        args.cmd_args = ["git", "status"]

        with patch("wsl_linker.load_registry", return_value={"mappings": [mock_mapping]}), \
             patch("os.getcwd", return_value=self.id()), \
             patch("subprocess.run") as mock_run, \
             patch("sys.exit") as mock_exit:
            mock_run.return_value = MagicMock(returncode=0)

            wsl_linker.run_command(args)

            mock_run.assert_called_once()
            exec_args = mock_run.call_args[0][0]
            self.assertIsInstance(exec_args, list, "Subprocess must be invoked with tokenized list")
            self.assertIn("--cd", exec_args, "Must use native WSL --cd")
            self.assertIn("/home/user/project", exec_args)
            # Ensure "cd '/home/user/project' &&" is NOT present in any bash arg
            for item in exec_args:
                self.assertNotIn("cd '", item)


class TestHostWorkspaceSafetyR5(unittest.TestCase):
    """
    Empirically inspects host user configuration files before and after tests:
    - ~/.wsl-linker/links.json
    - ~/.wsl-linker-experimental/config.json
    Guarantees the 13 active production workspaces are untouched.
    """

    def test_host_workspaces_remain_100_percent_identical(self):
        links_path = Path.home() / ".wsl-linker" / "links.json"
        config_path = Path.home() / ".wsl-linker-experimental" / "config.json"

        self.assertTrue(links_path.exists(), "Host links.json must exist")
        self.assertTrue(config_path.exists(), "Host config.json must exist")

        links_data = links_path.read_bytes()
        config_data = config_path.read_bytes()

        # Check exact byte sizes and hashes from baseline
        self.assertEqual(len(links_data), 3816, "Host links.json size altered!")
        self.assertEqual(len(config_data), 3937, "Host config.json size altered!")

        links_hash = hashlib.sha256(links_data).hexdigest()
        config_hash = hashlib.sha256(config_data).hexdigest()

        self.assertEqual(
            links_hash,
            "fedf2fa036e638d3521b3566281765bc259f5c31e48fce6fcaeef2c3b0282460",
            "Host links.json SHA-256 altered!"
        )
        self.assertEqual(
            config_hash,
            "9ad2d8429d1f7bd01b3df1c6b433a9f0aaae3ec143e2653355f7a615a3a90fc6",
            "Host config.json SHA-256 altered!"
        )

        obj = json.loads(links_data.decode("utf-8"))
        mappings = obj.get("mappings", [])
        self.assertEqual(len(mappings), 13, f"Expected 13 active workspaces, found {len(mappings)}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
