#!/usr/bin/env python3
"""
Comprehensive Live Empirical Benchmark:
1. Windows Native: NTFS (C:) vs Dev Drive ReFS (D:)
2. Cross-OS 9P: WSL accessing NTFS (/mnt/c) vs WSL accessing Dev Drive (/mnt/d)
3. WSL 2 ext4 VHDX Location:
   - ext4.vhdx located on NTFS (C:)
   - ext4.vhdx located on Dev Drive ReFS (D:)
4. fsync / Large file flush benchmark:
   - ext4.vhdx on NTFS (C:) vs ext4.vhdx on Dev Drive ReFS (D:)
"""

import os
import sys
import time
import json
import shutil
import tempfile
import subprocess
from pathlib import Path

NUM_FILES = 1000

def bench_python_io(base_dir, n=NUM_FILES):
    os.makedirs(base_dir, exist_ok=True)
    
    # 1. Writes
    t0 = time.perf_counter()
    for i in range(n):
        fp = os.path.join(base_dir, f"file_{i}.txt")
        with open(fp, "w") as f:
            f.write(f"export const COMPONENT_ID = {i};\n" * 4)
    t1 = time.perf_counter()

    # 2. Reads
    for i in range(n):
        fp = os.path.join(base_dir, f"file_{i}.txt")
        with open(fp, "r") as f:
            _ = f.read()
    t2 = time.perf_counter()

    # 3. Stat / Directory Walk
    count = 0
    total_bytes = 0
    for root, dirs, files in os.walk(base_dir):
        for file in files:
            st = os.stat(os.path.join(root, file))
            count += 1
            total_bytes += st.st_size
    t3 = time.perf_counter()

    # 4. Destroy
    t4 = time.perf_counter()
    shutil.rmtree(base_dir)
    t5 = time.perf_counter()

    return {
        "writes_s": round(t1 - t0, 4),
        "reads_s": round(t2 - t1, 4),
        "stat_s": round(t3 - t2, 4),
        "total_run_s": round(t3 - t0, 4),
        "destroy_s": round(t5 - t4, 4),
        "file_count": count
    }

def run_windows_native_tests():
    print("[1/4] Running Windows Native Benchmarks (NTFS C: vs Dev Drive D:)...")
    c_temp = os.path.join(tempfile.gettempdir(), "bench_win_c_ntfs")
    d_temp = r"D:\code\tmp_bench_win_d_refs"

    ntfs_res = bench_python_io(c_temp)
    refs_res = bench_python_io(d_temp)

    return {
        "win_native_ntfs_c": ntfs_res,
        "win_native_devdrive_d": refs_res
    }

def run_wsl_cross_mount_tests():
    print("[2/4] Running Cross-OS 9P Mount Benchmarks (/mnt/c vs /mnt/d)...")
    py_snippet = f"""
import os, time, shutil, json

def bench(base_dir, n={NUM_FILES}):
    os.makedirs(base_dir, exist_ok=True)
    t0 = time.perf_counter()
    for i in range(n):
        with open(os.path.join(base_dir, f'file_{{i}}.txt'), 'w') as f:
            f.write(f'export const COMPONENT_ID = {{i}};\\n' * 4)
    t1 = time.perf_counter()
    for i in range(n):
        with open(os.path.join(base_dir, f'file_{{i}}.txt'), 'r') as f:
            _ = f.read()
    t2 = time.perf_counter()
    count = 0
    for root, dirs, files in os.walk(base_dir):
        for file in files:
            st = os.stat(os.path.join(root, file))
            count += 1
    t3 = time.perf_counter()
    t4 = time.perf_counter()
    shutil.rmtree(base_dir)
    t5 = time.perf_counter()
    return {{
        'writes_s': round(t1 - t0, 4),
        'reads_s': round(t2 - t1, 4),
        'stat_s': round(t3 - t2, 4),
        'total_run_s': round(t3 - t0, 4),
        'destroy_s': round(t5 - t4, 4),
        'file_count': count
    }}

res_c = bench('/mnt/c/Users/fauzu/tmp_bench_cross_c')
res_d = bench('/mnt/d/code/tmp_bench_cross_d')
print('CROSS_JSON:' + json.dumps({{'wsl_mnt_c_ntfs': res_c, 'wsl_mnt_d_devdrive': res_d}}))
"""
    cmd = ["wsl", "-d", "Ubuntu-24.04", "--cd", "~", "-e", "python3", "-c", py_snippet]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    for line in r.stdout.splitlines():
        if line.startswith("CROSS_JSON:"):
            return json.loads(line.replace("CROSS_JSON:", ""))
    raise RuntimeError(f"WSL cross mount bench failed: {r.stderr or r.stdout}")

