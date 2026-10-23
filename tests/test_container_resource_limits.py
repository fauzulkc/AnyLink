#!/usr/bin/env python3
"""
Unit and Integration Tests for Container Resource Limits, Throttling, and Volume Mounting.
Verifies:
  - --cpus flag parsing, validation, and Docker cgroup allocation
  - --memory flag parsing, validation, and OOM swap ceilings
  - --pids-limit flag parsing, validation, and process cap enforcement
  - -v / --volume flag parsing and volume mounting
  - --storage-opt flag parsing for disk quotas
"""

import sys
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
sys.path.insert(0, str(BASE_DIR / "scripts"))

from scripts.sandbox_manager import build_parser, cmd_create

class TestResourceLimitFlagParsing(unittest.TestCase):
    """Verifies that the CLI parser correctly accepts resource limit flags."""

    def setUp(self):
        self.parser = build_parser()

    def test_parser_accepts_all_resource_flags(self):
        cmd = [
            "create",
            "--name", "test_box",
            "--cpus", "2.5",
            "--memory", "1g",
            "--pids-limit", "150",
            "-v", "my_data:/workspace",
            "-v", "cache_vol:/cache",
            "--storage-opt", "size=10G"
        ]
        args = self.parser.parse_args(cmd)
        self.assertEqual(args.name, "test_box")
        self.assertEqual(args.cpus, "2.5")
        self.assertEqual(args.memory, "1g")
        self.assertEqual(args.pids_limit, 150)
        self.assertEqual(args.volume, ["my_data:/workspace", "cache_vol:/cache"])
        self.assertEqual(args.storage_opt, ["size=10G"])

class TestResourceLimitValidation(unittest.TestCase):
    """Verifies input validation and rejection of invalid values."""

    def setUp(self):
        self.parser = build_parser()
        self.temp_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temp_dir.cleanup()

    @patch("scripts.sandbox_manager.load_registry", return_value={"docker_mappings": []})
    def test_invalid_cpus_rejected(self, mock_load):
        for bad_cpu in ["-1.0", "0", "0.0", "abc", "two"]:
            args = self.parser.parse_args(["create", "--name", "test_bad_cpu", "--parent", self.temp_dir.name, "--cpus", bad_cpu, "--json"])
            ret = cmd_create(args)
            self.assertEqual(ret, 1, f"Expected invalid cpus '{bad_cpu}' to fail with exit code 1")

    @patch("scripts.sandbox_manager.load_registry", return_value={"docker_mappings": []})
    def test_invalid_memory_rejected(self, mock_load):
        for bad_mem in ["--memory=0g", "--memory=-512m", "--memory=invalid", "--memory=1000", "--memory=512mb", "--memory=1gig"]:
            args = self.parser.parse_args(["create", "--name", "test_bad_mem", "--parent", self.temp_dir.name, bad_mem, "--json"])
            ret = cmd_create(args)
            self.assertEqual(ret, 1, f"Expected invalid memory '{bad_mem}' to fail with exit code 1")

    @patch("scripts.sandbox_manager.load_registry", return_value={"docker_mappings": []})
    def test_invalid_pids_limit_rejected(self, mock_load):
        for bad_pid in ["--pids-limit=-10", "--pids-limit=0"]:
            args = self.parser.parse_args(["create", "--name", "test_bad_pid", "--parent", self.temp_dir.name, bad_pid, "--json"])
            ret = cmd_create(args)
            self.assertEqual(ret, 1, f"Expected invalid pids-limit '{bad_pid}' to fail with exit code 1")

