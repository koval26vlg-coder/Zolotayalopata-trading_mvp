import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "reconcile_trading_mvp_public_probe_readiness_gate.ps1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PublicProbeGateReconciliationTests(unittest.TestCase):
    def make_fixture(self, root: Path) -> dict[str, Path]:
        run_id = "paper_public_readonly_probe_v3_test"
        evidence = root / "probe-evidence.json"
        evidence.write_text('{"verdict":"accepted"}\n', encoding="utf-8")

        audit = root / "audit-v9.json"
        audit.write_text(
            json.dumps(
                {
                    "schema": "trading_mvp_paper_product_readiness_audit_v9",
                    "public_data_plane": {
                        "readonly_probe_run_id": run_id,
                        "readonly_probe_evidence": "V3_ACCEPTED",
                    },
                    "verdict": (
                        "PUBLIC_PROBE_EVIDENCE_BINDING_COMPLETE_NO_MATERIAL_"
                        "OFFLINE_GAPS_EDGE_AND_FORWARD_GATES_REMAIN_BLOCKED"
                    ),
                    "next_allowed_action": "WAITING_SCHEDULE_WINDOW_NO_FALLBACK",
                    "maximum_authority": "PUBLIC_READONLY_RESEARCH_EVIDENCE_ONLY",
                    "evidence_gates": {
                        "edge_proven": False,
                        "replay_allowed": False,
                    },
                    "safety": {
                        "returns_or_pnl_read": False,
                        "oos_read": False,
                        "signals_read": False,
                        "hypothesis_changed": False,
                        "network_collection": False,
                        "grid_or_retune": False,
                        "paper_forward_started": False,
                        "live_orders": False,
                        "private_api_keys": False,
                        "leverage": False,
                        "margin": False,
                    },
                    "deterministic_result_hash": "audit-result-hash",
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        gate = root / "active-run-gate.json"
        gate.write_text(
            json.dumps(
                {
                    "schema": "active_run_gate_v2",
                    "project": "trading_mvp",
                    "run_id": run_id,
                    "status": "READY_FOR_POSTPROCESS",
                    "gate_status": "READY_FOR_POSTPROCESS",
                    "final": True,
                    "collector_pid": None,
                    "monitor_pid": None,
                    "process_ids": [],
                    "evidence_path": str(evidence),
                    "evidence_file_sha256": sha256(evidence),
                    "next_goal_decision": "RUN_PAPER_PRODUCT_READINESS_AUDIT_V8",
                    "replay_allowed": False,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        pointer = root / "current-run.json"
        pointer.write_text(
            json.dumps(
                {
                    "schema": "active_run_pointer_v1",
                    "project": "trading_mvp",
                    "run_id": run_id,
                    "status": "READY_FOR_POSTPROCESS",
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        backlog = root / "backlog.json"
        backlog.write_text(
            json.dumps(
                {
                    "tasks": [
                        {
                            "id": "paper_product_readiness_audit_v9",
                            "status": "COMPLETED",
                            "artifact_path": str(audit),
                            "artifact_sha256": sha256(audit),
                        }
                    ]
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return {
            "run_id": run_id,
            "evidence": evidence,
            "audit": audit,
            "gate": gate,
            "pointer": pointer,
            "backlog": backlog,
            "receipt": root / "receipt.json",
            "archive": root / "archive",
        }

    def run_script(self, fixture: dict[str, Path], *extra: str) -> subprocess.CompletedProcess:
        command = [
            "pwsh",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-GatePath",
            str(fixture["gate"]),
            "-CurrentRunPath",
            str(fixture["pointer"]),
            "-BacklogPath",
            str(fixture["backlog"]),
            "-AuditPath",
            str(fixture["audit"]),
            "-ReceiptPath",
            str(fixture["receipt"]),
            "-ArchiveDir",
            str(fixture["archive"]),
            "-ExpectedRunId",
            str(fixture["run_id"]),
            "-Json",
            *extra,
        ]
        return subprocess.run(command, capture_output=True, text=True, check=False)

    def test_reconciles_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(Path(temp_dir))

            first = self.run_script(fixture)
            self.assertEqual(first.returncode, 0, first.stderr)
            first_result = json.loads(first.stdout)
            self.assertEqual(
                first_result["decision"],
                "PUBLIC_PROBE_READINESS_GATE_RECONCILED",
            )
            self.assertTrue(first_result["gate_updated"])
            self.assertTrue(fixture["receipt"].is_file())

            gate = json.loads(fixture["gate"].read_text(encoding="utf-8-sig"))
            self.assertEqual(
                gate["next_goal_decision"],
                "PUBLIC_READONLY_PROBE_READINESS_CHAIN_COMPLETE",
            )
            self.assertFalse(gate["replay_allowed"])
            self.assertEqual(
                gate["downstream_readiness_reconciliation"]["status"],
                "COMPLETE",
            )
            archive_count = len(list(fixture["archive"].glob("*.json")))
            self.assertEqual(archive_count, 2)

            second = self.run_script(fixture)
            self.assertEqual(second.returncode, 0, second.stderr)
            second_result = json.loads(second.stdout)
            self.assertEqual(
                second_result["decision"],
                "PUBLIC_PROBE_READINESS_GATE_RECONCILIATION_REUSED",
            )
            self.assertFalse(second_result["gate_updated"])
            self.assertEqual(
                len(list(fixture["archive"].glob("*.json"))),
                archive_count,
            )

    def test_hash_mismatch_fails_without_mutating_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.make_fixture(Path(temp_dir))
            original_gate = fixture["gate"].read_bytes()
            backlog = json.loads(fixture["backlog"].read_text(encoding="utf-8"))
            backlog["tasks"][0]["artifact_sha256"] = "0" * 64
            fixture["backlog"].write_text(
                json.dumps(backlog, indent=2),
                encoding="utf-8",
            )

            result = self.run_script(fixture)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SHA256", result.stderr)
            self.assertEqual(fixture["gate"].read_bytes(), original_gate)
            self.assertFalse(fixture["receipt"].exists())


if __name__ == "__main__":
    unittest.main()
