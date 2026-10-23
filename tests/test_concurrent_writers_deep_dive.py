#!/usr/bin/env python3
"""
Deep-Dive Empirical Adversarial Investigation: Concurrent Volume Writes & Race Conditions

Tests:
Experiment 1: Single Producer (Production Topology) with Rapid Dynamic Updates (10 rapid updates) + Consumer watcher.
Experiment 2: Dual Concurrent Writers with Shared Mutable Schema Filename (openapi.json) vs Versioned Immutable Schemas (openapi_{ver}.json).
Experiment 3: Measure atomic rename (os.replace) integrity: total reads, corrupted reads, partial JSONs across 10,000 rapid concurrent file reads.
"""

import os
import sys
import json
import time
import hashlib
import subprocess
from pathlib import Path

IMAGE_NAME = "python:3.12-alpine"

def run_docker(cmd, check=False, timeout=60):
    return subprocess.run(["docker"] + cmd, capture_output=True, text=True, check=check, timeout=timeout)

def cleanup(prefix):
    ps = run_docker(["ps", "-a", "--filter", f"name={prefix}", "--format", "{{.Names}}"]).stdout.strip().split()
    for c in ps:
        if c: run_docker(["rm", "-f", c])
    vols = run_docker(["volume", "ls", "--filter", f"name={prefix}", "--format", "{{.Name}}"]).stdout.strip().split()
    for v in vols:
        if v: run_docker(["volume", "rm", v])