def run_wsl_distro_bench(distro_name):
    py_snippet = f"""
import os, time, shutil, json

def bench(base_dir, n={NUM_FILES}):
    os.makedirs(base_dir, exist_ok=True)
    t0 = time.perf_counter()
    for i in range(n):
        with open(os.path.join(base_dir, f'file_{{i}}.txt'), 'w') as f:
            f.write(f'export const COMPONENT_ID = {{i}};\\n' * 4)
    t1 = time.perf_counter()
    for i in range(n):
        with open(os.path.join(base_dir, f'file_{{i}}.txt'), 'r') as f:
            _ = f.read()
    t2 = time.perf_counter()
    count = 0
    for root, dirs, files in os.walk(base_dir):
        for file in files:
            st = os.stat(os.path.join(root, file))
            count += 1
    t3 = time.perf_counter()
    t4 = time.perf_counter()
    shutil.rmtree(base_dir)
    t5 = time.perf_counter()
    
    # Heavy fsync flush test (100 files with hard fsync)
    os.makedirs(base_dir + '_sync', exist_ok=True)
    t_sync0 = time.perf_counter()
    for i in range(100):
        fp = os.path.join(base_dir + '_sync', f'sync_{{i}}.bin')
        with open(fp, 'wb') as f:
            f.write(b'X' * 65536)
            f.flush()
            os.fsync(f.fileno())
    t_sync1 = time.perf_counter()
    shutil.rmtree(base_dir + '_sync')

    return {{
        'writes_s': round(t1 - t0, 4),
        'reads_s': round(t2 - t1, 4),
        'stat_s': round(t3 - t2, 4),
        'total_run_s': round(t3 - t0, 4),
        'destroy_s': round(t5 - t4, 4),
        'fsync_100_files_s': round(t_sync1 - t_sync0, 4),
        'file_count': count
    }}

res = bench('/root/test_bench_ext4')
print('DISTRO_JSON:' + json.dumps(res))
"""
    cmd = ["wsl", "-d", distro_name, "--cd", "/root", "-e", "python3", "-c", py_snippet]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    for line in r.stdout.splitlines():
        if line.startswith("DISTRO_JSON:"):
            return json.loads(line.replace("DISTRO_JSON:", ""))
    raise RuntimeError(f"WSL distro bench for {distro_name} failed: {r.stderr or r.stdout}")

def main():
    results = {}
    
    # 1. Windows Native
    win_res = run_windows_native_tests()
    results.update(win_res)

    # 2. Cross Mount
    cross_res = run_wsl_cross_mount_tests()
    results.update(cross_res)

    # 3. WSL VHDX on NTFS vs Dev Drive ReFS
    print("[3/4] Running WSL Native ext4 on NTFS VHDX (bench-ntfs)...")
    ntfs_vhdx_res = run_wsl_distro_bench("bench-ntfs")
    results["wsl_vhdx_on_ntfs"] = ntfs_vhdx_res

    print("[4/4] Running WSL Native ext4 on Dev Drive ReFS VHDX (bench-devdrive)...")
    refs_vhdx_res = run_wsl_distro_bench("bench-devdrive")
    results["wsl_vhdx_on_devdrive"] = refs_vhdx_res

    out_file = r"D:\code\sandbox-linker\DEVDRIVE_EMPIRICAL_BENCHMARK.json"
    with open(out_file, "w") as f:
        json.dump(results, f, indent=2)

    print("\nSUCCESS! Benchmark complete. Results written to:", out_file)
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    main()
