#!/usr/bin/env python3
"""
Adversarial Stress Harness: Resource Quota Isolation, Race Conditions, and Latency Thresholds

Conducts rigorous empirical adversarial verification:
1. Memory Quota Stress:
   - Hard memory ceiling (128MB) on hog container.
   - Dynamic memory allocation exceeding ceiling.
   - Verifies kernel OOM containment (exit code 137).
   - Verifies adjacent container remains ALIVE, responsive (exit code 0), and serves HTTP traffic without corruption.
2. CPU Quota Throttling & Non-Starvation:
   - 0.5 CPU container saturated with multi-process infinite burn loop.
   - Measures compute duration and HTTP response latency on adjacent container before and under stress.
   - Verifies jitter < 25% and adjacent container is non-starved (100% HTTP 200 OK).
3. Concurrent Volume Writes under Race Conditions:
   - Multiple concurrent container processes writing competing OpenAPI specs and manifests to /shared/contracts.
   - Continuous rapid reader reading manifest.json and verifying SHA-256 integrity under concurrency.
   - Abrupt process kill mid-staging to verify zero torn writes or corrupted JSON payloads.
4. Latency Thresholds Re-Verification:
   - Container spin-up latency (< 3.0s SLA) across 10 iterations.
   - Cross-volume file I/O latency (< 50ms SLA) across 20 iterations.
   - Inter-service dynamic handoff latency (< 500ms SLA) across multiple version bumps.
5. Docker Daemon Hygiene:
   - Zero dangling containers, volumes, or networks post-execution.
"""

import os
import sys
import json
import time
import math
import shutil
import hashlib
import tempfile
import threading
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
ORCHESTRATOR_PY = SCRIPTS_DIR / "mesh_orchestrator.py"
CANONICAL_MESH_JSON = REPO_ROOT / "test_projects" / "multi_agent_mesh" / "mesh.json"

IMAGE_NAME = "python:3.12-alpine"


def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def run_docker(cmd: List[str], check: bool = False, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker"] + cmd,
        capture_output=True,
        text=True,
        check=check,
        timeout=timeout,
    )


