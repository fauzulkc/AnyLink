#!/usr/bin/env python3
"""
Comprehensive Test Suite for Bi-Directional Manifest Transpiler:
Docker Compose & Kubernetes <===> AnyLink Mesh
"""

import os
import sys
import json
import yaml
import shutil
import tempfile
import unittest
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from scripts.manifest_transpiler import ManifestTranspiler, parse_k8s_cpu, parse_k8s_memory


class TestManifestTranspiler(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.work_dir = Path(self.temp_dir.name)
        self.transpiler = ManifestTranspiler(optimize_volumes=True)

    def tearDown(self):
        self.temp_dir.cleanup()

    # -------------------------------------------------------------------------
    # Unit Tests: Unit Normalization
    # -------------------------------------------------------------------------
    def test_k8s_cpu_parsing(self):
        self.assertEqual(parse_k8s_cpu("500m"), 0.5)
        self.assertEqual(parse_k8s_cpu("250m"), 0.25)
        self.assertEqual(parse_k8s_cpu("1.5"), 1.5)
        self.assertEqual(parse_k8s_cpu(2), 2.0)

    def test_k8s_memory_parsing(self):
        self.assertEqual(parse_k8s_memory("256Mi"), "256m")
        self.assertEqual(parse_k8s_memory("1Gi"), "1024m")
        self.assertEqual(parse_k8s_memory("512M"), "512m")
        self.assertEqual(parse_k8s_memory("512m"), "512m")

    # -------------------------------------------------------------------------
    # Ingestion Tests: Compose -> Mesh
    # -------------------------------------------------------------------------
    def test_compose_to_mesh_transpilation(self):
        compose_data = {
            "name": "ecommerce_stack",
            "services": {
                "api": {
                    "container_name": "ecommerce-api",
                    "image": "python:3.12-alpine",
                    "command": "python server.py",
                    "ports": ["8000:8000"],
                    "environment": {
                        "ENV": "dev",
                        "PORT": "8000"
                    },
                    "volumes": [
                        "./api_src:/workspace/src",
                        "shared_contracts:/shared/contracts:rw"
                    ],
                    "deploy": {
                        "resources": {
                            "limits": {
                                "cpus": "1.5",
                                "memory": "512M",
                                "pids": 64
                            }
                        }
                    }
                },
                "cache": {
                    "image": "redis:alpine",
                    "ports": ["6379:6379"],
                    "volumes": [
                        "redis_data:/data"
                    ]
                }
            },
            "volumes": {
                "shared_contracts": {},
                "redis_data": {}
            }
        }

        mesh = self.transpiler.compose_to_mesh(compose_data, project_name="ecommerce")
        self.assertEqual(mesh["name"], "ecommerce_stack")
        self.assertIn("api", mesh["services"])
        self.assertIn("cache", mesh["services"])

        api_svc = mesh["services"]["api"]
        self.assertEqual(api_svc["cpus"], 1.5)
        self.assertEqual(api_svc["memory"], "512m")
        self.assertEqual(api_svc["pids_limit"], 64)
        self.assertEqual(api_svc["environment"]["ENV"], "dev")
        self.assertIn("8000:8000", api_svc["ports"])

        # Check volume optimization: ./api_src converted to native ext4 named volume!
        vol_names = [v.split(":")[0] for v in api_svc["volumes"]]
        self.assertIn("api_data_vol", vol_names)
        self.assertIn("shared_contracts", vol_names)

        # Check shared_volumes registry
        shared_vol_names = [v["name"] for v in mesh["shared_volumes"]]
        self.assertIn("api_data_vol", shared_vol_names)
        self.assertIn("shared_contracts", shared_vol_names)
        self.assertIn("redis_data", shared_vol_names)

    # -------------------------------------------------------------------------
    # Ingestion Tests: Kubernetes -> Mesh
    # -------------------------------------------------------------------------
    def test_kubernetes_to_mesh_transpilation(self):
        k8s_yaml = """
apiVersion: apps/v1
kind: Deployment
metadata:
  name: payment-service
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: payment
          image: python:3.12-alpine
          env:
            - name: STRIPE_KEY
              value: test_key_123
          resources:
            limits:
              cpu: "750m"
              memory: "384Mi"
          volumeMounts:
            - name: ledger-vol
              mountPath: /data/ledger
---
apiVersion: v1
kind: Service
metadata:
  name: payment-service
spec:
  ports:
    - port: 9000
      targetPort: 9000
"""
        docs = list(yaml.safe_load_all(k8s_yaml))
        mesh = self.transpiler.kubernetes_to_mesh(docs, project_name="payments")

        self.assertIn("payment", mesh["services"])
        p_svc = mesh["services"]["payment"]
        self.assertEqual(p_svc["cpus"], 0.75)
        self.assertEqual(p_svc["memory"], "384m")
        self.assertEqual(p_svc["environment"]["STRIPE_KEY"], "test_key_123")
        self.assertIn("9000:9000", p_svc["ports"])
        self.assertIn("ledger-vol:/data/ledger:rw", p_svc["volumes"])

    # -------------------------------------------------------------------------
    # Round-Trip Fidelity: Compose -> Mesh -> Compose
    # -------------------------------------------------------------------------
    def test_compose_round_trip_fidelity(self):
        original_compose = {
            "name": "micro_roundtrip",
            "services": {
                "web": {
                    "container_name": "mesh-web",
                    "image": "python:3.12-alpine",
                    "command": ["python", "app.py"],
                    "ports": ["5000:5000"],
                    "environment": {
                        "DEBUG": "true"
                    },
                    "volumes": [
                        "web_data:/workspace:rw"
                    ],
                    "deploy": {
                        "resources": {
                            "limits": {
                                "cpus": "1.0",
                                "memory": "256m",
                                "pids": 64
                            }
                        }
                    }
                }
            },
            "volumes": {
                "web_data": {}
            }
        }

        # Step 1: Compose -> Mesh
        mesh = self.transpiler.compose_to_mesh(original_compose, project_name="micro_roundtrip")
        # Step 2: Mesh -> Compose
        exported_compose = self.transpiler.mesh_to_compose(mesh)

        self.assertEqual(exported_compose["name"], "micro_roundtrip")
        self.assertIn("web", exported_compose["services"])
        web_exp = exported_compose["services"]["web"]
        self.assertEqual(web_exp["image"], "python:3.12-alpine")
        self.assertEqual(web_exp["environment"]["DEBUG"], "true")
        self.assertEqual(web_exp["ports"], ["5000:5000"])
        self.assertEqual(web_exp["deploy"]["resources"]["limits"]["cpus"], "1.0")
        self.assertEqual(web_exp["deploy"]["resources"]["limits"]["memory"], "256m")

    # -------------------------------------------------------------------------
    # Round-Trip Fidelity: K8s -> Mesh -> K8s
    # -------------------------------------------------------------------------
    def test_kubernetes_round_trip_export(self):
        mesh_data = {
            "name": "k8s_export_mesh",
            "services": {
                "auth": {
                    "image": "python:3.12-alpine",
                    "command": ["tail", "-f", "/dev/null"],
                    "ports": ["8080:8080"],
                    "cpus": 0.5,
                    "memory": "256m",
                    "volumes": ["tokens_vol:/tokens:rw"],
                    "environment": {"JWT_SECRET": "xyz"}
                }
            }
        }

        k8s_docs = self.transpiler.mesh_to_kubernetes(mesh_data)
        self.assertEqual(len(k8s_docs), 2)  # 1 Deployment + 1 Service

        kinds = {d["kind"]: d for d in k8s_docs}
        self.assertIn("Deployment", kinds)
        self.assertIn("Service", kinds)

        dep = kinds["Deployment"]
        self.assertEqual(dep["metadata"]["name"], "auth")
        c = dep["spec"]["template"]["spec"]["containers"][0]
        self.assertEqual(c["image"], "python:3.12-alpine")
        self.assertEqual(c["resources"]["limits"]["cpu"], "0.5")
        self.assertEqual(c["resources"]["limits"]["memory"], "256Mi")

        svc = kinds["Service"]
        self.assertEqual(svc["metadata"]["name"], "auth")
        self.assertEqual(svc["spec"]["ports"][0]["port"], 8080)

    # -------------------------------------------------------------------------
    # Live Integration Test: Transpile Compose -> Launch with mesh_orchestrator
    # -------------------------------------------------------------------------
    def test_live_transpile_and_orchestrate(self):
        """Transpiles a real Compose file and boots the mesh via mesh_orchestrator."""
        compose_path = self.work_dir / "docker-compose.yml"
        mesh_path = self.work_dir / "mesh.json"

        compose_content = """services:
  live_producer:
    image: python:3.12-alpine
    command: tail -f /dev/null
    volumes:
      - "./source:/workspace"
      - "live_shared_vol:/shared:rw"
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M
  live_consumer:
    image: python:3.12-alpine
    command: tail -f /dev/null
    volumes:
      - "live_shared_vol:/shared:rw"
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M
volumes:
  live_shared_vol: {}
"""
        compose_path.write_text(compose_content, encoding="utf-8")

        # 1. Transpile via CLI
        r_tr = subprocess.run(
            [sys.executable, str(BASE_DIR / "scripts" / "manifest_transpiler.py"), "compose-to-mesh", "-i", str(compose_path), "-o", str(mesh_path)],
            capture_output=True,
            text=True
        )
        self.assertEqual(r_tr.returncode, 0, f"Transpile failed: {r_tr.stderr}")
        self.assertTrue(mesh_path.exists())

        # Verify generated mesh.json
        with open(mesh_path, "r", encoding="utf-8") as f:
            mesh_json = json.load(f)
        self.assertIn("live_producer", mesh_json["services"])
        self.assertIn("live_consumer", mesh_json["services"])

        # 2. Boot via mesh_orchestrator
        orchestrator_bin = BASE_DIR / "scripts" / "mesh_orchestrator.py"
        r_up = subprocess.run(
            [sys.executable, str(orchestrator_bin), "up", "--file", str(mesh_path), "--json"],
            capture_output=True,
            text=True
        )
        self.assertEqual(r_up.returncode, 0, f"Mesh up failed: {r_up.stderr or r_up.stdout}")

        # 3. Test Exec in producer: write file into shared volume
        r_exec1 = subprocess.run(
            [sys.executable, str(orchestrator_bin), "exec", "live_producer", "--file", str(mesh_path), "--json", "--",
             "sh", "-c", "echo 'transpiled_mesh_ok' > /shared/proof.txt"],
            capture_output=True,
            text=True
        )
        self.assertEqual(r_exec1.returncode, 0)

        # 4. Test Exec in consumer: read file from shared volume
        r_exec2 = subprocess.run(
            [sys.executable, str(orchestrator_bin), "exec", "live_consumer", "--file", str(mesh_path), "--json", "--",
             "cat", "/shared/proof.txt"],
            capture_output=True,
            text=True
        )
        self.assertEqual(r_exec2.returncode, 0)
        out_data = json.loads(r_exec2.stdout)
        self.assertEqual(out_data.get("stdout", "").strip(), "transpiled_mesh_ok")

        # 5. Clean teardown
        r_down = subprocess.run(
            [sys.executable, str(orchestrator_bin), "down", "--file", str(mesh_path), "--json"],
            capture_output=True,
            text=True
        )
        self.assertEqual(r_down.returncode, 0, f"Mesh down failed: {r_down.stderr}")


if __name__ == "__main__":
    unittest.main()
