#!/usr/bin/env python3
import os
import sys
import json
import argparse
import subprocess
import datetime
from pathlib import Path

# ANSI colors for beautiful terminal output
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

def get_registry_path():
    """Get the path to the central JSON link registry in user home."""
    home = Path.home()
    registry_dir = home / ".wsl-linker"
    registry_dir.mkdir(parents=True, exist_ok=True)
    return registry_dir / "links.json"

def load_registry():
    """Load registry mappings."""
    path = get_registry_path()
    if not path.exists():
        return {"mappings": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"mappings": []}

def save_registry(data):
    """Save registry mappings."""
    path = get_registry_path()
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"{RED}Error saving registry: {e}{RESET}")

def is_admin_windows():
    """Check if the script is running with Windows Administrator privileges."""
    if os.name != 'nt':
        return True
    import ctypes
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def add_link(args):
    """Create a new symbolic link and save it to the registry."""
    win_path = os.path.abspath(args.windows_path)
    wsl_path = args.wsl_path.replace('\\', '/')
    distro = args.distro or "Ubuntu-24.04"
    name = args.name or os.path.basename(win_path.rstrip("\\/"))

    if not name:
        print(f"{RED}Error: Could not derive a valid name. Please provide one with --name.{RESET}")
        return

    # Check if this name or local path already exists in registry
    registry = load_registry()
    for mapping in registry["mappings"]:
        if mapping["name"].lower() == name.lower():
            print(f"{RED}Error: A mapping named '{name}' already exists.{RESET}")
            return
        if os.path.abspath(mapping["windows_path"]).lower() == win_path.lower():
            print(f"{RED}Error: Local path '{win_path}' is already linked to '{mapping['wsl_path']}'.{RESET}")
            return

    # Target path in Windows for symbolic link creation
    target_win_unc = f"\\\\wsl.localhost\\{distro}" + wsl_path.replace('/', '\\')

    # Verify if WSL distro actually exists
    try:
        distro_check = subprocess.run(["wsl", "-d", distro, "-e", "true"], capture_output=True, text=True)
        if distro_check.returncode != 0:
            print(f"{YELLOW}Warning: WSL distro '{distro}' was not detected or is not running.{RESET}")
    except Exception:
         print(f"{YELLOW}Warning: Could not verify WSL installation.{RESET}")

    # Ensure remote directory exists inside WSL
    try:
        subprocess.run(["wsl", "-d", distro, "-e", "mkdir", "-p", wsl_path], check=True)
    except Exception as e:
        print(f"{RED}Error: Failed to ensure WSL directory '{wsl_path}' exists: {e}{RESET}")
        return

    # Verify if Windows destination directory already exists
    if os.path.exists(win_path):
        print(f"{RED}Error: The Windows destination '{win_path}' already exists.{RESET}")
        print(f"{YELLOW}Hint: To create a symlink, the target folder path must not already exist as a normal directory.{RESET}")
        return

    print(f"{CYAN}Creating link: {BOLD}{win_path}{RESET} {CYAN}--->{RESET} {BOLD}{target_win_unc}{RESET}")

    # Perform Symbolic Link Creation
    try:
        if os.name == 'nt':
            # Create directory symlink in Windows
            os.symlink(target_win_unc, win_path, target_is_directory=True)
        else:
            # Unix-like fallback
            os.symlink(wsl_path, win_path)
        print(f"{GREEN}✔ Directory symbolic link created successfully!{RESET}")
    except PermissionError:
        print(f"{RED}Permission Error: Symbolic link creation requires elevation on Windows.{RESET}")
        print(f"{YELLOW}Solutions:{RESET}")
        print(f" 1. Run your terminal/command prompt as {BOLD}Administrator{RESET}.")
        print(f" 2. Enable {BOLD}Developer Mode{RESET} in Windows Settings (Settings > Update & Security > For Developers).")
        return
    except Exception as e:
        print(f"{RED}Failed to create symbolic link: {e}{RESET}")
        return

    # Save to JSON registry
    new_mapping = {
        "name": name,
        "windows_path": win_path,
        "wsl_distro": distro,
        "wsl_path": wsl_path,
        "created_at": datetime.datetime.now().isoformat()
    }
    registry["mappings"].append(new_mapping)
    save_registry(registry)
    print(f"{GREEN}✔ Saved link '{name}' to mappings registry.{RESET}")

def remove_link(args):
    """Safely delete the symbolic link and remove it from the registry."""
    target = args.name_or_path
    registry = load_registry()
    match = None

    for mapping in registry["mappings"]:
        if mapping["name"].lower() == target.lower() or os.path.abspath(mapping["windows_path"]).lower() == os.path.abspath(target).lower():
            match = mapping
            break

    if not match:
        # Fallback to direct path deletion if symlink exists but is not registered
        if os.path.exists(target) and os.path.islink(target):
            win_path = os.path.abspath(target)
            print(f"{YELLOW}Warning: Path is a symbolic link but not found in the registry. Attempting direct removal...{RESET}")
        else:
            print(f"{RED}Error: No link named '{target}' found in mappings registry.{RESET}")
            return
    else:
        win_path = match["windows_path"]

    # Safely remove symbolic link
    if os.path.exists(win_path) or os.path.islink(win_path):
        if not os.path.islink(win_path):
            print(f"{RED}Safety Error: '{win_path}' is a normal directory, not a symbolic link!{RESET}")
            print(f"{YELLOW}Aborting to prevent accidental data deletion.{RESET}")
            return
        
        try:
            print(f"{CYAN}Safely removing Windows symbolic link: {BOLD}{win_path}{RESET}")
            if os.name == 'nt':
                # os.rmdir safely deletes the directory symbolic link, leaving target folder untouched
                os.rmdir(win_path)
            else:
                os.unlink(win_path)
            print(f"{GREEN}✔ Symbolic link removed successfully. (WSL target files remain fully preserved!){RESET}")
        except Exception as e:
            print(f"{RED}Failed to remove link file: {e}{RESET}")
            return
    else:
        print(f"{YELLOW}Warning: Physical symbolic link folder at '{win_path}' was already deleted.{RESET}")

    if match:
        registry["mappings"].remove(match)
        save_registry(registry)
        print(f"{GREEN}✔ Removed '{match['name']}' registry entry.{RESET}")