class TestDockerCommandAssembly(unittest.TestCase):
    """Verifies that docker_cmd correctly includes throttling and volume flags."""

    @patch("scripts.sandbox_manager.load_registry", return_value={"docker_mappings": []})
    @patch("scripts.sandbox_manager.find_free_port", return_value=2222)
    @patch("scripts.sandbox_manager.get_wsl_home", return_value="/home/user")
    @patch("scripts.sandbox_manager.setup_container_ssh", return_value=True)
    @patch("scripts.sandbox_manager.setup_wsl_sshfs_mount", return_value=True)
    @patch("scripts.sandbox_manager.save_registry")
    @patch("os.symlink")
    @patch("subprocess.run")
    def test_docker_run_arguments_constructed_correctly(
        self, mock_sub, mock_symlink, mock_save, mock_sshfs, mock_ssh, mock_home, mock_port, mock_load
    ):
        mock_sub.return_value = MagicMock(returncode=0, stdout="", stderr="")

        parser = build_parser()
        args = parser.parse_args([
            "create",
            "--name", "audit_throttle_box",
            "--cpus", "2.0",
            "-m", "512m",
            "--pids-limit", "100",
            "-v", "my_persistent_vol:/workspace",
            "--storage-opt", "size=15G",
            "--json"
        ])

        ret = cmd_create(args)
        self.assertEqual(ret, 0)

        # Inspect the docker run call
        docker_run_call = None
        for call_args in mock_sub.call_args_list:
            cmd = call_args[0][0]
            if isinstance(cmd, list) and len(cmd) > 2 and cmd[0] == "docker" and cmd[1] == "run":
                docker_run_call = cmd
                break

        self.assertIsNotNone(docker_run_call, "docker run was not invoked")

        # Verify cgroups & throttling flags
        self.assertIn("--cpus", docker_run_call)
        cpu_idx = docker_run_call.index("--cpus")
        self.assertEqual(docker_run_call[cpu_idx + 1], "2.0")

        self.assertIn("--memory", docker_run_call)
        mem_idx = docker_run_call.index("--memory")
        self.assertEqual(docker_run_call[mem_idx + 1], "512m")
        self.assertIn("--memory-swap", docker_run_call)

        self.assertIn("--pids-limit", docker_run_call)
        pid_idx = docker_run_call.index("--pids-limit")
        self.assertEqual(docker_run_call[pid_idx + 1], "100")

        # Verify volume mount
        self.assertIn("-v", docker_run_call)
        vol_idx = docker_run_call.index("-v")
        self.assertEqual(docker_run_call[vol_idx + 1], "my_persistent_vol:/workspace")

        # Verify storage opt
        self.assertIn("--storage-opt", docker_run_call)
        sopt_idx = docker_run_call.index("--storage-opt")
        self.assertEqual(docker_run_call[sopt_idx + 1], "size=15G")

class TestLiveDockerCgroupInspection(unittest.TestCase):
    """Tests live Docker inspect to confirm cgroup limits take effect inside engine."""

    def test_live_docker_inspect_limits(self):
        import subprocess
        cname = "audit_cgroup_live_probe"
        # Run an ephemeral container with strict throttling
        cmd = [
            "docker", "run", "-d",
            "--name", cname,
            "--cpus", "1.5",
            "--memory", "256m",
            "--pids-limit", "42",
            "alpine:latest",
            "tail", "-f", "/dev/null"
        ]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            self.skipTest(f"Docker not available or failed: {r.stderr}")

        try:
            inspect_res = subprocess.run(
                ["docker", "inspect", cname],
                capture_output=True, text=True
            )
            self.assertEqual(inspect_res.returncode, 0)
            data = json.loads(inspect_res.stdout)[0]
            host_cfg = data.get("HostConfig", {})

            # 1.5 cpus = 1,500,000,000 NanoCpus
            self.assertEqual(host_cfg.get("NanoCpus"), 1500000000)
            # 256m = 268435456 bytes
            self.assertEqual(host_cfg.get("Memory"), 268435456)
            # 42 pids limit
            self.assertEqual(host_cfg.get("PidsLimit"), 42)
        finally:
            subprocess.run(["docker", "rm", "-f", cname], capture_output=True)

if __name__ == "__main__":
    unittest.main()
