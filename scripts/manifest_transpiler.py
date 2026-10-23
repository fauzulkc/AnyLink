#!/usr/bin/env python3
"""
Bi-Directional Manifest Transpiler:
Docker Compose & Kubernetes <===> AnyLink / ext4 Container Mesh (mesh.json)

Capabilities:
1. Compose -> Mesh: Ingests docker-compose.yml, transforms slow host bind-mounts into
   isolated ext4 named volumes (with optional AnyLink host-link bridges), extracts
   cgroup quotas and bridge networks.
2. Kubernetes -> Mesh: Ingests multi-document K8s YAML (Deployments, Pods, Services, ConfigMaps),
   normalizes CPU (e.g. 500m -> 0.5) and Memory (e.g. 256Mi -> 256m), and builds mesh topology.
3. Mesh -> Compose: Exports mesh.json into canonical, production-grade docker-compose.yml.
4. Mesh -> Kubernetes: Exports mesh.json into standard Kubernetes Deployment & Service manifests.
"""

import os
import sys
import re
import json
import yaml
import argparse
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple, Union


def parse_k8s_cpu(cpu_str: Union[str, int, float]) -> float:
    """Converts K8s CPU string (e.g. '500m', '1.5', '2') to float cores."""
    if isinstance(cpu_str, (int, float)):
        return float(cpu_str)
    s = str(cpu_str).strip()
    if s.endswith("m"):
        return float(s[:-1]) / 1000.0
    return float(s)


def parse_k8s_memory(mem_str: Union[str, int]) -> str:
    """Converts K8s memory string (e.g. '256Mi', '1Gi', '512M') to Docker-compatible string ('256m', '1024m')."""
    s = str(mem_str).strip()
    match = re.match(r"^(\d+)([A-Za-z]+)?$", s)
    if not match:
        return s
    val = int(match.group(1))
    unit = match.group(2) or ""
    unit_lower = unit.lower()

    if unit_lower in ("gi", "g"):
        return f"{val * 1024}m"
    elif unit_lower in ("mi", "m"):
        return f"{val}m"
    elif unit_lower in ("ki", "k"):
        return f"{max(1, val // 1024)}m"
    return f"{val}m"


