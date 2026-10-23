#!/usr/bin/env python3
"""
Mesh Orchestrator CLI Engine

Orchestrates multi-agent, multi-container development environments with:
- Declarative topology parsing from mesh.json (--file)
- User-defined bridge network creation (mesh_net) with Docker internal DNS
- Concurrent shared named ext4 volume provisioning (mesh_contracts mounted at /shared/contracts)
- Independent cgroup resource limit enforcement (--cpus, --memory, --memory-swap, --pids-limit)
- Independent programmatic command execution (exec) with stdout/stderr capture and --json
- Reverse-dependency teardown (containers -> volumes -> network -> state file)
- Crash resilience with atexit and signal handlers
- State management isolated in .mesh_state.json (zero host config.json pollution)
"""

import os
import sys
import json
import time
import argparse
import subprocess
import signal
import atexit
import concurrent.futures
from pathlib import Path
from typing import Dict, Any, List, Optional, Set, Tuple

# In-flight resource tracking for crash resilience
_in_flight_resources: Dict[str, Set[str]] = {
    "containers": set(),
    "volumes": set(),
    "networks": set(),
}

_cleaned_up = False


def _in_flight_cleanup():
    global _cleaned_up
    if _cleaned_up:
        return
    _cleaned_up = True

    for cname in list(_in_flight_resources["containers"]):
        try:
            subprocess.run(["docker", "rm", "-f", cname], capture_output=True, timeout=10)
        except Exception:
            pass

    for vol in list(_in_flight_resources["volumes"]):
        try:
            subprocess.run(["docker", "volume", "rm", vol], capture_output=True, timeout=10)
        except Exception:
            pass

    for net in list(_in_flight_resources["networks"]):
        try:
            subprocess.run(["docker", "network", "rm", net], capture_output=True, timeout=10)
        except Exception:
            pass


atexit.register(_in_flight_cleanup)


def _signal_handler(signum, frame):
    _in_flight_cleanup()
    sys.exit(128 + signum)


try:
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
except Exception:
    pass


def find_mesh_file(file_arg: Optional[str] = None) -> Path:
    if file_arg:
        p = Path(file_arg).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Specified mesh topology file not found: {file_arg}")
        return p

    candidates = [
        Path.cwd() / "mesh.json",
        Path.cwd() / "test_projects" / "multi_agent_mesh" / "mesh.json",
        Path(__file__).resolve().parent.parent / "test_projects" / "multi_agent_mesh" / "mesh.json",
    ]
    for c in candidates:
        if c.exists():
            return c.resolve()

    # Fallback to mesh.json in cwd
    return (Path.cwd() / "mesh.json").resolve()


def get_state_file_path(mesh_file: Path) -> Path:
    return mesh_file.parent / ".mesh_state.json"


def load_state(mesh_file: Path) -> Dict[str, Any]:
    state_file = get_state_file_path(mesh_file)
    if state_file.exists():
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(mesh_file: Path, state_data: Dict[str, Any]) -> None:
    state_file = get_state_file_path(mesh_file)
    tmp_file = state_file.with_suffix(f".tmp.{os.getpid()}")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(state_data, f, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp_file, state_file)


def remove_state(mesh_file: Path) -> None:
    state_file = get_state_file_path(mesh_file)
    if state_file.exists():
        try:
            os.remove(state_file)
        except Exception:
            pass


def load_topology(mesh_file: Path) -> Dict[str, Any]:
    if not mesh_file.exists():
        raise FileNotFoundError(f"Mesh configuration file does not exist: {mesh_file}")
    with open(mesh_file, "r", encoding="utf-8") as f:
        return json.load(f)


def run_docker(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker"] + cmd,
        capture_output=True,
        text=True,
        check=check,
    )


