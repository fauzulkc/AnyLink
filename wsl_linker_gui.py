#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, filedialog
import customtkinter as ctk

# Set modern appearance mode and color theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Theme Colors (Modern Dark Slate & Blurple/Indigo palette)
COLOR_BG_MAIN = "#0d0e12"       # Extremely sleek, deep dark slate
COLOR_BG_CARD = "#15161e"       # Premium card background
COLOR_BG_INPUT = "#1c1d26"      # Input field background
COLOR_BORDER = "#252733"        # Thin subtle border
COLOR_TEXT_PRIMARY = "#ffffff"  # Pure white
COLOR_TEXT_MUTED = "#8e92a8"    # Muted gray for subtitles/secondary text
COLOR_ACCENT = "#5865f2"        # Discord-like Blurple
COLOR_ACCENT_HOVER = "#4752c4"  # Darker Blurple on hover
COLOR_SUCCESS = "#10b981"       # Emerald Green for status success
COLOR_DANGER = "#ef4444"        # Red for deletion/danger
COLOR_DANGER_HOVER = "#dc2626"  # Darker red on hover

class WSLLinkerApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # Window configuration
        self.title("WSL Linker - Workspace Manager")
        
        # Detect host screen resolution dynamically to decide the best default geometry
        try:
            screen_width = self.winfo_screenwidth()
            screen_height = self.winfo_screenheight()
            
            # Select optimal height based on screen limits (virtual scaled coordinates)
            if screen_height <= 800:
                # HD screens (1366x768) or heavily-scaled laptop screens
                default_width = 1100
                default_height = 650
            else:
                # Full HD (1920x1080), QHD, or 4K screens
                default_width = 1100
                default_height = 800
        except Exception:
            # Safe default fallback
            default_width = 1100
            default_height = 680

        self.geometry(f"{default_width}x{default_height}")
        self.configure(fg_color=COLOR_BG_MAIN)
        self.minsize(700, 550)

        # Sidebar state management
        self.sidebar_visible = True
        self.user_toggled_sidebar = False

        # Bind root window resize to handle dynamic responsive layout
        self.bind("<Configure>", self.on_window_resize)

        # Ensure DPI awareness for ultra-crisp text on high-res screens
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

        # Load WSL distributions dynamically
        self.distros = self.get_wsl_distros()

        # Initialize GUI Layout
        self.build_ui()

        # Load initial mappings into the interface
        self.refresh_workspace_list()
        self.log("WSL Linker successfully initialized.")

    def get_registry_path(self):
        """Get the path to the central JSON link registry in user home."""
        home = Path.home()
        registry_dir = home / ".wsl-linker"
        registry_dir.mkdir(parents=True, exist_ok=True)
        return registry_dir / "links.json"

    def load_registry(self):
        """Load registered mappings from links.json."""
        path = self.get_registry_path()
        if not path.exists():
            return {"mappings": []}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {"mappings": []}

    def save_registry(self, data):
        """Save registry mappings to links.json."""
        path = self.get_registry_path()
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log(f"Error saving registry: {e}", is_error=True)

    def get_wsl_distros(self):
        """Queries WSL to fetch all installed distributions on the host."""
        try:
            result = subprocess.run(["wsl", "--list", "--quiet"], capture_output=True, text=True, encoding="utf-16le")
            output = result.stdout
            if not output:
                result = subprocess.run(["wsl", "--list", "--quiet"], capture_output=True, text=True, encoding="utf-8")
                output = result.stdout
            
            distros = [line.strip() for line in output.split("\n") if line.strip() and "\x00" not in line]
            distros = [d.replace("\x00", "") for d in distros]
            return distros if distros else ["Ubuntu-24.04"]
        except Exception:
            return ["Ubuntu-24.04", "Ubuntu", "debian"]

    def build_ui(self):
        """Create a highly immersive, responsive, Discord-like dashboard layout."""
        # 1. Sleek Top Title Header
        header_frame = ctk.CTkFrame(self, fg_color=COLOR_BG_CARD, height=75, corner_radius=0, border_width=1, border_color=COLOR_BORDER)
        header_frame.pack(fill=tk.X, side=tk.TOP)
        header_frame.pack_propagate(False)

        logo_label = ctk.CTkLabel(header_frame, text="WSL LINKER", font=("Segoe UI", 22, "bold"), text_color=COLOR_TEXT_PRIMARY)
        logo_label.pack(side=tk.LEFT, padx=(25, 10), pady=20)
        
        sep_label = ctk.CTkLabel(header_frame, text="|", font=("Segoe UI", 18), text_color=COLOR_BORDER)
        sep_label.pack(side=tk.LEFT, padx=5)

        subtitle_label = ctk.CTkLabel(header_frame, text="Zero-Latency Native Workspace Mappings", font=("Segoe UI", 12), text_color=COLOR_TEXT_MUTED)
        subtitle_label.pack(side=tk.LEFT, padx=10, pady=24)

        # Elegant toggle button on the right side of the header (like a modern settings flyout)
        self.btn_toggle_sidebar = ctk.CTkButton(header_frame, text="✕ Close Form", width=160, height=36, fg_color="#2b2d3a", hover_color="#3e4052", text_color=COLOR_TEXT_PRIMARY, font=("Segoe UI", 11, "bold"), corner_radius=6, command=lambda: self.toggle_sidebar(user_clicked=True))
        self.btn_toggle_sidebar.pack(side=tk.RIGHT, padx=25, pady=20)

        # 2. Main Outer Layout Panel (Split Left Table List / Right Sidebar Form)
        content_frame = ctk.CTkFrame(self, fg_color="transparent")
        content_frame.pack(fill=tk.BOTH, expand=True, padx=25, pady=25)

        # Left Column - Workspace Registry List Box
        self.left_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        self.left_frame.pack(fill=tk.BOTH, side=tk.LEFT, expand=True, padx=(0, 15))

        list_header_row = ctk.CTkFrame(self.left_frame, fg_color="transparent")
        list_header_row.pack(fill=tk.X, pady=(0, 12))

        self.list_header = ctk.CTkLabel(list_header_row, text="Active Registry Mappings", font=("Segoe UI", 16, "bold"), text_color=COLOR_TEXT_PRIMARY)
        self.list_header.pack(side=tk.LEFT)

        # Scrollable list container representing cards
        self.cards_container = ctk.CTkScrollableFrame(self.left_frame, fg_color=COLOR_BG_MAIN, border_width=1, border_color=COLOR_BORDER)
        self.cards_container.pack(fill=tk.BOTH, expand=True)

        # Right Column - Sidebar Form Card
        self.right_frame = ctk.CTkFrame(content_frame, fg_color=COLOR_BG_CARD, width=360, corner_radius=12, border_width=1, border_color=COLOR_BORDER)
        self.right_frame.pack(fill=tk.BOTH, side=tk.RIGHT, padx=(15, 0))
        self.right_frame.pack_propagate(False)

        # Form Title (Pinned at the top of the sidebar, not scrollable)
        form_title = ctk.CTkLabel(self.right_frame, text="Link New Workspace", font=("Segoe UI", 16, "bold"), text_color=COLOR_TEXT_PRIMARY)
        form_title.pack(anchor=tk.W, padx=25, pady=(25, 15))

        # Scrollable inner container for fields (so buttons are never cut off)
        form_scroll = ctk.CTkScrollableFrame(self.right_frame, fg_color="transparent", corner_radius=0, border_width=0, label_text="")
        form_scroll.pack(fill=tk.BOTH, expand=True, padx=5, pady=(0, 15))

        # Inputs (packed inside form_scroll instead of self.right_frame)
        ctk.CTkLabel(form_scroll, text="ALIAS NAME", font=("Segoe UI", 9, "bold"), text_color=COLOR_TEXT_MUTED).pack(anchor=tk.W, padx=20, pady=(0, 2))
        self.entry_name = ctk.CTkEntry(form_scroll, placeholder_text="e.g. my-project", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, height=40, font=("Segoe UI", 11))
        self.entry_name.pack(fill=tk.X, padx=20, pady=(0, 15))
        self.entry_name.bind("<KeyRelease>", self.update_path_preview)

        ctk.CTkLabel(form_scroll, text="LOCAL PARENT WINDOWS DIRECTORY", font=("Segoe UI", 9, "bold"), text_color=COLOR_TEXT_MUTED).pack(anchor=tk.W, padx=20, pady=(0, 2))
        path_row = ctk.CTkFrame(form_scroll, fg_color="transparent")
        path_row.pack(fill=tk.X, padx=20, pady=(0, 4))
        
        self.entry_win_path = ctk.CTkEntry(path_row, placeholder_text="Select parent folder (e.g. D:\\Projects)...", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, height=40, font=("Segoe UI", 11))
        self.entry_win_path.pack(fill=tk.X, side=tk.LEFT, expand=True, padx=(0, 8))
        self.entry_win_path.bind("<KeyRelease>", self.update_path_preview)
        
        btn_browse = ctk.CTkButton(path_row, text="Browse", width=75, height=40, fg_color="#2b2d3a", hover_color="#3e4052", text_color=COLOR_TEXT_PRIMARY, font=("Segoe UI", 11, "bold"), command=self.browse_windows_folder)
        btn_browse.pack(side=tk.RIGHT)

        path_desc = ctk.CTkLabel(form_scroll, text="Your virtual symlink folder (named after the Alias) will be created inside this folder automatically.", font=("Segoe UI", 9), text_color=COLOR_TEXT_MUTED, justify=tk.LEFT, wraplength=280)
        path_desc.pack(anchor=tk.W, padx=20, pady=(0, 15))

        ctk.CTkLabel(form_scroll, text="WSL TARGET DIRECTORY PATH", font=("Segoe UI", 9, "bold"), text_color=COLOR_TEXT_MUTED).pack(anchor=tk.W, padx=20, pady=(0, 2))
        self.entry_wsl_path = ctk.CTkEntry(form_scroll, placeholder_text="e.g. /home/user/code/my-project", fg_color=COLOR_BG_INPUT, border_color=COLOR_BORDER, height=40, font=("Segoe UI", 11))
        self.entry_wsl_path.pack(fill=tk.X, padx=20, pady=(0, 15))

        ctk.CTkLabel(form_scroll, text="TARGET WSL DISTRIBUTION", font=("Segoe UI", 9, "bold"), text_color=COLOR_TEXT_MUTED).pack(anchor=tk.W, padx=20, pady=(0, 2))
        self.combo_distro = ctk.CTkOptionMenu(form_scroll, values=self.distros, fg_color=COLOR_BG_INPUT, button_color="#2b2d3a", button_hover_color="#3e4052", height=40, font=("Segoe UI", 11))
        self.combo_distro.pack(fill=tk.X, padx=20, pady=(0, 20))

        # Path Preview Section
        self.lbl_preview = ctk.CTkLabel(form_scroll, text="Preview: (Enter Alias and Parent Path)", font=("Segoe UI", 10, "italic"), text_color=COLOR_TEXT_MUTED, justify=tk.LEFT, wraplength=280)
        self.lbl_preview.pack(anchor=tk.W, padx=20, pady=(0, 20))

        # Submit Action
        self.btn_add = ctk.CTkButton(form_scroll, text="Create Direct Link 🔗", fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER, height=45, font=("Segoe UI", 12, "bold"), command=self.create_link)
        self.btn_add.pack(fill=tk.X, padx=20, pady=(0, 20))

        # Help Card inside sidebar
        help_card = ctk.CTkFrame(form_scroll, fg_color="#181a26", corner_radius=8, border_width=1, border_color="#252a45")
        help_card.pack(fill=tk.X, padx=20, pady=(0, 20))
        
        help_title = ctk.CTkLabel(help_card, text="💡 Developer Tip", font=("Segoe UI", 11, "bold"), text_color=COLOR_ACCENT)
        help_title.pack(anchor=tk.W, padx=15, pady=(12, 4))
        
        help_desc = ctk.CTkLabel(help_card, text="Windows symbolic links require Administrator elevation OR Windows Developer Mode active. Turn on Developer Mode in Windows Settings to create links instantly without prompt elevation.", font=("Segoe UI", 9), text_color="#acb1c9", justify=tk.LEFT, wraplength=240)
        help_desc.pack(anchor=tk.W, padx=15, pady=(0, 12))

        # 3. Bottom Scrolling Console Output (Activity Log)
        log_frame = ctk.CTkFrame(self, fg_color=COLOR_BG_CARD, height=130, corner_radius=0, border_width=1, border_color=COLOR_BORDER)
        log_frame.pack(fill=tk.X, side=tk.BOTTOM)
        log_frame.pack_propagate(False)

        log_title_row = ctk.CTkFrame(log_frame, fg_color="transparent")
        log_title_row.pack(fill=tk.X, padx=25, pady=(10, 5))

        log_label = ctk.CTkLabel(log_title_row, text="Activity Console Logs", font=("Segoe UI", 11, "bold"), text_color=COLOR_TEXT_MUTED)
        log_label.pack(side=tk.LEFT)

        btn_clear = ctk.CTkButton(log_title_row, text="Clear Log", width=65, height=20, fg_color="transparent", text_color=COLOR_TEXT_MUTED, hover_color="#22232e", font=("Segoe UI", 9), command=self.clear_logs)
        btn_clear.pack(side=tk.RIGHT)

        self.log_text = ctk.CTkTextbox(log_frame, fg_color="#090a0d", text_color="#acb1c9", font=("Consolas", 10), corner_radius=6, border_width=1, border_color=COLOR_BORDER)
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=25, pady=(0, 12))
        self.log_text.configure(state="disabled")

    def log(self, message, is_error=False, is_success=False):
        """Append beautiful timestamps and status messages to the activity log."""
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

    def clear_logs(self):
        """Flush terminal activity log."""
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", tk.END)
        self.log_text.configure(state="disabled")

    def browse_windows_folder(self):
        """Browse native folders and automatically generate aliases."""
        folder = filedialog.askdirectory(title="Select Local Parent Windows Directory")
        if folder:
            self.entry_win_path.delete(0, tk.END)
            self.entry_win_path.insert(0, os.path.abspath(folder))
            self.update_path_preview()

    def update_path_preview(self, event=None):
        """Dynamically compute and display the target Windows path in real-time."""
        name = self.entry_name.get().strip()
        win_parent = self.entry_win_path.get().strip()
        
        if not name and not win_parent:
            self.lbl_preview.configure(text="Preview: (Enter Alias and Parent Path)", text_color=COLOR_TEXT_MUTED)
        elif not win_parent:
            self.lbl_preview.configure(text=f"Preview: [Parent Folder]\\{name}", text_color=COLOR_ACCENT)
        elif not name:
            self.lbl_preview.configure(text=f"Preview: {win_parent}\\[Alias Name]", text_color=COLOR_ACCENT)
        else:
            try:
                full_path = os.path.join(win_parent, name)
                self.lbl_preview.configure(text=f"Preview: {full_path}", text_color=COLOR_SUCCESS)
            except Exception:
                self.lbl_preview.configure(text="Preview: Invalid Path", text_color=COLOR_DANGER)

    def refresh_workspace_list(self):
        """Read links.json registry and render gorgeous workspace card widgets inside the frame."""
        # 1. Clear out all existing workspace cards
        for widget in self.cards_container.winfo_children():
            widget.destroy()

        registry = self.load_registry()
        mappings = registry.get("mappings", [])

        # Update registry counter header
        self.list_header.configure(text=f"Active Registry Mappings ({len(mappings)})")

        # 2. Render Empty State if no mappings
        if not mappings:
            empty_frame = ctk.CTkFrame(self.cards_container, fg_color="transparent")
            empty_frame.pack(fill=tk.BOTH, expand=True, pady=100)

            empty_icon = ctk.CTkLabel(empty_frame, text="📁", font=("Segoe UI", 48))
            empty_icon.pack()

            empty_title = ctk.CTkLabel(empty_frame, text="No workspace mappings registered", font=("Segoe UI", 15, "bold"), text_color=COLOR_TEXT_PRIMARY)
            empty_title.pack(pady=(10, 5))

            empty_subtitle = ctk.CTkLabel(empty_frame, text="Use the form on the right to link a local Windows folder directly\nto a remote directory in your active WSL distribution.", font=("Segoe UI", 11), text_color=COLOR_TEXT_MUTED, justify=tk.CENTER)
            empty_subtitle.pack()
            return

        # 3. Populate cards
        for mapping in mappings:
            card = ctk.CTkFrame(self.cards_container, fg_color=COLOR_BG_CARD, corner_radius=10, border_width=1, border_color=COLOR_BORDER)
            card.pack(fill=tk.X, pady=6, padx=4)

            # Left side content info (pre-packed by default)
            info_frame = ctk.CTkFrame(card, fg_color="transparent")

            name_lbl = ctk.CTkLabel(info_frame, text=mapping["name"], font=("Segoe UI", 14, "bold"), text_color=COLOR_TEXT_PRIMARY)
            name_lbl.pack(anchor=tk.W)

            path_mapping_str = f"{mapping['windows_path']}  ➔  [{mapping['wsl_distro']}] {mapping['wsl_path']}"
            path_lbl = ctk.CTkLabel(info_frame, text=path_mapping_str, font=("Segoe UI", 10), text_color=COLOR_TEXT_MUTED, justify=tk.LEFT)
            path_lbl.pack(anchor=tk.W, pady=(2, 0), fill=tk.X, expand=True)

            # Right side actions row (pre-packed by default)
            btn_frame = ctk.CTkFrame(card, fg_color="transparent")

            # Create references to pass variables properly inside loops
            alias_name = mapping["name"]
            win_path = mapping["windows_path"]
            distro = mapping["wsl_distro"]
            wsl_path = mapping["wsl_path"]

            btn_term = ctk.CTkButton(btn_frame, text="💻 Open Terminal", width=120, height=34, fg_color="#22232e", hover_color="#2f3142", text_color=COLOR_TEXT_PRIMARY, font=("Segoe UI", 11, "bold"), corner_radius=6, command=lambda a=alias_name, d=distro, p=wsl_path: self.open_linux_bash(a, d, p))
            btn_term.pack(side=tk.LEFT, padx=4)

            btn_del = ctk.CTkButton(btn_frame, text="🗑 Safe Remove", width=115, height=34, fg_color="#2a1a1e", hover_color="#441f26", text_color=COLOR_DANGER, font=("Segoe UI", 11, "bold"), corner_radius=6, command=lambda a=alias_name, w=win_path, d=distro, p=wsl_path: self.delete_link(a, w, d, p))
            btn_del.pack(side=tk.LEFT, padx=4)

            # Pack containers by default in the wide layout so they are immediately visible
            btn_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 20), pady=12)
            info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(20, 10), pady=12)

            # Responsive layout logic based on card width
            def make_card_resize_handler(c_frame, i_frame, b_frame, p_label):
                current_state = {"layout": "wide"}  # Set to initial wide state since we pre-pack wide
                
                def on_card_configure(event):
                    # Compare string representations to handle CustomTkinter internal elements safely
                    if str(event.widget) != str(c_frame):
                        return
                    w = event.width
                    
                    if w < 580:
                        if current_state["layout"] != "compact":
                            # Switch to stacked compact layout
                            b_frame.pack_forget()
                            i_frame.pack_forget()
                            
                            i_frame.pack(side=tk.TOP, fill=tk.X, padx=(20, 20), pady=(12, 6))
                            b_frame.pack(side=tk.TOP, anchor=tk.W, padx=(20, 20), pady=(0, 12))
                            current_state["layout"] = "compact"
                        
                        # Adjust wraplength for text wrapping in compact view
                        p_label.configure(wraplength=w - 40)
                    else:
                        if current_state["layout"] != "wide":
                            # Switch to wide side-by-side layout
                            b_frame.pack_forget()
                            i_frame.pack_forget()
                            
                            b_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(10, 20), pady=12)
                            i_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(20, 10), pady=12)
                            current_state["layout"] = "wide"
                        
                        # Calculate exact wrapping width dynamically
                        btn_w = b_frame.winfo_reqwidth()
                        available_w = w - btn_w - 70
                        p_label.configure(wraplength=max(150, available_w))
                        
                return on_card_configure

            card.bind("<Configure>", make_card_resize_handler(card, info_frame, btn_frame, path_lbl))

    def create_link(self):
        """Implements safe symlink creation on form submit."""
        name = self.entry_name.get().strip()
        win_parent = self.entry_win_path.get().strip()
        wsl_path = self.entry_wsl_path.get().strip().replace('\\', '/')
        distro = self.combo_distro.get()

        if not name or not win_parent or not wsl_path:
            messagebox.showwarning("Incomplete Fields", "Please complete all inputs before establishing a link.")
            return

        win_parent = os.path.abspath(win_parent)
        if not os.path.isdir(win_parent):
            messagebox.showerror("Invalid Parent Directory", f"The local parent directory '{win_parent}' does not exist.\n\nPlease select an existing folder first.")
            return

        win_path = os.path.join(win_parent, name)
        target_win_unc = f"\\\\wsl.localhost\\{distro}" + wsl_path.replace('/', '\\')

        # Check duplicate configurations
        registry = self.load_registry()
        for m in registry.get("mappings", []):
            if m["name"].lower() == name.lower():
                messagebox.showerror("Conflict", f"A registered workspace with name '{name}' already exists.")
                return
            if os.path.abspath(m["windows_path"]).lower() == win_path.lower():
                messagebox.showerror("Conflict", f"The local path '{win_path}' is already registered.")
                return

        # Create remote target directory on WSL
        self.log(f"Verifying/creating WSL directory '{wsl_path}' inside distribution '{distro}'...")
        try:
            subprocess.run(["wsl", "-d", distro, "-e", "mkdir", "-p", wsl_path], check=True, capture_output=True)
        except Exception as e:
            self.log(f"WSL folder verification failed: {e}", is_error=True)
            messagebox.showerror("WSL Access Failure", f"Could not create path inside WSL distribution. Please ensure WSL is active.\n\nError: {e}")
            return

        # Verify host path is clean
        if os.path.exists(win_path):
            messagebox.showerror("Folder Exists", f"The local Windows path '{win_path}' already exists as a physical directory.\n\nPlease choose a different Alias name or delete the existing directory first.")
            return

        # Attempt to create directory symbolic link
        self.log(f"Creating Directory Symlink: '{win_path}' ---> '{target_win_unc}'")
        try:
            os.symlink(target_win_unc, win_path, target_is_directory=True)
            self.log("Symlink created successfully on Windows host.", is_success=True)
        except PermissionError:
            self.log("Permission Error: Administrator privileges are required to create symbolic links.", is_error=True)
            messagebox.showerror("Access Denied", "Creating directory symbolic links on Windows requires elevation.\n\nTo resolve this:\n1. Enable 'Developer Mode' in Windows Settings (Update & Security > For Developers)\nOR\n2. Run this application as Administrator.")
            return
        except Exception as e:
            self.log(f"Symlink failed: {e}", is_error=True)
            messagebox.showerror("Symlink Failure", f"Failed to create directory symbolic link:\n\n{e}")
            return

        # Save configuration to local database registry
        new_mapping = {
            "name": name,
            "windows_path": win_path,
            "wsl_distro": distro,
            "wsl_path": wsl_path,
            "created_at": datetime.datetime.now().isoformat()
        }
        registry["mappings"].append(new_mapping)
        self.save_registry(registry)
        
        self.log(f"Saved workspace mapping '{name}' to links registry.", is_success=True)
        
        # Clear fields
        self.entry_name.delete(0, tk.END)
        self.entry_win_path.delete(0, tk.END)
        self.entry_wsl_path.delete(0, tk.END)
        
        self.refresh_workspace_list()
        messagebox.showinfo("Success", f"Direct Symbolic Link '{name}' has been created successfully!")

    def delete_link(self, name, win_path, distro, wsl_path):
        """Removes Windows symlink folder safely via os.rmdir to preserve WSL contents."""
        confirm = messagebox.askyesno("Confirm Safe Deletion", f"Are you sure you want to remove the local symbolic link '{name}'?\n\nSafety check: The local Windows folder will be unlinked, but all your code files inside WSL ({wsl_path}) remain 100% untouched and safe.")
        if not confirm:
            return

        self.log(f"Removing symbolic link: '{name}'")
        win_path = os.path.abspath(win_path)

        if os.path.exists(win_path) or os.path.islink(win_path):
            if not os.path.islink(win_path):
                self.log("Action Aborted: Selection is a normal Windows directory, not a symbolic link! DANGER avoided.", is_error=True)
                messagebox.showerror("Safety Intercept", f"The directory path at '{win_path}' is a normal physical directory, not a symbolic link.\n\nDeletion has been aborted to prevent accidental file loss.")
                return

            try:
                # os.rmdir safely removes the directory symlink itself on Windows without recursing
                os.rmdir(win_path)
                self.log(f"Unlinked Windows workspace directory link: '{win_path}'", is_success=True)
            except Exception as e:
                self.log(f"Failed to remove symlink folder: {e}", is_error=True)
                messagebox.showerror("Deletion Error", f"Failed to delete the symbolic link folder:\n\n{e}")
                return
        else:
             self.log(f"Folder at '{win_path}' was already deleted. Cleaning up registry.")

        # Clean JSON database registry
        registry = self.load_registry()
        updated_mappings = [m for m in registry.get("mappings", []) if m["name"].lower() != name.lower()]
        registry["mappings"] = updated_mappings
        self.save_registry(registry)

        self.log(f"Removed '{name}' entry from registry map.", is_success=True)
        self.refresh_workspace_list()
        messagebox.showinfo("Removed", f"Workspace '{name}' has been safely unlinked!")

    def open_linux_bash(self, name, distro, wsl_path):
        """Spawns a native WSL Linux shell directly in the correct distro and directory.
        
        Launch priority:
          1. Windows Terminal (wt.exe) with the matching WSL distro profile — opens
             a proper tabbed terminal already logged into Linux.
          2. Plain wsl.exe with --cd — falls back gracefully on older Windows builds
             or systems without Windows Terminal installed.
        """
        self.log(f"Spawning WSL terminal inside '{distro}' at '{wsl_path}'...")

        # Strategy 1: Windows Terminal with correct WSL distro profile and starting directory
        # Convert the WSL Unix path to a Windows UNC path format so wt.exe can open it natively
        wsl_unc_path = f"\\\\wsl.localhost\\{distro}" + wsl_path.replace('/', '\\')
        wt_cmd = ["wt.exe", "-p", distro, "-d", wsl_unc_path]

        # Strategy 2: Fallback — direct wsl.exe in a new console window
        # "start" launches a detached window; wsl --cd lands directly in Linux directory
        fallback_cmd = f'start wsl.exe -d {distro} --cd "{wsl_path}"'

        try:
            # Check if Windows Terminal is available
            wt_check = subprocess.run(["where", "wt.exe"], capture_output=True, text=True)
            if wt_check.returncode == 0:
                subprocess.Popen(wt_cmd)
                self.log(f"Opened Windows Terminal → [{distro}] {wsl_path}", is_success=True)
            else:
                raise FileNotFoundError("wt.exe not found")
        except Exception:
            # Fallback to plain wsl.exe
            try:
                subprocess.run(fallback_cmd, shell=True)
                self.log(f"Opened WSL terminal → [{distro}] {wsl_path}", is_success=True)
            except Exception as e:
                self.log(f"Failed to launch terminal: {e}", is_error=True)
                messagebox.showerror("Launch Error", f"Failed to open a WSL terminal:\n\n{e}")

    def toggle_sidebar(self, force_hide=False, force_show=False, user_clicked=False):
        """Toggles the visibility of the link form sidebar card dynamically."""
        if user_clicked:
            self.user_toggled_sidebar = True

        if (self.sidebar_visible or force_hide) and not force_show:
            if not self.sidebar_visible:
                return
            # Hide the sidebar frame
            self.right_frame.pack_forget()
            # Set left frame to use full space
            self.left_frame.pack_configure(padx=0)
            self.btn_toggle_sidebar.configure(text="➕ Link New Workspace", fg_color=COLOR_ACCENT, hover_color=COLOR_ACCENT_HOVER)
            self.sidebar_visible = False
            self.log("Workspace form hidden. Mappings list expanded to full width.", is_success=True)
        else:
            if self.sidebar_visible:
                return
            # Show the sidebar frame on the right side
            self.left_frame.pack_configure(padx=(0, 15))
            self.right_frame.pack(fill=tk.BOTH, side=tk.RIGHT, padx=(15, 0))
            self.btn_toggle_sidebar.configure(text="✕ Close Form", fg_color="#2b2d3a", hover_color="#3e4052")
            self.sidebar_visible = True
            self.log("Workspace form sidebar revealed.", is_success=True)

    def on_window_resize(self, event):
        """Automatically collapses/expands the sidebar based on window size if not user-overridden."""
        if str(event.widget) != str(self):
            return
        
        w = event.width
        # Threshold layout: below 950px, we automatically hide the sidebar to prevent cramped lists.
        # Above 1050px, we automatically reveal it if the user hasn't explicitly closed it.
        if w < 950 and self.sidebar_visible and not self.user_toggled_sidebar:
            self.toggle_sidebar(force_hide=True)
        elif w >= 1050 and not self.sidebar_visible and not self.user_toggled_sidebar:
            self.toggle_sidebar(force_show=True)

if __name__ == "__main__":
    app = WSLLinkerApp()
    app.mainloop()