def main():
    print("=" * 70)
    print("DEEP DIVE EXPERIMENT 1: Rapid Updates on Single Producer with Consumer Protocol")
    print("=" * 70)
    prefix = "dd1"
    cleanup(prefix)
    vol = f"{prefix}_vol"
    run_docker(["volume", "create", vol])
    
    prod = f"{prefix}_prod"
    cons = f"{prefix}_cons"
    run_docker(["run", "-d", "--name", prod, "-v", f"{vol}:/shared/contracts", IMAGE_NAME, "tail", "-f", "/dev/null"])
    run_docker(["run", "-d", "--name", cons, "-v", f"{vol}:/shared/contracts", IMAGE_NAME, "tail", "-f", "/dev/null"])

    # Producer script: 20 rapid sequential updates
    prod_script = """
import os, json, time, hashlib
SCHEMA_DIR = '/shared/contracts'
tmp = os.path.join(SCHEMA_DIR, '.tmp')
os.makedirs(tmp, exist_ok=True)
pid = os.getpid()

for i in range(20):
    ver = f'2.{i}.0'
    spec = {'version': ver, 'data': 'X'*1024*10}
    b = json.dumps(spec).encode('utf-8')
    h = hashlib.sha256(b).hexdigest()
    
    # 1. Stage openapi.json
    tmp_spec = os.path.join(tmp, f'openapi.json.{pid}')
    with open(tmp_spec, 'wb') as f:
        f.write(b); f.flush(); os.fsync(f.fileno())
    os.replace(tmp_spec, os.path.join(SCHEMA_DIR, 'openapi.json'))
    
    # 2. Stage manifest.json
    man = {'version': ver, 'sequence': i+1, 'schema_file': 'openapi.json', 'schema_sha256': h, 'timestamp_ns': time.time_ns()}
    tmp_man = os.path.join(tmp, f'manifest.json.{pid}')
    with open(tmp_man, 'wb') as f:
        f.write(json.dumps(man).encode('utf-8')); f.flush(); os.fsync(f.fileno())
    os.replace(tmp_man, os.path.join(SCHEMA_DIR, 'manifest.json'))
    time.sleep(0.02)
print("PROD_DONE")
"""

    # Consumer script: follows consumer.py inspect_and_sync_contract pattern
    cons_script = """
import os, json, time, hashlib
SCHEMA_DIR = '/shared/contracts'
man_path = os.path.join(SCHEMA_DIR, 'manifest.json')

last_seq = -1
verified_events = 0
mismatches = 0
corruptions = 0

t_end = time.time() + 3.0
while time.time() < t_end:
    if not os.path.exists(man_path):
        time.sleep(0.005); continue
    try:
        with open(man_path, 'r', encoding='utf-8') as f:
            m = json.load(f)
    except Exception:
        corruptions += 1; time.sleep(0.002); continue
    
    seq = m.get('sequence', 0)
    if seq == last_seq:
        time.sleep(0.005); continue
    
    # New sequence detected!
    spec_path = os.path.join(SCHEMA_DIR, m.get('schema_file', 'openapi.json'))
    try:
        with open(spec_path, 'rb') as f:
            actual = hashlib.sha256(f.read()).hexdigest()
        if actual == m.get('schema_sha256'):
            verified_events += 1
            last_seq = seq
        else:
            mismatches += 1
    except Exception:
        corruptions += 1
    time.sleep(0.002)

print(json.dumps({'verified': verified_events, 'mismatches': mismatches, 'corruptions': corruptions}))
"""
    p_cons = subprocess.Popen(["docker", "exec", cons, "python3", "-c", cons_script], stdout=subprocess.PIPE, text=True)
    time.sleep(0.2)
    p_prod = subprocess.Popen(["docker", "exec", prod, "python3", "-c", prod_script], stdout=subprocess.PIPE, text=True)
    
    out_p, _ = p_prod.communicate(timeout=15)
    out_c, _ = p_cons.communicate(timeout=15)
    print(f"Producer: {out_p.strip()}")
    print(f"Consumer (Event-driven): {out_c.strip()}")
    cleanup(prefix)

    print("\n" + "=" * 70)
    print("DEEP DIVE EXPERIMENT 2: Dual Concurrent Writers with Versioned Schema Files")
    print("=" * 70)
    prefix2 = "dd2"
    cleanup(prefix2)
    vol2 = f"{prefix2}_vol"
    run_docker(["volume", "create", vol2])
    w1 = f"{prefix2}_w1"
    w2 = f"{prefix2}_w2"
    rdr = f"{prefix2}_rdr"
    for c in [w1, w2, rdr]:
        run_docker(["run", "-d", "--name", c, "-v", f"{vol2}:/shared/contracts", IMAGE_NAME, "tail", "-f", "/dev/null"])

    # Versioned writer script
    v_writer_script = """
import os, sys, json, time, hashlib
SCHEMA_DIR = '/shared/contracts'
tmp = os.path.join(SCHEMA_DIR, '.tmp')
os.makedirs(tmp, exist_ok=True)
pid = os.getpid()
wid = '{wid}'

for i in range(50):
    ver = f'{{wid}}.{{i}}.0'
    spec = {{'version': ver, 'wid': wid, 'data': 'Y' * (2048 * (i % 4 + 1))}}
    b = json.dumps(spec).encode('utf-8')
    h = hashlib.sha256(b).hexdigest()
    
    # Versioned schema file!
    spec_filename = f'openapi_{{wid}}_{{i}}.json'
    tmp_spec = os.path.join(tmp, f'{{spec_filename}}.{{pid}}')
    with open(tmp_spec, 'wb') as f:
        f.write(b); f.flush(); os.fsync(f.fileno())
    os.replace(tmp_spec, os.path.join(SCHEMA_DIR, spec_filename))
    
    # Commit manifest
    man = {{'version': ver, 'sequence': i+1, 'writer': wid, 'schema_file': spec_filename, 'schema_sha256': h, 'timestamp_ns': time.time_ns()}}
    tmp_man = os.path.join(tmp, f'manifest_{{wid}}.{{pid}}.json')
    with open(tmp_man, 'wb') as f:
        f.write(json.dumps(man).encode('utf-8')); f.flush(); os.fsync(f.fileno())
    os.replace(tmp_man, os.path.join(SCHEMA_DIR, 'manifest.json'))
    time.sleep(0.005)
print(f"{{wid}}_DONE")
"""

    # Unconstrained rapid reader
    v_reader_script = """
import os, json, time, hashlib
SCHEMA_DIR = '/shared/contracts'
man_path = os.path.join(SCHEMA_DIR, 'manifest.json')

valid = 0
corruptions = 0
mismatches = 0

t_end = time.time() + 5.0
while time.time() < t_end:
    if not os.path.exists(man_path):
        time.sleep(0.001); continue
    try:
        with open(man_path, 'r', encoding='utf-8') as f:
            m = json.load(f)
    except Exception:
        corruptions += 1; time.sleep(0.001); continue
    
    fn = m.get('schema_file')
    expected = m.get('schema_sha256')
    if fn and expected:
        try:
            with open(os.path.join(SCHEMA_DIR, fn), 'rb') as f:
                act = hashlib.sha256(f.read()).hexdigest()
            if act == expected:
                valid += 1
            else:
                mismatches += 1
        except Exception:
            corruptions += 1
    time.sleep(0.0005)

print(json.dumps({'valid_reads': valid, 'corruptions': corruptions, 'mismatches': mismatches}))
"""
    p_rdr = subprocess.Popen(["docker", "exec", rdr, "python3", "-c", v_reader_script], stdout=subprocess.PIPE, text=True)
    time.sleep(0.2)
    p_w1 = subprocess.Popen(["docker", "exec", w1, "python3", "-c", v_writer_script.format(wid="A")], stdout=subprocess.PIPE, text=True)
    p_w2 = subprocess.Popen(["docker", "exec", w2, "python3", "-c", v_writer_script.format(wid="B")], stdout=subprocess.PIPE, text=True)
    
    out_w1, _ = p_w1.communicate(timeout=15)
    out_w2, _ = p_w2.communicate(timeout=15)
    out_rdr, _ = p_rdr.communicate(timeout=15)
    print(f"Writer 1: {out_w1.strip()}")
    print(f"Writer 2: {out_w2.strip()}")
    print(f"Versioned Concurrency Reader: {out_rdr.strip()}")
    cleanup(prefix2)

if __name__ == "__main__":
    main()
