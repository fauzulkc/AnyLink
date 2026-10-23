#!/usr/bin/env python3
"""
Cross-Platform Bridging & Storage Driver Layer for AnyLink & Sandbox Linker

Supports:
- Windows (via WSL 2 + SSHFS + NTFS Directory Junctions / symlinks)
- macOS / Darwin (via OrbStack volume symlinks, native macOS /sbin/mount_nfs, or FUSE-T/SSHFS)
- Linux (via direct ext4 named volume mount & POSIX symlinks)
"""

import os
import sys
import json
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple


class BasePlatformDriver(ABC):
    """Abstract base platform driver for container workspace host-bridging."""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Returns normalized platform name: 'windows', 'darwin', or 'linux'."""
        pass

    @abstractmethod
    def detect_runtime(self) -> Dict[str, Any]:
        """Detects available container runtimes and bridge capabilities."""
        pass

    @abstractmethod
    def create_host_link(
        self,
        alias: str,
        host_target: Path,
        container_name: str,
        bridge_port: int,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Creates a host-accessible path linking to the container's isolated ext4 workspace.
        Returns metadata dict containing link details for registry storage.
        """
        pass

    @abstractmethod
    def teardown_host_link(self, mapping: Dict[str, Any]) -> bool:
        """Safely untethers and unmounts the host-link without destroying container data."""
        pass

    @abstractmethod
    def check_link_health(self, mapping: Dict[str, Any]) -> Dict[str, Any]:
        """Inspects whether the host link and underlying mount are healthy."""
        pass


class WindowsPlatformDriver(BasePlatformDriver):
    """Windows implementation utilizing WSL 2, SSHFS FUSE, and NTFS Directory Junctions."""

    @property
    def platform_name(self) -> str:
        return "windows"

    def detect_runtime(self) -> Dict[str, Any]:
        distros = self.get_wsl_distros()
        has_docker = shutil.which("docker") is not None
        has_wsl = shutil.which("wsl") is not None
        return {
            "platform": "windows",
            "has_wsl": has_wsl,
            "has_docker": has_docker,
            "wsl_distros": distros,
            "default_distro": distros[0] if distros else None,
            "mount_strategy": "wsl_sshfs_junction",
        }

    def get_wsl_distros(self) -> List[str]:
        if shutil.which("wsl") is None:
            return []
        try:
            r = subprocess.run(["wsl", "--list", "--quiet"], capture_output=True, text=True, encoding="utf-16le", timeout=5)
            if r.returncode != 0:
                r = subprocess.run(["wsl", "--list", "--quiet"], capture_output=True, text=True, encoding="utf-8", timeout=5)
            if r.returncode == 0:
                return [line.strip().replace("\x00", "") for line in r.stdout.splitlines() if line.strip() and not line.strip().startswith("Docker Desktop")]
        except Exception:
            pass
        return ["Ubuntu-24.04"]

    def create_host_link(
        self,
        alias: str,
        host_target: Path,
        container_name: str,
        bridge_port: int,
        **kwargs
    ) -> Dict[str, Any]:
        distro = kwargs.get("distro") or (self.get_wsl_distros()[0] if self.get_wsl_distros() else "Ubuntu")
        wsl_home = kwargs.get("wsl_home", f"/home/{os.environ.get('USERNAME', 'user').lower()}")
        wsl_mount_path = f"{wsl_home}/.devlinker-mounts/{alias}"

        normalized_mnt = "/" + f"{wsl_mount_path}/workspace".replace("\\", "/").lstrip("/")
        wsl_unc = f"\\\\wsl.localhost\\{distro}" + normalized_mnt.replace("/", "\\")

        # Create NTFS Directory Symlink / Junction on Windows host
        link_created = False
        target_path = str(host_target)
        try:
            if not host_target.exists():
                os.symlink(wsl_unc, target_path, target_is_directory=True)
                link_created = True
        except Exception:
            # Fallback to direct UNC path if developer mode symlink fails
            target_path = wsl_unc

        return {
            "platform": "windows",
            "mount_strategy": "wsl_sshfs_junction",
            "host_path": target_path,
            "unc_path": wsl_unc,
            "wsl_distro": distro,
            "wsl_mount_path": wsl_mount_path,
            "symlink_created": link_created,
            "bridge_port": bridge_port,
        }

    def teardown_host_link(self, mapping: Dict[str, Any]) -> bool:
        host_path = mapping.get("host_path")
        if host_path and os.path.exists(host_path):
            try:
                if os.path.islink(host_path):
                    os.unlink(host_path)
                elif os.path.isdir(host_path):
                    os.rmdir(host_path)
            except Exception:
                pass
        return True

    def check_link_health(self, mapping: Dict[str, Any]) -> Dict[str, Any]:
        host_path = mapping.get("host_path", "")
        exists = os.path.exists(host_path)
        is_link = os.path.islink(host_path) if exists else False
        return {
            "healthy": exists,
            "is_symlink": is_link,
            "host_path": host_path,
        }


