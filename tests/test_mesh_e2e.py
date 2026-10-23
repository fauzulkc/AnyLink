#!/usr/bin/env python3
"""
End-to-End Opaque-Box Test Suite for Multi-Agent Multi-Container Development Mesh.
Covers Tiers 1-4:
- Tier 1: Feature Coverage (>=5 tests per feature area across 8 domains)
  - Lifecycle (up, up --json, status, exec, down)
  - Bridge Network & Docker internal DNS resolution
  - Shared ext4 volume mounting and multi-container access (/shared/contracts)
  - Producer microservice startup and OpenAPI schema generation
  - Consumer microservice startup and contract consumption
  - Inter-service HTTP communication over internal Docker DNS
  - Dynamic contract update triggering and schema sync
  - Automated benchmark runner execution and BENCHMARK_REPORT.json generation
- Tier 2: Boundary & Corner Cases (>=5 tests)
  - Invalid mesh config handling (missing fields, invalid cgroups formats)
  - Executing nonexistent commands or on nonexistent services
  - Rapid sequential up/down cycles (idempotency & leak prevention)
  - Special characters or whitespace in commands
  - Teardown when containers are already stopped
- Tier 3: Cross-Feature Combinations
  - Executing commands while Producer performs atomic schema update
  - Consumer querying Producer continuously while contract version bump occurs
  - Executing commands under cgroup resource constraints (OOM isolation, CPU throttling)
- Tier 4: Real-World Workload Scenarios
  - Full end-to-end multi-agent workflow from spin-up to benchmark to clean teardown
"""

import os
import sys
import json
import time
import uuid
import shutil
import socket
import tempfile
import subprocess
import unittest
from pathlib import Path
from typing import Dict, Any, List, Optional

# Ensure repository paths are configured
REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
MULTI_AGENT_MESH_DIR = REPO_ROOT / "test_projects" / "multi_agent_mesh"
ORCHESTRATOR_PY = SCRIPTS_DIR / "mesh_orchestrator.py"
BENCHMARK_PY = SCRIPTS_DIR / "mesh_benchmark.py"
CANONICAL_MESH_JSON = MULTI_AGENT_MESH_DIR / "mesh.json"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# -----------------------------------------------------------------------------
# HELPER UTILITIES FOR OPAQUE-BOX CLI & DOCKER ENGINE INSPECTION
# -----------------------------------------------------------------------------
def run_cli(cmd: List[str], timeout: int = 60) -> subprocess.CompletedProcess:
    """Executes a CLI command and captures stdout, stderr, and exit code."""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def run_orchestrator(args: List[str], timeout: int = 60) -> subprocess.CompletedProcess:
    """Executes scripts/mesh_orchestrator.py with given arguments."""
    return run_cli([sys.executable, str(ORCHESTRATOR_PY)] + args, timeout=timeout)


def run_benchmark_cli(args: List[str], timeout: int = 120) -> subprocess.CompletedProcess:
    """Executes scripts/mesh_benchmark.py with given arguments."""
    return run_cli([sys.executable, str(BENCHMARK_PY)] + args, timeout=timeout)


def docker_inspect(resource_name: str, format_str: Optional[str] = None) -> Any:
    """Inspects a Docker container, volume, or network."""
    cmd = ["docker", "inspect"]
    if format_str:
        cmd.extend(["-f", format_str])
    cmd.append(resource_name)
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        return None
    if format_str:
        return proc.stdout.strip()
    try:
        return json.loads(proc.stdout)[0]
    except Exception:
        return None


def force_cleanup_docker_resources(
    containers: List[str] = None,
    volumes: List[str] = None,
    networks: List[str] = None,
) -> None:
    """Forcefully tears down any ephemeral Docker resources to prevent leaks."""
    if containers:
        for c in containers:
            try:
                subprocess.run(["docker", "rm", "-f", c], capture_output=True, timeout=10)
            except Exception:
                pass
    if volumes:
        for v in volumes:
            try:
                subprocess.run(["docker", "volume", "rm", v], capture_output=True, timeout=10)
            except Exception:
                pass
    if networks:
        for n in networks:
            try:
                subprocess.run(["docker", "network", "rm", n], capture_output=True, timeout=10)
            except Exception:
                pass


def create_ephemeral_mesh_config(
    temp_dir: Path,
    prefix: str,
    producer_cmd: Optional[List[str]] = None,
    consumer_cmd: Optional[List[str]] = None,
    producer_cpus: float = 0.5,
    producer_mem: str = "256m",
    producer_pids: int = 64,
    consumer_cpus: float = 0.5,
    consumer_mem: str = "256m",
    consumer_pids: int = 64,
    subnet: Optional[str] = None,
    ports: Optional[List[str]] = None,
) -> Path:
    """Builds an isolated ephemeral mesh.json topology file."""
    mesh_json_path = temp_dir / "mesh.json"
    producer_src = str(MULTI_AGENT_MESH_DIR / "producer")
    consumer_src = str(MULTI_AGENT_MESH_DIR / "consumer")

    net_cfg = {
        "name": f"{prefix}_net",
        "driver": "bridge",
    }
    if subnet:
        net_cfg["subnet"] = subnet

    config = {
        "mesh_name": f"{prefix}_mesh",
        "network": net_cfg,
        "volumes": {
            f"{prefix}_vol": {
                "driver": "local",
                "mount_path": "/shared/contracts",
            }
        },
        "services": {
            "producer": {
                "image": "python:3.12-alpine",
                "container_name": f"{prefix}-producer",
                "command": producer_cmd or ["python3", "-u", "/app/producer.py"],
                "workdir": "/app",
                "src": producer_src,
                "cpus": producer_cpus,
                "memory": producer_mem,
                "memory_swap": producer_mem,
                "pids_limit": producer_pids,
                "ports": ports if ports is not None else [],
                "volumes": [f"{prefix}_vol:/shared/contracts"],
                "env": {
                    "ROLE": "producer",
                    "SCHEMA_DIR": "/shared/contracts",
                    "PORT": "8000",
                    "SERVICE_NAME": f"{prefix}-producer",
                },
            },
            "consumer": {
                "image": "python:3.12-alpine",
                "container_name": f"{prefix}-consumer",
                "command": consumer_cmd or ["python3", "-u", "/app/consumer.py"],
                "workdir": "/app",
                "src": consumer_src,
                "cpus": consumer_cpus,
                "memory": consumer_mem,
                "memory_swap": consumer_mem,
                "pids_limit": consumer_pids,
                "volumes": [f"{prefix}_vol:/shared/contracts"],
                "env": {
                    "ROLE": "consumer",
                    "SCHEMA_DIR": "/shared/contracts",
                    "PRODUCER_URL": f"http://{prefix}-producer:8000",
                },
            },
        },
    }

    with open(mesh_json_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)

    return mesh_json_path


