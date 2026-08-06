from __future__ import annotations

import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gate_historical_membership_v2 import build_plan as build_v2_plan  # noqa: E402
from gate_historical_membership_v2 import run_probe as run_v2_probe  # noqa: E402
from gate_historical_membership_v2_closure import build_source_reject_closure  # noqa: E402
from gate_historical_membership_v3 import (  # noqa: E402
    ACCEPTED_PROBE_DECISION,
    PLAN_DECISION,
    REJECTED_PROBE_DECISION,
    authorize_probe,
    build_plan,
    run_probe,
)


END_SEC = 1_800_000_000


def _write_daily_manifest(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "schema": "daily_collect_v1",
                "run_id": "daily_fixture",
                "params": {"exchanges": ["mexc", "gateio"], "days": 220, "end_sec": END_SEC},
                "statuses": [],
            }
        ),
        encoding="utf-8",
    )


def _raw_contract(index: int, cohort: str) -> dict:
    delisted = cohort != "active"
    age_offset = index % 100
    row = {
        "name": f"C{index:03d}_USDT",
        "type": "direct",
        "contract_type": "crypto",
        "status": "delisted" if delisted else "trading",
        "create_time": END_SEC - (120 + age_offset) * 86_400,
        "launch_time": END_SEC - (119 + age_offset) * 86_400,
        "in_delisting": delisted,
        "position_size": "0" if delisted else "100",
        "quanto_multiplier": "0.01",
        "funding_interval": 28_800,
        "order_size_min": 1,
        "order_size_max": 1_000_000,
    }
    if cohort == "known_end":
        row["delisted_time"] = END_SEC - (10 + age_offset) * 86_400
    return row


def _write_registry(path: Path, raw: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["rank", "symbol", "name", "coin_id"])
        writer.writeheader()
        for index, row in enumerate(raw):
            base = row["name"].rsplit("_", 1)[0]
            writer.writerow(
                {"rank": index + 1, "symbol": base, "name": f"Coin {base}", "coin_id": f"coin-{base.lower()}"}
            )


class GateHistoricalMembershipV3Tests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, Path]:
        daily = root / "daily.json"
        registry = root / "registry.csv"
        v2_plan_path = root / "v2-plan.json"
        v2_probe_path = root / "v2-probe.json"
        closure_dir = root / "closure"
        _write_daily_manifest(daily)
        raw = []
        raw.extend(_raw_contract(index, "active") for index in range(100))
        raw.extend(_raw_contract(200 + index, "missing_end") for index in range(15))
        raw.extend(_raw_contract(300 + index, "known_end") for index in range(10))
        raw.append(dict(raw[0]))
        _write_registry(registry, raw[:-1])
        v2_plan = build_v2_plan(
            daily_manifest_path=daily,
            output_path=v2_plan_path,
            run_id="membership_v2_fixture",
            generated_at_utc="2026-07-17T00:00:00Z",
        )
        v2_probe = run_v2_probe(
            plan_path=v2_plan_path,
            expected_plan_hash=v2_plan["plan_hash"],
            output_path=v2_probe_path,
            max_runtime_sec=600,
            fetch_page_override=lambda _limit, offset: raw if offset == 0 else [],
        )
        self.assertFalse(v2_probe["accepted"])
        closure = build_source_reject_closure(
            plan_path=v2_plan_path,
            probe_path=v2_probe_path,
            output_dir=closure_dir,
            run_id="membership_v2_source_reject",
            generated_at_utc="2026-07-17T01:00:00Z",
        )
        return Path(closure["manifest_path"]), daily, registry

    def test_plan_is_deterministic_and_source_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure, daily, registry = self._fixture(root)
            first = build_plan(
                closure_manifest_path=closure,
                daily_manifest_path=daily,
                coin_registry_path=registry,
                output_path=root / "v3-plan.json",
                run_id="membership_v3_fixture",
                generated_at_utc="2026-07-17T02:00:00Z",
            )
            second = build_plan(
                closure_manifest_path=closure,
                daily_manifest_path=daily,
                coin_registry_path=registry,
                output_path=None,
                run_id="membership_v3_fixture",
                generated_at_utc="2026-07-17T03:00:00Z",
            )

            self.assertEqual(first["decision"], PLAN_DECISION)
            self.assertEqual(first["plan_hash"], second["plan_hash"])
            self.assertFalse(first["network_calls_now"])
            self.assertFalse(first["research_contract"]["returns_read"])
            self.assertEqual(first["probe_task_summary"]["cohort_symbol_counts"]["missing_end_delisted"], 10)
            self.assertNotIn("C000_USDT", {row["symbol"] for row in first["candidate_universe"]["candidates"]})
            self.assertIn(first["plan_hash"], first["approval_phrase"])

    def test_probe_accepts_available_archive_objects_and_reuses_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure, daily, registry = self._fixture(root)
            plan_path = root / "v3-plan.json"
            output = root / "v3-probe.json"
            plan = build_plan(
                closure_manifest_path=closure,
                daily_manifest_path=daily,
                coin_registry_path=registry,
                output_path=plan_path,
                run_id="membership_v3_fixture",
            )

            report = run_probe(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=output,
                max_runtime_sec=600,
                fetch_override=lambda _task, _timeout: (200, {"Content-Length": "100"}),
            )

            self.assertEqual(report["decision"], ACCEPTED_PROBE_DECISION)
            self.assertTrue(report["accepted"])
            self.assertFalse(report["data_access_audit"]["archive_payload_read"])
            cached = run_probe(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=output,
                max_runtime_sec=600,
                fetch_override=lambda *_args: self.fail("cache reuse must avoid requests"),
            )
            self.assertTrue(cached["cache_reused"])

    def test_probe_rejects_when_missing_end_cohort_has_no_archive_objects(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure, daily, registry = self._fixture(root)
            plan_path = root / "v3-plan.json"
            plan = build_plan(
                closure_manifest_path=closure,
                daily_manifest_path=daily,
                coin_registry_path=registry,
                output_path=plan_path,
                run_id="membership_v3_fixture",
            )

            report = run_probe(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash"],
                output_path=root / "v3-probe.json",
                max_runtime_sec=600,
                fetch_override=lambda task, _timeout: (
                    404 if task["cohort"] == "missing_end_delisted" else 200,
                    {},
                ),
            )

            self.assertEqual(report["decision"], REJECTED_PROBE_DECISION)
            self.assertFalse(report["accepted"])

    def test_authorizer_rejects_tampered_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            closure, daily, registry = self._fixture(root)
            plan_path = root / "v3-plan.json"
            plan = build_plan(
                closure_manifest_path=closure,
                daily_manifest_path=daily,
                coin_registry_path=registry,
                output_path=plan_path,
                run_id="membership_v3_fixture",
            )
            payload = json.loads(plan_path.read_text(encoding="utf-8"))
            payload["quality_gates"]["minimum_cohort_symbol_availability"] = 0.1
            plan_path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "plan hash mismatch"):
                authorize_probe(plan_path, plan["plan_hash"])


