#!/usr/bin/env python3
"""
Comprehensive Live Performance Proof: Setup, Run, and Destroy Comparison
Compares:
  - Option 1: Host Storage / Docker Bind Mount (-v /mnt/c/...)
  - Option 2: Native WSL 2 Linux ext4 (wsl-linker)
  - Option 3: AnyLink Reverse Docker Sandbox (Container ext4)
"""

import os
import sys
import time
import json
import subprocess
from pathlib import Path

NUM_OPS = 1500

def run_wsl_bench():
    """Runs low-level 1,500 operations inside WSL 2 measuring Host 9P vs Native ext4."""
    py_code = f"""
import os, time, shutil

def run_test(path, n={NUM_OPS}):
    # Setup
    t_s0 = time.perf_counter()
    os.makedirs(path, exist_ok=True)
    t_setup = time.perf_counter() - t_s0

    # Run
    t0 = time.perf_counter()
    for i in range(n):
        with open(os.path.join(path, f'f_{{i}}.txt'), 'w') as f:
            f.write(f'export const MODULE_ID = {{i}};')
    t1 = time.perf_counter()

    for i in range(n):
        with open(os.path.join(path, f'f_{{i}}.txt'), 'r') as f:
            _ = f.read()
    t2 = time.perf_counter()

    count = 0
    total_bytes = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            st = os.stat(os.path.join(root, f))
            count += 1
            total_bytes += st.st_size
    t3 = time.perf_counter()

    # Destroy
    t_d0 = time.perf_counter()
    shutil.rmtree(path)
    t_destroy = time.perf_counter() - t_d0

    return {{
        'setup_s': t_setup,
        'writes_s': t1 - t0,
        'reads_s': t2 - t1,
        'stat_s': t3 - t2,
        'run_total_s': t3 - t0,
        'destroy_s': t_destroy,
        'files_count': count
    }}

import json
res_host = run_test('/mnt/c/Users/fauzu/bench_host_proof')
res_native = run_test('/home/fauzul/bench_native_proof')
print('RESULT_JSON:' + json.dumps({{'host_9p': res_host, 'native_ext4': res_native}}))
"""
    cmd = ["wsl", "-d", "Ubuntu-24.04", "--cd", "~", "-e", "python3", "-c", py_code]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    for line in r.stdout.splitlines():
        if line.startswith("RESULT_JSON:"):
            return json.loads(line.replace("RESULT_JSON:", ""))
    raise RuntimeError(f"WSL benchmark failed: {r.stderr or r.stdout}")

def run_docker_container_bench():
    """Runs 1,500 operations inside Docker container ext4 storage."""
    py_code = f"""
import os, time, shutil, json

t_s0 = time.perf_counter()
path = '/workspace/bench_container'
os.makedirs(path, exist_ok=True)
t_setup = time.perf_counter() - t_s0

t0 = time.perf_counter()
for i in range({NUM_OPS}):
    with open(os.path.join(path, f'f_{{i}}.txt'), 'w') as f:
        f.write(f'export const MODULE_ID = {{i}};')
t1 = time.perf_counter()

for i in range({NUM_OPS}):
    with open(os.path.join(path, f'f_{{i}}.txt'), 'r') as f:
        _ = f.read()
t2 = time.perf_counter()

count = 0
for root, dirs, files in os.walk(path):
    for f in files:
        _ = os.stat(os.path.join(root, f))
        count += 1
t3 = time.perf_counter()

t_d0 = time.perf_counter()
shutil.rmtree(path)
t_destroy = time.perf_counter() - t_d0

print('DOCKER_JSON:' + json.dumps({{
    'setup_s': t_setup,
    'writes_s': t1 - t0,
    'reads_s': t2 - t1,
    'stat_s': t3 - t2,
    'run_total_s': t3 - t0,
    'destroy_s': t_destroy,
    'files_count': count
}}))
"""
    cmd = [
        "docker", "run", "--rm",
        "python:3.12-alpine",
        "python", "-c", py_code
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    for line in r.stdout.splitlines():
        if line.startswith("DOCKER_JSON:"):
            return json.loads(line.replace("DOCKER_JSON:", ""))
    raise RuntimeError(f"Docker benchmark failed: {r.stderr or r.stdout}")

def main():
    print("Executing live empirical benchmark (1,500 File I/O Operations)...")
    wsl_res = run_wsl_bench()
    docker_res = run_docker_container_bench()

    host_data = wsl_res["host_9p"]
    ext4_data = wsl_res["native_ext4"]
    anylink_data = docker_res

    print("\n" + "="*80)
    print("LIVE EMPIRICAL BENCHMARK PROOF RESULTS")
    print("="*80)
    print(f"Host 9P NTFS     | Setup: {host_data['setup_s']:.4f}s | Run: {host_data['run_total_s']:.3f}s (Writes: {host_data['writes_s']:.3f}s, Reads: {host_data['reads_s']:.3f}s, Stat: {host_data['stat_s']*1000:.1f}ms) | Destroy: {host_data['destroy_s']:.4f}s")
    print(f"Native ext4 WSL  | Setup: {ext4_data['setup_s']:.4f}s | Run: {ext4_data['run_total_s']:.3f}s (Writes: {ext4_data['writes_s']:.3f}s, Reads: {ext4_data['reads_s']:.3f}s, Stat: {ext4_data['stat_s']*1000:.1f}ms) | Destroy: {ext4_data['destroy_s']:.4f}s")
    print(f"AnyLink Box ext4 | Setup: {anylink_data['setup_s']:.4f}s | Run: {anylink_data['run_total_s']:.3f}s (Writes: {anylink_data['writes_s']:.3f}s, Reads: {anylink_data['reads_s']:.3f}s, Stat: {anylink_data['stat_s']*1000:.1f}ms) | Destroy: {anylink_data['destroy_s']:.4f}s")

    speedup_ext4 = host_data['run_total_s'] / ext4_data['run_total_s']
    speedup_anylink = host_data['run_total_s'] / anylink_data['run_total_s']
    print(f"\nSpeedup Native ext4 vs Host Mount: {speedup_ext4:.1f}x FASTER")
    print(f"Speedup AnyLink Container vs Host Mount: {speedup_anylink:.1f}x FASTER")

    output_summary = {
        "workload": f"{NUM_OPS} file writes, reads, stat traversals, and deletions",
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "host_9p": host_data,
        "native_ext4": ext4_data,
        "anylink_container": anylink_data,
        "speedup_ext4": speedup_ext4,
        "speedup_anylink": speedup_anylink
    }

    with open("D:/code/sandbox-linker/EMPIRICAL_BENCHMARK_DATA.json", "w", encoding="utf-8") as f:
        json.dump(output_summary, f, indent=2)
    print("\nSaved JSON evidence to D:/code/sandbox-linker/EMPIRICAL_BENCHMARK_DATA.json")

if __name__ == "__main__":
    main()