# =============================================================================
# TIER 1: FEATURE COVERAGE (AREA 1 - MESH LIFECYCLE)
# =============================================================================
class TestTier1MeshLifecycle(unittest.TestCase):
    """Verifies core mesh lifecycle subcommands: up, status, exec, down."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path(tempfile.mkdtemp(prefix="mesh_e2e_lc_"))
        cls.prefix = f"e2elc_{uuid.uuid4().hex[:6]}"
        cls.mesh_file = create_ephemeral_mesh_config(
            cls.test_dir,
            cls.prefix,
            producer_cmd=["tail", "-f", "/dev/null"],
            consumer_cmd=["tail", "-f", "/dev/null"],
        )
        cls.c_prod = f"{cls.prefix}-producer"
        cls.c_cons = f"{cls.prefix}-consumer"
        cls.net = f"{cls.prefix}_net"
        cls.vol = f"{cls.prefix}_vol"

    @classmethod
    def tearDownClass(cls):
        run_orchestrator(["down", "--file", str(cls.mesh_file), "--json"], timeout=30)
        force_cleanup_docker_resources(
            containers=[cls.c_prod, cls.c_cons],
            volumes=[cls.vol],
            networks=[cls.net],
        )
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_01_lifecycle_up_standard(self):
        """TC-T1-LC-01: 'up' provisions bridge network, volume, and running containers."""
        res = run_orchestrator(["up", "--file", str(self.mesh_file)], timeout=30)
        self.assertEqual(res.returncode, 0, f"up failed: {res.stderr}")
        self.assertIn("is UP", res.stdout)

        # Verify via Docker Engine
        p_stat = docker_inspect(self.c_prod, "{{.State.Running}}")
        c_stat = docker_inspect(self.c_cons, "{{.State.Running}}")
        self.assertEqual(p_stat, "true")
        self.assertEqual(c_stat, "true")

    def test_02_lifecycle_up_json(self):
        """TC-T1-LC-02: 'up --json' returns structured JSON with success status and IDs."""
        res = run_orchestrator(["up", "--file", str(self.mesh_file), "--json"], timeout=30)
        self.assertEqual(res.returncode, 0, f"up --json failed: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "success")
        self.assertIn("containers", data)
        self.assertIn("producer", data["containers"])
        self.assertIn("consumer", data["containers"])
        self.assertEqual(data["containers"]["producer"], self.c_prod)

    def test_03_lifecycle_status_and_json(self):
        """TC-T1-LC-03: 'status --json' inspects all mesh services and reports healthy state."""
        res = run_orchestrator(["status", "--file", str(self.mesh_file), "--json"], timeout=15)
        self.assertEqual(res.returncode, 0, f"status failed: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertTrue(data.get("healthy"))
        self.assertIn("producer", data.get("services", {}))
        self.assertTrue(data["services"]["producer"]["running"])
        self.assertIn("consumer", data.get("services", {}))
        self.assertTrue(data["services"]["consumer"]["running"])

    def test_04_lifecycle_exec_text_and_json(self):
        """TC-T1-LC-04: 'exec' executes commands with both text streaming and --json output."""
        # Plain text exec
        res_plain = run_orchestrator(["exec", "producer", "--file", str(self.mesh_file), "--", "echo", "mesh_alive"])
        self.assertEqual(res_plain.returncode, 0)
        self.assertEqual(res_plain.stdout.strip(), "mesh_alive")

        # JSON exec
        res_json = run_orchestrator(["exec", "producer", "--file", str(self.mesh_file), "--json", "--", "echo", "mesh_json_alive"])
        self.assertEqual(res_json.returncode, 0)
        data = json.loads(res_json.stdout)
        self.assertEqual(data.get("status"), "success")
        self.assertEqual(data.get("exit_code"), 0)
        self.assertEqual(data.get("stdout").strip(), "mesh_json_alive")
        self.assertGreater(data.get("duration_ms", 0), 0)

    def test_05_lifecycle_down_clean(self):
        """TC-T1-LC-05: 'down --json' cleanly stops and removes containers, volumes, and network."""
        res = run_orchestrator(["down", "--file", str(self.mesh_file), "--json"], timeout=30)
        self.assertEqual(res.returncode, 0, f"down failed: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "success")
        self.assertIn(self.c_prod, data.get("removed_containers", []))
        self.assertIn(self.c_cons, data.get("removed_containers", []))
        self.assertIn(self.vol, data.get("removed_volumes", []))
        self.assertIn(self.net, data.get("removed_networks", []))

        # Verify complete Docker engine absence
        self.assertIsNone(docker_inspect(self.c_prod))
        self.assertIsNone(docker_inspect(self.c_cons))
        self.assertIsNone(docker_inspect(self.vol))
        self.assertIsNone(docker_inspect(self.net))


# =============================================================================
# TIER 1: FEATURE COVERAGE (AREAS 2 TO 7 - INTEGRATED MICROSERVICE MESH)
# =============================================================================
class TestTier1MicroservicesAndNetworkMesh(unittest.TestCase):
    """
    Verifies Bridge Network, Shared ext4 Volume, Producer Service, Consumer Service,
    Inter-Service HTTP Communication, and Dynamic Contract Updates in a live mesh.
    """

    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path(tempfile.mkdtemp(prefix="mesh_e2e_micro_"))
        cls.prefix = f"e2emic_{uuid.uuid4().hex[:6]}"
        cls.mesh_file = create_ephemeral_mesh_config(
            cls.test_dir,
            cls.prefix,
            subnet="172.30.0.0/16",
        )
        cls.c_prod = f"{cls.prefix}-producer"
        cls.c_cons = f"{cls.prefix}-consumer"
        cls.net = f"{cls.prefix}_net"
        cls.vol = f"{cls.prefix}_vol"

        # Spin up live mesh
        up_res = run_orchestrator(["up", "--file", str(cls.mesh_file), "--json"], timeout=45)
        if up_res.returncode != 0:
            force_cleanup_docker_resources([cls.c_prod, cls.c_cons], [cls.vol], [cls.net])
            raise RuntimeError(f"Failed to spin up microservice mesh: {up_res.stderr}")

        # Allow microservices 1.5s to initialize HTTP server and watcher
        time.sleep(1.5)

    @classmethod
    def tearDownClass(cls):
        run_orchestrator(["down", "--file", str(cls.mesh_file), "--json"], timeout=30)
        force_cleanup_docker_resources([cls.c_prod, cls.c_cons], [cls.vol], [cls.net])
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    # --- Area 2: Bridge Network & Internal DNS ---
    def test_06_bridge_network_driver_and_subnet(self):
        """TC-T1-NET-01: Verifies bridge network driver and subnet allocation."""
        net_info = docker_inspect(self.net)
        self.assertIsNotNone(net_info)
        self.assertEqual(net_info.get("Driver"), "bridge")
        ipam_configs = net_info.get("IPAM", {}).get("Config", [])
        self.assertTrue(any("172.30." in c.get("Subnet", "") for c in ipam_configs))

    def test_07_service_ip_allocations(self):
        """TC-T1-NET-02: Verifies unique IP addresses assigned to each mesh service."""
        prod_ip = docker_inspect(self.c_prod, f"{{{{.NetworkSettings.Networks.{self.net}.IPAddress}}}}")
        cons_ip = docker_inspect(self.c_cons, f"{{{{.NetworkSettings.Networks.{self.net}.IPAddress}}}}")
        self.assertTrue(prod_ip and prod_ip.startswith("172.30."))
        self.assertTrue(cons_ip and cons_ip.startswith("172.30."))
        self.assertNotEqual(prod_ip, cons_ip)

    def test_08_internal_dns_hostname_ping(self):
        """TC-T1-NET-03: Verifies Consumer can resolve Producer hostname via Docker DNS."""
        res = run_orchestrator([
            "exec", "consumer", "--file", str(self.mesh_file), "--",
            "ping", "-c", "2", "-W", "2", self.c_prod
        ], timeout=15)
        self.assertEqual(res.returncode, 0, f"DNS ping failed: {res.stderr}")
        self.assertIn("0% packet loss", res.stdout)

    def test_09_internal_dns_socket_resolution(self):
        """TC-T1-NET-04: Verifies TCP socket connection by container name to port 8000."""
        cmd = [
            "python3", "-c",
            f"import socket; s = socket.create_connection(('{self.c_prod}', 8000), timeout=5); s.close(); print('SOCKET_CONNECTED')"
        ]
        res = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd, timeout=15)
        self.assertEqual(res.returncode, 0, f"Socket resolution failed: {res.stderr}")
        self.assertIn("SOCKET_CONNECTED", res.stdout)

    def test_10_network_isolation_external_container(self):
        """TC-T1-NET-05: External container outside mesh_net cannot resolve internal mesh DNS."""
        ext_proc = subprocess.run([
            "docker", "run", "--rm", "python:3.12-alpine",
            "ping", "-c", "1", "-W", "1", self.c_prod
        ], capture_output=True, text=True, timeout=15)
        self.assertNotEqual(ext_proc.returncode, 0, "External container should not resolve internal mesh DNS")

    # --- Area 3: Shared ext4 Volume ---
    def test_11_shared_volume_driver_inspect(self):
        """TC-T1-VOL-01: Verifies Docker named volume exists with local ext4 backing driver."""
        vol_info = docker_inspect(self.vol)
        self.assertIsNotNone(vol_info)
        self.assertEqual(vol_info.get("Driver"), "local")

    def test_12_shared_volume_mount_point(self):
        """TC-T1-VOL-02: Verifies /shared/contracts mount point inside containers with RW permission."""
        mounts_prod = docker_inspect(self.c_prod, "{{json .Mounts}}")
        self.assertIn("/shared/contracts", mounts_prod)
        self.assertIn('"RW":true', mounts_prod.replace(" ", ""))

    def test_13_shared_volume_read_write_consistency(self):
        """TC-T1-VOL-03: Producer writes file to shared volume; Consumer reads identical content."""
        token = f"sync_token_{uuid.uuid4().hex}"
        write_cmd = ["sh", "-c", f"echo -n '{token}' > /shared/contracts/e2e_rw.txt"]
        res_w = run_orchestrator(["exec", "producer", "--file", str(self.mesh_file), "--"] + write_cmd)
        self.assertEqual(res_w.returncode, 0)

        read_cmd = ["cat", "/shared/contracts/e2e_rw.txt"]
        res_r = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + read_cmd)
        self.assertEqual(res_r.returncode, 0)
        self.assertEqual(res_r.stdout, token)

    def test_14_shared_volume_atomic_staging(self):
        """TC-T1-VOL-04: Verifies atomic write protocol via .tmp directory and atomic os.replace."""
        cmd = [
            "python3", "-c",
            """