class GateHistoricalMembershipV3WrapperTests(unittest.TestCase):
    def test_run_mvp_exposes_plan_and_fail_closed_visible_probe_route(self) -> None:
        wrapper = Path(__file__).resolve().parents[1] / "run_mvp.ps1"
        text = wrapper.read_text(encoding="utf-8-sig")
        plan_start = text.index('"fast-edge-membership-v3-source-plan" {')
        probe_start = text.index('"fast-edge-membership-v3-source-probe" {', plan_start)
        history_start = text.index('"fast-edge-membership-history-plan" {', probe_start)
        plan_case = text[plan_start:probe_start]
        probe_case = text[probe_start:history_start]

        self.assertIn("gate_historical_membership_v3.py", plan_case)
        self.assertIn('"--closure-manifest", $ClosurePath', plan_case)
        self.assertIn('"--daily-manifest", $InputPath', plan_case)
        self.assertIn('"--coin-registry", $CoinRegistryPath', plan_case)
        self.assertIn("MaxRuntimeSec must be <= 600", plan_case)

        self.assertIn("start_gate_historical_membership_v3_probe_visible.ps1", probe_case)
        self.assertIn("Direct membership-v3 network execution is disabled", probe_case)
        self.assertIn("-ConfirmedPublicProbe", probe_case)
        self.assertIn("MaxRuntimeSec must be <= 600", probe_case)
        self.assertNotIn("Invoke-TradingMvpCli", probe_case)
        self.assertNotIn("gate_historical_membership_v3.py", probe_case)

    def test_visible_launcher_is_planonly_and_confirmation_gated(self) -> None:
        root = Path(__file__).resolve().parents[2]
        launcher = (root / "tools" / "start_gate_historical_membership_v3_probe_visible.ps1").read_text(
            encoding="utf-8-sig"
        )
        worker = (root / "tools" / "run_gate_historical_membership_v3_probe_visible.ps1").read_text(
            encoding="utf-8-sig"
        )

        self.assertIn("[switch]$PlanOnly", launcher)
        self.assertIn("[switch]$ConfirmedPublicProbe", launcher)
        self.assertIn("authorize_probe", launcher)
        self.assertIn("Start-Process", launcher)
        self.assertIn("-WindowStyle Normal", launcher)
        self.assertIn("network_access = $false", launcher)
        self.assertIn("archive_payload_read = $false", launcher)
        self.assertIn("Refusing to overwrite immutable visible launch record", launcher)
        self.assertIn("LaunchRecordPath", worker)
        self.assertIn("READY_FOR_POSTPROCESS", worker)
        self.assertIn("STOPPED_INCOMPLETE", worker)
        self.assertIn("$reportErrors = @()", worker)
        self.assertIn("Where-Object { $null -ne $_ -and [string]$_ -ne '' }", worker)
        self.assertIn("$errorCount = $reportErrors.Count + $resultErrors.Count", worker)


if __name__ == "__main__":
    unittest.main()