class ManifestTranspiler:
    """Core transpilation engine between Docker Compose / K8s and AnyLink mesh.json."""

    def __init__(self, optimize_volumes: bool = True, default_base_image: str = "python:3.12-alpine"):
        self.optimize_volumes = optimize_volumes
        self.default_base_image = default_base_image

    # -------------------------------------------------------------------------
    # Compose -> Mesh
    # -------------------------------------------------------------------------
    def compose_to_mesh(self, compose_dict: Dict[str, Any], project_name: str = "mesh_project") -> Dict[str, Any]:
        """Transpiles a Docker Compose v2/v3 dictionary into a canonical mesh.json."""
        mesh: Dict[str, Any] = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "name": compose_dict.get("name", project_name),
            "description": f"Transpiled AnyLink ext4 development mesh from Docker Compose ({project_name})",
            "version": "1.0.0",
            "network": {
                "name": f"{project_name}_net",
                "driver": "bridge",
                "subnet": "172.28.0.0/16"
            },
            "shared_volumes": [],
            "services": {}
        }

        # Track volumes to create
        declared_volumes = set(compose_dict.get("volumes", {}).keys()) if isinstance(compose_dict.get("volumes"), dict) else set()
        active_volumes = set()

        raw_services = compose_dict.get("services", {})
        if not isinstance(raw_services, dict):
            raise ValueError("Docker Compose file must contain a 'services' dictionary.")

        for svc_name, svc in raw_services.items():
            if not isinstance(svc, dict):
                continue

            cname = svc.get("container_name") or f"mesh-{svc_name}"
            image = svc.get("image") or self.default_base_image
            command = svc.get("command")
            if isinstance(command, str):
                command = command.split()
            elif not command:
                command = ["tail", "-f", "/dev/null"]

            # Environment
            env_dict = {}
            raw_env = svc.get("environment", {})
            if isinstance(raw_env, list):
                for item in raw_env:
                    if "=" in item:
                        k, v = item.split("=", 1)
                        env_dict[k.strip()] = v.strip()
            elif isinstance(raw_env, dict):
                env_dict = {str(k): str(v) for k, v in raw_env.items()}

            # Ports
            ports_list = []
            for p in svc.get("ports", []):
                ports_list.append(str(p))

            # Resource Limits
            deploy_limits = svc.get("deploy", {}).get("resources", {}).get("limits", {})
            cpus = 1.0
            if "cpus" in deploy_limits:
                try:
                    cpus = float(deploy_limits["cpus"])
                except Exception:
                    pass
            elif "cpus" in svc:
                try:
                    cpus = float(svc["cpus"])
                except Exception:
                    pass

            memory = deploy_limits.get("memory") or svc.get("mem_limit") or "512m"
            memory = parse_k8s_memory(memory)
            pids_limit = deploy_limits.get("pids") or svc.get("pids_limit") or 128

            # Volumes & Bind-Mount Optimization
            service_volumes = []
            for v in svc.get("volumes", []):
                if isinstance(v, str):
                    parts = v.split(":")
                    if len(parts) >= 2:
                        src, dst = parts[0], parts[1]
                        mode = parts[2] if len(parts) > 2 else "rw"

                        # Detect host bind-mount (e.g. ./src, /host/path, C:\...)
                        is_host_bind = src.startswith(".") or "/" in src or "\\" in src
                        if is_host_bind and self.optimize_volumes:
                            # Optimize: Convert sluggish host bind-mount to native ext4 named volume!
                            safe_name = f"{svc_name}_data_vol"
                            active_volumes.add(safe_name)
                            service_volumes.append(f"{safe_name}:{dst}:{mode}")
                        else:
                            active_volumes.add(src)
                            service_volumes.append(f"{src}:{dst}:{mode}")
                elif isinstance(v, dict):
                    v_type = v.get("type", "volume")
                    src = v.get("source", "")
                    target = v.get("target", "")
                    mode = "ro" if v.get("read_only") else "rw"
                    if v_type == "bind" and self.optimize_volumes:
                        safe_name = f"{svc_name}_data_vol"
                        active_volumes.add(safe_name)
                        service_volumes.append(f"{safe_name}:{target}:{mode}")
                    elif src and target:
                        active_volumes.add(src)
                        service_volumes.append(f"{src}:{target}:{mode}")

            mesh["services"][svc_name] = {
                "container_name": cname,
                "image": image,
                "command": command,
                "environment": env_dict,
                "volumes": service_volumes,
                "ports": ports_list,
                "cpus": cpus,
                "memory": memory,
                "pids_limit": int(pids_limit),
                "workdir": "/workspace"
            }

        # Add shared volumes
        for vol in sorted(active_volumes | declared_volumes):
            mesh["shared_volumes"].append({
                "name": vol,
                "driver": "local",
                "mount_path": "/shared"
            })

        return mesh

    # -------------------------------------------------------------------------
    # Kubernetes -> Mesh
    # -------------------------------------------------------------------------
    def kubernetes_to_mesh(self, k8s_docs: List[Dict[str, Any]], project_name: str = "k8s_mesh") -> Dict[str, Any]:
        """Transpiles a list of Kubernetes YAML documents (Deployment, Pod, Service) into mesh.json."""
        mesh: Dict[str, Any] = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "name": project_name,
            "description": f"Transpiled AnyLink ext4 development mesh from Kubernetes YAML ({project_name})",
            "version": "1.0.0",
            "network": {
                "name": f"{project_name}_net",
                "driver": "bridge",
                "subnet": "172.30.0.0/16"
            },
            "shared_volumes": [],
            "services": {}
        }

        services_ports: Dict[str, List[str]] = {}
        active_volumes = set()

        # Phase 1: Extract Service port mappings
        for doc in k8s_docs:
            if not isinstance(doc, dict):
                continue
            kind = doc.get("kind", "")
            if kind == "Service":
                svc_meta = doc.get("metadata", {})
                s_name = svc_meta.get("name", "")
                spec = doc.get("spec", {})
                ports = []
                for p in spec.get("ports", []):
                    port_num = p.get("port")
                    target = p.get("targetPort", port_num)
                    if port_num:
                        ports.append(f"{port_num}:{target}")
                if s_name and ports:
                    services_ports[s_name] = ports

        # Phase 2: Extract Deployments / Pods
        for doc in k8s_docs:
            if not isinstance(doc, dict):
                continue
            kind = doc.get("kind", "")
            meta = doc.get("metadata", {})
            workload_name = meta.get("name", "workload")

            pod_spec = None
            if kind == "Deployment":
                pod_spec = doc.get("spec", {}).get("template", {}).get("spec", {})
            elif kind == "Pod":
                pod_spec = doc.get("spec", {})

            if not pod_spec:
                continue

            containers = pod_spec.get("containers", [])
            for c in containers:
                c_name = c.get("name") or workload_name
                image = c.get("image") or self.default_base_image
                command = c.get("command") or ["tail", "-f", "/dev/null"]
                if isinstance(command, str):
                    command = [command]

                # Env
                env_dict = {}
                for env_item in c.get("env", []):
                    k = env_item.get("name")
                    v = env_item.get("value", "")
                    if k:
                        env_dict[str(k)] = str(v)

                # Resources
                resources = c.get("resources", {}).get("limits", {})
                cpus = parse_k8s_cpu(resources.get("cpu", 1.0))
                memory = parse_k8s_memory(resources.get("memory", "512m"))

                # Volumes
                service_volumes = []
                for vm in c.get("volumeMounts", []):
                    vname = vm.get("name", "vol")
                    mpath = vm.get("mountPath", "/shared")
                    active_volumes.add(vname)
                    service_volumes.append(f"{vname}:{mpath}:rw")

                ports = services_ports.get(c_name) or services_ports.get(workload_name) or []
                if not ports:
                    for cp in c.get("ports", []):
                        if "containerPort" in cp:
                            ports.append(f"{cp['containerPort']}:{cp['containerPort']}")

                mesh["services"][c_name] = {
                    "container_name": f"mesh-{c_name}",
                    "image": image,
                    "command": command,
                    "environment": env_dict,
                    "volumes": service_volumes,
                    "ports": ports,
                    "cpus": cpus,
                    "memory": memory,
                    "pids_limit": 128,
                    "workdir": "/workspace"
                }

        # Add shared volumes
        for vol in sorted(active_volumes):
            mesh["shared_volumes"].append({
                "name": vol,
                "driver": "local",
                "mount_path": "/shared"
            })

        return mesh

    # -------------------------------------------------------------------------
    # Mesh -> Compose
    # -------------------------------------------------------------------------
    def mesh_to_compose(self, mesh: Dict[str, Any]) -> Dict[str, Any]:
        """Exports a mesh.json specification back into standard docker-compose.yml dict."""
        compose: Dict[str, Any] = {
            "name": mesh.get("name", "mesh_exported"),
            "services": {},
            "volumes": {},
            "networks": {
                "default": {
                    "name": mesh.get("network", {}).get("name", "mesh_net"),
                    "driver": mesh.get("network", {}).get("driver", "bridge")
                }
            }
        }

        for vol in mesh.get("shared_volumes", []):
            vname = vol.get("name")
            if vname:
                compose["volumes"][vname] = {"driver": vol.get("driver", "local")}

        for svc_name, svc in mesh.get("services", {}).items():
            c_entry: Dict[str, Any] = {
                "container_name": svc.get("container_name", f"mesh-{svc_name}"),
                "image": svc.get("image", self.default_base_image),
                "command": svc.get("command", ["tail", "-f", "/dev/null"]),
            }

            if svc.get("environment"):
                c_entry["environment"] = dict(svc["environment"])

            if svc.get("ports"):
                c_entry["ports"] = list(svc["ports"])

            if svc.get("volumes"):
                c_entry["volumes"] = list(svc["volumes"])

            # Deploy limits
            cpus = svc.get("cpus")
            mem = svc.get("memory")
            pids = svc.get("pids_limit")
            if cpus or mem or pids:
                c_entry["deploy"] = {
                    "resources": {
                        "limits": {}
                    }
                }
                if cpus:
                    c_entry["deploy"]["resources"]["limits"]["cpus"] = str(cpus)
                if mem:
                    c_entry["deploy"]["resources"]["limits"]["memory"] = str(mem)
                if pids:
                    c_entry["deploy"]["resources"]["limits"]["pids"] = int(pids)

            compose["services"][svc_name] = c_entry

        return compose

    # -------------------------------------------------------------------------
    # Mesh -> Kubernetes
    # -------------------------------------------------------------------------
    def mesh_to_kubernetes(self, mesh: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Exports mesh.json into a list of Kubernetes manifests (Deployment and Service)."""
        docs: List[Dict[str, Any]] = []

        for svc_name, svc in mesh.get("services", {}).items():
            # 1. Deployment
            dep: Dict[str, Any] = {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {
                    "name": svc_name,
                    "labels": {"app": svc_name}
                },
                "spec": {
                    "replicas": 1,
                    "selector": {
                        "matchLabels": {"app": svc_name}
                    },
                    "template": {
                        "metadata": {
                            "labels": {"app": svc_name}
                        },
                        "spec": {
                            "containers": [
                                {
                                    "name": svc_name,
                                    "image": svc.get("image", self.default_base_image),
                                    "command": svc.get("command", ["tail", "-f", "/dev/null"]),
                                    "resources": {
                                        "limits": {
                                            "cpu": str(svc.get("cpus", 1.0)),
                                            "memory": f"{str(svc.get('memory', '512m')).rstrip('m')}Mi"
                                        }
                                    }
                                }
                            ]
                        }
                    }
                }
            }

            # Env
            c_spec = dep["spec"]["template"]["spec"]["containers"][0]
            if svc.get("environment"):
                c_spec["env"] = [{"name": k, "value": str(v)} for k, v in svc["environment"].items()]

            # Volumes
            if svc.get("volumes"):
                c_spec["volumeMounts"] = []
                dep["spec"]["template"]["spec"]["volumes"] = []
                for v in svc["volumes"]:
                    parts = v.split(":")
                    if len(parts) >= 2:
                        vname, mpath = parts[0], parts[1]
                        c_spec["volumeMounts"].append({"name": vname, "mountPath": mpath})
                        dep["spec"]["template"]["spec"]["volumes"].append({
                            "name": vname,
                            "emptyDir": {}
                        })

            docs.append(dep)

            # 2. Service (if ports exposed)
            if svc.get("ports"):
                svc_ports = []
                for p in svc["ports"]:
                    parts = p.split(":")
                    if len(parts) >= 2:
                        p_host, p_target = int(parts[0]), int(parts[1])
                        svc_ports.append({"port": p_host, "targetPort": p_target, "name": f"port-{p_host}"})
                    elif len(parts) == 1:
                        p_val = int(parts[0])
                        svc_ports.append({"port": p_val, "targetPort": p_val, "name": f"port-{p_val}"})

                if svc_ports:
                    k8s_svc: Dict[str, Any] = {
                        "apiVersion": "v1",
                        "kind": "Service",
                        "metadata": {
                            "name": svc_name,
                            "labels": {"app": svc_name}
                        },
                        "spec": {
                            "selector": {"app": svc_name},
                            "ports": svc_ports
                        }
                    }
                    docs.append(k8s_svc)

        return docs


# -----------------------------------------------------------------------------
# CLI Entrypoint
# -----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Bi-Directional Manifest Transpiler: Docker Compose & K8s <===> AnyLink Mesh"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # compose-to-mesh
    p_c2m = sub.add_parser("compose-to-mesh", help="Transpile docker-compose.yml to mesh.json")
    p_c2m.add_argument("-i", "--input", default="docker-compose.yml", help="Path to docker-compose.yml")
    p_c2m.add_argument("-o", "--output", default="mesh.json", help="Output path for mesh.json")
    p_c2m.add_argument("--no-optimize", action="store_true", help="Do not convert host bind-mounts to ext4 volumes")

    # k8s-to-mesh
    p_k2m = sub.add_parser("k8s-to-mesh", help="Transpile Kubernetes manifests to mesh.json")
    p_k2m.add_argument("-i", "--input", required=True, help="Path to Kubernetes YAML manifest file")
    p_k2m.add_argument("-o", "--output", default="mesh.json", help="Output path for mesh.json")

    # mesh-to-compose
    p_m2c = sub.add_parser("mesh-to-compose", help="Export mesh.json to docker-compose.yml")
    p_m2c.add_argument("-i", "--input", default="mesh.json", help="Path to mesh.json")
    p_m2c.add_argument("-o", "--output", default="docker-compose.yml", help="Output path for docker-compose.yml")

    # mesh-to-k8s
    p_m2k = sub.add_parser("mesh-to-k8s", help="Export mesh.json to Kubernetes YAML manifests")
    p_m2k.add_argument("-i", "--input", default="mesh.json", help="Path to mesh.json")
    p_m2k.add_argument("-o", "--output", default="kubernetes.yaml", help="Output path for kubernetes.yaml")

    args = parser.parse_args()
    transpiler = ManifestTranspiler(optimize_volumes=not getattr(args, "no_optimize", False))

    if args.command == "compose-to-mesh":
        in_path = Path(args.input)
        if not in_path.exists():
            print(f"[ERROR] Input Compose file not found: {in_path}", file=sys.stderr)
            sys.exit(1)
        with open(in_path, "r", encoding="utf-8") as f:
            compose_data = yaml.safe_load(f)
        mesh_res = transpiler.compose_to_mesh(compose_data, project_name=in_path.stem)
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(mesh_res, f, indent=2)
        print(f"[SUCCESS] Transpiled '{in_path}' -> '{out_path}' ({len(mesh_res.get('services', {}))} services)")

    elif args.command == "k8s-to-mesh":
        in_path = Path(args.input)
        if not in_path.exists():
            print(f"[ERROR] Input Kubernetes manifest not found: {in_path}", file=sys.stderr)
            sys.exit(1)
        with open(in_path, "r", encoding="utf-8") as f:
            k8s_docs = list(yaml.safe_load_all(f))
        mesh_res = transpiler.kubernetes_to_mesh(k8s_docs, project_name=in_path.stem)
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(mesh_res, f, indent=2)
        print(f"[SUCCESS] Transpiled '{in_path}' -> '{out_path}' ({len(mesh_res.get('services', {}))} services)")

    elif args.command == "mesh-to-compose":
        in_path = Path(args.input)
        if not in_path.exists():
            print(f"[ERROR] Input mesh.json not found: {in_path}", file=sys.stderr)
            sys.exit(1)
        with open(in_path, "r", encoding="utf-8") as f:
            mesh_data = json.load(f)
        compose_res = transpiler.mesh_to_compose(mesh_data)
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(compose_res, f, sort_keys=False)
        print(f"[SUCCESS] Exported '{in_path}' -> '{out_path}' ({len(compose_res.get('services', {}))} services)")

    elif args.command == "mesh-to-k8s":
        in_path = Path(args.input)
        if not in_path.exists():
            print(f"[ERROR] Input mesh.json not found: {in_path}", file=sys.stderr)
            sys.exit(1)
        with open(in_path, "r", encoding="utf-8") as f:
            mesh_data = json.load(f)
        k8s_docs = transpiler.mesh_to_kubernetes(mesh_data)
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            yaml.safe_dump_all(k8s_docs, f, sort_keys=False)
        print(f"[SUCCESS] Exported '{in_path}' -> '{out_path}' ({len(k8s_docs)} K8s documents)")


if __name__ == "__main__":
    main()