def list_links(args):
    """Print the registry links map in a beautiful layout."""
    registry = load_registry()
    mappings = registry["mappings"]

    if not mappings:
        print(f"{YELLOW}No mapped WSL links found.{RESET}")
        print("Use 'wsl-linker add' to create a link.")
        return

    print(f"\n{BOLD}{GREEN}WSL Linker Registry Mappings{RESET}")
    print("=" * 110)
    print(f"{BOLD}{'Name':<20} | {'Windows Path':<40} | {'Distro':<15} | {'WSL Target Path':<25}{RESET}")
    print("-" * 110)
    for m in mappings:
        print(f"{m['name']:<20} | {m['windows_path']:<40} | {m['wsl_distro']:<15} | {m['wsl_path']:<25}")
    print("=" * 110)
    print(f"Config path: {get_registry_path()}\n")

def run_command(args):
    """Translate path context and proxy execution inside WSL."""
    current_dir = os.path.abspath(os.getcwd())
    registry = load_registry()
    match = None

    # Find which mapped link our current directory belongs to
    for mapping in registry["mappings"]:
        win_path = os.path.abspath(mapping["windows_path"])
        if current_dir.lower() == win_path.lower() or current_dir.lower().startswith(win_path.lower() + os.sep):
            match = mapping
            break

    if not match:
        print(f"{RED}Error: Current directory is not inside any registered wsl-linker workspace.{RESET}")
        print("Please navigate to a linked workspace or register one using 'wsl-linker add'.")
        return

    # Translate the directory path relative to the symlink root
    win_root = os.path.abspath(match["windows_path"])
    relative = current_dir[len(win_root):].replace('\\', '/')
    guest_target_dir = (match["wsl_path"] + relative).replace('//', '/')
    
    # Extract command arguments
    command = " ".join(args.cmd_args)
    if not command:
        print(f"{RED}Error: Please specify a command to execute inside WSL.{RESET}")
        print("Example: wsl-linker run npm install")
        return

    print(f"{CYAN}[wsl-linker] Executing inside {match['wsl_distro']} ({guest_target_dir}):{RESET}")
    print(f"{BOLD}> {command}{RESET}\n")

    # Call WSL to execute the proxied command
    try:
        wsl_exec = ["wsl", "-d", match["wsl_distro"], "-e", "bash", "-c", f"cd '{guest_target_dir}' && {command}"]
        result = subprocess.run(wsl_exec)
        sys.exit(result.returncode)
    except Exception as e:
        print(f"{RED}Failed to execute command in WSL: {e}{RESET}")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        description="WSL Linker - Open Source Windows to WSL Directory Symlinker and Proxy Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
{BOLD}Examples:{RESET}
  wsl-linker add D:\\projects\\workspace /home/fauzul/projects/fauzul --distro Ubuntu-24.04
  wsl-linker list
  wsl-linker run npm install
  wsl-linker remove my-workspace
        """
    )
    
    subparsers = parser.add_subparsers(title="commands", dest="command", required=True)

    # ADD Command
    parser_add = subparsers.add_parser("add", help="Link a Windows folder path to a WSL path")
    parser_add.add_argument("windows_path", help="Local Windows folder path (must not exist yet)")
    parser_add.add_argument("wsl_path", help="Target WSL Linux directory path (e.g. /home/user/code)")
    parser_add.add_argument("-d", "--distro", help="WSL target distribution name (defaults to 'Ubuntu-24.04')")
    parser_add.add_argument("-n", "--name", help="Custom alias name for the mapping registry")

    # REMOVE Command
    parser_remove = subparsers.add_parser("remove", help="Safely remove a symbolic link and its registry mapping")
    parser_remove.add_argument("name_or_path", help="Registry alias name or local Windows folder path")

    # LIST Command
    subparsers.add_parser("list", help="List all registered mappings and connection status")

    # RUN Command
    parser_run = subparsers.add_parser("run", help="Proxy execution of a terminal command inside the linked WSL folder")
    parser_run.add_argument("cmd_args", nargs=argparse.REMAINDER, help="Command and arguments to run (e.g., npm install)")

    # Parse arguments
    args = parser.parse_args()

    # Dispatch command handlers
    if args.command == "add":
        add_link(args)
    elif args.command == "remove":
        remove_link(args)
    elif args.command == "list":
        list_links(args)
    elif args.command == "run":
        run_command(args)

if __name__ == "__main__":
    main()