# -----------------------------------------------------------------------------
# SUBCOMMAND: UP
# -----------------------------------------------------------------------------
def cmd_up(args: argparse.Namespace) -> int:
    mesh_file = find_mesh_file(args.file)
    topology = load_topology(mesh_file)

    mesh_name = topology.get("mesh_name", "multi_agent_mesh")
    network_cfg = topology.get("network", {})
    net_name = network_cfg.get("name", f"{mesh_name}_net")
    subnet = network_cfg.get("subnet")

    # Validation: driver
    driver = network_cfg.get("driver", "bridge")
    if driver not in ["bridge", "overlay", "macvlan", "ipvlan", "host", "none"]:
        err = f"Invalid network driver: {driver}"
        if args.json:
            print(json.dumps({"status": "error", "message": err}))
        else:
            print(f"[ERROR] {err}", file=sys.stderr)
        return 1

    volumes_cfg = topology.get("volumes", {})
    services_cfg = topology.get("services", {})

    # Validation: services must be a non-empty dictionary
    if not services_cfg or not isinstance(services_cfg, dict):
        err = "Invalid topology: 'services' must be a non-empty dictionary."
        if args.json:
            print(json.dumps({"status": "error", "message": err}))
        else:
            print(f"[ERROR] {err}", file=sys.stderr)
        return 1

    t0 = time.perf_counter()

    # 1. Provision Network
    inspect_net = run_docker(["network", "inspect", net_name], check=False)
    if inspect_net.returncode != 0:
        create_net_cmd = ["network", "create", "--driver", driver]
        if subnet:
            create_net_cmd.extend(["--subnet", subnet])
        create_net_cmd.append(net_name)
        res_net = run_docker(create_net_cmd, check=False)
        if res_net.returncode != 0:
            err = f"Failed to create network {net_name}: {res_net.stderr.strip()}"
            if args.json:
                print(json.dumps({"status": "error", "message": err}))
            else:
                print(f"[ERROR] {err}", file=sys.stderr)
            return 1
        _in_flight_resources["networks"].add(net_name)

    # 2. Provision Named Volumes
    created_volumes = []
    for vol_key, vol_info in volumes_cfg.items():
        vol_name = vol_key
        inspect_vol = run_docker(["volume", "inspect", vol_name], check=False)
        if inspect_vol.returncode != 0:
            res_vol = run_docker(["volume", "create", vol_name], check=False)
            if res_vol.returncode != 0:
                err = f"Failed to create volume {vol_name}: {res_vol.stderr.strip()}"
                if args.json:
                    print(json.dumps({"status": "error", "message": err}))
                else:
                    print(f"[ERROR] {err}", file=sys.stderr)
                return 1
            _in_flight_resources["volumes"].add(vol_name)
        created_volumes.append(vol_name)

    # 3. Provision Containers (Concurrently for maximum speed)
    def _provision_service(item: Tuple[str, Dict[str, Any]]) -> Tuple[Optional[str], Optional[Dict[str, Any]], Optional[str]]:
        svc_name, svc_cfg = item
        cname = svc_cfg.get("container_name", f"{mesh_name}_{svc_name}")
        image = svc_cfg.get("image", "python:3.12-alpine")
        command = svc_cfg.get("command", ["tail", "-f", "/dev/null"])
        if isinstance(command, str):
            command = [command]
        workdir = svc_cfg.get("workdir", "/app")

        # Cleanup prior container instance if exists
        insp_prior = run_docker(["inspect", cname], check=False)
        if insp_prior.returncode == 0:
            run_docker(["rm", "-f", cname], check=False)
        _in_flight_resources["containers"].add(cname)

        create_cmd = [
            "create",
            "--name",
            cname,
            "--network",
            net_name,
            "--network-alias",
            svc_name,
            "--network-alias",
            cname,
        ]

        # Resource limits
        if "cpus" in svc_cfg and svc_cfg["cpus"] is not None:
            create_cmd.extend(["--cpus", str(svc_cfg["cpus"])])

        if "memory" in svc_cfg and svc_cfg["memory"]:
            mem = str(svc_cfg["memory"]).lower()
            create_cmd.extend(["--memory", mem])
            mem_swap = str(svc_cfg.get("memory_swap", mem)).lower()
            create_cmd.extend(["--memory-swap", mem_swap])

        if "pids_limit" in svc_cfg and svc_cfg["pids_limit"] is not None:
            create_cmd.extend(["--pids-limit", str(svc_cfg["pids_limit"])])

        # Volumes
        svc_vols = svc_cfg.get("volumes", [])
        for v in svc_vols:
            create_cmd.extend(["-v", v])

        # Ports
        svc_ports = svc_cfg.get("ports", [])
        for p in svc_ports:
            create_cmd.extend(["-p", p])

        # Environment
        svc_env = svc_cfg.get("env", {})
        for k, val in svc_env.items():
            create_cmd.extend(["-e", f"{k}={val}"])

        # Workdir
        if workdir:
            create_cmd.extend(["-w", workdir])

        # Image & Command
        create_cmd.append(image)
        create_cmd.extend(command)

        res_create = run_docker(create_cmd, check=False)
        if res_create.returncode != 0:
            return None, None, f"Failed to create container {cname}: {res_create.stderr.strip()}"

        cid = res_create.stdout.strip()

        # Copy local source files if configured
        src_path = svc_cfg.get("src")
        if not src_path:
            candidate_src = mesh_file.parent / svc_name
            if candidate_src.exists() and candidate_src.is_dir():
                src_path = str(candidate_src)
        else:
            resolved_src = (mesh_file.parent / src_path).resolve()
            if resolved_src.exists():
                src_path = str(resolved_src)

        if src_path and Path(src_path).exists():
            src_str = str(Path(src_path).resolve())
            if Path(src_path).is_dir():
                src_str = os.path.join(src_str, ".")
            cp_cmd = ["cp", src_str, f"{cname}:{workdir}"]
            res_cp = run_docker(cp_cmd, check=False)
            if res_cp.returncode != 0:
                return None, None, f"Failed to copy {src_path} to {cname}:{workdir}: {res_cp.stderr.strip()}"

        # Start container
        res_start = run_docker(["start", cname], check=False)
        if res_start.returncode != 0:
            return None, None, f"Failed to start container {cname}: {res_start.stderr.strip()}"

        # Verify running
        running = False
        for _ in range(20):
            insp = run_docker(["inspect", "-f", "{{.State.Running}}", cname], check=False)
            if insp.stdout.strip() == "true":
                running = True
                break
            time.sleep(0.05)

        if not running:
            logs = run_docker(["logs", "--tail", "20", cname], check=False)
            return None, None, f"Container {cname} failed to stay running. Logs:\n{logs.stderr or logs.stdout}"

        return svc_name, {
            "id": cid[:12],
            "name": cname,
            "image": image,
            "service": svc_name,
            "cpus": svc_cfg.get("cpus"),
            "memory": svc_cfg.get("memory"),
            "pids_limit": svc_cfg.get("pids_limit"),
        }, None

    container_map: Dict[str, Dict[str, Any]] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(services_cfg))) as executor:
        results = list(executor.map(_provision_service, services_cfg.items()))

    for s_name, s_info, s_err in results:
        if s_err:
            if args.json:
                print(json.dumps({"status": "error", "message": s_err}))
            else:
                print(f"[ERROR] {s_err}", file=sys.stderr)
            return 1
        container_map[s_name] = s_info

    duration = time.perf_counter() - t0

    # Save state
    state_data = {
        "mesh_name": mesh_name,
        "mesh_file": str(mesh_file),
        "network": net_name,
        "volumes": created_volumes,
        "containers": container_map,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    save_state(mesh_file, state_data)

    # Disarm in-flight cleanup since provisioning is fully successful
    _in_flight_resources["containers"].clear()
    _in_flight_resources["volumes"].clear()
    _in_flight_resources["networks"].clear()

    out = {
        "status": "success",
        "mesh": mesh_name,
        "network": net_name,
        "volumes": created_volumes,
        "containers": {k: v["name"] for k, v in container_map.items()},
        "duration_seconds": round(duration, 3),
    }

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"[SUCCESS] Mesh '{mesh_name}' is UP in {duration:.2f}s")
        print(f"  Network: {net_name}")
        print(f"  Volumes: {', '.join(created_volumes)}")
        print("  Services:")
        for svc_name, info in container_map.items():
            print(f"    - {svc_name}: {info['name']} (limits: cpus={info['cpus']}, mem={info['memory']}, pids={info['pids_limit']})")

    return 0


