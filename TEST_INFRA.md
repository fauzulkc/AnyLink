# Test Infrastructure & Coverage Matrix: Multi-Agent Sandbox Mesh

## 1. Overview & Test Architecture

The Multi-Agent Multi-Container Development Mesh End-to-End Test Suite (`tests/test_mesh_e2e.py`) is designed as a strict, opaque-box, requirement-driven test harness. It validates the multi-agent mesh orchestration engine (`scripts/mesh_orchestrator.py`), microservice contract prototype (`test_projects/multi_agent_mesh/`), and automated benchmark harness (`scripts/mesh_benchmark.py`) exclusively through their documented public interfaces, CLI subcommands, exit codes, JSON outputs, and observable Docker engine states.

### 1.1 Core Testing Principles
1. **Opaque-Box Boundary**: The test suite does not reach into internal Python function implementations. It invokes public CLI commands (`python scripts/mesh_orchestrator.py <cmd>`, `python scripts/mesh_benchmark.py`, `docker inspect`, `docker network inspect`, `docker volume inspect`), testing observable behavior, stdout/stderr streams, exit codes, and filesystem artifacts.
2. **Deterministic Isolation**: Every test case runs within an ephemeral, isolated sandbox context. Test configurations, network names, container aliases, and volume names utilize unique cryptographic or random prefixes (`e2e_test_<uuid>`).
3. **Zero Host & Registry Pollution**: Tests maintain strict isolation from host filesystems and existing developer WSL mappings (`~/.wsl-linker-experimental/config.json`). All mesh states are stored in isolated `.mesh_state.json` files within temporary test directories.
4. **Leak-Proof Resource Teardown**: Pytest/Unittest fixtures enforce fail-safe cleanup with `try...finally` teardown semantics. Even in the event of unexpected test assertion aborts, SIGINT, or container crashes, all ephemeral Docker containers, networks, and named volumes are guaranteed to be destroyed.
5. **Multi-Tiered Verification**: Tests are partitioned across 4 distinct rigor tiers ranging from atomic CLI feature coverage to real-world autonomous multi-agent workloads under stress.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       E2E TEST HARNESS ARCHITECTURE                         │
│                          (tests/test_mesh_e2e.py)                           │
└─────────────────────────────────────┬───────────────────────────────────────┘
                                      │
            ┌─────────────────────────┴─────────────────────────┐
            │                                                   │
  ┌─────────▼────────────────────────┐        ┌─────────────────▼───────────────┐
  │      CLI & API INTERFACES        │        │      DOCKER ENGINE ORACLE       │
  │ • scripts/mesh_orchestrator.py   │        │ • docker inspect (HostConfig)   │
  │   - up, down, exec, status, heal │        │ • docker network inspect        │
  │ • scripts/mesh_benchmark.py      │        │ • docker volume inspect         │
  │   - benchmark execution & report │        │ • docker ps -a                  │
  └─────────────────┬────────────────┘        └─────────────────┬───────────────┘
                    │                                           │
  ┌─────────────────▼───────────────────────────────────────────▼───────────────┐
  │                               TEST TIERS                                    │
  │ • Tier 1: Feature Coverage (>=5 tests per 8 feature domains)                │
  │ • Tier 2: Boundary & Corner Cases (invalid configs, rapid churn, errors)    │
  │ • Tier 3: Cross-Feature Interactions (concurrency, load, cgroups quotas)    │
  │ • Tier 4: Real-World Workload Scenarios (end-to-end autonomous flow)        │
  └─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Test Fixture & Lifecycle Isolation Framework

### 2.1 Ephemeral Mesh Configuration Generator
The harness provides a dynamic `create_test_mesh_config(...)` builder generating isolated `mesh.json` specifications on the fly:
- Custom bridge network: `e2e_net_<id>`
- Custom ext4 volume: `e2e_vol_<id>`
- Dynamic service definitions with custom resource quotas (CPU, Memory, PIDs).
- Isolated state file: `<temp_dir>/.mesh_state.json`.

### 2.2 Execution Engine (`run_mesh_cli`)
Executes orchestrator and benchmark commands via `subprocess.run` with:
- Subcommand string/list parsing
- Environment variable isolation
- Automatic `--json` parsing when requested
- Programmatic capture of `stdout`, `stderr`, `exit_code`, and `duration_ms`.

### 2.3 Docker State Oracle
An independent oracle using the Docker CLI to verify:
- Container presence, running status, and health check state.
- `HostConfig.NanoCpus`, `HostConfig.Memory`, `HostConfig.PidsLimit`.
- Network attachment and IP allocation on bridge network.
- Named volume mount path (`/shared/contracts`) and read/write mode.
- Verification of zero lingering resources after `down`.

---

## 3. Feature Coverage Matrix (Tiers 1–4)

