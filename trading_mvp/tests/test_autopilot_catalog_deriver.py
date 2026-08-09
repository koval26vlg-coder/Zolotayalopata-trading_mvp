from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import autopilot_catalog_deriver as deriver  # noqa: E402


def _audit(path: Path) -> Path:
    requirements = [
        {
            "id": task_id,
            "priority": index,
            "reason": "fixture",
            "maximum_runtime_sec": 1200,
            "network": False,
        }
        for index, task_id in enumerate(deriver.TASK_TEMPLATES, start=1)
    ]
    path.write_text(
        json.dumps(
            {
                "schema": deriver.AUDIT_SCHEMA,
                "next_allowed_action": (
                    "derive_and_install_catalog_v3_then_continue_bounded_offline_work"
                ),
                "next_bounded_catalog_requirement": requirements,
                "deterministic_result_hash": "a" * 64,
            }
        ),
        encoding="utf-8",
    )
    return path


def _audit_v4(path: Path) -> Path:
    requirements = [
        {
            "id": task_id,
            "priority": index,
            "reason": "fixture",
            "maximum_runtime_sec": 1200,
            "network": False,
        }
        for index, task_id in enumerate(
            deriver.TASK_TEMPLATES_V4, start=1
        )
    ]
    path.write_text(
        json.dumps(
            {
                "schema": deriver.AUDIT_SCHEMA_V4,
                "next_allowed_action": (
                    "derive_and_install_catalog_v4_then_continue_bounded_offline_work"
                ),
                "next_bounded_catalog_requirement": requirements,
                "deterministic_result_hash": "b" * 64,
            }
        ),
        encoding="utf-8",
    )
    return path


def _audit_v5(path: Path) -> Path:
    requirements = [
        {
            "id": task_id,
            "priority": index,
            "reason": "fixture",
            "maximum_runtime_sec": 1200,
            "network": False,
        }
        for index, task_id in enumerate(
            deriver.TASK_TEMPLATES_V5, start=1
        )
    ]
    path.write_text(
        json.dumps(
            {
                "schema": deriver.AUDIT_SCHEMA_V5,
                "next_allowed_action": (
                    "derive_and_install_catalog_v5_then_continue_bounded_offline_work"
                ),
                "next_bounded_catalog_requirement": requirements,
                "deterministic_result_hash": "c" * 64,
            }
        ),
        encoding="utf-8",
    )
    return path


def _audit_v6(path: Path) -> Path:
    requirements = [
        {
            "id": task_id,
            "priority": index,
            "reason": "fixture",
            "maximum_runtime_sec": 1200,
            "network": False,
        }
        for index, task_id in enumerate(
            deriver.TASK_TEMPLATES_V6, start=1
        )
    ]
    path.write_text(
        json.dumps(
            {
                "schema": deriver.AUDIT_SCHEMA_V6,
                "next_allowed_action": (
                    "derive_and_install_catalog_v6_then_continue_bounded_offline_work"
                ),
                "next_bounded_catalog_requirement": requirements,
                "deterministic_result_hash": "d" * 64,
            }
        ),
        encoding="utf-8",
    )
    return path


def _audit_v8(path: Path) -> Path:
    requirements = [
        {
            "id": task_id,
            "priority": index,
            "reason": "fixture",
            "maximum_runtime_sec": 1200,
            "network": False,
        }
        for index, task_id in enumerate(
            deriver.TASK_TEMPLATES_V8, start=1
        )
    ]
    path.write_text(
        json.dumps(
            {
                "schema": deriver.AUDIT_SCHEMA_V8,
                "next_allowed_action": (
                    "derive_and_install_catalog_v8_then_continue_bounded_offline_work"
                ),
                "next_bounded_catalog_requirement": requirements,
                "deterministic_result_hash": "e" * 64,
            }
        ),
        encoding="utf-8",
    )
    return path


def _audit_v10(path: Path) -> Path:
    requirements = [
        {
            "id": task_id,
            "priority": index,
            "reason": "fixture",
            "maximum_runtime_sec": 1200,
            "network": False,
        }
        for index, task_id in enumerate(
            deriver.TASK_TEMPLATES_V10, start=1
        )
    ]
    path.write_text(
        json.dumps(
            {
                "schema": deriver.AUDIT_SCHEMA_V10,
                "next_allowed_action": (
                    "derive_and_install_catalog_v10_then_continue_bounded_offline_work"
                ),
                "next_bounded_catalog_requirement": requirements,
                "deterministic_result_hash": "f" * 64,
            }
        ),
        encoding="utf-8",
    )
    return path