# -----------------------------------------------------------------------------
# SUBCOMMAND: DOWN
# -----------------------------------------------------------------------------
def cmd_down(args: argparse.Namespace) -> int:
    mesh_file = find_mesh_file(args.file)
    state = load_state(mesh_file)
    topology = {}
    if mesh_file.exists():
        try:
            topology = load_topology(mesh_file)
        except Exception:
            pass

    mesh_name = state.get("mesh_name") or topology.get("mesh_name", "multi_agent_mesh")
    net_name = state.get("network") or topology.get("network", {}).get("name", f"{mesh_name}_net")

    # Collect containers to remove
    containers_to_remove: Set[str] = set()
    if "containers" in state:
        for info in state["containers"].values():
            if isinstance(info, dict) and "name" in info:
                containers_to_remove.add(info["name"])
            elif isinstance(info, str):
                containers_to_remove.add(info)

    if "services" in topology:
        for svc_name, svc_cfg in topology["services"].items():
            cname = svc_cfg.get("container_name", f"{mesh_name}_{svc_name}")
            containers_to_remove.add(cname)

    removed_containers = []
    # 1. Stop & Remove Containers
    for cname in containers_to_remove:
        run_docker(["stop", "-t", "3", cname], check=False)
        r = run_docker(["rm", "-f", cname], check=False)
        if r.returncode == 0:
            removed_containers.append(cname)

    # 2. Remove Shared Volumes
    removed_volumes = []
    if not getattr(args, "keep_volumes", False):
        vols_to_remove: Set[str] = set(state.get("volumes", []))
        if "volumes" in topology:
            for vol_k in topology["volumes"].keys():
                vols_to_remove.add(vol_k)

        for vol in vols_to_remove:
            r = run_docker(["volume", "rm", vol], check=False)
            if r.returncode == 0:
                removed_volumes.append(vol)

    # 3. Remove Network
    removed_networks = []
    if net_name:
        r = run_docker(["network", "rm", net_name], check=False)
        if r.returncode == 0:
            removed_networks.append(net_name)

    # 4. Remove State File
    remove_state(mesh_file)

    out = {
        "status": "success",
        "mesh": mesh_name,
        "removed_containers": removed_containers,
        "removed_volumes": removed_volumes,
        "removed_networks": removed_networks,
    }

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"[SUCCESS] Mesh '{mesh_name}' torn down cleanly.")
        if removed_containers:
            print(f"  Removed containers: {', '.join(removed_containers)}")
        if removed_volumes:
            print(f"  Removed volumes: {', '.join(removed_volumes)}")
        if removed_networks:
            print(f"  Removed networks: {', '.join(removed_networks)}")

    return 0


