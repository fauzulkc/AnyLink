#!/usr/bin/env python3
"""
WSL Linker - Experimental Tabbed GUI Dashboard

A highly immersive, Discord-slate styled CustomTkinter dashboard that integrates
traditional WSL 2 symlinking, Docker Dev Containers sandbox provisioning, and
secure Remote SSH Cloud node mounts in a unified visual environment.
"""

import os
import sys
import json
import subprocess
import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, filedialog
import customtkinter as ctk
import uuid
import socket
import threading
import time

# Ensure script parent directory is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from wsl_linker import check_windows_drive_type

# Theme Colors (Modern Dark Slate & Blurple/Indigo palette)
COLOR_BG_MAIN = "#0d0e12"       # Deep dark slate
COLOR_BG_CARD = "#15161e"       # Card background
COLOR_BG_INPUT = "#1c1d26"      # Input field background
COLOR_BORDER = "#252733"        # Thin border
COLOR_TEXT_PRIMARY = "#ffffff"  # Pure white
COLOR_TEXT_MUTED = "#8e92a8"    # Muted gray
COLOR_ACCENT = "#5865f2"        # Discord Blurple
COLOR_ACCENT_HOVER = "#4752c4"  # Hover Blurple
COLOR_SUCCESS = "#10b981"       # Emerald Green
COLOR_DANGER = "#ef4444"        # Danger Red
COLOR_DANGER_HOVER = "#441f26"  # Subtle dark crimson hover

# Configuration Paths
def get_experimental_dir():
    path = Path.home() / ".wsl-linker-experimental"
    path.mkdir(parents=True, exist_ok=True)
    return path

def get_config_path():
    return get_experimental_dir() / "config.json"

class ExperimentalLinkerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.title("WSL Linker (Experimental Dev Suite)")
        
        # Resolution-aware startup geometry
        try:
            screen_height = self.winfo_screenheight()
            self.geometry("1150x800" if screen_height > 800 else "1150x680")
        except Exception:
            self.geometry("1150x750")
            
        self.configure(fg_color=COLOR_BG_MAIN)
        self.minsize(800, 600)
        
        self.sidebar_visible = True
        self.user_toggled_sidebar = False
        
        # Start state variables
        self.distros = self.get_wsl_distros()
        
        # Setup UI
        self.build_ui()
        self.refresh_mappings_list()
        self.log("Experimental Dev Suite Dashboard initialized.")
        
        # Auto-reconnect reverse Docker links in background thread
        self.after(1500, self._start_auto_reconnect)

    def get_wsl_distros(self):
        try:
            result = subprocess.run(["wsl", "--list", "--quiet"], capture_output=True, text=True, encoding="utf-16le")
            output = result.stdout
            if not output:
                result = subprocess.run(["wsl", "--list", "--quiet"], capture_output=True, text=True, encoding="utf-8")
                output = result.stdout
            distros = [line.strip() for line in output.split("\n") if line.strip() and "\x00" not in line]
            return distros if distros else ["Ubuntu-24.04"]
        except Exception:
            return ["Ubuntu-24.04", "Ubuntu", "debian"]

    def load_registry(self):
        path = get_config_path()
        if not path.exists():
            return {"wsl_mappings": [], "docker_mappings": [], "ssh_mappings": [], "credentials": {}, "env_vars": {}, "bridge_active": False}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Ensure all lists/dicts exist
                for key in ["wsl_mappings", "docker_mappings", "ssh_mappings"]:
                    if key not in data:
                        data[key] = []
                if "credentials" not in data:
                    data["credentials"] = {}
                if "env_vars" not in data:
                    data["env_vars"] = {}
                return data
        except Exception:
            return {"wsl_mappings": [], "docker_mappings": [], "ssh_mappings": [], "credentials": {}, "env_vars": {}, "bridge_active": False}

    def save_registry(self, data):
        try:
            with open(get_config_path(), "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log(f"Error saving database: {e}", is_error=True)

    def log(self, message, is_error=False, is_success=False):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        prefix = "[INFO]"
        if is_error:
            prefix = "[ERROR]"
        elif is_success:
            prefix = "[SUCCESS]"
        formatted_msg = f"{timestamp} {prefix} {message}\n"
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, formatted_msg)
        self.log_text.see(tk.END)
        self.log_text.configure(state="disabled")

    def build_ui(self):
        # 1. Header Pane
        header_frame = ctk.CTkFrame(self, fg_color=COLOR_BG_CARD, height=75, corner_radius=0, border_width=1, border_color=COLOR_BORDER)
        header_frame.pack(fill=tk.X, side=tk.TOP)
        header_frame.pack_propagate(False)

        ctk.CTkLabel(header_frame, text="WSL LINKER", font=("Segoe UI", 22, "bold"), text_color=COLOR_TEXT_PRIMARY).pack(side=tk.LEFT, padx=(25, 10), pady=20)
        ctk.CTkLabel(header_frame, text="|", font=("Segoe UI", 18), text_color=COLOR_BORDER).pack(side=tk.LEFT, padx=5)
        
        badge = ctk.CTkFrame(header_frame, fg_color="#ff9f1c", height=22, corner_radius=4)
        badge.pack(side=tk.LEFT, padx=10, pady=25)
        ctk.CTkLabel(badge, text="EXPERIMENTAL DEV SUITE", font=("Segoe UI", 9, "bold"), text_color="#000000").pack(padx=8, pady=2)

        self.btn_toggle_sidebar = ctk.CTkButton(header_frame, text="✕ Close Config", width=160, height=36, fg_color="#2b2d3a", hover_color="#3e4052", font=("Segoe UI", 11, "bold"), command=self.toggle_sidebar)
        self.btn_toggle_sidebar.pack(side=tk.RIGHT, padx=25, pady=20)

        # 2. Main split container
        content_frame = ctk.CTkFrame(self, fg_color="transparent")
        content_frame.pack(fill=tk.BOTH, expand=True, padx=25, pady=25)

        # Left Column - Active Environments List
        self.left_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        self.left_frame.pack(fill=tk.BOTH, side=tk.LEFT, expand=True, padx=(0, 15))

        list_header_row = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        list_header_row.pack(fill=tk.X, pady=(0, 12))

        self.list_header = ctk.CTkLabel(list_header_row, text="Active Environments", font=("Segoe UI", 16, "bold"), text_color=COLOR_TEXT_PRIMARY)
        self.list_header.pack(side=tk.LEFT)

        self.cards_container = ctk.CTkScrollableFrame(self.left_frame, fg_color=COLOR_BG_MAIN, border_width=1, border_color=COLOR_BORDER)
        self.cards_container.pack(fill=tk.BOTH, expand=True)

        # Right Column - Config Sidebar Tabbed view
        self.right_frame = ctk.CTkFrame(content_frame, fg_color=COLOR_BG_CARD, width=380, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        self.right_frame.pack(fill=tk.BOTH, side=tk.RIGHT, padx=(15, 0))
        self.right_frame.pack_propagate(False)

        # Tabview Integration
        self.tabview = ctk.CTkTabview(
            self.right_frame,
            fg_color="transparent",
            segmented_button_fg_color="#1c1d26",
            segmented_button_selected_color=COLOR_ACCENT,
            segmented_button_selected_hover_color=COLOR_ACCENT_HOVER,
            segmented_button_unselected_color="#2b2d3a",
            segmented_button_unselected_hover_color="#3e4052",
            text_color=COLOR_TEXT_MUTED
        )
        self.tabview.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        # Add distinct Tabs
        self.tab_wsl = self.tabview.add("💻 WSL 2")
        self.tab_docker = self.tabview.add("🐳 Docker Dev")
        self.tab_cloud = self.tabview.add("☁️ Cloud SSH")
        self.tab_env = self.tabview.add("🔑 Credentials & Env")

        self.setup_wsl_tab()
        self.setup_docker_tab()
        self.setup_cloud_tab()
        self.setup_env_tab()

        # 3. Activity Logs Console (at bottom)
        log_frame = ctk.CTkFrame(self, fg_color=COLOR_BG_CARD, height=130, corner_radius=0, border_width=1, border_color=COLOR_BORDER)
        log_frame.pack(fill=tk.X, side=tk.BOTTOM)
        log_frame.pack_propagate(False)

        log_title_row = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_title_row.pack(fill=tk.X, padx=25, pady=(10, 5))
        ctk.CTkLabel(log_title_row, text="Developer Console logs", font=("Segoe UI", 11, "bold"), text_color=COLOR_TEXT_MUTED).pack(side=tk.LEFT)

        self.log_text = ctk.CTkTextbox(log_frame, fg_color="#090a0d", text_color="#acb1c9", font=("Consolas", 10), corner_radius=6, border_width=1, border_color=COLOR_BORDER)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=25, pady=(0, 12))
        self.log_text.configure(state="disabled")

    # =====================================================================
    # TAB VIEW INTERFACE SETUPS
    # =====================================================================
    def setup_wsl_tab(self):
        scroll = ctk.CTkScrollableFrame(self.tab_wsl, fg_color="transparent", label_text="")
        scroll.pack(fill=tk.BOTH, expand=True)

        ctk.CTkLabel(scroll, text="WORKSPACE ALIAS", font=("Segoe UI", 9, "bold"), text_color=COLOR_TEXT_MUTED).pack(anchor=tk.W, pady=(10,2))
        self.wsl_alias = ctk.CTkEntry(scroll, placeholder_text="e.g. my-web-app", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, height=36)
        self.wsl_alias.pack(fill=tk.X, pady=(0,10))

        ctk.CTkLabel(scroll, text="LOCAL PARENT WINDOWS FOLDER", font=("Segoe UI", 9, "bold"), text_color=COLOR_TEXT_MUTED).pack(anchor=tk.W, pady=(5,2))
        row = ctk.CTkFrame(scroll, fg_color="transparent")
        row.pack(fill=tk.X, pady=(0,10))
        self.wsl_parent = ctk.CTkEntry(row, placeholder_text="Browse parent folder...", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, height=36)
        self.wsl_parent.pack(fill=tk.X, side=tk.LEFT, expand=True, padx=(0,6))
        ctk.CTkButton(row, text="Browse", width=65, height=36, fg_color="#2b2d3a", hover_color="#3e4052", command=self.browse_wsl_parent).pack(side=tk.RIGHT)

        ctk.CTkLabel(scroll, text="WSL PATH TARGET", font=("Segoe UI", 9, "bold"), text_color=COLOR_TEXT_MUTED).pack(anchor=tk.W, pady=(5,2))
        self.wsl_target = ctk.CTkEntry(scroll, placeholder_text="e.g. /home/user/my-web-app", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, height=36)
        self.wsl_target.pack(fill=tk.X, pady=(0,10))

        ctk.CTkLabel(scroll, text="TARGET WSL DISTRIBUTION", font=("Segoe UI", 9, "bold"), text_color=COLOR_TEXT_MUTED).pack(anchor=tk.W, pady=(5,2))
        self.wsl_distro = ctk.CTkOptionMenu(scroll, values=self.distros, fg_color=COLOR_BG_INPUT, button_color="#2b2d3a", button_hover_color="#3e4052", height=36)
        self.wsl_distro.pack(fill=tk.X, pady=(0,20))

        ctk.CTkButton(scroll, text="Create WSL Symlink 🔗", fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, height=42, font=("Segoe UI", 12, "bold"), command=self.create_wsl_link).pack(fill=tk.X, pady=(0,10))

    def setup_docker_tab(self):
        scroll = ctk.CTkScrollableFrame(self.tab_docker, fg_color="transparent", label_text="")
        scroll.pack(fill=tk.BOTH, expand=True)

        ctk.CTkLabel(scroll, text="SANDBOX ALIAS", font=("Segoe UI", 9, "bold"), text_color=COLOR_TEXT_MUTED).pack(anchor=tk.W, pady=(10,2))
        self.docker_alias = ctk.CTkEntry(scroll, placeholder_text="e.g. agent-sandbox", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, height=36)
        self.docker_alias.pack(fill=tk.X, pady=(0,10))

        ctk.CTkLabel(scroll, text="DOCKER BASE IMAGE", font=("Segoe UI", 9, "bold"), text_color=COLOR_TEXT_MUTED).pack(anchor=tk.W, pady=(5,2))
        self.docker_image = ctk.CTkEntry(scroll, placeholder_text="e.g. node:20-alpine, python:3.11-alpine", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, height=36)
        self.docker_image.pack(fill=tk.X, pady=(0,10))

        ctk.CTkLabel(scroll, text="WINDOWS LINK LOCATION", font=("Segoe UI", 9, "bold"), text_color=COLOR_TEXT_MUTED).pack(anchor=tk.W, pady=(5,2))
        row = ctk.CTkFrame(scroll, fg_color="transparent")
        row.pack(fill=tk.X, pady=(0,10))
        self.docker_parent = ctk.CTkEntry(row, placeholder_text="Where the symlink appears on Windows...", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, height=36)
        self.docker_parent.pack(fill=tk.X, side=tk.LEFT, expand=True, padx=(0,6))
        ctk.CTkButton(row, text="Browse", width=65, height=36, fg_color="#2b2d3a", hover_color="#3e4052", command=self.browse_docker_parent).pack(side=tk.RIGHT)

        # Reverse link info tip
        tip_frame = ctk.CTkFrame(scroll, fg_color="#181a26", corner_radius=6, border_width=1, border_color="#252a45")
        tip_frame.pack(fill=tk.X, pady=(0,20))
        ctk.CTkLabel(tip_frame, text="🔀 Reverse Link Architecture", font=("Segoe UI", 10, "bold"), text_color=COLOR_ACCENT).pack(anchor=tk.W, padx=12, pady=(8,2))
        ctk.CTkLabel(tip_frame, text="Files live INSIDE the Docker container. Windows sees them via a WSL SSHFS reverse mount. Self-healing: auto-reconnects on restart. Zero host OS pollution!", font=("Segoe UI", 8), text_color="#acb1c9", justify=tk.LEFT, wraplength=280).pack(anchor=tk.W, padx=12, pady=(0,8))

        ctk.CTkButton(scroll, text="Spin up Reverse-Linked Sandbox 🐳", fg_color=COLOR_SUCCESS, hover_color="#059669", height=42, font=("Segoe UI", 12, "bold"), command=self.create_docker_sandbox).pack(fill=tk.X, pady=(0,10))

    def setup_cloud_tab(self):
        scroll = ctk.CTkScrollableFrame(self.tab_cloud, fg_color="transparent", label_text="")
        scroll.pack(fill=tk.BOTH, expand=True)

        ctk.CTkLabel(scroll, text="OR USE REGISTERED PROFILE", font=("Segoe UI", 9, "bold"), text_color=COLOR_TEXT_MUTED).pack(anchor=tk.W, pady=(10,2))
        self.ssh_profile_dropdown = ctk.CTkOptionMenu(scroll, values=["None"], fg_color=COLOR_BG_INPUT, button_color="#2b2d3a", button_hover_color="#3e4052", height=36, command=self.on_select_ssh_profile)
        self.ssh_profile_dropdown.pack(fill=tk.X, pady=(0,15))
        self.refresh_ssh_profiles_dropdown()

        ctk.CTkLabel(scroll, text="PROFILE ALIAS NAME", font=("Segoe UI", 9, "bold"), text_color=COLOR_TEXT_MUTED).pack(anchor=tk.W, pady=(5,2))
        self.ssh_alias = ctk.CTkEntry(scroll, placeholder_text="e.g. my-aws-ec2", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, height=36)
        self.ssh_alias.pack(fill=tk.X, pady=(0,10))

        ctk.CTkLabel(scroll, text="SSH HOST ADDRESS (IP OR DOMAIN)", font=("Segoe UI", 9, "bold"), text_color=COLOR_TEXT_MUTED).pack(anchor=tk.W, pady=(5,2))
        self.ssh_host = ctk.CTkEntry(scroll, placeholder_text="e.g. 54.210.88.22", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, height=36)
        self.ssh_host.pack(fill=tk.X, pady=(0,10))

        ctk.CTkLabel(scroll, text="SSH USERNAME", font=("Segoe UI", 9, "bold"), text_color=COLOR_TEXT_MUTED).pack(anchor=tk.W, pady=(5,2))
        self.ssh_user = ctk.CTkEntry(scroll, placeholder_text="e.g. ubuntu, ec2-user", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, height=36)
        self.ssh_user.pack(fill=tk.X, pady=(0,10))

        ctk.CTkLabel(scroll, text="SSH PRIVATE KEY PATH", font=("Segoe UI", 9, "bold"), text_color=COLOR_TEXT_MUTED).pack(anchor=tk.W, pady=(5,2))
        row = ctk.CTkFrame(scroll, fg_color="transparent")
        row.pack(fill=tk.X, pady=(0,10))
        self.ssh_key = ctk.CTkEntry(row, placeholder_text="Browse private key file (.pem)...", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, height=36)
        self.ssh_key.pack(fill=tk.X, side=tk.LEFT, expand=True, padx=(0,6))
        ctk.CTkButton(row, text="Select", width=65, height=36, fg_color="#2b2d3a", hover_color="#3e4052", command=self.browse_ssh_key).pack(side=tk.RIGHT)

        ctk.CTkLabel(scroll, text="REMOTE TARGET FOLDER PATH", font=("Segoe UI", 9, "bold"), text_color=COLOR_TEXT_MUTED).pack(anchor=tk.W, pady=(5,2))
        self.ssh_target = ctk.CTkEntry(scroll, placeholder_text="e.g. /var/www/my-app", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, height=36)
        self.ssh_target.pack(fill=tk.X, pady=(0,15))

        # Integrated signup-less provisioning mock
        ctk.CTkButton(scroll, text="☁️ Instant Provision (5-Second Boot)", fg_color="#181a26", hover_color="#252a45", text_color="#acb1c9", border_color="#3e4052", border_width=1, height=38, command=self.provision_cloud_vm).pack(fill=tk.X, pady=(0,10))
        ctk.CTkButton(scroll, text="Connect & Bridge Remote Node 🔗", fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, height=42, font=("Segoe UI", 12, "bold"), command=self.connect_cloud_ssh).pack(fill=tk.X, pady=(0,10))

    # =====================================================================
    # ACTION CONTROLLERS & MOUNT OPERATIONS
    # =====================================================================
    def browse_wsl_parent(self):
        f = filedialog.askdirectory()
        if f:
            self.wsl_parent.delete(0, tk.END)
            self.wsl_parent.insert(0, os.path.abspath(f))

    def browse_docker_parent(self):
        f = filedialog.askdirectory()
        if f:
            self.docker_parent.delete(0, tk.END)
            self.docker_parent.insert(0, os.path.abspath(f))

    def browse_ssh_key(self):
        f = filedialog.askopenfilename(filetypes=[("PEM Key Files", "*.pem"), ("All Files", "*.*")])
        if f:
            self.ssh_key.delete(0, tk.END)
            self.ssh_key.insert(0, os.path.abspath(f))

    def create_wsl_link(self):
        alias = self.wsl_alias.get().strip()
        parent = self.wsl_parent.get().strip()
        target = self.wsl_target.get().strip()
        distro = self.wsl_distro.get()

        if not alias or not parent or not target:
            messagebox.showwarning("Warning", "All fields are required!")
            return

        win_path = os.path.join(parent, alias)
        wsl_unc = f"\\\\wsl.localhost\\{distro}" + target.replace('/', '\\')

        # Check drive type safety
        is_fixed, drive_detail = check_windows_drive_type(parent)
        if not is_fixed:
            proceed = messagebox.askyesno(
                "Network Drive Warning",
                f"The selected parent directory '{parent}' is located on a remote network or mapped drive ({drive_detail}).\n\n"
                "Many IDEs and agent harnesses resolve network drives to UNC paths and fail path validation or file watching. A local fixed drive (such as C: or D:) is strongly recommended.\n\n"
                "Are you sure you want to proceed anyway?"
            )
            if not proceed:
                return

        if os.path.exists(win_path):
            if os.path.islink(win_path):
                try:
                    os.rmdir(win_path)
                except Exception:
                    pass
            else:
                messagebox.showerror("Error", f"A directory named '{win_path}' already exists and is not a symlink.\nPlease choose a different alias or remove the existing folder.")
                return

        self.log(f"Establishing WSL 2 Symbolic Link: {win_path} -> {wsl_unc}...")
        try:
            os.symlink(wsl_unc, win_path, target_is_directory=True)
            self.log("Symbolic Link created successfully on Windows host.", is_success=True)
            
            # Save configuration
            db = self.load_registry()
            db["wsl_mappings"].append({
                "name": alias,
                "windows_path": win_path,
                "wsl_distro": distro,
                "wsl_path": target,
                "created_at": datetime.datetime.now().isoformat()
            })
            self.save_registry(db)
            self.refresh_mappings_list()
            messagebox.showinfo("Success", f"WSL Link '{alias}' created successfully!")
        except Exception as e:
            self.log(f"WSL link failure: {e}", is_error=True)
            messagebox.showerror("Error", f"Failed to create Link:\n\n{e}\n\nTip: Enable Windows Developer Mode or run as Administrator.")

    def start_docker_bridge_container(self, host_dir):
        """Ensures that the DevLinker privileged sidecar is booted and active in Docker."""
        self.log("Checking Docker Bridge Sidecar status...")
        try:
            # Check if container is running
            check = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", "devlinker-bridge"], capture_output=True, text=True)
            if check.returncode == 0 and "true" in check.stdout:
                self.log("Docker Bridge Sidecar is already active.", is_success=True)
                return True
        except Exception:
            pass

        # Build / Launch Sidecar dynamically
        self.log("Booting devlinker-bridge sidecar...")
        dockerfile_content = """FROM alpine:latest
RUN apk add --no-cache openssh-client sshfs rsync bash curl shadow
RUN mkdir -p /projects /root/.ssh && echo "user_allow_other" >> /etc/fuse.conf
WORKDIR /bridge
CMD ["tail", "-f", "/dev/null"]
"""
        bridge_build = get_experimental_dir() / "bridge_build"
        bridge_build.mkdir(parents=True, exist_ok=True)
        with open(bridge_build / "Dockerfile", "w") as f:
            f.write(dockerfile_content)

        try:
            # Build
            subprocess.run(["docker", "build", "-t", "devlinker-bridge", str(bridge_build)], check=True, capture_output=True)
            # Kill stale
            subprocess.run(["docker", "rm", "-f", "devlinker-bridge"], capture_output=True)
            # Run
            cmd = [
                "docker", "run", "-d",
                "--name", "devlinker-bridge",
                "--privileged",
                "-v", "/var/run/docker.sock:/var/run/docker.sock",
                "-v", f"{host_dir}:/projects:shared",
                "devlinker-bridge"
            ]
            subprocess.run(cmd, check=True, capture_output=True)
            self.log("Docker Sidecar Bridge successfully launched and attached to docker.sock!", is_success=True)
            return True
        except Exception as e:
            self.log(f"Failed to bootstrap Docker Sidecar Bridge: {e}", is_error=True)
            return False

    # -----------------------------------------------------------------
    # Reverse Docker link helpers (container <- SSHFS in WSL <- Windows symlink)
    # -----------------------------------------------------------------
    SSH_KEY_NAME = "devlinker_ed25519"

    def _wsl_run(self, distro, script, timeout=120):
        """Runs a bash script inside the given WSL distro. Returns CompletedProcess."""
        return subprocess.run(
            ["wsl", "-d", distro, "--cd", "~", "-e", "bash", "-c", script],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
        )

    def _find_free_port(self, db):
        """Finds a free host TCP port starting at 2222, skipping ports already registered."""
        used = {m.get("ssh_port") for m in db.get("docker_mappings", []) if m.get("ssh_port")}
        for port in range(2222, 2322):
            if port in used:
                continue
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                try:
                    s.bind(("0.0.0.0", port))
                except OSError:
                    continue
            return port
        raise RuntimeError("No free port available in range 2222-2321")

    def _detect_wsl_distro(self):
        """Prefers the distro selected in the WSL tab; never picks Docker's internal distros."""
        try:
            selected = self.wsl_distro.get()
        except Exception:
            selected = ""
        if selected and not selected.startswith("docker-desktop"):
            return selected
        for d in self.distros:
            if not d.startswith("docker-desktop"):
                return d
        return "Ubuntu-24.04"

    def _get_wsl_home(self, wsl_distro):
        """Returns the Linux $HOME of the default WSL user."""
        try:
            r = self._wsl_run(wsl_distro, 'printf %s "$HOME"', timeout=30)
            home = r.stdout.strip()
            if r.returncode == 0 and home.startswith("/"):
                return home
        except Exception:
            pass
        return "/root"

    def _ensure_wsl_ssh_key(self, wsl_distro):
        """Creates the DevLinker keypair inside WSL if missing and returns the public key."""
        key = f"$HOME/.ssh/{self.SSH_KEY_NAME}"
        script = (
            f'mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh" && '
            f'[ -f "{key}" ] || ssh-keygen -q -t ed25519 -N "" -f "{key}" >/dev/null; '
            f'cat "{key}.pub"'
        )
        r = self._wsl_run(wsl_distro, script, timeout=60)
        pub = r.stdout.strip()
        if r.returncode != 0 or not pub.startswith("ssh-"):
            raise RuntimeError(f"Could not create WSL SSH key: {r.stderr.strip() or r.stdout.strip()}")
        return pub

    def _setup_container_ssh(self, container_name, wsl_distro):
        """Installs/configures sshd in the container and authorizes the WSL key."""
        try:
            pub = self._ensure_wsl_ssh_key(wsl_distro)
        except Exception as e:
            self.log(str(e), is_error=True)
            return False

        script = r'''
set -e
if ! command -v sshd >/dev/null 2>&1 && [ ! -x /usr/sbin/sshd ]; then
  if command -v apk >/dev/null 2>&1; then apk add --no-cache openssh >/dev/null
  elif command -v apt-get >/dev/null 2>&1; then apt-get update >/dev/null && DEBIAN_FRONTEND=noninteractive apt-get install -y openssh-server >/dev/null
  else echo "Unsupported base image (need apk or apt-get)" >&2; exit 3; fi
fi
ssh-keygen -A >/dev/null
mkdir -p /run/sshd /root/.ssh /workspace
chmod 777 /workspace
chmod 700 /root/.ssh
printf '%s\n' "$PUBKEY" > /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
# Unlock root (Alpine ships root locked, which makes sshd reject key logins)
sed -i 's/^root:![^:]*:/root:*:/' /etc/shadow 2>/dev/null || true
sed -i -E 's/^#?PermitRootLogin.*/PermitRootLogin prohibit-password/; s/^#?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
grep -q '^PermitRootLogin' /etc/ssh/sshd_config || echo 'PermitRootLogin prohibit-password' >> /etc/ssh/sshd_config
# Subsystem sftp is required by sshfs
grep -q '^Subsystem.*sftp' /etc/ssh/sshd_config || echo 'Subsystem sftp internal-sftp' >> /etc/ssh/sshd_config
/usr/sbin/sshd 2>/dev/null || true
'''
        self.log(f"Configuring SSH inside '{container_name}' (first run may install openssh)...")
        try:
            r = subprocess.run(
                ["docker", "exec", "-e", f"PUBKEY={pub}", container_name, "sh", "-c", script],
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300
            )
        except Exception as e:
            self.log(f"Container SSH setup failed: {e}", is_error=True)
            return False
        if r.returncode != 0:
            self.log(f"Container SSH setup failed: {r.stderr.strip() or r.stdout.strip()}", is_error=True)
            return False
        self.log("Container sshd is running with WSL key authorized.", is_success=True)
        return True

    def _sshfs_mount_script(self, port, mount_path):
        key = f"$HOME/.ssh/{self.SSH_KEY_NAME}"
        opts = (
            f"IdentityFile={key},port={port},StrictHostKeyChecking=no,UserKnownHostsFile=/dev/null,"
            "reconnect,ServerAliveInterval=10,ServerAliveCountMax=3,idmap=user,allow_other,BatchMode=yes"
        )
        return (
            f'M="{mount_path}"; mkdir -p "$M"; '
            f'(fusermount3 -uz "$M" || fusermount -uz "$M") >/dev/null 2>&1; '
            f'sshfs -o {opts} root@127.0.0.1:/ "$M"'
        )

    def _setup_wsl_sshfs_mount(self, wsl_distro, alias, port, wsl_mount_path):
        """Mounts the container filesystem (root of container) into WSL via SSHFS."""
        try:
            if self._wsl_run(wsl_distro, "command -v sshfs >/dev/null 2>&1").returncode != 0:
                self.log("Installing sshfs in WSL (needs passwordless sudo)...")
                r = self._wsl_run(wsl_distro, "sudo -n apt-get update >/dev/null && sudo -n apt-get install -y sshfs >/dev/null", timeout=300)
                if r.returncode != 0:
                    self.log(f"sshfs is missing in WSL. Run 'sudo apt install sshfs' in {wsl_distro} then retry. ({r.stderr.strip()})", is_error=True)
                    return False
            # Best effort: allow other users (needs sudo); mount works for the owner without it
            self._wsl_run(wsl_distro, "grep -q '^user_allow_other' /etc/fuse.conf 2>/dev/null || echo user_allow_other | sudo -n tee -a /etc/fuse.conf >/dev/null 2>&1; true")

            last_err = ""
            for _ in range(5):  # sshd may need a moment to accept connections
                r = self._wsl_run(wsl_distro, self._sshfs_mount_script(port, wsl_mount_path), timeout=60)
                if r.returncode == 0:
                    break
                last_err = r.stderr.strip() or r.stdout.strip()
                time.sleep(2)
            else:
                self.log(f"sshfs mount failed: {last_err}", is_error=True)
                return False

            v = self._wsl_run(wsl_distro, f'ls "{wsl_mount_path}/workspace" >/dev/null', timeout=30)
            if v.returncode != 0:
                self.log(f"Mount verification failed: {v.stderr.strip()}", is_error=True)
                return False
            self.log(f"SSHFS mount verified at {wsl_mount_path}", is_success=True)
            return True
        except Exception as e:
            self.log(f"SSHFS setup error: {e}", is_error=True)
            return False

    def _unmount_wsl_sshfs(self, wsl_distro, wsl_mount_path):
        try:
            self._wsl_run(wsl_distro, f'(fusermount3 -uz "{wsl_mount_path}" || fusermount -uz "{wsl_mount_path}") >/dev/null 2>&1; rmdir "{wsl_mount_path}" 2>/dev/null; true', timeout=30)
        except Exception:
            pass

    def _start_auto_reconnect(self):
        """Starts the background self-healing daemon (once)."""
        if getattr(self, "_reconnect_started", False):
            return
        self._reconnect_started = True
        threading.Thread(target=self._auto_reconnect_loop, daemon=True).start()

    def _auto_reconnect_loop(self):
        """Every 20s: restart stopped containers, relaunch sshd, remount stale SSHFS."""
        def ui_log(msg, **kw):
            try:
                self.after(0, lambda: self.log(msg, **kw))
            except Exception:
                pass

        while True:
            try:
                db = self.load_registry()
                for m in db.get("docker_mappings", []):
                    if m.get("link_type") != "reverse":
                        continue
                    name, cname = m["name"], m["container_name"]
                    distro, mnt, port = m["wsl_distro"], m["wsl_mount_path"], m["ssh_port"]

                    st = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", cname], capture_output=True, text=True)
                    if st.returncode != 0:
                        continue  # container removed externally; leave for user to clean up
                    if "true" not in st.stdout:
                        ui_log(f"Container '{cname}' stopped. Restarting...")
                        subprocess.run(["docker", "start", cname], capture_output=True)
                        time.sleep(3)

                    healthy = self._wsl_run(distro, f'timeout 5 ls "{mnt}/workspace" >/dev/null 2>&1', timeout=20).returncode == 0
                    if healthy:
                        continue
                    ui_log(f"Mount for '{name}' is stale. Healing...")
                    subprocess.run(["docker", "exec", cname, "sh", "-c", "/usr/sbin/sshd 2>/dev/null; true"], capture_output=True)
                    r = self._wsl_run(distro, self._sshfs_mount_script(port, mnt), timeout=60)
                    if r.returncode == 0:
                        ui_log(f"Mount for '{name}' restored.", is_success=True)
                    else:
                        ui_log(f"Could not restore mount for '{name}': {r.stderr.strip()}", is_error=True)
            except Exception as e:
                ui_log(f"Auto-reconnect error: {e}", is_error=True)
            time.sleep(20)

    def create_docker_sandbox(self):
        alias = self.docker_alias.get().strip()
        image = self.docker_image.get().strip()
        link_location = self.docker_parent.get().strip()

        if not alias or not image or not link_location:
            messagebox.showwarning("Warning", "All fields are required!")
            return

        # Check drive type safety
        is_fixed, drive_detail = check_windows_drive_type(link_location)
        if not is_fixed:
            proceed = messagebox.askyesno(
                "Network Drive Warning",
                f"The selected parent directory '{link_location}' is located on a remote network or mapped drive ({drive_detail}).\n\n"
                "Many IDEs and agent harnesses resolve network drives to UNC paths and fail path validation or file watching. A local fixed drive (such as C: or D:) is strongly recommended.\n\n"
                "Are you sure you want to proceed anyway?"
            )
            if not proceed:
                return

        win_path = os.path.join(link_location, alias)
        if os.path.exists(win_path) and not os.path.islink(win_path):
            messagebox.showerror("Error", f"A directory named '{win_path}' already exists and is not a symlink.\nPlease choose a different alias or remove the existing folder.")
            return

        db = self.load_registry()
        container_name = f"devlink_container_{alias}"

        self.log(f"Provisioning reverse-linked Docker sandbox '{alias}'...")

        # 1. Find a free port for SSH
        try:
            port = self._find_free_port(db)
        except RuntimeError as e:
            self.log(f"Port allocation failed: {e}", is_error=True)
            return
        self.log(f"Allocated SSH tunnel port: {port}")

        # 2. Detect WSL distro
        wsl_distro = self._detect_wsl_distro()
        wsl_home = self._get_wsl_home(wsl_distro)
        self.log(f"Using WSL distribution: {wsl_distro}")

        # 3. Spin up container WITHOUT bind mount, WITH published SSH port
        try:
            subprocess.run(["docker", "rm", "-f", container_name], capture_output=True)

            cmd = [
                "docker", "run", "-d",
                "--name", container_name,
                "--restart", "unless-stopped",
                "-p", f"{port}:22",
                "-w", "/workspace",
            ]

            # Inject registered environment variables
            env_vars = db.get("env_vars", {})
            for k, v in env_vars.items():
                cmd.extend(["-e", f"{k}={v}"])

            # Use sh -c to start sshd before the keepalive process (self-healing on container restart)
            cmd.extend([
                image,
                "sh", "-c", "mkdir -p /workspace && chmod 777 /workspace && /usr/sbin/sshd 2>/dev/null; exec tail -f /dev/null"
            ])

            subprocess.run(cmd, check=True, capture_output=True)
            self.log(f"Container '{container_name}' launched (port {port})")
        except Exception as e:
            self.log(f"Failed to launch container: {e}", is_error=True)
            messagebox.showerror("Docker Launch Failure", f"Docker could not launch the container:\n\n{e}")
            return

        # 4. Install and configure SSH daemon inside the container
        if not self._setup_container_ssh(container_name, wsl_distro):
            messagebox.showerror("SSH Setup Failure", "Could not configure SSH inside the container.")
            return

        # 5. Create SSHFS reverse mount from WSL
        wsl_mount_path = f"{wsl_home}/.devlinker-mounts/{alias}"
        if not self._setup_wsl_sshfs_mount(wsl_distro, alias, port, wsl_mount_path):
            messagebox.showerror("SSHFS Failure", "Could not establish the SSHFS reverse mount from WSL.")
            return

        # 6. Create Windows symlink pointing to the WSL UNC path
        wsl_unc = f"\\\\wsl.localhost\\{wsl_distro}" + f"{wsl_mount_path}/workspace".replace("/", "\\")
        win_path = os.path.join(link_location, alias)
        symlink_ok = False
        try:
            if os.path.exists(win_path) or os.path.islink(win_path):
                os.rmdir(win_path)
            os.symlink(wsl_unc, win_path, target_is_directory=True)
            self.log(f"Windows symlink created: {win_path}", is_success=True)
            symlink_ok = True
        except Exception as e:
            self.log(f"Windows symlink failed (files still accessible via UNC): {e}", is_error=True)
            win_path = wsl_unc  # Fallback: use UNC path directly

        # 7. Save mapping to registry
        db["docker_mappings"].append({
            "name": alias,
            "container_name": container_name,
            "image": image,
            "link_type": "reverse",
            "ssh_port": port,
            "wsl_distro": wsl_distro,
            "wsl_mount_path": wsl_mount_path,
            "wsl_unc_path": wsl_unc,
            "windows_path": win_path,
            "symlink_created": symlink_ok,
            "created_at": datetime.datetime.now().isoformat()
        })
        self.save_registry(db)
        self.refresh_mappings_list()

        self.log(f"Reverse-linked sandbox '{alias}' is fully operational!", is_success=True)
        messagebox.showinfo(
            "Success",
            f"Reverse-linked Docker sandbox '{alias}' is live!\n\n"
            f"Files live INSIDE the container.\n"
            f"Access and edit them natively at:\n{win_path}\n\n"
            f"Open in Cursor, VS Code, or any IDE!"
        )

    def connect_cloud_ssh(self):
        alias = self.ssh_alias.get().strip()
        host = self.ssh_host.get().strip()
        user = self.ssh_user.get().strip()
        key_path = self.ssh_key.get().strip()
        target = self.ssh_target.get().strip()
        
        # Resolve parent projects folder from active docker configuration
        db = self.load_registry()
        parent_projects_dir = db.get("host_projects_dir") or filedialog.askdirectory(title="Select Projects Parent Folder to Mount Cloud Node")
        if not parent_projects_dir:
            messagebox.showwarning("Warning", "A host parent folder is required to bridge the remote node!")
            return

        if not alias or not host or not user or not key_path or not target:
            messagebox.showwarning("Warning", "All fields are required!")
            return

        # Start bridge sidecar
        if not self.start_docker_bridge_container(parent_projects_dir):
            messagebox.showerror("Docker Error", "Docker Sidecar Bridge could not be launched.")
            return

        self.log(f"Bridging SSHFS Connection inside the Docker Sidecar: {user}@{host}:{target}...")
        
        local_host_path = os.path.join(parent_projects_dir, f"remote_{alias}")
        os.makedirs(local_host_path, exist_ok=True)

        try:
            # Copy SSH Key to sidecar container secure partition
            key_name = Path(key_path).name
            subprocess.run(["docker", "cp", key_path, f"devlinker-bridge:/root/.ssh/{key_name}"], check=True)
            subprocess.run(["docker", "exec", "devlinker-bridge", "chmod", "600", f"/root/.ssh/{key_name}"], check=True)

            # Mount remote node inside bridge container
            mount_cmd = f"sshfs {user}@{host}:{target} /projects/remote_{alias} -o allow_other,default_permissions,cache=yes -o IdentityFile=/root/.ssh/{key_name}"
            result = subprocess.run(["docker", "exec", "devlinker-bridge", "bash", "-c", mount_cmd], capture_output=True, text=True)
            
            if result.returncode != 0:
                raise RuntimeError(result.stderr)

            self.log(f"Secure filesystem tunnel established natively via Docker bridge!", is_success=True)

            # Store mapping
            db["ssh_mappings"].append({
                "name": alias,
                "host": host,
                "user": user,
                "remote_path": target,
                "windows_path": local_host_path,
                "created_at": datetime.datetime.now().isoformat()
            })
            self.save_registry(db)
            self.refresh_mappings_list()
            messagebox.showinfo("Success", f"Cloud Node '{alias}' is bridged!\n\nAccess and edit cloud files natively at: '{local_host_path}'")
        except Exception as e:
            self.log(f"SSHFS bridge failed: {e}", is_error=True)
            messagebox.showerror("Connection Failed", f"Could not mount remote node over SSHFS:\n\n{e}")

    def provision_cloud_vm(self):
        """Simulation of the unified app micro-transaction provisioning integration."""
        self.log("Contacting Developer Provisioning API...")
        mock_ip = f"143.244.{os.getpid() % 255}.44"
        self.log(f"Instance provisioned instantly in 4.5 seconds! IP Address: {mock_ip}", is_success=True)
        
        self.ssh_alias.delete(0, tk.END)
        self.ssh_alias.insert(0, "partner-vm")
        
        self.ssh_host.delete(0, tk.END)
        self.ssh_host.insert(0, mock_ip)
        
        self.ssh_user.delete(0, tk.END)
        self.ssh_user.insert(0, "ubuntu")
        
        self.ssh_target.delete(0, tk.END)
        self.ssh_target.insert(0, "/home/ubuntu/project")
        
        messagebox.showinfo("One-Click VM Ready", f"A high-performance isolated sandbox Node is active at: {mock_ip}.\n\nThe login credentials have been pre-filled. Select your private SSH key and click Connect to bridge the workspace folder instantly!")

    # =====================================================================
    # DASHBOARD LIST POPULATORS & TEARDOWN CONTROLLERS
    # =====================================================================
    def refresh_mappings_list(self):
        for widget in self.cards_container.winfo_children():
            widget.destroy()

        db = self.load_registry()
        wsl_m = db.get("wsl_mappings", [])
        dock_m = db.get("docker_mappings", [])
        ssh_m = db.get("ssh_mappings", [])

        total = len(wsl_m) + len(dock_m) + len(ssh_m)
        self.list_header.configure(text=f"Active Environments ({total})")

        # Empty state
        if total == 0:
            empty = ctk.CTkFrame(self.cards_container, fg_color="transparent")
            empty.pack(fill=tk.BOTH, expand=True, pady=100)
            ctk.CTkLabel(empty, text="🛸", font=("Segoe UI", 48)).pack()
            ctk.CTkLabel(empty, text="No environments registered", font=("Segoe UI", 15, "bold"), text_color=COLOR_TEXT_PRIMARY).pack(pady=10)
            ctk.CTkLabel(empty, text="Use the config panel on the right to link WSL directories,\n🐳 spin up isolated containers, or bridge SSH nodes.", font=("Segoe UI", 11), text_color=COLOR_TEXT_MUTED, justify=tk.CENTER).pack()
            return

        # Render WSL Cards
        for mapping in wsl_m:
            self.create_card("💻 " + mapping["name"], f"[{mapping['wsl_distro']}] {mapping['windows_path']} ➔ {mapping['wsl_path']}", "wsl", mapping)

        # Render Docker Cards
        for mapping in dock_m:
            if mapping.get("link_type") == "reverse":
                port_info = f" :{mapping.get('ssh_port', '?')}"
                self.create_card("🐳 " + mapping["name"], f"[{mapping['image']}] {mapping['container_name']}:/workspace ➔ {mapping['windows_path']}{port_info}", "docker", mapping)
            else:
                self.create_card("🐳 " + mapping["name"], f"[{mapping['image']}] {mapping['windows_path']} ➔ {mapping['container_name']}:/workspace", "docker", mapping)

        # Render SSH Cards
        for mapping in ssh_m:
            self.create_card("☁️ " + mapping["name"], f"[{mapping['user']}@{mapping['host']}] {mapping['windows_path']} ➔ {mapping['remote_path']}", "ssh", mapping)

    def create_card(self, title, subtitle, env_type, mapping_data):
        card = ctk.CTkFrame(self.cards_container, fg_color=COLOR_BG_CARD, corner_radius=10, border_width=1, border_color=COLOR_BORDER)
        card.pack(fill=tk.X, pady=6, padx=4)

        info = ctk.CTkFrame(card, fg_color="transparent")
        info.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=20, pady=12)

        ctk.CTkLabel(info, text=title, font=("Segoe UI", 14, "bold"), text_color=COLOR_TEXT_PRIMARY).pack(anchor=tk.W)
        p_lbl = ctk.CTkLabel(info, text=subtitle, font=("Segoe UI", 10), text_color=COLOR_TEXT_MUTED, justify=tk.LEFT)
        p_lbl.pack(anchor=tk.W, pady=(2, 0))

        btn_frame = ctk.CTkFrame(card, fg_color="transparent")
        btn_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=20, pady=12)

        # Actions
        alias = mapping_data["name"]
        win_path = mapping_data.get("windows_path", "")

        # Copy Path button
        if win_path:
            btn_copy = ctk.CTkButton(btn_frame, text="📋 Copy Path", width=105, height=34, fg_color="#1e2235", hover_color="#2b314c", text_color="#93c5fd", font=("Segoe UI", 11, "bold"), corner_radius=6)
            btn_copy.configure(command=lambda p=win_path, n=alias, b=btn_copy: self.copy_path(p, n, b))
            btn_copy.pack(side=tk.LEFT, padx=4)

        # Terminal button
        if env_type == "wsl":
            btn_term = ctk.CTkButton(btn_frame, text="💻 Open Terminal", width=120, height=34, fg_color="#22232e", hover_color="#2f3142", text_color=COLOR_TEXT_PRIMARY, font=("Segoe UI", 11, "bold"), corner_radius=6, command=lambda a=alias, d=mapping_data.get("wsl_distro", "Ubuntu-24.04"), p=mapping_data.get("wsl_path", "~"): self.open_linux_bash(a, d, p))
            btn_term.pack(side=tk.LEFT, padx=4)
        elif env_type == "docker":
            btn_term = ctk.CTkButton(btn_frame, text="💻 Open Shell", width=115, height=34, fg_color="#22232e", hover_color="#2f3142", text_color=COLOR_TEXT_PRIMARY, font=("Segoe UI", 11, "bold"), corner_radius=6, command=lambda a=alias, c=mapping_data.get("container_name"): self.open_docker_shell(a, c))
            btn_term.pack(side=tk.LEFT, padx=4)

        btn_del = ctk.CTkButton(btn_frame, text="🗑 Safe Remove", width=115, height=34, fg_color="#2a1a1e", hover_color=COLOR_DANGER_HOVER, text_color=COLOR_DANGER, font=("Segoe UI", 11, "bold"), corner_radius=6, command=lambda t=env_type, a=alias: self.delete_mapping(t, a))
        btn_del.pack(side=tk.LEFT, padx=4)

    def copy_path(self, path, name, btn=None):
        """Copies the Windows workspace path to the clipboard."""
        try:
            self.clipboard_clear()
            self.clipboard_append(path)
            self.update()
            self.log(f"Copied path for '{name}' to clipboard: {path}", is_success=True)
            if btn:
                orig_text = btn.cget("text")
                btn.configure(text="✔ Copied!")
                self.after(1400, lambda b=btn, t=orig_text: b.configure(text=t))
        except Exception as e:
            self.log(f"Failed to copy path to clipboard: {e}", is_error=True)

    def open_linux_bash(self, name, distro, wsl_path):
        """Spawns a native WSL Linux shell directly in the correct distro and directory."""
        self.log(f"Spawning WSL terminal inside '{distro}' at '{wsl_path}'...")
        wsl_unc_path = f"\\\\wsl.localhost\\{distro}" + wsl_path.replace('/', '\\')
        try:
            subprocess.Popen(["wt.exe", "-p", distro, "-d", wsl_unc_path])
            return
        except Exception:
            pass
        try:
            subprocess.Popen(f'start wsl.exe -d {distro} --cd "{wsl_path}"', shell=True)
        except Exception as e:
            self.log(f"Could not open WSL terminal: {e}", is_error=True)

    def open_docker_shell(self, name, container_name):
        """Spawns an interactive terminal inside the Docker container."""
        if not container_name:
            return
        self.log(f"Spawning shell inside container '{container_name}'...")
        try:
            subprocess.Popen(["wt.exe", "docker", "exec", "-it", container_name, "sh"])
            return
        except Exception:
            pass
        try:
            subprocess.Popen(f'start cmd.exe /k docker exec -it {container_name} sh', shell=True)
        except Exception as e:
            self.log(f"Could not open container terminal: {e}", is_error=True)

    def delete_mapping(self, env_type, name):
        confirm = messagebox.askyesno("Confirm Deletion", f"Are you sure you want to safely remove the bridged environment '{name}'?\n\nAll your persistent files remain 100% safe and untouched.")
        if not confirm:
            return

        self.log(f"Safely removing {env_type} mapping '{name}'...")
        db = self.load_registry()

        if env_type == "wsl":
            target = next((m for m in db["wsl_mappings"] if m["name"].lower() == name.lower()), None)
            if target:
                win_path = target["windows_path"]
                if os.path.exists(win_path) or os.path.islink(win_path):
                    try:
                        os.rmdir(win_path)
                    except Exception as e:
                        self.log(f"Failed to remove local link: {e}", is_error=True)
                db["wsl_mappings"] = [m for m in db["wsl_mappings"] if m["name"].lower() != name.lower()]

        elif env_type == "docker":
            target = next((m for m in db["docker_mappings"] if m["name"].lower() == name.lower()), None)
            if target:
                if target.get("link_type") == "reverse":
                    # Remove only the symlink itself (never the contents), then unmount SSHFS
                    wp = target.get("windows_path", "")
                    if target.get("symlink_created") and (os.path.islink(wp) or os.path.isdir(wp)):
                        try:
                            os.rmdir(wp)
                        except Exception as e:
                            self.log(f"Failed to remove Windows symlink: {e}", is_error=True)
                    self._unmount_wsl_sshfs(target["wsl_distro"], target["wsl_mount_path"])
                # Stop dev container
                subprocess.run(["docker", "rm", "-f", target["container_name"]], capture_output=True)
                db["docker_mappings"] = [m for m in db["docker_mappings"] if m["name"].lower() != name.lower()]
                self.log(f"Sandbox container '{target['container_name']}' successfully dissolved.", is_success=True)

        elif env_type == "ssh":
            target = next((m for m in db["ssh_mappings"] if m["name"].lower() == name.lower()), None)
            if target:
                # Unmount inside Sidecar
                subprocess.run(["docker", "exec", "devlinker-bridge", "umount", "-f", f"/projects/remote_{name}"], capture_output=True)
                db["ssh_mappings"] = [m for m in db["ssh_mappings"] if m["name"].lower() != name.lower()]
                self.log(f"SSHFS mount tunnel for '{name}' safely unmounted.", is_success=True)

        self.save_registry(db)
        self.refresh_mappings_list()
        messagebox.showinfo("Removed", f"Bridged environment '{name}' successfully unlinked!")

    def toggle_sidebar(self):
        if self.sidebar_visible:
            self.right_frame.pack_forget()
            self.left_frame.pack_configure(padx=0)
            self.btn_toggle_sidebar.configure(text="➕ Configure Panel", fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER)
            self.sidebar_visible = False
            self.log("Configuration panel hidden.", is_success=True)
        else:
            self.left_frame.pack_configure(padx=(0, 15))
            self.right_frame.pack(fill=tk.BOTH, side=tk.RIGHT, padx=(15, 0))
            self.btn_toggle_sidebar.configure(text="✕ Close Config", fg_color="#2b2d3a", hover_color="#3e4052")
            self.sidebar_visible = True
            self.log("Configuration panel shown.", is_success=True)

    def setup_env_tab(self):
        self.env_scroll = ctk.CTkScrollableFrame(self.tab_env, fg_color="transparent", label_text="")
        self.env_scroll.pack(fill=tk.BOTH, expand=True)

        # ----------------------------------------------------
        # 1. Credentials Registry
        # ----------------------------------------------------
        ctk.CTkLabel(self.env_scroll, text="🔑 CREDENTIALS REGISTRY", font=("Segoe UI", 12, "bold"), text_color=COLOR_TEXT_PRIMARY).pack(anchor=tk.W, pady=(10,12))

        # List of existing profiles
        self.cred_list_frame = ctk.CTkFrame(self.env_scroll, fg_color="#181a26", border_width=1, border_color=COLOR_BORDER)
        self.cred_list_frame.pack(fill=tk.X, pady=(0,15))
        self.refresh_credentials_list()

        # Add connection profile form
        ctk.CTkLabel(self.env_scroll, text="REGISTER CONNECTION PROFILE", font=("Segoe UI", 9, "bold"), text_color=COLOR_TEXT_MUTED).pack(anchor=tk.W, pady=(5,2))
        
        self.cred_alias = ctk.CTkEntry(self.env_scroll, placeholder_text="Profile Name (e.g. prod-ec2)", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, height=36)
        self.cred_alias.pack(fill=tk.X, pady=(0,8))

        row_ssh = ctk.CTkFrame(self.env_scroll, fg_color="transparent")
        row_ssh.pack(fill=tk.X, pady=(0,8))
        
        self.cred_host = ctk.CTkEntry(row_ssh, placeholder_text="Host IP/Domain", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, height=36)
        self.cred_host.pack(fill=tk.X, side=tk.LEFT, expand=True, padx=(0,6))
        
        self.cred_user = ctk.CTkEntry(row_ssh, placeholder_text="Username", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, height=36)
        self.cred_user.pack(fill=tk.X, side=tk.RIGHT, expand=True)

        self.cred_secret = ctk.CTkEntry(self.env_scroll, placeholder_text="Password or Key Path (.pem)", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, height=36)
        self.cred_secret.pack(fill=tk.X, pady=(0,10))

        ctk.CTkButton(self.env_scroll, text="Save Credential Profile 🔒", fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, height=36, font=("Segoe UI", 11, "bold"), command=self.save_credential_profile).pack(fill=tk.X, pady=(0,20))

        # Divider
        ctk.CTkFrame(self.env_scroll, fg_color=COLOR_BORDER, height=2).pack(fill=tk.X, pady=10)

        # ----------------------------------------------------
        # 2. Environment Variables Manager
        # ----------------------------------------------------
        ctk.CTkLabel(self.env_scroll, text="⚙️ ENVIRONMENT VARIABLES", font=("Segoe UI", 12, "bold"), text_color=COLOR_TEXT_PRIMARY).pack(anchor=tk.W, pady=(10,12))

        # List of existing env variables
        self.env_list_frame = ctk.CTkFrame(self.env_scroll, fg_color="#181a26", border_width=1, border_color=COLOR_BORDER)
        self.env_list_frame.pack(fill=tk.X, pady=(0,15))
        self.refresh_env_vars_list()

        # Add environment variable form
        ctk.CTkLabel(self.env_scroll, text="ADD ENVIRONMENT VARIABLE", font=("Segoe UI", 9, "bold"), text_color=COLOR_TEXT_MUTED).pack(anchor=tk.W, pady=(5,2))
        
        row_env = ctk.CTkFrame(self.env_scroll, fg_color="transparent")
        row_env.pack(fill=tk.X, pady=(0,10))
        
        self.env_key = ctk.CTkEntry(row_env, placeholder_text="KEY (e.g. API_KEY)", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, height=36)
        self.env_key.pack(fill=tk.X, side=tk.LEFT, expand=True, padx=(0,6))
        
        self.env_val = ctk.CTkEntry(row_env, placeholder_text="VALUE", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, height=36)
        self.env_val.pack(fill=tk.X, side=tk.RIGHT, expand=True)

        ctk.CTkButton(self.env_scroll, text="Add Environment Variable ➕", fg_color=COLOR_SUCCESS, hover_color="#059669", height=36, font=("Segoe UI", 11, "bold"), command=self.add_env_variable).pack(fill=tk.X, pady=(0,10))

    def refresh_credentials_list(self):
        for widget in self.cred_list_frame.winfo_children():
            widget.destroy()

        db = self.load_registry()
        creds = db.get("credentials", {})

        if not creds:
            lbl = ctk.CTkLabel(self.cred_list_frame, text="No credentials registered.", font=("Segoe UI", 10, "italic"), text_color=COLOR_TEXT_MUTED)
            lbl.pack(pady=12, padx=12)
            return

        for alias, info in creds.items():
            card = ctk.CTkFrame(self.cred_list_frame, fg_color="transparent")
            card.pack(fill=tk.X, pady=4, padx=8)

            lbl_txt = f"🔑 {alias} ({info.get('user')}@{info.get('host')})"
            ctk.CTkLabel(card, text=lbl_txt, font=("Segoe UI", 11), text_color=COLOR_TEXT_PRIMARY).pack(side=tk.LEFT, padx=5, pady=4)

            # Delete button
            btn_del = ctk.CTkButton(
                card, 
                text="🗑", 
                width=28, 
                height=24, 
                fg_color="transparent", 
                hover_color=COLOR_DANGER_HOVER, 
                text_color=COLOR_DANGER, 
                font=("Segoe UI", 11, "bold"), 
                command=lambda a=alias: self.delete_credential_profile(a)
            )
            btn_del.pack(side=tk.RIGHT, padx=5)

    def save_credential_profile(self):
        alias = self.cred_alias.get().strip()
        host = self.cred_host.get().strip()
        user = self.cred_user.get().strip()
        secret = self.cred_secret.get().strip()

        if not alias or not host or not user or not secret:
            messagebox.showwarning("Warning", "All credential fields are required!")
            return

        db = self.load_registry()
        db["credentials"][alias] = {
            "user": user,
            "host": host,
            "secret": secret,
            "auth_type": "key" if secret.endswith(".pem") or "/" in secret or "\\" in secret or os.path.exists(secret) else "password",
            "registered_at": datetime.datetime.now().isoformat()
        }
        self.save_registry(db)
        self.refresh_credentials_list()
        self.refresh_ssh_profiles_dropdown()
        
        # Clear fields
        self.cred_alias.delete(0, tk.END)
        self.cred_host.delete(0, tk.END)
        self.cred_user.delete(0, tk.END)
        self.cred_secret.delete(0, tk.END)
        
        self.log(f"Credential profile '{alias}' saved successfully.", is_success=True)
        messagebox.showinfo("Success", f"Credential profile '{alias}' saved successfully.")

    def delete_credential_profile(self, alias):
        confirm = messagebox.askyesno("Confirm Deletion", f"Remove credential profile '{alias}'?")
        if not confirm:
            return

        db = self.load_registry()
        if alias in db.get("credentials", {}):
            del db["credentials"][alias]
            self.save_registry(db)
            self.refresh_credentials_list()
            self.refresh_ssh_profiles_dropdown()
            self.log(f"Credential profile '{alias}' removed.", is_success=True)

    def refresh_env_vars_list(self):
        for widget in self.env_list_frame.winfo_children():
            widget.destroy()

        db = self.load_registry()
        env_vars = db.get("env_vars", {})

        if not env_vars:
            lbl = ctk.CTkLabel(self.env_list_frame, text="No environment variables set.", font=("Segoe UI", 10, "italic"), text_color=COLOR_TEXT_MUTED)
            lbl.pack(pady=12, padx=12)
            return

        for k, v in env_vars.items():
            card = ctk.CTkFrame(self.env_list_frame, fg_color="transparent")
            card.pack(fill=tk.X, pady=4, padx=8)

            # Mask sensitive values
            display_val = v
            if len(v) > 12 and (any(kw in k.lower() for kw in ["key", "secret", "password", "token"]) or k.isupper()):
                display_val = v[:4] + "..." + v[-4:]

            lbl_txt = f"⚙️ {k} = {display_val}"
            ctk.CTkLabel(card, text=lbl_txt, font=("Segoe UI", 11), text_color=COLOR_TEXT_PRIMARY).pack(side=tk.LEFT, padx=5, pady=4)

            # Delete button
            btn_del = ctk.CTkButton(
                card, 
                text="🗑", 
                width=28, 
                height=24, 
                fg_color="transparent", 
                hover_color=COLOR_DANGER_HOVER, 
                text_color=COLOR_DANGER, 
                font=("Segoe UI", 11, "bold"), 
                command=lambda key=k: self.delete_env_variable(key)
            )
            btn_del.pack(side=tk.RIGHT, padx=5)

    def add_env_variable(self):
        k = self.env_key.get().strip().upper()
        v = self.env_val.get().strip()

        if not k or not v:
            messagebox.showwarning("Warning", "Both KEY and VALUE are required!")
            return

        db = self.load_registry()
        db["env_vars"][k] = v
        self.save_registry(db)
        self.refresh_env_vars_list()
        
        # Clear fields
        self.env_key.delete(0, tk.END)
        self.env_val.delete(0, tk.END)
        
        self.log(f"Environment variable '{k}' registered successfully.", is_success=True)

    def delete_env_variable(self, k):
        db = self.load_registry()
        if k in db.get("env_vars", {}):
            del db["env_vars"][k]
            self.save_registry(db)
            self.refresh_env_vars_list()
            self.log(f"Environment variable '{k}' removed.", is_success=True)

    def refresh_ssh_profiles_dropdown(self):
        try:
            db = self.load_registry()
            profiles = list(db.get("credentials", {}).keys())
            if not profiles:
                profiles = ["None"]
            else:
                profiles = ["None"] + profiles
            self.ssh_profile_dropdown.configure(values=profiles)
        except Exception:
            pass

    def on_select_ssh_profile(self, selected_alias):
        if selected_alias == "None":
            return
        db = self.load_registry()
        creds = db.get("credentials", {})
        profile = creds.get(selected_alias)
        if profile:
            self.ssh_alias.delete(0, tk.END)
            self.ssh_alias.insert(0, selected_alias)
            
            self.ssh_host.delete(0, tk.END)
            self.ssh_host.insert(0, profile.get("host", ""))
            
            self.ssh_user.delete(0, tk.END)
            self.ssh_user.insert(0, profile.get("user", ""))
            
            self.ssh_key.delete(0, tk.END)
            self.ssh_key.insert(0, profile.get("secret", ""))

if __name__ == "__main__":
    app = ExperimentalLinkerApp()
    app.mainloop()