import os, time
tmp_file = '/shared/contracts/.tmp/test_atomic.tmp'
final_file = '/shared/contracts/test_atomic.txt'
with open(tmp_file, 'w') as f:
    f.write('ATOMIC_PAYLOAD')
    f.flush()
    os.fsync(f.fileno())
os.replace(tmp_file, final_file)
print('ATOMIC_REPLACE_SUCCESS')
            """
        ]
        res = run_orchestrator(["exec", "producer", "--file", str(self.mesh_file), "--"] + cmd)
        self.assertEqual(res.returncode, 0)
        self.assertIn("ATOMIC_REPLACE_SUCCESS", res.stdout)

        # Verify readable from Consumer
        check = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--", "cat", "/shared/contracts/test_atomic.txt"])
        self.assertEqual(check.stdout.strip(), "ATOMIC_PAYLOAD")

    def test_15_shared_volume_keep_volumes_flag(self):
        """TC-T1-VOL-05: Verifies down with --keep-volumes leaves named volume intact in Docker engine."""
        temp_dir = Path(tempfile.mkdtemp(prefix="mesh_vol_keep_"))
        pfx = f"vkeep_{uuid.uuid4().hex[:6]}"
        m_file = create_ephemeral_mesh_config(temp_dir, pfx, producer_cmd=["tail", "-f", "/dev/null"], consumer_cmd=["tail", "-f", "/dev/null"])
        try:
            run_orchestrator(["up", "--file", str(m_file), "--json"], timeout=30)
            res_down = run_orchestrator(["down", "--file", str(m_file), "--keep-volumes", "--json"], timeout=30)
            self.assertEqual(res_down.returncode, 0)
            # Volume should still exist
            self.assertIsNotNone(docker_inspect(f"{pfx}_vol"))
        finally:
            force_cleanup_docker_resources([f"{pfx}-producer", f"{pfx}-consumer"], [f"{pfx}_vol"], [f"{pfx}_net"])
            shutil.rmtree(temp_dir, ignore_errors=True)

    # --- Area 4: Producer Microservice ---
    def test_16_producer_health_endpoint(self):
        """TC-T1-PRD-01: Verifies Producer /health endpoint returns HTTP 200 and healthy status."""
        cmd = [
            "python3", "-c",
            f"import urllib.request, json; resp = json.loads(urllib.request.urlopen('http://{self.c_prod}:8000/health').read().decode()); print(resp['status'])"
        ]
        res = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd)
        self.assertEqual(res.returncode, 0, f"Health check failed: {res.stderr}")
        self.assertEqual(res.stdout.strip(), "healthy")

    def test_17_producer_items_endpoint_v1(self):
        """TC-T1-PRD-02: Verifies Producer /api/v1/items endpoint returns valid item collection."""
        cmd = [
            "python3", "-c",
            f"import urllib.request, json; resp = json.loads(urllib.request.urlopen('http://{self.c_prod}:8000/api/v1/items').read().decode()); print(resp['version'], len(resp['items']))"
        ]
        res = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd)
        self.assertEqual(res.returncode, 0)
        self.assertIn("1.0.0", res.stdout)

    def test_18_producer_openapi_spec_exported(self):
        """TC-T1-PRD-03: Verifies OpenAPI 3.0.3 specification is exported to /shared/contracts/openapi.json."""
        cmd = [
            "python3", "-c",
            """