class DarwinPlatformDriver(BasePlatformDriver):
    """
    macOS (Darwin) implementation supporting:
    1. OrbStack native volume symlinking (~/OrbStack/docker/volumes/)
    2. Native kernel NFS mounting (/sbin/mount_nfs -o resvport) with zero kernel extensions
    3. FUSE-T / SSHFS reverse mounting
    """

    @property
    def platform_name(self) -> str:
        return "darwin"

    def detect_runtime(self) -> Dict[str, Any]:
        has_docker = shutil.which("docker") is not None
        has_colima = shutil.which("colima") is not None
        has_orbstack = (Path.home() / "OrbStack").exists() or (Path.home() / ".orbstack").exists()
        has_nfs = Path("/sbin/mount_nfs").exists() or shutil.which("mount_nfs") is not None
        has_sshfs = shutil.which("sshfs") is not None

        strategy = "nfs"
        if has_orbstack:
            strategy = "orbstack"
        elif has_nfs:
            strategy = "nfs"
        elif has_sshfs:
            strategy = "sshfs"

        return {
            "platform": "darwin",
            "has_docker": has_docker,
            "has_colima": has_colima,
            "has_orbstack": has_orbstack,
            "has_nfs": has_nfs,
            "has_sshfs": has_sshfs,
            "mount_strategy": strategy,
        }

    def create_host_link(
        self,
        alias: str,
        host_target: Path,
        container_name: str,
        bridge_port: int,
        **kwargs
    ) -> Dict[str, Any]:
        strategy = kwargs.get("mount_strategy") or self.detect_runtime()["mount_strategy"]
        host_target.parent.mkdir(parents=True, exist_ok=True)
        target_path = str(host_target)

        if strategy == "orbstack":
            # OrbStack Fast-Path: Volumes are directly accessible on macOS
            volume_name = kwargs.get("volume_name", f"{alias}_data")
            orb_vol_path = Path.home() / "OrbStack" / "docker" / "volumes" / volume_name
            if not host_target.exists():
                try:
                    os.symlink(str(orb_vol_path), target_path, target_is_directory=True)
                except Exception:
                    pass
            return {
                "platform": "darwin",
                "mount_strategy": "orbstack",
                "host_path": target_path,
                "target_source": str(orb_vol_path),
                "bridge_port": bridge_port,
                "is_symlink": True,
            }

        elif strategy == "nfs":
            # Native macOS in-kernel NFS mount (/sbin/mount_nfs -o resvport,rw,noatime,nolocks)
            host_target.mkdir(parents=True, exist_ok=True)
            nfs_port = kwargs.get("nfs_port", bridge_port)
            mount_cmd = [
                "/sbin/mount_nfs",
                "-o", f"port={nfs_port},mountport={nfs_port},resvport,rw,noatime,nolocks,locallocks",
                f"127.0.0.1:/workspace",
                target_path,
            ]
            mounted = False
            # If executing on real Darwin, attempt mount
            if sys.platform == "darwin":
                try:
                    r = subprocess.run(mount_cmd, capture_output=True, text=True, timeout=10)
                    mounted = (r.returncode == 0)
                except Exception:
                    pass

            return {
                "platform": "darwin",
                "mount_strategy": "nfs",
                "host_path": target_path,
                "target_source": f"127.0.0.1:{nfs_port}/workspace",
                "mount_cmd": mount_cmd,
                "mounted": mounted,
                "bridge_port": bridge_port,
            }

        else:
            # Fallback SSHFS via FUSE-T or macFUSE
            host_target.mkdir(parents=True, exist_ok=True)
            ssh_key = kwargs.get("ssh_key_path", str(Path.home() / ".ssh" / "id_ed25519"))
            sshfs_cmd = [
                "sshfs",
                "-p", str(bridge_port),
                f"devlinker@127.0.0.1:/workspace",
                target_path,
                "-o", f"IdentityFile={ssh_key},StrictHostKeyChecking=no,UserKnownHostsFile=/dev/null,reconnect,defer_permissions",
            ]
            mounted = False
            if sys.platform == "darwin" and shutil.which("sshfs"):
                try:
                    r = subprocess.run(sshfs_cmd, capture_output=True, text=True, timeout=10)
                    mounted = (r.returncode == 0)
                except Exception:
                    pass

            return {
                "platform": "darwin",
                "mount_strategy": "sshfs",
                "host_path": target_path,
                "target_source": f"127.0.0.1:{bridge_port}:/workspace",
                "mount_cmd": sshfs_cmd,
                "mounted": mounted,
                "bridge_port": bridge_port,
            }

    def teardown_host_link(self, mapping: Dict[str, Any]) -> bool:
        host_path = mapping.get("host_path")
        strategy = mapping.get("mount_strategy", "nfs")
        if not host_path or not os.path.exists(host_path):
            return True

        if strategy == "orbstack" or os.path.islink(host_path):
            try:
                os.unlink(host_path)
            except Exception:
                pass
            return True

        # For NFS / SSHFS mounts, unmount cleanly
        if sys.platform == "darwin":
            subprocess.run(["/sbin/umount", host_path], capture_output=True, timeout=5)
            # Fallback force unmount if busy
            if os.path.exists(host_path):
                subprocess.run(["diskutil", "unmount", "force", host_path], capture_output=True, timeout=5)

        if os.path.exists(host_path):
            try:
                shutil.rmtree(host_path, ignore_errors=True)
            except Exception:
                pass
        return True

    def check_link_health(self, mapping: Dict[str, Any]) -> Dict[str, Any]:
        host_path = mapping.get("host_path", "")
        exists = os.path.exists(host_path)
        return {
            "healthy": exists,
            "platform": "darwin",
            "mount_strategy": mapping.get("mount_strategy"),
            "host_path": host_path,
        }


