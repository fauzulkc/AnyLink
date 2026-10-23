#!/usr/bin/env python3
import os
import sys
import json
import argparse
import subprocess
import datetime
import tempfile
import shutil
from pathlib import Path

# Safe encoding for Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# ANSI colors for beautiful terminal output
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
CYAN = "\033[96m"
RESET = "\033[0m"
BOLD = "\033[1m"

def get_registry_path():
    """Get the path to the central JSON link registry in user home."""
    env_dir = os.environ.get("WSL_LINKER_CONFIG_DIR")
    registry_dir = Path(env_dir) if env_dir else Path.home() / ".wsl-linker"
    registry_dir.mkdir(parents=True, exist_ok=True)
    return registry_dir / "links.json"

def load_registry():
    """Load registry mappings with corruption backup."""
    path = get_registry_path()
    if not path.exists():
        return {"mappings": []}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError(f"Root JSON entity in '{path}' must be an object")
            if "mappings" not in data:
                data["mappings"] = []
            return data
    except Exception as e:
        bak_path = path.with_name(path.name + ".corrupt.bak")
        try:
            shutil.copy2(path, bak_path)
        except Exception:
            pass
        raise RuntimeError(f"Corrupt registry at '{path}': {e}. Backup created at '{bak_path}'") from e

def save_registry(data):
    """Save registry mappings atomically."""
    path = get_registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    dir_path = path.parent
    temp_file = None
    try:
        with tempfile.NamedTemporaryFile("w", dir=dir_path, delete=False, encoding="utf-8") as f:
            temp_file = f.name
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_file, path)
        temp_file = None
    except Exception as e:
        sys.stderr.write(f"{RED}Error saving registry: {e}{RESET}\n")
        raise
    finally:
        if temp_file and os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except Exception:
                pass

def is_admin_windows():
    """Check if the script is running with Windows Administrator privileges."""
    if os.name != 'nt':
        return True
    import ctypes
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return False

def check_windows_drive_type(win_path):
    """Verify that the destination drive is a local fixed drive (DRIVE_FIXED)."""
    if os.name != 'nt':
        return True, "non-windows"
    import ctypes
    root = os.path.splitdrive(os.path.abspath(win_path))[0] + "\\"
    drive_type = ctypes.windll.kernel32.GetDriveTypeW(root)
    # 3: DRIVE_FIXED, 4: DRIVE_REMOTE
    if drive_type == 4:
        return False, "remote_network"
    elif drive_type == 3:
        return True, "local_fixed"
    return True, f"type_{drive_type}"

def add_link(args):
    """Create a new symbolic link and save it to the registry."""
    win_path = os.path.abspath(args.windows_path)
    distro = args.distro or "Ubuntu-24.04"
    name = args.name or os.path.basename(win_path.rstrip("\\/"))

    if not name:
        sys.stderr.write(f"{RED}Error: Could not derive a valid name. Please provide one with --name.{RESET}\n")
        sys.exit(1)

    # Normalize WSL target path to always ensure leading slash
    wsl_path = "/" + args.wsl_path.strip().replace('\\', '/').lstrip('/')

    # Check if this name or local path already exists in registry
    registry = load_registry()
    for mapping in registry["mappings"]:
        if mapping["name"].lower() == name.lower():
            sys.stderr.write(f"{RED}Error: A mapping named '{name}' already exists.{RESET}\n")
            sys.exit(1)
        if os.path.abspath(mapping["windows_path"]).lower() == win_path.lower():
            sys.stderr.write(f"{RED}Error: Local path '{win_path}' is already linked to '{mapping['wsl_path']}'.{RESET}\n")
            sys.exit(1)

    # Check drive type on Windows
    is_fixed, drive_desc = check_windows_drive_type(win_path)
    if not is_fixed:
        print(f"{YELLOW}Warning: Destination drive is a network or remote drive ({drive_desc}).{RESET}")
        print(f"{YELLOW}Network drives are resolved to UNC paths (\\\\wsl.localhost\\...) by many tools,{RESET}")
        print(f"{YELLOW}and file watchers/path validation often fail on them (IDEs, agent harnesses, etc.).{RESET}")
        print(f"{YELLOW}For best compatibility, use a local fixed drive (such as D:\\ or C:\\).{RESET}")

    # Target path in Windows for symbolic link creation (guaranteed leading slash)
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
        sys.stderr.write(f"{RED}Error: Failed to ensure WSL directory '{wsl_path}' exists: {e}{RESET}\n")
        sys.exit(1)

    # Verify if Windows destination directory already exists
    if os.path.exists(win_path):
        sys.stderr.write(f"{RED}Error: The Windows destination '{win_path}' already exists.{RESET}\n{YELLOW}Hint: To create a symlink, the target folder path must not already exist as a normal directory.{RESET}\n")
        sys.exit(1)

    print(f"{CYAN}Creating link: {BOLD}{win_path}{RESET} {CYAN}--->{RESET} {BOLD}{target_win_unc}{RESET}")

    # Perform Symbolic Link Creation
    try:
        if os.name == 'nt':
            os.symlink(target_win_unc, win_path, target_is_directory=True)
        else:
            os.symlink(wsl_path, win_path)
        print(f"{GREEN}✔ Directory symbolic link created successfully!{RESET}")
    except PermissionError:
        sys.stderr.write(f"{RED}Permission Error: Symbolic link creation requires elevation on Windows.{RESET}\n{YELLOW}Solutions:{RESET}\n 1. Run your terminal/command prompt as {BOLD}Administrator{RESET}.\n 2. Enable {BOLD}Developer Mode{RESET} in Windows Settings (Settings > Update & Security > For Developers).\n")
        sys.exit(1)
    except Exception as e:
        sys.stderr.write(f"{RED}Failed to create symbolic link: {e}{RESET}\n")
        sys.exit(1)

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
    print(f"{GREEN}✔ Open this folder in any IDE or agent harness: {BOLD}{win_path}{RESET}")

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
        if os.path.exists(target) and os.path.islink(target):
            win_path = os.path.abspath(target)
            print(f"{YELLOW}Warning: Path is a symbolic link but not found in the registry. Attempting direct removal...{RESET}")
        else:
            sys.stderr.write(f"{RED}Error: No link named '{target}' found in mappings registry.{RESET}\n")
            sys.exit(1)
    else:
        win_path = match["windows_path"]

    # Safely remove symbolic link (NEVER delete normal directory)
    if os.path.exists(win_path) or os.path.islink(win_path):
        if not os.path.islink(win_path):
            sys.stderr.write(f"{RED}Safety Error: '{win_path}' is a normal directory, not a symbolic link!{RESET}\n{YELLOW}Aborting to prevent accidental data deletion.{RESET}\n")
            sys.exit(1)

        try:
            print(f"{CYAN}Safely removing Windows symbolic link: {BOLD}{win_path}{RESET}")
            if os.name == 'nt':
                os.rmdir(win_path)
            else:
                os.unlink(win_path)
            print(f"{GREEN}✔ Symbolic link removed successfully. (WSL target files remain fully preserved!){RESET}")
        except Exception as e:
            sys.stderr.write(f"{RED}Failed to remove link file: {e}{RESET}\n")
            sys.exit(1)
    else:
        print(f"{YELLOW}Warning: Physical symbolic link folder at '{win_path}' was already deleted.{RESET}")

    if match:
        registry["mappings"].remove(match)
        save_registry(registry)
        print(f"{GREEN}✔ Removed '{match['name']}' registry entry.{RESET}")