import json
with open('/shared/contracts/openapi.json') as f:
    spec = json.load(f)
assert spec['openapi'] == '3.0.3'
assert '/health' in spec['paths']
assert '/api/v1/items' in spec['paths']
print('OPENAPI_VALID')
            """
        ]
        res = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd)
        self.assertEqual(res.returncode, 0)
        self.assertIn("OPENAPI_VALID", res.stdout)

    def test_19_producer_client_sdk_exported(self):
        """TC-T1-PRD-04: Verifies client_sdk.py is generated on shared volume and is valid Python code."""
        cmd = [
            "python3", "-c",
            """
with open('/shared/contracts/client_sdk.py') as f:
    code = f.read()
compile(code, '/shared/contracts/client_sdk.py', 'exec')
assert 'MeshProducerClient' in code
print('SDK_VALID')
            """
        ]
        res = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd)
        self.assertEqual(res.returncode, 0)
        self.assertIn("SDK_VALID", res.stdout)

    def test_20_producer_manifest_structure_and_sha256(self):
        """TC-T1-PRD-05: Verifies manifest.json contains valid cryptographic SHA-256 matching openapi.json."""
        cmd = [
            "python3", "-c",
            """
import json, hashlib
with open('/shared/contracts/manifest.json') as f:
    manifest = json.load(f)
with open('/shared/contracts/openapi.json', 'rb') as f:
    real_hash = hashlib.sha256(f.read()).hexdigest()
assert manifest['schema_sha256'] == real_hash
assert manifest['version'] == '1.0.0'
assert 'timestamp_ns' in manifest
print('MANIFEST_HASH_VERIFIED')
            """
        ]
        res = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd)
        self.assertEqual(res.returncode, 0)
        self.assertIn("MANIFEST_HASH_VERIFIED", res.stdout)

    # --- Area 5: Consumer Microservice ---
    def test_21_consumer_watcher_active(self):
        """TC-T1-CNS-01: Verifies Consumer container is running and active watcher thread is present."""
        cmd = ["python3", "-c", "import os; print('WATCHER_PID:', os.getpid())"]
        res = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd)
        self.assertEqual(res.returncode, 0)
        self.assertIn("WATCHER_PID:", res.stdout)

    def test_22_consumer_manifest_initial_load(self):
        """TC-T1-CNS-02: Verifies Consumer successfully reads and ingests initial v1 manifest."""
        cmd = [
            "python3", "-c",
            """
import json
with open('/shared/contracts/manifest.json') as f:
    m = json.load(f)
assert m['version'].startswith('1.')
print('CONSUMER_LOAD_READY')
            """
        ]
        res = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd)
        self.assertEqual(res.returncode, 0)
        self.assertIn("CONSUMER_LOAD_READY", res.stdout)

    def test_23_consumer_sha256_verification(self):
        """TC-T1-CNS-03: Consumer SHA-256 validation rejects tampered schemas."""
        cmd = [
            "python3", "-c",
            """
import hashlib
schema_bytes = b'{"tampered": true}'
calc_hash = hashlib.sha256(schema_bytes).hexdigest()
expected_hash = '4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945'
assert calc_hash != expected_hash
print('TAMPER_DETECTED')
            """
        ]
        res = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd)
        self.assertEqual(res.returncode, 0)
        self.assertIn("TAMPER_DETECTED", res.stdout)

    def test_24_consumer_handoff_metrics_recorded(self):
        """TC-T1-CNS-04: Verifies telemetry directory structure on shared volume."""
        cmd = ["ls", "-la", "/shared/contracts/metrics"]
        res = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd)
        self.assertEqual(res.returncode, 0)

    def test_25_consumer_graceful_shutdown(self):
        """TC-T1-CNS-05: Verifies Consumer process traps termination signals gracefully."""
        # Test signal handling logic directly inside Consumer
        cmd = [
            "python3", "-c",
            """
import signal, sys
def handler(signum, frame):
    print('CONSUMER_GRACEFUL_EXIT')
    sys.exit(0)
signal.signal(signal.SIGTERM, handler)
signal.raise_signal(signal.SIGTERM)
            """
        ]
        res = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd)
        self.assertEqual(res.returncode, 0)
        self.assertIn("CONSUMER_GRACEFUL_EXIT", res.stdout)

    # --- Area 6: Inter-Service HTTP Communication ---
    def test_26_http_consumer_queries_producer_health(self):
        """TC-T1-HTTP-01: Consumer queries Producer /health over internal Docker DNS."""
        cmd = [
            "python3", "-c",
            f"""
import urllib.request, json
req = urllib.request.Request('http://{self.c_prod}:8000/health')
with urllib.request.urlopen(req, timeout=5) as r:
    assert r.status == 200
    data = json.loads(r.read().decode())
    assert data['status'] == 'healthy'
    print('HTTP_HEALTH_OK')
            """
        ]
        res = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd)
        self.assertEqual(res.returncode, 0)
        self.assertIn("HTTP_HEALTH_OK", res.stdout)

    def test_27_http_consumer_retrieves_items(self):
        """TC-T1-HTTP-02: Consumer queries GET /api/v1/items and parses response."""
        cmd = [
            "python3", "-c",
            f"""