def run_orchestrator(args: List[str], timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ORCHESTRATOR_PY)] + args,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def percentile(data: List[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_d = sorted(data)
    k = (len(sorted_d) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_d[int(k)]
    d0 = sorted_d[int(f)] * (c - k)
    d1 = sorted_d[int(c)] * (k - f)
    return d0 + d1


# =============================================================================
# STRESS HARNESS SUITE
# =============================================================================

class AdversarialStressHarness:
    def __init__(self):
        self.results: Dict[str, Any] = {}
        self.passed_all = True

    def cleanup_ephemeral_resources(self, prefix: str):
        """Forcefully cleans up any containers, volumes, or networks with the given prefix."""
        # Containers
        ps = run_docker(["ps", "-a", "--filter", f"name={prefix}", "--format", "{{.Names}}"])
        for c in ps.stdout.strip().split():
            if c:
                run_docker(["rm", "-f", c])
        # Volumes
        vols = run_docker(["volume", "ls", "--filter", f"name={prefix}", "--format", "{{.Name}}"])
        for v in vols.stdout.strip().split():
            if v:
                run_docker(["volume", "rm", v])
        # Networks
        nets = run_docker(["network", "ls", "--filter", f"name={prefix}", "--format", "{{.Name}}"])
        for n in nets.stdout.strip().split():
            if n:
                run_docker(["network", "rm", n])

    # -------------------------------------------------------------------------
    # TEST 1: MEMORY QUOTA STRESS & KERNEL OOM CONTAINMENT
    # -------------------------------------------------------------------------
    def test_memory_quota_stress(self) -> Dict[str, Any]:
        log("\n" + "=" * 70)
        log("STAGE 1: ADVERSARIAL MEMORY QUOTA STRESS & OOM CONTAINMENT")
        log("=" * 70)

        prefix = "adv_mem"
        self.cleanup_ephemeral_resources(prefix)

        net_name = f"{prefix}_net"
        vol_name = f"{prefix}_vol"
        hog_name = f"{prefix}_hog"
        adj_name = f"{prefix}_adj"

        try:
            # 1. Setup network & volume
            run_docker(["network", "create", "--driver", "bridge", net_name])
            run_docker(["volume", "create", vol_name])

            # 2. Spawn adjacent container with HTTP server and 256MB limit
            server_script = (
                "from http.server import HTTPServer, BaseHTTPRequestHandler\n"
                "import json\n"
                "class H(BaseHTTPRequestHandler):\n"
                "    def do_GET(self):\n"
                "        self.send_response(200)\n"
                "        self.send_header('Content-Type', 'application/json')\n"
                "        self.end_headers()\n"
                "        self.wfile.write(b'{\"status\":\"healthy\",\"container\":\"adjacent\"}')\n"
                "HTTPServer(('0.0.0.0', 8080), H).serve_forever()\n"
            )
            run_docker([
                "run", "-d",
                "--name", adj_name,
                "--network", net_name,
                "--network-alias", "adjacent-svc",
                "--memory", "256m",
                "--memory-swap", "256m",
                "--cpus", "0.5",
                "-v", f"{vol_name}:/shared",
                IMAGE_NAME,
                "python3", "-c", server_script
            ])

            # 3. Spawn hog container with tight 128MB limit
            run_docker([
                "run", "-d",
                "--name", hog_name,
                "--network", net_name,
                "--network-alias", "hog-svc",
                "--memory", "128m",
                "--memory-swap", "128m",
                "--cpus", "0.5",
                "-v", f"{vol_name}:/shared",
                IMAGE_NAME,
                "tail", "-f", "/dev/null"
            ])

            time.sleep(1.0)

            # Verify adjacent server is responding initially
            r_init = run_docker([
                "exec", hog_name, "python3", "-c",
                "import urllib.request; print(urllib.request.urlopen('http://adjacent-svc:8080').read().decode())"
            ])
            log(f"Initial cross-container HTTP probe: {r_init.stdout.strip()}")

            # 4. Adversarial Attack: Allocate 250MB under 128MB limit in hog
            log("Executing memory burst allocation exceeding 128MB limit (attempting 250MB)...")
            alloc_script = (
                "import sys, time\n"
                "print('BURST_START', flush=True)\n"
                "chunks = []\n"
                "# Allocate 25 chunks of 10MB = 250MB\n"
                "for i in range(25):\n"
                "    chunks.append(bytearray(10 * 1024 * 1024))\n"
                "    time.sleep(0.01)\n"
                "print('BURST_END', flush=True)\n"
            )

            t0 = time.perf_counter()
            r_alloc = run_docker(["exec", hog_name, "python3", "-c", alloc_script], timeout=15)
            d_alloc = time.perf_counter() - t0

            hog_exit_code = r_alloc.returncode
            log(f"Hog memory burst completed in {d_alloc:.3f}s with exit code: {hog_exit_code}")
            log(f"Hog stderr: {r_alloc.stderr.strip()}")

            # Kernel OOM killer sends SIGKILL (9) -> 128 + 9 = 137
            oom_isolated = (hog_exit_code == 137)
            log(f"Kernel OOM containment verified (exit code == 137): {oom_isolated}")

            # 5. Verify Adjacent Container: Health, responsiveness, memory stability
            adj_inspect = run_docker(["inspect", adj_name])
            adj_state = json.loads(adj_inspect.stdout)[0]["State"]
            adj_is_running = adj_state.get("Running", False)
            adj_oom_killed = adj_state.get("OOMKilled", False)

            # Exec into adjacent container and run active queries
            r_adj_exec = run_docker([
                "exec", adj_name, "python3", "-c",
                "import urllib.request, json\n"
                "resp = urllib.request.urlopen('http://127.0.0.1:8080')\n"
                "data = json.loads(resp.read().decode())\n"
                "assert data['status'] == 'healthy'\n"
                "print('ADJACENT_VERIFIED_HEALTHY')"
            ])
            adj_exec_code = r_adj_exec.returncode
            adj_exec_out = r_adj_exec.stdout.strip()

            log(f"Adjacent container state: Running={adj_is_running}, OOMKilled={adj_oom_killed}")
            log(f"Adjacent container exec exit code: {adj_exec_code}, output: {adj_exec_out}")

            pass_stage1 = (oom_isolated and adj_is_running and not adj_oom_killed and adj_exec_code == 0 and "ADJACENT_VERIFIED_HEALTHY" in adj_exec_out)

            res = {
                "stage": "memory_quota_stress",
                "passed": pass_stage1,
                "hog_memory_limit": "128m",
                "attempted_allocation_mb": 250,
                "hog_exit_code": hog_exit_code,
                "oom_isolated_code_137": oom_isolated,
                "adjacent_container_running": adj_is_running,
                "adjacent_oom_killed": adj_oom_killed,
                "adjacent_exec_code": adj_exec_code,
                "adjacent_health_verified": "ADJACENT_VERIFIED_HEALTHY" in adj_exec_out,
            }
            log(f"STAGE 1 VERDICT: {'PASS' if pass_stage1 else 'FAIL'}")
            return res

        finally:
            self.cleanup_ephemeral_resources(prefix)

    # -------------------------------------------------------------------------
    # TEST 2: CPU QUOTA THROTTLING, JITTER & NON-STARVATION
    # -------------------------------------------------------------------------
    def test_cpu_quota_throttling(self) -> Dict[str, Any]:
        log("\n" + "=" * 70)
        log("STAGE 2: ADVERSARIAL CPU QUOTA THROTTLING & JITTER VERIFICATION")
        log("=" * 70)

        prefix = "adv_cpu"
        self.cleanup_ephemeral_resources(prefix)

        net_name = f"{prefix}_net"
        hog_name = f"{prefix}_hog"
        adj_name = f"{prefix}_adj"

        try:
            run_docker(["network", "create", "--driver", "bridge", net_name])

            # Spawn adjacent container with 0.5 CPU and an internal HTTP server + compute responder
            adj_code = (
                "from http.server import HTTPServer, BaseHTTPRequestHandler\n"
                "import time, json, hashlib\n"
                "class H(BaseHTTPRequestHandler):\n"
                "    def do_GET(self):\n"
                "        # perform standard 200,000 iter compute work\n"
                "        t0 = time.perf_counter()\n"
                "        total = sum(i*i for i in range(200_000))\n"
                "        h = hashlib.sha256(str(total).encode()).hexdigest()\n"
                "        dur_ms = (time.perf_counter() - t0) * 1000.0\n"
                "        self.send_response(200)\n"
                "        self.send_header('Content-Type', 'application/json')\n"
                "        self.end_headers()\n"
                "        self.wfile.write(json.dumps({'dur_ms': dur_ms, 'hash': h[:8]}).encode())\n"
                "    def log_message(self, *args): pass\n"
                "HTTPServer(('0.0.0.0', 8080), H).serve_forever()\n"
            )
            run_docker([
                "run", "-d",
                "--name", adj_name,
                "--network", net_name,
                "--network-alias", "adj-worker",
                "--cpus", "0.5",
                IMAGE_NAME,
                "python3", "-c", adj_code
            ])

            # Spawn hog container with 0.5 CPU
            run_docker([
                "run", "-d",
                "--name", hog_name,
                "--network", net_name,
                "--network-alias", "hog-burner",
                "--cpus", "0.5",
                IMAGE_NAME,
                "tail", "-f", "/dev/null"
            ])

            time.sleep(1.0)

            # Baseline Benchmark: Compute workload & HTTP latency on adj container without hog CPU load
            log("Measuring baseline compute & HTTP latency on adjacent container (no hog load)...")
            comp_workload = (
                "import time, hashlib\n"
                "t0 = time.perf_counter()\n"
                "res = sum(i*i for i in range(1_500_000))\n"
                "h = hashlib.sha256(str(res).encode()).hexdigest()\n"
                "print(f'{time.perf_counter() - t0:.5f}')\n"
            )

            base_comp_times = []
            for _ in range(5):
                r = run_docker(["exec", adj_name, "python3", "-c", comp_workload])
                if r.returncode == 0:
                    base_comp_times.append(float(r.stdout.strip()))

            base_http_latencies = []
            for _ in range(10):
                t0 = time.perf_counter()
                r = run_docker(["exec", adj_name, "python3", "-c",
                                "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080', timeout=2).read()"])
                if r.returncode == 0:
                    base_http_latencies.append((time.perf_counter() - t0) * 1000.0)

            base_comp_mean = sum(base_comp_times) / len(base_comp_times) if base_comp_times else 0.15
            base_http_mean = sum(base_http_latencies) / len(base_http_latencies) if base_http_latencies else 20.0
            base_http_p95 = percentile(base_http_latencies, 95)

            log(f"  Baseline Compute Time (mean): {base_comp_mean:.4f}s")
            log(f"  Baseline HTTP Latency (mean): {base_http_mean:.2f}ms, (p95): {base_http_p95:.2f}ms")

            # Adversarial Stress: Launch high-intensity multi-process CPU burn loop in hog container
            log("Launching 100% CPU burn loop across 4 worker processes in hog container (0.5 CPU cap)...")
            burn_script = (
                "import multiprocessing as mp, time\n"
                "def burner():\n"
                "    t_end = time.time() + 10.0\n"
                "    while time.time() < t_end:\n"
                "        _ = [x*x for x in range(10000)]\n"
                "if __name__ == '__main__':\n"
                "    procs = [mp.Process(target=burner) for _ in range(4)]\n"
                "    for p in procs: p.start()\n"
                "    for p in procs: p.join()\n"
            )
            # Run burn in detached mode
            run_docker(["exec", "-d", hog_name, "python3", "-c", burn_script])
            time.sleep(0.5)

            # While hog is actively burning CPU, run stressed benchmarks on adjacent container
            log("Measuring compute & HTTP latency on adjacent container under active CPU saturation...")
            stress_comp_times = []
            for _ in range(5):
                r = run_docker(["exec", adj_name, "python3", "-c", comp_workload])
                if r.returncode == 0:
                    stress_comp_times.append(float(r.stdout.strip()))

            stress_http_latencies = []
            http_failures = 0
            for _ in range(10):
                t0 = time.perf_counter()
                r = run_docker(["exec", adj_name, "python3", "-c",
                                "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080', timeout=2).read()"])
                if r.returncode == 0:
                    stress_http_latencies.append((time.perf_counter() - t0) * 1000.0)
                else:
                    http_failures += 1

            stress_comp_mean = sum(stress_comp_times) / len(stress_comp_times) if stress_comp_times else base_comp_mean
            stress_http_mean = sum(stress_http_latencies) / len(stress_http_latencies) if stress_http_latencies else base_http_mean
            stress_http_p95 = percentile(stress_http_latencies, 95)

            compute_jitter = ((stress_comp_mean - base_comp_mean) / base_comp_mean) * 100.0
            http_jitter = ((stress_http_p95 - base_http_p95) / max(base_http_p95, 0.001)) * 100.0

            log(f"  Stressed Compute Time (mean): {stress_comp_mean:.4f}s (Jitter: {compute_jitter:+.2f}%)")
            log(f"  Stressed HTTP Latency (p95): {stress_http_p95:.2f}ms (Jitter: {http_jitter:+.2f}%)")
            log(f"  HTTP Probe Failures / Dropped: {http_failures}/10")

            # Check criteria: Jitter < 25% (or non-positive if cache improved), adjacent container not starved (0 dropped requests)
            jitter_acceptable = abs(compute_jitter) < 25.0
            non_starved = (http_failures == 0 and stress_comp_mean < (base_comp_mean * 1.4))

            pass_stage2 = (jitter_acceptable and non_starved)
            res = {
                "stage": "cpu_quota_throttling",
                "passed": pass_stage2,
                "base_compute_seconds": round(base_comp_mean, 4),
                "stressed_compute_seconds": round(stress_comp_mean, 4),
                "compute_jitter_percent": round(compute_jitter, 2),
                "base_http_p95_ms": round(base_http_p95, 2),
                "stressed_http_p95_ms": round(stress_http_p95, 2),
                "http_jitter_percent": round(http_jitter, 2),
                "http_failures": http_failures,
                "jitter_under_25_pct": jitter_acceptable,
                "adjacent_non_starved": non_starved,
            }
            log(f"STAGE 2 VERDICT: {'PASS' if pass_stage2 else 'FAIL'}")
            return res

        finally:
            self.cleanup_ephemeral_resources(prefix)

    # -------------------------------------------------------------------------
    # TEST 3: CONCURRENT VOLUME WRITES & RACE CONDITION INTEGRITY
    # -------------------------------------------------------------------------
    def test_concurrent_volume_writes(self) -> Dict[str, Any]:
        log("\n" + "=" * 70)
        log("STAGE 3: CONCURRENT VOLUME WRITES & ATOMIC RENAME RACE INTEGRITY")
        log("=" * 70)

        prefix = "adv_race"
        self.cleanup_ephemeral_resources(prefix)

        vol_name = f"{prefix}_vol"
        w1_name = f"{prefix}_writer1"
        w2_name = f"{prefix}_writer2"
        reader_name = f"{prefix}_reader"

        try:
            run_docker(["volume", "create", vol_name])

            # Spawn 2 writer containers and 1 continuous reader container sharing /shared/contracts
            for cname in [w1_name, w2_name, reader_name]:
                run_docker([
                    "run", "-d",
                    "--name", cname,
                    "-v", f"{vol_name}:/shared/contracts",
                    IMAGE_NAME,
                    "tail", "-f", "/dev/null"
                ])

            time.sleep(1.0)

            # Writer script: Publishes N atomic versions with staging in .tmp and os.replace
            writer_code_template = """
import os, sys, json, time, hashlib

SCHEMA_DIR = '/shared/contracts'
TMP_DIR = os.path.join(SCHEMA_DIR, '.tmp')
os.makedirs(TMP_DIR, exist_ok=True)
pid = os.getpid()

writer_id = '{writer_id}'
count = {count}

for i in range(count):
    version = f'{{writer_id}}.{{i}}.0'
    schema = {{
        'openapi': '3.0.3',
        'info': {{'title': f'API by {{writer_id}}', 'version': version}},
        'iteration': i,
        'payload': 'X' * (4096 * (i % 5 + 1))  # varying payloads
    }}
    schema_bytes = json.dumps(schema).encode('utf-8')
    schema_hash = hashlib.sha256(schema_bytes).hexdigest()
    
    # 1. Stage schema (versioned file to guarantee immutability under concurrency)
    schema_filename = f'openapi_{{writer_id}}_{{i}}.json'
    tmp_schema = os.path.join(TMP_DIR, f'{{schema_filename}}.{{pid}}')
    with open(tmp_schema, 'wb') as f:
        f.write(schema_bytes)
        f.flush()
        os.fsync(f.fileno())
    final_schema = os.path.join(SCHEMA_DIR, schema_filename)
    os.replace(tmp_schema, final_schema)
    
    # 2. Stage manifest with cryptographic commit
    manifest = {{
        'version': version,
        'sequence': i,
        'writer': writer_id,
        'timestamp_ns': time.time_ns(),
        'schema_file': schema_filename,
        'schema_sha256': schema_hash
    }}
    manifest_bytes = json.dumps(manifest).encode('utf-8')
    tmp_manifest = os.path.join(TMP_DIR, f'manifest_{{writer_id}}_{{pid}}.json')
    with open(tmp_manifest, 'wb') as f:
        f.write(manifest_bytes)
        f.flush()
        os.fsync(f.fileno())
    final_manifest = os.path.join(SCHEMA_DIR, 'manifest.json')
    os.replace(tmp_manifest, final_manifest)
    time.sleep(0.005)

print(f'WRITER_{{writer_id}}_DONE', flush=True)
"""

            # Reader script: Continually reads manifest.json, verifies SHA-256 against referenced schema_file
            reader_code = """
import os, sys, json, time, hashlib

SCHEMA_DIR = '/shared/contracts'
manifest_path = os.path.join(SCHEMA_DIR, 'manifest.json')

valid_reads = 0
hash_mismatches = 0
json_corruptions = 0
missing_schema_files = 0

t_end = time.time() + 6.0
while time.time() < t_end:
    if not os.path.exists(manifest_path):
        time.sleep(0.002)
        continue
    try:
        with open(manifest_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except Exception as e:
        # Torn read / corruption!
        json_corruptions += 1
        time.sleep(0.002)
        continue

    schema_file = data.get('schema_file')
    expected_sha = data.get('schema_sha256')
    if not schema_file or not expected_sha:
        json_corruptions += 1
        continue

    target_path = os.path.join(SCHEMA_DIR, schema_file)
    if not os.path.exists(target_path):
        missing_schema_files += 1
        time.sleep(0.002)
        continue

    try:
        with open(target_path, 'rb') as f:
            actual_sha = hashlib.sha256(f.read()).hexdigest()
        if actual_sha == expected_sha:
            valid_reads += 1
        else:
            hash_mismatches += 1
    except Exception:
        json_corruptions += 1

    time.sleep(0.001)

result = {
    'valid_reads': valid_reads,
    'json_corruptions': json_corruptions,
    'hash_mismatches': hash_mismatches,
    'missing_schema_files': missing_schema_files
}
print(json.dumps(result), flush=True)
"""

            log("Starting concurrent reader in reader container...")
            # Start reader process in background
            p_reader = subprocess.Popen(
                ["docker", "exec", reader_name, "python3", "-c", reader_code],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            time.sleep(0.2)

            log("Launching 2 concurrent writers producing 50 updates each (100 total concurrent atomic commits)...")
            w1_script = writer_code_template.format(writer_id="alpha", count=50)
            w2_script = writer_code_template.format(writer_id="beta", count=50)

            p_w1 = subprocess.Popen(
                ["docker", "exec", w1_name, "python3", "-c", w1_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            p_w2 = subprocess.Popen(
                ["docker", "exec", w2_name, "python3", "-c", w2_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )

            out_w1, err_w1 = p_w1.communicate(timeout=15)
            out_w2, err_w2 = p_w2.communicate(timeout=15)

            log(f"Writer 1 status: {p_w1.returncode}, output: {out_w1.strip()}")
            log(f"Writer 2 status: {p_w2.returncode}, output: {out_w2.strip()}")

            out_reader, err_reader = p_reader.communicate(timeout=15)
            log(f"Reader raw result: {out_reader.strip()}")

            reader_stats = {}
            try:
                reader_stats = json.loads(out_reader.strip())
            except Exception as e:
                log(f"Failed to parse reader output: {e}")

            valid_reads = reader_stats.get("valid_reads", 0)
            json_corruptions = reader_stats.get("json_corruptions", 0)
            hash_mismatches = reader_stats.get("hash_mismatches", 0)
            missing_files = reader_stats.get("missing_schema_files", 0)

            log(f"Reader Statistics: Valid Reads={valid_reads}, JSON Corruptions={json_corruptions}, Hash Mismatches={hash_mismatches}, Missing Files={missing_files}")

            # Adversarial probe 2: Abruptly kill a writer process mid-staging and verify manifest validity
            log("Testing abrupt process SIGKILL mid-staging...")
            kill_script = (
                "import os, signal, time\n"
                "p = '/shared/contracts/.tmp/aborted_test.tmp'\n"
                "with open(p, 'wb') as f: f.write(b'partial data')\n"
                "os.kill(os.getpid(), signal.SIGKILL)\n"
            )
            r_kill = run_docker(["exec", w1_name, "python3", "-c", kill_script])
            log(f"Abrupt kill exit code (expected 137): {r_kill.returncode}")

            # Verify manifest.json is still completely uncorrupted
            r_check_manifest = run_docker([
                "exec", reader_name, "python3", "-c",
                "import json; m = json.load(open('/shared/contracts/manifest.json')); print('VALID_MANIFEST:', m.get('version'))"
            ])
            log(f"Post-kill manifest check: {r_check_manifest.stdout.strip()}")

            pass_stage3 = (
                p_w1.returncode == 0 and
                p_w2.returncode == 0 and
                valid_reads > 50 and
                json_corruptions == 0 and
                hash_mismatches == 0 and
                missing_files == 0 and
                r_kill.returncode == 137 and
                "VALID_MANIFEST:" in r_check_manifest.stdout
            )

            res = {
                "stage": "concurrent_volume_writes",
                "passed": pass_stage3,
                "writer1_exit_code": p_w1.returncode,
                "writer2_exit_code": p_w2.returncode,
                "valid_reads": valid_reads,
                "json_corruptions": json_corruptions,
                "hash_mismatches": hash_mismatches,
                "missing_files": missing_files,
                "mid_staging_kill_exit_code": r_kill.returncode,
                "post_kill_manifest_intact": "VALID_MANIFEST:" in r_check_manifest.stdout,
            }
            log(f"STAGE 3 VERDICT: {'PASS' if pass_stage3 else 'FAIL'}")
            return res

        finally:
            self.cleanup_ephemeral_resources(prefix)

    # -------------------------------------------------------------------------
    # TEST 4: LATENCY THRESHOLDS RE-VERIFICATION
    # -------------------------------------------------------------------------
    def test_latency_thresholds(self) -> Dict[str, Any]:
        log("\n" + "=" * 70)
        log("STAGE 4: QUANTITATIVE LATENCY THRESHOLDS EMPIRICAL RE-VERIFICATION")
        log("=" * 70)

        # 1. Container Spin-Up Latency (< 3.0s SLA)
        log("1. Measuring Container Spin-Up Latency across 10 iterations...")
        spinup_times = []
        for i in range(10):
            cname = f"adv_spin_{i}"
            run_docker(["rm", "-f", cname])
            t0 = time.perf_counter()
            r_run = run_docker(["run", "-d", "--name", cname, "--cpus", "0.5", "--memory", "128m", IMAGE_NAME, "tail", "-f", "/dev/null"])
            r_exec = run_docker(["exec", cname, "echo", "SPINUP_READY"])
            t1 = time.perf_counter()
            run_docker(["rm", "-f", cname])
            if r_run.returncode == 0 and r_exec.returncode == 0 and "SPINUP_READY" in r_exec.stdout:
                spinup_times.append(t1 - t0)

        mean_spinup = sum(spinup_times) / len(spinup_times) if spinup_times else 999.0
        p95_spinup = percentile(spinup_times, 95)
        min_spinup = min(spinup_times) if spinup_times else 999.0
        max_spinup = max(spinup_times) if spinup_times else 999.0

        pass_spinup = (mean_spinup < 3.0 and p95_spinup < 3.0)
        log(f"  Container Spin-Up: mean={mean_spinup:.4f}s, min={min_spinup:.4f}s, max={max_spinup:.4f}s, p95={p95_spinup:.4f}s (SLA < 3.0s: {pass_spinup})")

        # 2. Cross-Volume File I/O Latency (< 50ms SLA)
        log("2. Measuring Cross-Volume File I/O Latency across 20 iterations...")
        vol_io = "adv_io_vol"
        cw = "adv_io_writer"
        cr = "adv_io_reader"
        run_docker(["rm", "-f", cw, cr])
        run_docker(["volume", "rm", vol_io])
        run_docker(["volume", "create", vol_io])

        run_docker(["run", "-d", "--name", cw, "-v", f"{vol_io}:/shared", IMAGE_NAME, "tail", "-f", "/dev/null"])
        run_docker(["run", "-d", "--name", cr, "-v", f"{vol_io}:/shared", IMAGE_NAME, "tail", "-f", "/dev/null"])

        io_latencies_ms = []
        for i in range(20):
            fname = f"ping_{i}.ts"
            rx_name = f"pong_{i}.ts"

            reader_cmd = (
                "import time, pathlib\n"
                f"p = pathlib.Path('/shared/{fname}')\n"
                "while not p.exists(): time.sleep(0.0001)\n"
                f"pathlib.Path('/shared/{rx_name}').write_text(str(time.time_ns()))\n"
            )
            run_docker(["exec", "-d", cr, "python3", "-c", reader_cmd])
            time.sleep(0.02)

            writer_cmd = (
                "import time, pathlib\n"
                f"pathlib.Path('/shared/{fname}').write_text(str(time.time_ns()))\n"
            )
            run_docker(["exec", cw, "python3", "-c", writer_cmd])
            time.sleep(0.05)

            tx_str = run_docker(["exec", cw, "cat", f"/shared/{fname}"]).stdout.strip()
            rx_str = run_docker(["exec", cr, "cat", f"/shared/{rx_name}"]).stdout.strip()
            try:
                tx_ns = int(tx_str)
                rx_ns = int(rx_str)
                dur_ms = max(0.01, (rx_ns - tx_ns) / 1_000_000.0)
                io_latencies_ms.append(dur_ms)
            except Exception:
                pass

        run_docker(["rm", "-f", cw, cr])
        run_docker(["volume", "rm", vol_io])

        mean_io = sum(io_latencies_ms) / len(io_latencies_ms) if io_latencies_ms else 999.0
        p95_io = percentile(io_latencies_ms, 95)
        min_io = min(io_latencies_ms) if io_latencies_ms else 999.0
        max_io = max(io_latencies_ms) if io_latencies_ms else 999.0

        pass_io = (mean_io < 50.0 and p95_io < 50.0)
        log(f"  Cross-Volume I/O: mean={mean_io:.4f}ms, min={min_io:.4f}ms, max={max_io:.4f}ms, p95={p95_io:.4f}ms (SLA < 50ms: {pass_io})")

        # 3. Inter-Service Handoff Latency (< 500ms SLA)
        log("3. Measuring Inter-Service Dynamic Contract Handoff Latency on canonical mesh...")
        # Spin up canonical mesh
        up_res = run_orchestrator(["up", "--file", str(CANONICAL_MESH_JSON), "--json"])
        log(f"  Mesh up status: {up_res.returncode}")
        time.sleep(1.5)

        handoff_latencies = []
        try:
            versions_to_test = ["2.0.0", "2.1.0", "2.2.0", "3.0.0"]
            for v in versions_to_test:
                # Trigger update in Producer
                update_py = (
                    f"import urllib.request, json\n"
                    f"req = urllib.request.Request('http://127.0.0.1:8000/admin/contract/update', "
                    f"data=json.dumps({{'version': '{v}'}}).encode(), headers={{'Content-Type': 'application/json'}})\n"
                    f"print(urllib.request.urlopen(req).read().decode())\n"
                )
                r_upd = run_orchestrator(["exec", "producer", "--file", str(CANONICAL_MESH_JSON), "--", "python3", "-c", update_py])
                time.sleep(0.15)

                # Check Consumer handoff events
                check_py = (
                    f"import json\n"
                    f"events = json.load(open('/shared/contracts/metrics/handoff_events.json'))\n"
                    f"match = [e for e in events if e.get('version') == '{v}']\n"
                    f"if match:\n"
                    f"    print(f\"{{match[0]['latency_ms']}},{{match[0]['verified']}}\")\n"
                    f"else:\n"
                    f"    print('-1,False')\n"
                )
                r_chk = run_orchestrator(["exec", "consumer", "--file", str(CANONICAL_MESH_JSON), "--", "python3", "-c", check_py])
                line = r_chk.stdout.strip().split(",")
                try:
                    lat = float(line[0])
                    ver = (line[1].strip() == "True")
                    if lat >= 0 and ver:
                        handoff_latencies.append(lat)
                        log(f"    Version {v} update detected: {lat:.3f}ms (SHA256 verified: {ver})")
                except Exception as e:
                    log(f"    Failed checking version {v}: {e}")

        finally:
            down_res = run_orchestrator(["down", "--file", str(CANONICAL_MESH_JSON), "--json"])
            log(f"  Mesh down status: {down_res.returncode}")

        mean_handoff = sum(handoff_latencies) / len(handoff_latencies) if handoff_latencies else 999.0
        max_handoff = max(handoff_latencies) if handoff_latencies else 999.0
        pass_handoff = (mean_handoff < 500.0 and max_handoff < 500.0 and len(handoff_latencies) == len(versions_to_test))
        log(f"  Inter-Service Handoff: mean={mean_handoff:.4f}ms, max={max_handoff:.4f}ms (SLA < 500ms: {pass_handoff})")

        pass_stage4 = (pass_spinup and pass_io and pass_handoff)
        res = {
            "stage": "latency_thresholds",
            "passed": pass_stage4,
            "container_spinup": {
                "mean_seconds": round(mean_spinup, 4),
                "p95_seconds": round(p95_spinup, 4),
                "target_seconds": 3.0,
                "passed": pass_spinup
            },
            "cross_volume_io": {
                "mean_ms": round(mean_io, 4),
                "p95_ms": round(p95_io, 4),
                "target_ms": 50.0,
                "passed": pass_io
            },
            "inter_service_handoff": {
                "mean_ms": round(mean_handoff, 4),
                "max_ms": round(max_handoff, 4),
                "tested_versions": len(handoff_latencies),
                "target_ms": 500.0,
                "passed": pass_handoff
            }
        }
        log(f"STAGE 4 VERDICT: {'PASS' if pass_stage4 else 'FAIL'}")
        return res

    # -------------------------------------------------------------------------
    # TEST 5: DOCKER DAEMON HYGIENE
    # -------------------------------------------------------------------------
    def test_docker_hygiene(self) -> Dict[str, Any]:
        log("\n" + "=" * 70)
        log("STAGE 5: DOCKER DAEMON HYGIENE & RESIDUAL RESOURCE AUDIT")
        log("=" * 70)

        # Inspect containers with prefixes used in testing
        test_prefixes = ["adv_", "bench_", "probe_", "mesh-", "multi_agent_mesh_"]
        dangling_containers = []
        dangling_volumes = []
        dangling_networks = []

        for p in test_prefixes:
            c = run_docker(["ps", "-a", "--filter", f"name={p}", "--format", "{{.Names}}"]).stdout.strip().split()
            dangling_containers.extend([x for x in c if x])

            v = run_docker(["volume", "ls", "--filter", f"name={p}", "--format", "{{.Name}}"]).stdout.strip().split()
            dangling_volumes.extend([x for x in v if x])

            n = run_docker(["network", "ls", "--filter", f"name={p}", "--format", "{{.Name}}"]).stdout.strip().split()
            dangling_networks.extend([x for x in n if x])

        log(f"Dangling Containers: {len(dangling_containers)} {dangling_containers}")
        log(f"Dangling Volumes: {len(dangling_volumes)} {dangling_volumes}")
        log(f"Dangling Networks: {len(dangling_networks)} {dangling_networks}")

        clean = (len(dangling_containers) == 0 and len(dangling_volumes) == 0 and len(dangling_networks) == 0)

        res = {
            "stage": "docker_daemon_hygiene",
            "passed": clean,
            "dangling_containers": dangling_containers,
            "dangling_volumes": dangling_volumes,
            "dangling_networks": dangling_networks,
        }
        log(f"STAGE 5 VERDICT: {'PASS' if clean else 'FAIL'}")
        return res

    def run_all(self) -> Dict[str, Any]:
        t_start = time.perf_counter()
        log("STARTING COMPREHENSIVE EMPIRICAL ADVERSARIAL STRESS HARNESS...")

        res1 = self.test_memory_quota_stress()
        res2 = self.test_cpu_quota_throttling()
        res3 = self.test_concurrent_volume_writes()
        res4 = self.test_latency_thresholds()
        res5 = self.test_docker_hygiene()

        total_dur = time.perf_counter() - t_start

        all_passed = (
            res1["passed"] and
            res2["passed"] and
            res3["passed"] and
            res4["passed"] and
            res5["passed"]
        )

        overall = {
            "timestamp": time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            "total_duration_seconds": round(total_dur, 2),
            "verdict": "APPROVE" if all_passed else "REJECT",
            "stages": {
                "stage1_memory_quota_stress": res1,
                "stage2_cpu_quota_throttling": res2,
                "stage3_concurrent_volume_writes": res3,
                "stage4_latency_thresholds": res4,
                "stage5_docker_daemon_hygiene": res5,
            }
        }

        log("\n" + "=" * 70)
        log(f"FINAL ADVERSARIAL CHALLENGER VERDICT: {overall['verdict']} (Duration: {total_dur:.2f}s)")
        log("=" * 70)
        return overall


if __name__ == "__main__":
    harness = AdversarialStressHarness()
    summary = harness.run_all()
    out_file = REPO_ROOT / "tests" / "STRESS_HARNESS_RESULTS.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    log(f"Detailed stress harness results written to: {out_file}")
    sys.exit(0 if summary["verdict"] == "APPROVE" else 1)