class AutopilotCatalogDeriverTests(unittest.TestCase):
    def test_derives_exact_bounded_task_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit = _audit(Path(tmp) / "audit.json")
            catalog = deriver.derive_catalog(
                audit_path=audit, catalog_id="catalog-v3"
            )
        self.assertEqual(
            [task["id"] for task in catalog["tasks"]],
            list(deriver.TASK_TEMPLATES),
        )
        self.assertFalse(catalog["constraints"]["network_access"])
        self.assertTrue(
            all(
                task["max_runtime_sec"] <= 1800
                for task in catalog["tasks"]
            )
        )

    def test_rejects_unknown_or_network_task(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit_path = _audit(root / "audit.json")
            payload = json.loads(audit_path.read_text(encoding="utf-8"))
            payload["next_bounded_catalog_requirement"][0][
                "network"
            ] = True
            audit_path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "network"):
                deriver.derive_catalog(
                    audit_path=audit_path, catalog_id="catalog-v3"
                )

    def test_derives_v4_catalog_from_v4_audit_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit = _audit_v4(Path(tmp) / "audit-v4.json")
            catalog = deriver.derive_catalog(
                audit_path=audit, catalog_id="catalog-v4"
            )
        self.assertEqual(
            [task["id"] for task in catalog["tasks"]],
            list(deriver.TASK_TEMPLATES_V4),
        )
        self.assertTrue(
            all(task["max_runtime_sec"] <= 1800 for task in catalog["tasks"])
        )
        self.assertFalse(catalog["constraints"]["network_access"])

    def test_derives_v5_catalog_from_v5_audit_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit = _audit_v5(Path(tmp) / "audit-v5.json")
            catalog = deriver.derive_catalog(
                audit_path=audit, catalog_id="catalog-v5"
            )
        self.assertEqual(
            [task["id"] for task in catalog["tasks"]],
            list(deriver.TASK_TEMPLATES_V5),
        )
        self.assertTrue(
            all(task["max_runtime_sec"] <= 1800 for task in catalog["tasks"])
        )
        self.assertFalse(catalog["constraints"]["network_access"])

    def test_derives_v6_catalog_from_v6_audit_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit = _audit_v6(Path(tmp) / "audit-v6.json")
            catalog = deriver.derive_catalog(
                audit_path=audit, catalog_id="catalog-v6"
            )
        self.assertEqual(
            [task["id"] for task in catalog["tasks"]],
            list(deriver.TASK_TEMPLATES_V6),
        )
        self.assertFalse(catalog["constraints"]["network_access"])

    def test_derives_v8_catalog_from_v8_audit_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit = _audit_v8(Path(tmp) / "audit-v8.json")
            catalog = deriver.derive_catalog(
                audit_path=audit, catalog_id="catalog-v8"
            )
        self.assertEqual(
            [task["id"] for task in catalog["tasks"]],
            list(deriver.TASK_TEMPLATES_V8),
        )
        self.assertFalse(catalog["constraints"]["network_access"])
        self.assertFalse(catalog["constraints"]["returns_or_pnl_read"])
        self.assertTrue(
            all(task["max_runtime_sec"] <= 1800 for task in catalog["tasks"])
        )

    def test_derives_v10_reconciliation_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            audit = _audit_v10(Path(tmp) / "audit-v10.json")
            catalog = deriver.derive_catalog(
                audit_path=audit, catalog_id="catalog-v10"
            )
        self.assertEqual(
            [task["id"] for task in catalog["tasks"]],
            list(deriver.TASK_TEMPLATES_V10),
        )
        self.assertFalse(catalog["constraints"]["network_access"])
        self.assertFalse(catalog["constraints"]["returns_or_pnl_read"])

    def test_activation_updates_pointers_and_refills_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = _audit(root / "audit.json")
            catalog = deriver.derive_catalog(
                audit_path=audit, catalog_id="catalog-v3"
            )
            catalog_path = root / "catalog.json"
            deriver._write_json_immutable(catalog_path, catalog)
            policy_path = root / "policy.json"
            backlog_path = root / "backlog.json"
            policy_path.write_text(
                json.dumps(
                    {
                        "schema": deriver.POLICY_SCHEMA,
                        "bounded_research_backlog": {
                            "catalog_path": "old",
                            "catalog_file_sha256": "0" * 64,
                        },
                    }
                ),
                encoding="utf-8",
            )
            backlog_path.write_text(
                json.dumps(
                    {
                        "schema": deriver.BACKLOG_SCHEMA,
                        "project": "trading_mvp",
                        "auto_refill": True,
                        "catalog_path": "old",
                        "catalog_file_sha256": "0" * 64,
                        "tasks": [
                            {
                                "id": "done",
                                "max_runtime_sec": 1,
                                "output_path": "done.json",
                                "status": "COMPLETED",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            result = deriver.activate_catalog(
                catalog_path=catalog_path,
                policy_path=policy_path,
                backlog_path=backlog_path,
            )
            backlog = json.loads(backlog_path.read_text(encoding="utf-8"))
        self.assertEqual(
            result["status"], "CATALOG_ACTIVATED_AND_BACKLOG_REFILLED"
        )
        self.assertEqual(
            [task["id"] for task in backlog["tasks"][1:]],
            list(deriver.TASK_TEMPLATES),
        )

    def test_reuses_only_an_identical_existing_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            audit = _audit(root / "audit.json")
            catalog = deriver.derive_catalog(
                audit_path=audit, catalog_id="catalog-v3"
            )
            catalog_path = root / "catalog.json"
            self.assertEqual(
                deriver._write_or_reuse_catalog(
                    catalog_path, catalog, reuse_existing=True
                ),
                "CATALOG_DERIVED",
            )
            self.assertEqual(
                deriver._write_or_reuse_catalog(
                    catalog_path, catalog, reuse_existing=True
                ),
                "CATALOG_REUSED",
            )
            changed = dict(catalog)
            changed["catalog_id"] = "different"
            with self.assertRaisesRegex(ValueError, "does not match"):
                deriver._write_or_reuse_catalog(
                    catalog_path, changed, reuse_existing=True
                )


if __name__ == "__main__":
    unittest.main()