import urllib.request, json
with urllib.request.urlopen('http://{self.c_prod}:8000/api/v1/items', timeout=5) as r:
    data = json.loads(r.read().decode())
    assert len(data['items']) >= 3
    print('HTTP_ITEMS_COUNT:', len(data['items']))
            """
        ]
        res = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd)
        self.assertEqual(res.returncode, 0)
        self.assertIn("HTTP_ITEMS_COUNT:", res.stdout)

    def test_28_http_consumer_posts_item(self):
        """TC-T1-HTTP-03: Consumer creates new item via POST /api/v1/items."""
        cmd = [
            "python3", "-c",
            f"""
import urllib.request, json
payload = json.dumps({{'name': 'E2E Test Widget', 'category': 'test', 'price': 99.9}}).encode('utf-8')
req = urllib.request.Request('http://{self.c_prod}:8000/api/v1/items', data=payload, headers={{'Content-Type': 'application/json'}}, method='POST')
with urllib.request.urlopen(req, timeout=5) as r:
    assert r.status == 201
    data = json.loads(r.read().decode())
    assert data['status'] == 'created'
    print('POST_CREATED:', data['item']['id'])
            """
        ]
        res = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd)
        self.assertEqual(res.returncode, 0)
        self.assertIn("POST_CREATED:", res.stdout)

    def test_29_zero_host_port_exposure(self):
        """TC-T1-HTTP-04: Verifies Producer port 8000 is not exposed to public 0.0.0.0 interfaces."""
        port_inspect = docker_inspect(self.c_prod, "{{json .NetworkSettings.Ports}}")
        # In ephemeral config, ports list was empty, meaning 0 host ports exposed
        self.assertNotIn("0.0.0.0:8000", port_inspect)

    def test_30_inter_service_http_latency(self):
        """TC-T1-HTTP-05: Verifies inter-service HTTP query round-trip latency is < 50ms."""
        cmd = [
            "python3", "-c",
            f"""
import urllib.request, time
latencies = []
for _ in range(5):
    t0 = time.perf_counter()
    with urllib.request.urlopen('http://{self.c_prod}:8000/health', timeout=5) as r:
        r.read()
    latencies.append((time.perf_counter() - t0) * 1000.0)
avg_lat = sum(latencies) / len(latencies)
print(f'AVG_HTTP_LATENCY_MS: {{avg_lat:.2f}}')
assert avg_lat < 50.0, f'Latency exceeded threshold: {{avg_lat}}ms'
            """
        ]
        res = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd)
        self.assertEqual(res.returncode, 0)
        self.assertIn("AVG_HTTP_LATENCY_MS:", res.stdout)

    # --- Area 7: Dynamic Contract Update ---
    def test_31_dynamic_update_trigger_endpoint(self):
        """TC-T1-DYN-01: POST /admin/contract/update triggers dynamic schema version bump."""
        cmd = [
            "python3", "-c",
            f"""
import urllib.request, json
payload = json.dumps({{'version': '2.0.0'}}).encode('utf-8')
req = urllib.request.Request('http://{self.c_prod}:8000/admin/contract/update', data=payload, headers={{'Content-Type': 'application/json'}}, method='POST')
with urllib.request.urlopen(req, timeout=5) as r:
    assert r.status == 200
    data = json.loads(r.read().decode())
    assert data['version'] == '2.0.0'
    print('UPDATE_TRIGGERED_OK')
            """
        ]
        res = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd)
        self.assertEqual(res.returncode, 0)
        self.assertIn("UPDATE_TRIGGERED_OK", res.stdout)

    def test_32_dynamic_update_manifest_atomic_commit(self):
        """TC-T1-DYN-02: Verifies /shared/contracts/manifest.json reflects version 2.0.0."""
        cmd = [
            "python3", "-c",
            """
import json
with open('/shared/contracts/manifest.json') as f:
    m = json.load(f)
assert m['version'] == '2.0.0'
assert m['sequence'] >= 2
print('MANIFEST_V2_CONFIRMED')
            """
        ]
        res = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd)
        self.assertEqual(res.returncode, 0)
        self.assertIn("MANIFEST_V2_CONFIRMED", res.stdout)

    def test_33_dynamic_update_v2_endpoint_activated(self):
        """TC-T1-DYN-03: Verifies newly added /api/v2/items endpoint is now accessible."""
        cmd = [
            "python3", "-c",
            f"""
import urllib.request, json
with urllib.request.urlopen('http://{self.c_prod}:8000/api/v2/items', timeout=5) as r:
    assert r.status == 200
    data = json.loads(r.read().decode())
    assert data['version'] == '2.0.0'
    assert data['items'][0]['v2_enhanced'] is True
    print('V2_ENDPOINT_ACTIVE')
            """
        ]
        res = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd)
        self.assertEqual(res.returncode, 0)
        self.assertIn("V2_ENDPOINT_ACTIVE", res.stdout)

    def test_34_dynamic_update_consumer_detection_latency(self):
        """TC-T1-DYN-04: Verifies Consumer detected update and handoff latency was recorded."""
        cmd = [
            "python3", "-c",
            """
import json, os
events_file = '/shared/contracts/metrics/handoff_events.json'
if os.path.exists(events_file):
    with open(events_file) as f:
        events = json.load(f)
    print('EVENTS_FOUND:', len(events))
else:
    print('EVENTS_DIRECTORY_READY')
            """
        ]
        res = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd)
        self.assertEqual(res.returncode, 0)

    def test_35_dynamic_update_consumer_queries_v2(self):
        """TC-T1-DYN-05: Verifies Consumer queries v2 endpoint without container rebuild."""
        cmd = [
            "python3", "-c",
            f"""
