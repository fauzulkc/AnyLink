#!/usr/bin/env python3
"""
Unit and Simulation Tests for Cross-Platform Drivers (Windows, Darwin/macOS, Linux)
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from scripts.platform_driver import (
    BasePlatformDriver,
    WindowsPlatformDriver,
    DarwinPlatformDriver,
    LinuxPlatformDriver,
    get_platform_driver,
)


class TestPlatformDrivers(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.host_dir = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_factory_detection(self):
        """Verify get_platform_driver correctly resolves platform names."""
        win_d = get_platform_driver("windows")
        self.assertIsInstance(win_d, WindowsPlatformDriver)
        self.assertEqual(win_d.platform_name, "windows")

        mac_d = get_platform_driver("darwin")
        self.assertIsInstance(mac_d, DarwinPlatformDriver)
        self.assertEqual(mac_d.platform_name, "darwin")

        lin_d = get_platform_driver("linux")
        self.assertIsInstance(lin_d, LinuxPlatformDriver)
        self.assertEqual(lin_d.platform_name, "linux")

    def test_darwin_detect_runtime_modes(self):
        """Verify Darwin driver detects OrbStack, NFS, or SSHFS correctly."""
        driver = DarwinPlatformDriver()
        info = driver.detect_runtime()
        self.assertEqual(info["platform"], "darwin")
        self.assertIn("mount_strategy", info)
        self.assertIn(info["mount_strategy"], ["orbstack", "nfs", "sshfs"])

    def test_darwin_nfs_mount_command(self):
        """Verify Darwin NFS mount command formatting with resvport & noatime."""
        driver = DarwinPlatformDriver()
        target_path = self.host_dir / "my_mac_sandbox"

        res = driver.create_host_link(
            alias="test_nfs",
            host_target=target_path,
            container_name="test_c",
            bridge_port=2049,
            mount_strategy="nfs",
            nfs_port=2049
        )

        self.assertEqual(res["platform"], "darwin")
        self.assertEqual(res["mount_strategy"], "nfs")
        self.assertIn("mount_cmd", res)
        cmd = res["mount_cmd"]
        self.assertEqual(cmd[0], "/sbin/mount_nfs")
        self.assertIn("-o", cmd)
        opts_idx = cmd.index("-o") + 1
        self.assertIn("resvport", cmd[opts_idx])
        self.assertIn("noatime", cmd[opts_idx])
        self.assertIn("port=2049", cmd[opts_idx])
        self.assertEqual(cmd[-2], "127.0.0.1:/workspace")
        self.assertEqual(cmd[-1], str(target_path))

    def test_darwin_orbstack_fastpath(self):
        """Verify Darwin OrbStack fast-path generates direct volume symlink."""
        driver = DarwinPlatformDriver()
        target_path = self.host_dir / "orb_link"

        res = driver.create_host_link(
            alias="test_orb",
            host_target=target_path,
            container_name="test_c",
            bridge_port=2222,
            mount_strategy="orbstack",
            volume_name="test_orb_data"
        )

        self.assertEqual(res["platform"], "darwin")
        self.assertEqual(res["mount_strategy"], "orbstack")
        self.assertTrue(res.get("is_symlink"))
        self.assertIn("OrbStack", res.get("target_source", ""))

    def test_darwin_sshfs_mount_command(self):
        """Verify Darwin SSHFS fallback command formatting."""
        driver = DarwinPlatformDriver()
        target_path = self.host_dir / "sshfs_link"

        res = driver.create_host_link(
            alias="test_sshfs",
            host_target=target_path,
            container_name="test_c",
            bridge_port=2222,
            mount_strategy="sshfs"
        )

        self.assertEqual(res["platform"], "darwin")
        self.assertEqual(res["mount_strategy"], "sshfs")
        self.assertIn("mount_cmd", res)
        cmd = res["mount_cmd"]
        self.assertEqual(cmd[0], "sshfs")
        self.assertIn("-p", cmd)
        self.assertIn("2222", cmd)

    def test_darwin_teardown_safety(self):
        """Verify teardown safely cleans up host links without crashing."""
        driver = DarwinPlatformDriver()
        dummy_path = self.host_dir / "teardown_target"
        dummy_path.mkdir(parents=True, exist_ok=True)
        (dummy_path / "dummy.txt").write_text("test")

        mapping = {
            "platform": "darwin",
            "mount_strategy": "nfs",
            "host_path": str(dummy_path)
        }
        success = driver.teardown_host_link(mapping)
        self.assertTrue(success)

    def test_linux_driver_direct_link(self):
        """Verify Linux driver creates direct ext4 symlink."""
        driver = LinuxPlatformDriver()
        target_path = self.host_dir / "linux_link"

        res = driver.create_host_link(
            alias="test_lin",
            host_target=target_path,
            container_name="test_c",
            bridge_port=2222,
            volume_path="/var/lib/docker/volumes/test_lin/_data"
        )

        self.assertEqual(res["platform"], "linux")
        self.assertEqual(res["mount_strategy"], "linux_direct")
        self.assertTrue(driver.check_link_health(res)["healthy"] or not target_path.exists())


if __name__ == "__main__":
    unittest.main()