def list_links(args):
    """Print the registry links map."""
    registry = load_registry()
    mappings = registry["mappings"]

    if not mappings:
        print(f"{YELLOW}No mapped WSL links found.{RESET}")
        print("Use 'wsl-linker add' to create a link.")
        return

    print(f"\n{BOLD}{GREEN}WSL Linker Registry Mappings{RESET}")
    print("=" * 110)
    print(f"{BOLD}{'Name':<20} | {'Windows Path':<38} | {'Distro':<14} | {'WSL Target Path'}{RESET}")
    print("-" * 110)
    for m in mappings:
        print(f"{m['name']:<20} | {m['windows_path']:<38} | {m['wsl_distro']:<14} | {m['wsl_path']}")
    print("=" * 110)
    print(f"Config path: {get_registry_path()}\n")

def run_command(args):
    """Translate path context and proxy execution inside WSL."""
    current_dir = os.path.abspath(os.getcwd())
    registry = load_registry()
    match = None

    for mapping in registry["mappings"]:
        win_path = os.path.abspath(mapping["windows_path"])
        if current_dir.lower() == win_path.lower() or current_dir.lower().startswith(win_path.lower() + os.sep):
            match = mapping
            break

    if not match:
        sys.stderr.write(f"{RED}Error: Current directory is not inside any registered wsl-linker workspace.{RESET}\n{YELLOW}Please navigate to a linked workspace or register one using 'wsl-linker add'.{RESET}\n")
        sys.exit(1)

    win_root = os.path.abspath(match["windows_path"])
    rel = os.path.relpath(current_dir, win_root)
    if rel == ".":
        guest_target_dir = match["wsl_path"]
    else:
        guest_target_dir = (match["wsl_path"].rstrip('/') + "/" + rel.replace('\\', '/')).replace('//', '/')

    command = " ".join(args.cmd_args)
    if not command:
        sys.stderr.write(f"{RED}Error: Please specify a command to execute inside WSL.{RESET}\n{YELLOW}Example: wsl-linker run npm install{RESET}\n")
        sys.exit(1)

    print(f"{CYAN}[wsl-linker] Executing inside {match['wsl_distro']} ({guest_target_dir}):{RESET}")
    print(f"{BOLD}> {command}{RESET}\n")

    try:
        wsl_exec = ["wsl", "-d", match["wsl_distro"], "--cd", guest_target_dir, "-e", "bash", "-c", command]
        result = subprocess.run(wsl_exec)
        sys.exit(result.returncode)
    except Exception as e:
        sys.stderr.write(f"{RED}Failed to execute command in WSL: {e}{RESET}\n")
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        description="WSL Linker - Open Source Windows to WSL Directory Symlinker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
{BOLD}Examples:{RESET}
  wsl-linker add D:\\code\\my-project /home/user/code/my-project --distro Ubuntu-24.04
  wsl-linker list
  wsl-linker run npm install
  wsl-linker remove my-project
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