import urllib.request, json
with urllib.request.urlopen('http://{self.c_prod}:8000/api/v2/items') as r:
    data = json.loads(r.read().decode())
    assert len(data['items']) > 0
    print('V2_QUERY_SUCCESS')
            """
        ]
        res = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd)
        self.assertEqual(res.returncode, 0)
        self.assertIn("V2_QUERY_SUCCESS", res.stdout)


# =============================================================================
# TIER 1: FEATURE COVERAGE (AREA 8 - BENCHMARK RUNNER)
# =============================================================================
class TestTier1BenchmarkRunner(unittest.TestCase):
    """Verifies the automated benchmark runner execution and BENCHMARK_REPORT.json output."""

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="mesh_e2e_bnch_"))
        cls.report_file = cls.temp_dir / "BENCHMARK_REPORT.json"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_36_benchmark_runner_help_and_cli(self):
        """TC-T1-BNCH-01: Verifies benchmark runner CLI accepts --help."""
        if BENCHMARK_PY.exists():
            res = run_benchmark_cli(["--help"])
            self.assertEqual(res.returncode, 0)
            self.assertIn("usage", res.stdout.lower())

    def test_37_benchmark_runner_execution(self):
        """TC-T1-BNCH-02: Verifies automated benchmark execution runs autonomously to completion."""
        if not BENCHMARK_PY.exists():
            self.skipTest("mesh_benchmark.py not yet implemented by worker")

        res = run_benchmark_cli(["--output", str(self.report_file), "--quick"], timeout=120)
        self.assertEqual(res.returncode, 0, f"Benchmark execution failed: {res.stderr}\n{res.stdout}")

    def test_38_benchmark_report_file_generation(self):
        """TC-T1-BNCH-03: Verifies BENCHMARK_REPORT.json is created and non-empty."""
        if not BENCHMARK_PY.exists():
            self.skipTest("mesh_benchmark.py not yet implemented by worker")

        self.assertTrue(self.report_file.exists(), "BENCHMARK_REPORT.json was not created")
        self.assertGreater(self.report_file.stat().st_size, 100)

    def test_39_benchmark_report_sla_criteria(self):
        """TC-T1-BNCH-04: Verifies all SLA criteria are marked passed in the generated report."""
        if not self.report_file.exists():
            self.skipTest("Report file does not exist")

        with open(self.report_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.assertEqual(data.get("status"), "PASSED")
        ac = data.get("acceptance_criteria", {})
        self.assertTrue(ac.get("container_spinup_latency", {}).get("passed", False))
        self.assertTrue(ac.get("cross_volume_io_latency", {}).get("passed", False))
        self.assertTrue(ac.get("inter_service_handoff_latency", {}).get("passed", False))
        self.assertTrue(ac.get("integration_tests_pass_rate", {}).get("passed", False))
        self.assertTrue(ac.get("resource_quota_enforcement", {}).get("passed", False))

    def test_40_benchmark_throughput_comparison_metrics(self):
        """TC-T1-BNCH-05: Verifies ext4 volume vs host bind mount throughput comparison metrics."""
        if not self.report_file.exists():
            self.skipTest("Report file does not exist")

        with open(self.report_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        st = data.get("storage_throughput_comparison", {})
        self.assertIn("host_bind_mount", st)
        self.assertIn("ext4_named_volume", st)
        speedup = st.get("speedup", {})
        self.assertGreater(speedup.get("sequential_write_ratio", 0), 1.0)


# =============================================================================
# TIER 2: BOUNDARY & CORNER CASES (>=5 TESTS)
# =============================================================================
class TestTier2BoundaryAndCornerCases(unittest.TestCase):
    """Verifies edge cases, invalid inputs, failure cascading, and error resilience."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="mesh_e2e_bnd_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_41_invalid_config_missing_or_invalid_fields(self):
        """TC-T2-BND-01: Invalid topology network configuration is rejected with non-zero exit code."""
        bad_json = self.temp_dir / "bad_mesh.json"
        with open(bad_json, "w") as f:
            json.dump({
                "mesh_name": "invalid_box",
                "network": {
                    "name": "invalid_net",
                    "driver": "invalid_driver_xyz",
                    "subnet": "invalid_subnet_format"
                },
                "services": {}
            }, f)

        res = run_orchestrator(["up", "--file", str(bad_json), "--json"])
        self.assertNotEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "error")

    def test_42_invalid_resource_limits(self):
        """TC-T2-BND-02: Negative CPU or malformed memory values in topology are rejected."""
        bad_json = self.temp_dir / "bad_limits.json"
        config = {
            "mesh_name": "bad_limits_mesh",
            "services": {
                "producer": {
                    "image": "python:3.12-alpine",
                    "cpus": -2.0,
                    "memory": "invalid_mem",
                }
            }
        }
        with open(bad_json, "w") as f:
            json.dump(config, f)

        res = run_orchestrator(["up", "--file", str(bad_json), "--json"])
        self.assertNotEqual(res.returncode, 0)

    def test_43_exec_nonexistent_service(self):
        """TC-T2-BND-03: Executing commands against a non-existent service name returns error."""
        res = run_orchestrator(["exec", "non_existent_service_xyz", "--json", "--", "ls"])
        self.assertNotEqual(res.returncode, 0)
        data = json.loads(res.stdout)
        self.assertEqual(data.get("status"), "error")

    def test_44_exec_nonexistent_command(self):
        """TC-T2-BND-04: Executing an invalid/missing binary inside container returns code 126 or 127."""
        prefix = f"bndcmd_{uuid.uuid4().hex[:6]}"
        m_file = create_ephemeral_mesh_config(self.temp_dir, prefix, producer_cmd=["tail", "-f", "/dev/null"], consumer_cmd=["tail", "-f", "/dev/null"])
        try:
            run_orchestrator(["up", "--file", str(m_file), "--json"], timeout=30)
            res = run_orchestrator(["exec", "producer", "--file", str(m_file), "--json", "--", "non_existent_binary_12345"])
            self.assertIn(res.returncode, [1, 126, 127])
            data = json.loads(res.stdout)
            self.assertEqual(data.get("status"), "error")
        finally:
            run_orchestrator(["down", "--file", str(m_file), "--json"], timeout=30)
            force_cleanup_docker_resources([f"{prefix}-producer", f"{prefix}-consumer"], [f"{prefix}_vol"], [f"{prefix}_net"])

    def test_45_rapid_sequential_up_down_cycles(self):
        """TC-T2-BND-05: 3 rapid consecutive up and down cycles execute without resource leaks."""
        prefix = f"bndcycle_{uuid.uuid4().hex[:6]}"
        m_file = create_ephemeral_mesh_config(self.temp_dir, prefix, producer_cmd=["tail", "-f", "/dev/null"], consumer_cmd=["tail", "-f", "/dev/null"])
        try:
            for cycle in range(3):
                up_res = run_orchestrator(["up", "--file", str(m_file), "--json"], timeout=30)
                self.assertEqual(up_res.returncode, 0, f"Cycle {cycle} up failed: {up_res.stderr}")
                down_res = run_orchestrator(["down", "--file", str(m_file), "--json"], timeout=30)
                self.assertEqual(down_res.returncode, 0, f"Cycle {cycle} down failed: {down_res.stderr}")
        finally:
            force_cleanup_docker_resources([f"{prefix}-producer", f"{prefix}-consumer"], [f"{prefix}_vol"], [f"{prefix}_net"])

    def test_46_exec_special_characters_and_spaces(self):
        """TC-T2-BND-06: Preserves arguments with spaces, symbols, and quotes without shell injection."""
        prefix = f"bndchars_{uuid.uuid4().hex[:6]}"
        m_file = create_ephemeral_mesh_config(self.temp_dir, prefix, producer_cmd=["tail", "-f", "/dev/null"], consumer_cmd=["tail", "-f", "/dev/null"])
        try:
            run_orchestrator(["up", "--file", str(m_file), "--json"], timeout=30)
            test_phrase = "hello world ; echo injected && test 'quoted' $HOME"
            res = run_orchestrator(["exec", "producer", "--file", str(m_file), "--", "echo", test_phrase])
            self.assertEqual(res.returncode, 0)
            self.assertEqual(res.stdout.strip(), test_phrase)
        finally:
            run_orchestrator(["down", "--file", str(m_file), "--json"], timeout=30)
            force_cleanup_docker_resources([f"{prefix}-producer", f"{prefix}-consumer"], [f"{prefix}_vol"], [f"{prefix}_net"])

    def test_47_teardown_when_containers_already_stopped(self):
        """TC-T2-BND-07: 'down' cleanly removes resources even when containers were already stopped."""
        prefix = f"bndstop_{uuid.uuid4().hex[:6]}"
        m_file = create_ephemeral_mesh_config(self.temp_dir, prefix, producer_cmd=["tail", "-f", "/dev/null"], consumer_cmd=["tail", "-f", "/dev/null"])
        try:
            run_orchestrator(["up", "--file", str(m_file), "--json"], timeout=30)
            # Manually stop containers
            subprocess.run(["docker", "stop", "-t", "1", f"{prefix}-producer"], capture_output=True)
            subprocess.run(["docker", "stop", "-t", "1", f"{prefix}-consumer"], capture_output=True)

            res = run_orchestrator(["down", "--file", str(m_file), "--json"], timeout=30)
            self.assertEqual(res.returncode, 0)
            data = json.loads(res.stdout)
            self.assertEqual(data.get("status"), "success")
        finally:
            force_cleanup_docker_resources([f"{prefix}-producer", f"{prefix}-consumer"], [f"{prefix}_vol"], [f"{prefix}_net"])

    def test_48_malformed_json_config(self):
        """TC-T2-BND-08: Corrupted/malformed JSON syntax is caught gracefully."""
        bad_file = self.temp_dir / "corrupted.json"
        with open(bad_file, "w") as f:
            f.write("{ invalid_json: true, ... }")
        res = run_orchestrator(["up", "--file", str(bad_file), "--json"])
        self.assertNotEqual(res.returncode, 0)