# -----------------------------------------------------------------------------
# SUBCOMMAND: EXEC
# -----------------------------------------------------------------------------
def cmd_exec(args: argparse.Namespace) -> int:
    mesh_file = find_mesh_file(args.file)
    state = load_state(mesh_file)
    target = args.service

    # Resolve target to container name
    cname = None
    if "containers" in state and target in state["containers"]:
        cname = state["containers"][target].get("name")
    elif "containers" in state:
        for svc_k, info in state["containers"].items():
            if isinstance(info, dict) and info.get("name") == target:
                cname = target
                break

    if not cname:
        # Fallback to topology or direct name
        if mesh_file.exists():
            try:
                topo = load_topology(mesh_file)
                if target in topo.get("services", {}):
                    cname = topo["services"][target].get("container_name", f"{topo.get('mesh_name', 'multi_agent_mesh')}_{target}")
            except Exception:
                pass

    if not cname:
        cname = target

    # Clean command arguments (strip leading '--' if passed)
    cmd_args = list(args.cmd)
    if cmd_args and cmd_args[0] == "--":
        cmd_args = cmd_args[1:]

    if not cmd_args:
        err = "No command specified to execute."
        if args.json:
            print(json.dumps({"status": "error", "message": err}))
        else:
            print(f"[ERROR] {err}", file=sys.stderr)
        return 1

    exec_cmd = ["docker", "exec"]
    if args.user:
        exec_cmd.extend(["-u", args.user])
    if args.workdir:
        exec_cmd.extend(["-w", args.workdir])
    exec_cmd.append(cname)
    exec_cmd.extend(cmd_args)

    t0 = time.perf_counter()
    proc = subprocess.run(exec_cmd, capture_output=True, text=True)
    duration_ms = (time.perf_counter() - t0) * 1000.0

    if args.json:
        out = {
            "status": "success" if proc.returncode == 0 else "error",
            "service": target,
            "container": cname,
            "exit_code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "duration_ms": round(duration_ms, 2),
        }
        print(json.dumps(out, indent=2))
    else:
        if proc.stdout:
            sys.stdout.write(proc.stdout)
            sys.stdout.flush()
        if proc.stderr:
            sys.stderr.write(proc.stderr)
            sys.stderr.flush()

    return proc.returncode