| Test ID | Tier | Feature Area / Scenario | Verification Target | Expected Outcome |
| :--- | :--- | :--- | :--- | :--- |
| **TC-T1-LC-01** | Tier 1 | Mesh Lifecycle: `up` standard mode | Spawns configured containers on bridge network | Status code 0, containers active |
| **TC-T1-LC-02** | Tier 1 | Mesh Lifecycle: `up --json` | Programmatic JSON output structure | Valid JSON with status: success, container IDs |
| **TC-T1-LC-03** | Tier 1 | Mesh Lifecycle: `status` & `status --json` | Inspects all services in mesh | Returns running=True, health=healthy/ok |
| **TC-T1-LC-04** | Tier 1 | Mesh Lifecycle: `exec` basic command | `exec producer -- echo 'mesh_active'` | Stdout contains 'mesh_active', exit_code 0 |
| **TC-T1-LC-05** | Tier 1 | Mesh Lifecycle: `down` clean teardown | Reverse dependency destruction | Containers, networks, volumes removed; status 0 |
| **TC-T1-NET-01** | Tier 1 | Bridge Network: Creation & Subnet | Custom bridge network creation | Network driver=bridge, inspect shows active |
| **TC-T1-NET-02** | Tier 1 | Bridge Network: IP Allocation | IP assignment to services | Unique IPv4 assigned within mesh subnet |
| **TC-T1-NET-03** | Tier 1 | Bridge Network: Internal DNS ping | Consumer pings Producer by hostname | 0% packet loss, RTT < 5ms |
| **TC-T1-NET-04** | Tier 1 | Bridge Network: DNS port resolution | Producer port 8000 accessible via DNS | Socket connection to `mesh-producer:8000` succeeds |
| **TC-T1-NET-05** | Tier 1 | Bridge Network: Multi-container isolation | Unconnected containers cannot resolve DNS | Unknown host error when resolving outside network |
| **TC-T1-VOL-01** | Tier 1 | Shared Volume: Provisioning | Named Docker volume creation | Volume exists in `docker volume ls` |
| **TC-T1-VOL-02** | Tier 1 | Shared Volume: Mount Path | Mounted at `/shared/contracts` | Directory exists and is ext4 filesystem |
| **TC-T1-VOL-03** | Tier 1 | Shared Volume: Multi-container RW | Concurrent write from C1, read from C2 | Data written by C1 immediately visible to C2 |
| **TC-T1-VOL-04** | Tier 1 | Shared Volume: Atomic Staging | Staging in `.tmp/` + `os.replace` | Atomic commit without partial reads |
| **TC-T1-VOL-05** | Tier 1 | Shared Volume: Persistence across reload | Container restart retains volume data | Data in `/shared/contracts` survives restarts |
| **TC-T1-PRD-01** | Tier 1 | Producer Service: Startup & Health | `GET /health` endpoint | HTTP 200, status=ok, version present |
| **TC-T1-PRD-02** | Tier 1 | Producer Service: Items API v1 | `GET /api/v1/items` | HTTP 200, returns item collection |
| **TC-T1-PRD-03** | Tier 1 | Producer Service: OpenAPI Generation | Export of `openapi.json` | Valid OpenAPI 3.0.3 specification exported |
| **TC-T1-PRD-04** | Tier 1 | Producer Service: Client SDK Export | Export of `client_sdk.py` | Python SDK generated on shared volume |
| **TC-T1-PRD-05** | Tier 1 | Producer Service: Contract Manifest | Generation of `manifest.json` | Manifest contains SHA-256 and timestamp |
| **TC-T1-CNS-01** | Tier 1 | Consumer Service: Startup & Watcher | Inotify/polling watcher initialization | Consumer logs watcher active on `/shared/contracts` |
| **TC-T1-CNS-02** | Tier 1 | Consumer Service: Contract Ingestion | Ingest `manifest.json` on boot | Consumer parses endpoints and initial contract |
| **TC-T1-CNS-03** | Tier 1 | Consumer Service: SHA-256 Validation | Verifies checksum of `openapi.json` | Rejects mismatched/tampered schemas |
| **TC-T1-CNS-04** | Tier 1 | Consumer Service: Latency Telemetry | Appends to `metrics/handoff_events.json` | Event log recorded with latency_ms |
| **TC-T1-CNS-05** | Tier 1 | Consumer Service: Clean Termination | Graceful SIGTERM shutdown | Exits with code 0 without dangling watcher threads |
| **TC-T1-HTTP-01**| Tier 1 | Inter-Service HTTP: Health Query | Consumer queries `http://mesh-producer:8000/health` | HTTP 200, payload validated |
| **TC-T1-HTTP-02**| Tier 1 | Inter-Service HTTP: Data Retrieval | Consumer queries `GET /api/v1/items` | JSON payload parsed successfully |
| **TC-T1-HTTP-03**| Tier 1 | Inter-Service HTTP: Data Insertion | Consumer posts `POST /api/v1/items` | HTTP 201/200, item persisted |
| **TC-T1-HTTP-04**| Tier 1 | Inter-Service HTTP: Zero Host Exposure | No host port mapping required | Producer accessible ONLY on bridge network |
| **TC-T1-HTTP-05**| Tier 1 | Inter-Service HTTP: Low Latency | Round-trip request/response latency | RTT < 10ms over internal Docker bridge |
| **TC-T1-DYN-01** | Tier 1 | Dynamic Update: Trigger Endpoint | `POST /admin/contract/update` | HTTP 200, version bumped to 2.0.0 |
| **TC-T1-DYN-02** | Tier 1 | Dynamic Update: Atomic Manifest Commit | Producer replaces `manifest.json` atomically | Nanosecond timestamp updated |
| **TC-T1-DYN-03** | Tier 1 | Dynamic Update: Consumer Detection | Consumer detects update in < 500ms | Measured detection latency < 50ms |
| **TC-T1-DYN-04** | Tier 1 | Dynamic Update: Route Table Reload | Consumer dispatches to `/api/v2/items` | Zero container restart, immediate query |
| **TC-T1-DYN-05** | Tier 1 | Dynamic Update: SHA-256 Verification | Consumer verifies new contract hash | Matches manifest `schema_sha256` |
| **TC-T1-BNCH-01**| Tier 1 | Benchmark Runner: Execution | Run `python scripts/mesh_benchmark.py` | Runs autonomously, exit code 0 |
| **TC-T1-BNCH-02**| Tier 1 | Benchmark Runner: Report File | Generates `BENCHMARK_REPORT.json` | Valid file created at target path |
| **TC-T1-BNCH-03**| Tier 1 | Benchmark Runner: Schema Validation | Report conforms to JSON schema | All required keys present and valid |
| **TC-T1-BNCH-04**| Tier 1 | Benchmark Runner: SLA Evaluation | Evaluates spinup (<3s), IO (<50ms), handoff (<500ms)| All criteria marked `passed: true` |
| **TC-T1-BNCH-05**| Tier 1 | Benchmark Runner: Throughput Analysis | Compares ext4 vs host bind mount | Shows ext4 speedup factor > 10x |
| **TC-T2-BND-01** | Tier 2 | Boundary: Missing Config Fields | `mesh.json` missing `services` or `network` | Non-zero exit code, informative error |
| **TC-T2-BND-02** | Tier 2 | Boundary: Invalid Resource Quotas | Negative CPU, invalid memory (`-10g`, `abc`) | Non-zero exit code, validation error |
| **TC-T2-BND-03** | Tier 2 | Boundary: Nonexistent Service Exec | `exec nonexistent_svc -- ls` | Non-zero exit code, error message |
| **TC-T2-BND-04** | Tier 2 | Boundary: Nonexistent Command Exec | `exec producer -- non_existent_binary_xyz` | Non-zero exit code (126/127) |
| **TC-T2-BND-05** | Tier 2 | Boundary: Rapid Sequential Cycles | 3 rapid `up` and `down` cycles in succession | 0 errors, no port/network collisions |
| **TC-T2-BND-06** | Tier 2 | Boundary: Special Characters & Quotes | `exec producer -- sh -c 'echo "hello $PATH *"'` | Preserves escaping, zero shell injection |
| **TC-T2-BND-07** | Tier 2 | Boundary: Teardown on Stopped Box | `down` when containers already stopped | Gracefully handles stopped state, exits 0 |
| **TC-T3-XFT-01** | Tier 3 | Cross-Feature: Exec during Schema Update | Execute commands while Producer writes contract | No race conditions, commands succeed |
| **TC-T3-XFT-02** | Tier 3 | Cross-Feature: Querying during Version Bump | Consumer queries continuously during update | Zero dropped requests, seamless transition |
| **TC-T3-XFT-03** | Tier 3 | Cross-Feature: Exec under Memory Ceiling | Run memory allocation near quota | Cgroup enforces limit without host crash |
| **TC-T3-XFT-04** | Tier 3 | Cross-Feature: CPU Throttling Isolation | Heavy CPU burn in service 1, query service 2 | Service 2 answers within latency tolerance |
| **TC-T4-E2E-01** | Tier 4 | Real-World Workload: End-to-End Workflow | Full autonomous multi-agent lifecycle | 100% pass, SLA met, zero dangling resources |

---

## 4. Test Execution & Reporting

### 4.1 Invocation Commands
```bash
# Execute complete E2E test suite
python -m unittest tests/test_mesh_e2e.py -v

# Run with pytest (if installed)
pytest tests/test_mesh_e2e.py -v --durations=10
```

### 4.2 Teardown Verification Invariant
Following every test session, the harness validates the Docker Engine state:
- `docker ps -a --filter "name=e2e_"` returns 0 lines.
- `docker network ls --filter "name=e2e_"` returns 0 lines.
- `docker volume ls --filter "name=e2e_"` returns 0 lines.
- Host configuration `~/.wsl-linker-experimental/config.json` retains identical SHA-256 checksum before and after test execution.