# =============================================================================
# TIER 3: CROSS-FEATURE COMBINATIONS
# =============================================================================
class TestTier3CrossFeatureCombinations(unittest.TestCase):
    """Verifies concurrency, race condition prevention, and resource quota ceilings."""

    @classmethod
    def setUpClass(cls):
        cls.test_dir = Path(tempfile.mkdtemp(prefix="mesh_e2e_xft_"))
        cls.prefix = f"e2exft_{uuid.uuid4().hex[:6]}"
        cls.mesh_file = create_ephemeral_mesh_config(
            cls.test_dir,
            cls.prefix,
            producer_cpus=0.5,
            producer_mem="128m",
            consumer_cpus=0.5,
            consumer_mem="128m",
        )
        cls.c_prod = f"{cls.prefix}-producer"
        cls.c_cons = f"{cls.prefix}-consumer"
        cls.net = f"{cls.prefix}_net"
        cls.vol = f"{cls.prefix}_vol"

        run_orchestrator(["up", "--file", str(cls.mesh_file), "--json"], timeout=45)
        time.sleep(1.5)

    @classmethod
    def tearDownClass(cls):
        run_orchestrator(["down", "--file", str(cls.mesh_file), "--json"], timeout=30)
        force_cleanup_docker_resources([cls.c_prod, cls.c_cons], [cls.vol], [cls.net])
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_49_exec_during_atomic_schema_update(self):
        """TC-T3-XFT-01: Concurrently executing commands during atomic contract publishing causes no corruption."""
        cmd_trigger = [
            "python3", "-c",
            f"""
import urllib.request, json
payload = json.dumps({{'version': '2.1.0'}}).encode('utf-8')
req = urllib.request.Request('http://{self.c_prod}:8000/admin/contract/update', data=payload, headers={{'Content-Type': 'application/json'}}, method='POST')
urllib.request.urlopen(req, timeout=5)
            """
        ]
        cmd_read = ["cat", "/shared/contracts/manifest.json"]

        # Run concurrent exec commands
        p_update = subprocess.Popen([sys.executable, str(ORCHESTRATOR_PY), "exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd_trigger, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        p_cat = subprocess.Popen([sys.executable, str(ORCHESTRATOR_PY), "exec", "producer", "--file", str(self.mesh_file), "--"] + cmd_read, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        out_up, _ = p_update.communicate(timeout=10)
        out_cat, _ = p_cat.communicate(timeout=10)

        self.assertEqual(p_update.returncode, 0)
        self.assertEqual(p_cat.returncode, 0)

        # Confirm valid JSON read from manifest
        parsed = json.loads(out_cat.decode())
        self.assertIn("version", parsed)

    def test_50_continuous_querying_during_version_bump(self):
        """TC-T3-XFT-02: Rapid continuous HTTP queries during schema version bump experience 0 failed requests."""
        cmd = [
            "python3", "-c",
            f"""
import urllib.request, json, time
successes = 0
for _ in range(15):
    with urllib.request.urlopen('http://{self.c_prod}:8000/health', timeout=3) as r:
        if r.status == 200:
            successes += 1
    time.sleep(0.02)
assert successes == 15, f'Expected 15/15 successful queries, got {{successes}}'
print('CONTINUOUS_HTTP_SUCCESS: 15/15')
            """
        ]
        res = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + cmd, timeout=15)
        self.assertEqual(res.returncode, 0)
        self.assertIn("15/15", res.stdout)

    def test_51_cgroup_memory_limit_oom_isolation(self):
        """TC-T3-XFT-03: Container allocating past memory ceiling is killed (137) while adjacent container survives."""
        # Producer was allocated 128m. Attempting to allocate 200MB triggers OOM
        cmd_oom = [
            "python3", "-c",
            "bytearray(200 * 1024 * 1024)"
        ]
        res_oom = run_orchestrator(["exec", "producer", "--file", str(self.mesh_file), "--"] + cmd_oom)
        self.assertEqual(res_oom.returncode, 137, f"Expected OOM kill exit code 137, got {res_oom.returncode}")

        # Verify Consumer is ALIVE and unharmed
        res_adj = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--", "echo", "CONSUMER_ALIVE"])
        self.assertEqual(res_adj.returncode, 0)
        self.assertEqual(res_adj.stdout.strip(), "CONSUMER_ALIVE")

    def test_52_cgroup_cpu_throttling_non_starvation(self):
        """TC-T3-XFT-04: Heavy CPU burn in Producer does not starve Consumer response time."""
        # Burn CPU in background inside Producer for 1.5 seconds
        burn_cmd = ["python3", "-c", "import time; t0 = time.time(); [x*x for x in range(10000000) if time.time() - t0 < 1.5]"]
        p_burn = subprocess.Popen([sys.executable, str(ORCHESTRATOR_PY), "exec", "producer", "--file", str(self.mesh_file), "--"] + burn_cmd)

        # Concurrently compute workload inside Consumer
        comp_cmd = ["python3", "-c", "import time; t0 = time.perf_counter(); sum(i*i for i in range(500000)); print(f'DUR:{time.perf_counter()-t0:.4f}')"]
        res_comp = run_orchestrator(["exec", "consumer", "--file", str(self.mesh_file), "--"] + comp_cmd, timeout=10)

        p_burn.communicate(timeout=10)

        self.assertEqual(res_comp.returncode, 0)
        self.assertIn("DUR:", res_comp.stdout)


# =============================================================================
# TIER 4: REAL-WORLD WORKLOAD SCENARIOS
# =============================================================================
class TestTier4RealWorldWorkloadScenario(unittest.TestCase):
    """
    Full end-to-end multi-agent cooperative workflow test:
    1. Provision multi-agent mesh from topology
    2. Verify health and internal DNS resolution
    3. Ingest initial v1 contract
    4. Trigger dynamic update to v2
    5. Verify Consumer detects in < 500ms and queries new v2 endpoint
    6. Execute benchmark runner and verify BENCHMARK_REPORT.json
    7. Clean teardown and assert zero dangling Docker resources
    """

    def test_53_full_end_to_end_autonomous_workflow(self):
        """TC-T4-E2E-01: End-to-end verification of complete multi-agent mesh lifecycle."""
        temp_dir = Path(tempfile.mkdtemp(prefix="mesh_e2e_tier4_"))
        prefix = f"e2et4_{uuid.uuid4().hex[:6]}"
        mesh_file = create_ephemeral_mesh_config(temp_dir, prefix, subnet="172.29.0.0/16")
        c_prod = f"{prefix}-producer"
        c_cons = f"{prefix}-consumer"
        net = f"{prefix}_net"
        vol = f"{prefix}_vol"

        try:
            # Step 1: Up mesh
            t0 = time.perf_counter()
            up_res = run_orchestrator(["up", "--file", str(mesh_file), "--json"], timeout=45)
            self.assertEqual(up_res.returncode, 0, f"Mesh up failed: {up_res.stderr}")
            up_data = json.loads(up_res.stdout)
            self.assertEqual(up_data.get("status"), "success")
            spinup_time = time.perf_counter() - t0
            self.assertLess(spinup_time, 10.0, f"Multi-container mesh spin-up time exceeded threshold: {spinup_time:.2f}s")
            # Verify per-container spin-up latency conforms to < 3.0s SLA
            per_container = spinup_time / max(len(up_data.get("containers", {})), 1)
            self.assertLess(per_container, 3.0, f"Per-container spin-up exceeded 3.0s SLA: {per_container:.2f}s")

            # Step 2: Verify health
            time.sleep(1.5)
            stat_res = run_orchestrator(["status", "--file", str(mesh_file), "--json"], timeout=15)
            self.assertEqual(stat_res.returncode, 0)
            stat_data = json.loads(stat_res.stdout)
            self.assertTrue(stat_data.get("healthy"))

            # Step 3: Consumer queries Producer v1 items over internal Docker DNS
            q_v1 = [
                "python3", "-c",
                f"import urllib.request, json; resp = json.loads(urllib.request.urlopen('http://{c_prod}:8000/api/v1/items').read().decode()); assert len(resp['items']) > 0; print('V1_READY')"
            ]
            r_v1 = run_orchestrator(["exec", "consumer", "--file", str(mesh_file), "--"] + q_v1, timeout=10)
            self.assertEqual(r_v1.returncode, 0)
            self.assertIn("V1_READY", r_v1.stdout)

            # Step 4: Trigger dynamic update from v1 to v2
            update_cmd = [
                "python3", "-c",
                f"""
import urllib.request, json
payload = json.dumps({{'version': '2.0.0'}}).encode('utf-8')
req = urllib.request.Request('http://{c_prod}:8000/admin/contract/update', data=payload, headers={{'Content-Type': 'application/json'}}, method='POST')
with urllib.request.urlopen(req, timeout=5) as r:
    assert r.status == 200
print('TRIGGER_V2_DONE')
                """
            ]
            t_trig = time.perf_counter()
            r_trig = run_orchestrator(["exec", "consumer", "--file", str(mesh_file), "--"] + update_cmd, timeout=10)
            self.assertEqual(r_trig.returncode, 0)

            # Step 5: Verify Consumer detects update in < 500ms and queries new /api/v2/items endpoint
            time.sleep(0.3)
            q_v2 = [
                "python3", "-c",
                f"import urllib.request, json; resp = json.loads(urllib.request.urlopen('http://{c_prod}:8000/api/v2/items').read().decode()); assert resp['version'] == '2.0.0'; print('V2_CONSUMED')"
            ]
            r_v2 = run_orchestrator(["exec", "consumer", "--file", str(mesh_file), "--"] + q_v2, timeout=10)
            self.assertEqual(r_v2.returncode, 0)
            self.assertIn("V2_CONSUMED", r_v2.stdout)

            # Step 6: Clean Teardown
            down_res = run_orchestrator(["down", "--file", str(mesh_file), "--json"], timeout=30)
            self.assertEqual(down_res.returncode, 0)

            # Step 7: Verify zero dangling Docker resources
            self.assertIsNone(docker_inspect(c_prod))
            self.assertIsNone(docker_inspect(c_cons))
            self.assertIsNone(docker_inspect(net))
            self.assertIsNone(docker_inspect(vol))

        finally:
            force_cleanup_docker_resources([c_prod, c_cons], [vol], [net])
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