# -----------------------------------------------------------------------------
# SUBCOMMAND: STATUS
# -----------------------------------------------------------------------------
def cmd_status(args: argparse.Namespace) -> int:
    mesh_file = find_mesh_file(args.file)
    state = load_state(mesh_file)
    topology = {}
    if mesh_file.exists():
        try:
            topology = load_topology(mesh_file)
        except Exception:
            pass

    mesh_name = state.get("mesh_name") or topology.get("mesh_name", "multi_agent_mesh")
    net_name = state.get("network") or topology.get("network", {}).get("name")

    status_data: Dict[str, Any] = {
        "mesh": mesh_name,
        "network": net_name,
        "services": {},
    }

    # Query network inspect
    if net_name:
        insp_net = run_docker(["network", "inspect", net_name], check=False)
        status_data["network_active"] = (insp_net.returncode == 0)

    # Collect service names
    services_to_check = {}
    if "containers" in state:
        services_to_check.update(state["containers"])
    elif "services" in topology:
        for svc_name, svc_cfg in topology["services"].items():
            services_to_check[svc_name] = {"name": svc_cfg.get("container_name", f"{mesh_name}_{svc_name}")}

    all_healthy = True
    for svc_name, info in services_to_check.items():
        cname = info.get("name") if isinstance(info, dict) else info
        insp = run_docker(["inspect", cname], check=False)
        if insp.returncode == 0:
            try:
                data = json.loads(insp.stdout)[0]
                state_info = data.get("State", {})
                net_settings = data.get("NetworkSettings", {})
                ip_addr = ""
                for net_k, net_v in net_settings.get("Networks", {}).items():
                    if net_v.get("IPAddress"):
                        ip_addr = net_v.get("IPAddress")
                        break

                svc_status = {
                    "container": cname,
                    "running": state_info.get("Running", False),
                    "status": state_info.get("Status", "unknown"),
                    "exit_code": state_info.get("ExitCode", 0),
                    "ip_address": ip_addr,
                    "started_at": state_info.get("StartedAt"),
                    "nano_cpus": data.get("HostConfig", {}).get("NanoCpus"),
                    "memory": data.get("HostConfig", {}).get("Memory"),
                    "pids_limit": data.get("HostConfig", {}).get("PidsLimit"),
                }
                if not svc_status["running"]:
                    all_healthy = False
            except Exception as e:
                svc_status = {"container": cname, "running": False, "error": str(e)}
                all_healthy = False
        else:
            svc_status = {"container": cname, "running": False, "status": "not_found"}
            all_healthy = False

        status_data["services"][svc_name] = svc_status

    status_data["healthy"] = all_healthy

    if args.json:
        print(json.dumps(status_data, indent=2))
    else:
        print(f"Mesh: {mesh_name} (Network: {net_name}, Status: {'HEALTHY' if all_healthy else 'DEGRADED'})")
        for svc, s in status_data["services"].items():
            state_str = "RUNNING" if s.get("running") else f"STOPPED ({s.get('status')})"
            print(f"  - {svc} ({s.get('container')}): {state_str} IP: {s.get('ip_address')}")

    return 0 if all_healthy else 1


# -----------------------------------------------------------------------------
# SUBCOMMAND: HEAL
# -----------------------------------------------------------------------------
def cmd_heal(args: argparse.Namespace) -> int:
    mesh_file = find_mesh_file(args.file)
    state = load_state(mesh_file)
    topology = {}
    if mesh_file.exists():
        try:
            topology = load_topology(mesh_file)
        except Exception:
            pass

    net_name = state.get("network") or topology.get("network", {}).get("name")
    healed: List[str] = []

    # Verify/repair network
    if net_name:
        insp_net = run_docker(["network", "inspect", net_name], check=False)
        if insp_net.returncode != 0:
            run_docker(["network", "create", "--driver", "bridge", net_name], check=False)
            healed.append(f"recreated_network:{net_name}")

    target_service = getattr(args, "service", None)
    containers_to_check = {}
    if "containers" in state:
        containers_to_check.update(state["containers"])

    for svc_name, info in containers_to_check.items():
        if target_service and svc_name != target_service:
            continue
        cname = info.get("name") if isinstance(info, dict) else info
        insp = run_docker(["inspect", "-f", "{{.State.Running}}", cname], check=False)
        if insp.returncode != 0 or insp.stdout.strip() != "true":
            # Restart container
            r = run_docker(["start", cname], check=False)
            if r.returncode == 0:
                healed.append(f"restarted_container:{cname}")
            else:
                # If cannot start, recreate from topology
                if "services" in topology and svc_name in topology["services"]:
                    cmd_up(args)
                    healed.append(f"reprovisioned_mesh")
                    break

    out = {
        "status": "success",
        "healed": healed,
    }

    if args.json:
        print(json.dumps(out, indent=2))
    else:
        print(f"[HEAL] Completed. Actions taken: {', '.join(healed) if healed else 'None (all healthy)'}")

    return 0