class LinuxPlatformDriver(BasePlatformDriver):
    """Native Linux implementation using direct POSIX ext4 symlinks & volume mounts."""

    @property
    def platform_name(self) -> str:
        return "linux"

    def detect_runtime(self) -> Dict[str, Any]:
        has_docker = shutil.which("docker") is not None
        has_podman = shutil.which("podman") is not None
        return {
            "platform": "linux",
            "has_docker": has_docker,
            "has_podman": has_podman,
            "mount_strategy": "linux_direct",
        }

    def create_host_link(
        self,
        alias: str,
        host_target: Path,
        container_name: str,
        bridge_port: int,
        **kwargs
    ) -> Dict[str, Any]:
        host_target.parent.mkdir(parents=True, exist_ok=True)
        target_path = str(host_target)
        # On Linux, target volume or container mount is direct
        vol_path = kwargs.get("volume_path", f"/var/lib/docker/volumes/{alias}_data/_data")
        if not host_target.exists():
            try:
                os.symlink(vol_path, target_path, target_is_directory=True)
            except Exception:
                pass
        return {
            "platform": "linux",
            "mount_strategy": "linux_direct",
            "host_path": target_path,
            "target_source": vol_path,
            "bridge_port": bridge_port,
        }

    def teardown_host_link(self, mapping: Dict[str, Any]) -> bool:
        host_path = mapping.get("host_path")
        if host_path and os.path.exists(host_path):
            try:
                if os.path.islink(host_path):
                    os.unlink(host_path)
                elif os.path.isdir(host_path):
                    os.rmdir(host_path)
            except Exception:
                pass
        return True

    def check_link_health(self, mapping: Dict[str, Any]) -> Dict[str, Any]:
        host_path = mapping.get("host_path", "")
        return {
            "healthy": os.path.exists(host_path),
            "platform": "linux",
            "host_path": host_path,
        }


def get_platform_driver(forced_platform: Optional[str] = None) -> BasePlatformDriver:
    """
    Factory function returning the driver corresponding to the current host OS
    or an explicitly forced platform string ('windows', 'darwin', 'linux').
    """
    plat = (forced_platform or sys.platform).lower()
    if plat.startswith("win"):
        return WindowsPlatformDriver()
    elif plat.startswith("darwin"):
        return DarwinPlatformDriver()
    elif plat.startswith("linux"):
        return LinuxPlatformDriver()
    else:
        # Default fallback to Linux
        return LinuxPlatformDriver()