# -----------------------------------------------------------------------------
# SUBCOMMAND: BENCHMARK
# -----------------------------------------------------------------------------
def cmd_benchmark(args: argparse.Namespace) -> int:
    benchmark_script = Path(__file__).resolve().parent / "mesh_benchmark.py"
    if not benchmark_script.exists():
        err = f"Benchmark script not found at {benchmark_script}"
        if args.json:
            print(json.dumps({"status": "error", "message": err}))
        else:
            print(f"[ERROR] {err}", file=sys.stderr)
        return 1

    cmd = [sys.executable, str(benchmark_script)]
    if getattr(args, "file", None):
        cmd.extend(["--file", str(args.file)])
    if getattr(args, "output", None):
        cmd.extend(["--output", str(args.output)])
    if getattr(args, "quick", False):
        cmd.append("--quick")

    proc = subprocess.run(cmd)
    return proc.returncode


# -----------------------------------------------------------------------------
# CLI PARSER
# -----------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mesh_orchestrator",
        description="Multi-Agent Multi-Container Mesh Orchestrator Engine",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # Subcommand: up
    p_up = subparsers.add_parser("up", help="Provision and start mesh containers, networks, and volumes")
    p_up.add_argument("--file", "-f", help="Path to mesh.json topology file")
    p_up.add_argument("--detach", "-d", action="store_true", default=True, help="Run containers in background")
    p_up.add_argument("--json", action="store_true", help="Output result in JSON format")

    # Subcommand: down
    p_down = subparsers.add_parser("down", help="Tear down all mesh containers, networks, and volumes")
    p_down.add_argument("--file", "-f", help="Path to mesh.json topology file")
    p_down.add_argument("--keep-volumes", action="store_true", help="Preserve shared named volumes")
    p_down.add_argument("--json", action="store_true", help="Output result in JSON format")

    # Subcommand: exec
    p_exec = subparsers.add_parser("exec", help="Execute command inside a mesh container")
    p_exec.add_argument("service", help="Service name or container name")
    p_exec.add_argument("--file", "-f", help="Path to mesh.json topology file")
    p_exec.add_argument("--user", "-u", help="Username or UID inside container")
    p_exec.add_argument("--workdir", "-w", help="Working directory inside container")
    p_exec.add_argument("--json", action="store_true", help="Output result in JSON format")
    p_exec.add_argument("cmd", nargs="+", help="Command and arguments to execute")

    # Subcommand: status
    p_status = subparsers.add_parser("status", help="Inspect status and health of mesh services")
    p_status.add_argument("--file", "-f", help="Path to mesh.json topology file")
    p_status.add_argument("--json", action="store_true", help="Output result in JSON format")

    # Subcommand: heal
    p_heal = subparsers.add_parser("heal", help="Repair dead or disconnected mesh containers")
    p_heal.add_argument("--file", "-f", help="Path to mesh.json topology file")
    p_heal.add_argument("--service", "-s", help="Target specific service to heal")
    p_heal.add_argument("--json", action="store_true", help="Output result in JSON format")

    # Subcommand: benchmark
    p_bench = subparsers.add_parser("benchmark", help="Run automated performance benchmark and verification harness")
    p_bench.add_argument("--file", "-f", help="Path to mesh.json topology file")
    p_bench.add_argument("--output", "-o", help="Path to output BENCHMARK_REPORT.json")
    p_bench.add_argument("--quick", action="store_true", help="Run quick benchmark pass")
    p_bench.add_argument("--json", action="store_true", help="Output result in JSON format")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    dispatch = {
        "up": cmd_up,
        "down": cmd_down,
        "exec": cmd_exec,
        "status": cmd_status,
        "heal": cmd_heal,
        "benchmark": cmd_benchmark,
    }

    handler = dispatch.get(args.subcommand)
    if not handler:
        parser.print_help()
        return 1

    try:
        return handler(args)
    except Exception as e:
        if getattr(args, "json", False):
            print(json.dumps({"status": "error", "error": str(e)}))
        else:
            print(f"[ERROR] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
