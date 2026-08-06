from __future__ import annotations

import hashlib
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from trading_mvp.tests import test_pit_membership_drift_pipeline as pit_fixture


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "trading_mvp" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pit_membership_drift_evaluator import (  # noqa: E402
    build_evaluation_input_plan,
    run_oos_evaluation,
    run_train_feasibility,
)
from pit_membership_drift_execution_probe import (  # noqa: E402
    build_execution_probe_plan,
    evaluate_execution_probe,
)
from pit_membership_drift_execution_probe_collector import (  # noqa: E402
    _atomic_write_json,
    collect_execution_probe,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class _FakeClock:
    def __init__(self) -> None:
        self.elapsed = 0.0

    def monotonic(self) -> float:
        return self.elapsed

    def wall_time(self) -> float:
        return 1_750_000_000.0 + self.elapsed

    def sleep(self, seconds: float) -> None:
        self.elapsed += max(0.0, seconds)


class AtomicWriteTests(unittest.TestCase):
    def test_atomic_write_retries_transient_windows_permission_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "manifest.json"
            real_replace = __import__("os").replace
            calls = {"count": 0}

            def flaky_replace(source: Path, destination: Path) -> None:
                calls["count"] += 1
                if calls["count"] < 3:
                    raise PermissionError("transient scanner lock")
                real_replace(source, destination)

            with patch(
                "pit_membership_drift_execution_probe_collector.os.replace",
                side_effect=flaky_replace,
            ), patch("pit_membership_drift_execution_probe_collector.time.sleep") as sleep:
                _atomic_write_json(target, {"final": True})

            self.assertEqual(calls["count"], 3)
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"final": True})


def _valid_pair(base: str, *, impact_bps: float = 5.0) -> dict:
    buy_vwap = 100.0 * (1.0 + impact_bps / 10_000.0)
    sell_vwap = 100.0 * (1.0 - impact_bps / 10_000.0)
    return {
        "base": base,
        "fully_valid": True,
        "invalid_reasons": [],
        "venues": {
            venue: {
                "exchange": venue,
                "base": base,
                "quote": "USDT",
                "bid_price": 100.0,
                "ask_price": 100.0,
            }
            for venue in ("mexc", "gateio")
        },
        "depth_fills": {
            venue: {
                "buy": {
                    "complete": True,
                    "target_quote_notional": 500.0,
                    "filled_quote_notional": 500.0,
                    "vwap": buy_vwap,
                },
                "sell": {
                    "complete": True,
                    "target_quote_notional": 500.0,
                    "filled_quote_notional": 500.0,
                    "vwap": sell_vwap,
                },
            }
            for venue in ("mexc", "gateio")
        },
    }


class PitMembershipDriftExecutionProbeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._temp = tempfile.TemporaryDirectory()
        root = Path(cls._temp.name)
        fixture = pit_fixture.PitMembershipDriftPipelineTests()
        train_path, train, bank, ledger, contract = fixture._train_plan(root, days=120)
        feasibility_path = root / "feasibility.json"
        feasibility = run_train_feasibility(
            train_path,
            expected_plan_hash=train["plan_hash"],
            output_path=feasibility_path,
        )
        if feasibility["verdict"] != "FEASIBLE_FOR_OOS":
            raise AssertionError(feasibility)
        full_plan_path = root / "full-plan.json"
        full_plan = build_evaluation_input_plan(
            quality_ledger_path=ledger,
            hypothesis_bank_path=bank,
            hypothesis_id=contract["id"],
            output_path=full_plan_path,
            plan_stage="full_evaluation",
            train_plan_path=train_path,
            feasibility_path=feasibility_path,
        )
        evaluation_path = root / "evaluation.json"
        evaluation = run_oos_evaluation(
            full_plan_path,
            expected_plan_hash=full_plan["plan_hash"],
            feasibility_path=feasibility_path,
            output_path=evaluation_path,
            created_at_utc="2026-07-15T03:30:00+00:00",
        )
        if evaluation["verdict"] != "ACCEPT_FOR_SHORT_EXECUTION_PROBE":
            raise AssertionError(evaluation["verdict"])
        cls.root = root
        cls.evaluation_path = evaluation_path

    @classmethod
    def tearDownClass(cls) -> None:
        cls._temp.cleanup()

    def _plan(self, name: str) -> tuple[Path, dict]:
        path = self.root / name
        plan = build_execution_probe_plan(self.evaluation_path, path)
        return path, plan

    def _probe_run(
        self,
        plan_path: Path,
        plan: dict,
        name: str,
        *,
        attempts: int = 225,
        valid: int = 225,
        impact_bps: float = 5.0,
        elapsed_sec: float = 1200.0,
        bad_mexc_buy_count: int = 0,
        bad_mexc_buy_impact_bps: float = 20.0,
        degraded_base: str | None = None,
        degraded_base_invalid_count: int = 0,
        bad_impact_base: str | None = None,
        bad_impact_base_count: int = 0,
    ) -> tuple[Path, Path]:
        sample_path = self.root / f"{name}.jsonl"
        candidates = plan["instrument_scope"]["candidate_bases"]
        rows = []
        occurrences = {base: 0 for base in candidates}
        for index in range(attempts):
            base = candidates[index % len(candidates)]
            base_occurrence = occurrences[base]
            occurrences[base] += 1
            fully_valid = (
                not (base == degraded_base and base_occurrence < degraded_base_invalid_count)
                if degraded_base is not None
                else index < valid
            )
            buy_vwap = 100.0 * (1.0 + impact_bps / 10_000.0)
            sell_vwap = 100.0 * (1.0 - impact_bps / 10_000.0)
            rows.append(
                {
                    "schema": "pit_membership_drift_execution_probe_sample_v1",
                    "run_id": name,
                    "plan_hash": plan["plan_hash"],
                    "attempt_index": index,
                    "base": base,
                    "started_at_utc": f"2026-07-15T04:{index // 60:02d}:{index % 60:02d}+00:00",
                    "finished_at_utc": f"2026-07-15T04:{index // 60:02d}:{index % 60:02d}+00:00",
                    "pair": {
                        "base": base,
                        "fully_valid": fully_valid,
                        "invalid_reasons": [] if fully_valid else ["fixture_invalid"],
                        "venues": {
                            venue: {
                                "exchange": venue,
                                "base": base,
                                "quote": "USDT",
                                "bid_price": 100.0,
                                "ask_price": 100.0,
                            }
                            for venue in ("mexc", "gateio")
                        },
                        "depth_fills": {
                            venue: {
                                "buy": {
                                    "complete": fully_valid,
                                    "target_quote_notional": 500.0,
                                    "filled_quote_notional": 500.0 if fully_valid else 0.0,
                                    "vwap": buy_vwap if fully_valid else None,
                                },
                                "sell": {
                                    "complete": fully_valid,
                                    "target_quote_notional": 500.0,
                                    "filled_quote_notional": 500.0 if fully_valid else 0.0,
                                    "vwap": sell_vwap if fully_valid else None,
                                },
                            }
                            for venue in ("mexc", "gateio")
                        },
                    },
                }
            )
            if fully_valid and index < bad_mexc_buy_count:
                rows[-1]["pair"]["depth_fills"]["mexc"]["buy"]["vwap"] = 100.0 * (
                    1.0 + bad_mexc_buy_impact_bps / 10_000.0
                )
            if fully_valid and base == bad_impact_base and base_occurrence < bad_impact_base_count:
                rows[-1]["pair"]["depth_fills"]["mexc"]["buy"]["vwap"] = 100.0 * (
                    1.0 + bad_mexc_buy_impact_bps / 10_000.0
                )
        sample_path.write_text(
            "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
            encoding="utf-8",
        )
        manifest_path = self.root / f"{name}.manifest.json"
        _write_json(
            manifest_path,
            {
                "schema": "pit_membership_drift_execution_probe_manifest_v1",
                "mode": "pit_membership_drift_execution_probe_collect",
                "run_id": name,
                "plan_path": str(plan_path.resolve()),
                "plan_file_sha256": _sha256(plan_path),
                "plan_hash": plan["plan_hash"],
                "sample_path": str(sample_path.resolve()),
                "sample_file_sha256": _sha256(sample_path),
                "attempted_snapshots": attempts,
                "elapsed_active_sec": elapsed_sec,
                "final": True,
                "incomplete": False,
                "stop_reason": "duration_complete",
                "network_access": True,
                "grid_search": False,
                "retune": False,
                "paper_forward": False,
                "live_orders": False,
                "api_keys": False,
            },
        )
        return manifest_path, sample_path

    def test_plan_is_hash_bound_and_freezes_canonical_probe_gates(self) -> None:
        plan_path, plan = self._plan("probe-plan.json")

        self.assertEqual(plan["schema"], "pit_membership_drift_execution_probe_plan_v1")
        self.assertEqual(plan["mode"], "PlanOnly")
        self.assertEqual(plan["hypothesis_id"], "pit_universe_membership_drift_reversion_v1")
        self.assertEqual(plan["collection_contract"]["duration_sec"], 1200)
        self.assertEqual(plan["collection_contract"]["interval_sec"], 5)
        self.assertEqual(plan["collection_contract"]["target_notional_quote_per_leg"], 500.0)
        self.assertEqual(plan["acceptance_gates"]["minimum_valid_snapshots"], 180)
        self.assertEqual(plan["acceptance_gates"]["minimum_coverage_ratio"], 0.80)
        self.assertEqual(plan["acceptance_gates"]["maximum_p95_impact_bps_per_leg"], 10.0)
        self.assertGreater(len(plan["instrument_scope"]["candidate_bases"]), 0)
        self.assertEqual(plan["source"]["evaluation_file_sha256"], _sha256(self.evaluation_path))
        self.assertIn(plan["plan_hash"], plan["approval_phrase"])
        self.assertFalse(plan["would_start"])
        self.assertFalse(plan["network_access"])
        self.assertFalse(plan["paper_forward_allowed"])
        self.assertFalse(plan["live_orders"])
        self.assertTrue(plan_path.is_file())

    def test_plan_rejects_tampered_evaluation(self) -> None:
        tampered = self.root / "evaluation-tampered.json"
        payload = json.loads(self.evaluation_path.read_text(encoding="utf-8"))
        payload["verdict"] = "REJECT"
        _write_json(tampered, payload)

        with self.assertRaisesRegex(ValueError, "deterministic result hash"):
            build_execution_probe_plan(tampered, self.root / "tampered-plan.json")

    def test_completed_probe_passes_only_at_all_frozen_gates(self) -> None:
        plan_path, plan = self._plan("pass-plan.json")
        manifest, _ = self._probe_run(plan_path, plan, "pass-run")
        output = self.root / "pass-evaluation.json"

        result = evaluate_execution_probe(plan_path, manifest, output)

        self.assertEqual(result["verdict"], "PAPER_READY")
        self.assertEqual(result["metrics"]["valid_snapshots"], 225)
        self.assertEqual(result["metrics"]["coverage_ratio"], 1.0)
        self.assertLessEqual(result["metrics"]["p95_impact_bps_per_leg"], 10.0)
        self.assertTrue(result["paper_forward_allowed"])
        self.assertTrue(result["requires_explicit_user_approval_for_paper_forward"])
        self.assertFalse(result["live_orders"])

    def test_probe_rejects_excess_p95_impact_without_retune_route(self) -> None:
        plan_path, plan = self._plan("impact-plan.json")
        manifest, _ = self._probe_run(plan_path, plan, "impact-run", impact_bps=12.0)

        result = evaluate_execution_probe(plan_path, manifest, self.root / "impact-evaluation.json")

        self.assertEqual(result["verdict"], "REJECT_EXECUTION")
        self.assertIn("p95_impact_above_gate", result["rejection_reasons"])
        self.assertEqual(result["next_allowed_command"], "NO_COMMAND_TERMINAL_HYPOTHESIS_CLOSED")
        self.assertFalse(result["paper_forward_allowed"])

    def test_probe_uses_worst_per_leg_p95_instead_of_pooled_distribution(self) -> None:
        plan_path, plan = self._plan("per-leg-impact-plan.json")
        manifest, _ = self._probe_run(
            plan_path,
            plan,
            "per-leg-impact-run",
            bad_mexc_buy_count=18,
            bad_mexc_buy_impact_bps=20.0,
        )

        result = evaluate_execution_probe(plan_path, manifest, self.root / "per-leg-impact-evaluation.json")

        self.assertEqual(result["verdict"], "REJECT_EXECUTION")
        self.assertGreater(result["metrics"]["p95_impact_bps_by_leg"]["mexc_buy"], 10.0)
        self.assertEqual(
            result["metrics"]["p95_impact_bps_per_leg"],
            max(result["metrics"]["p95_impact_bps_by_leg"].values()),
        )

    def test_probe_rejects_base_with_low_coverage_even_when_global_coverage_passes(self) -> None:
        plan_path, plan = self._plan("per-base-coverage-plan.json")
        candidates = plan["instrument_scope"]["candidate_bases"]
        self.assertGreater(len(candidates), 1)
        attempts_for_base = math.ceil(225 / len(candidates))
        invalid_count = math.ceil(attempts_for_base * 0.25)
        manifest, _ = self._probe_run(
            plan_path,
            plan,
            "per-base-coverage-run",
            degraded_base=candidates[0],
            degraded_base_invalid_count=invalid_count,
        )

        result = evaluate_execution_probe(
            plan_path,
            manifest,
            self.root / "per-base-coverage-evaluation.json",
        )

        self.assertEqual(result["verdict"], "REJECT_EXECUTION")
        self.assertIn(
            f"candidate_base_coverage_below_gate:{candidates[0]}",
            result["rejection_reasons"],
        )
        self.assertGreaterEqual(result["metrics"]["coverage_ratio"], 0.80)

    def test_probe_rejects_bad_base_leg_p95_hidden_by_global_pool(self) -> None:
        plan_path, plan = self._plan("per-base-impact-plan.json")
        candidates = plan["instrument_scope"]["candidate_bases"]
        self.assertGreater(len(candidates), 1)
        attempts_for_base = math.ceil(225 / len(candidates))
        bad_count = math.ceil(attempts_for_base * 0.06)
        manifest, _ = self._probe_run(
            plan_path,
            plan,
            "per-base-impact-run",
            attempts=225,
            valid=225,
            bad_impact_base=candidates[0],
            bad_impact_base_count=bad_count,
            bad_mexc_buy_impact_bps=20.0,
        )

        result = evaluate_execution_probe(
            plan_path,
            manifest,
            self.root / "per-base-impact-evaluation.json",
        )

        self.assertEqual(result["verdict"], "REJECT_EXECUTION")
        self.assertIn(
            f"candidate_base_p95_impact_above_gate:{candidates[0]}",
            result["rejection_reasons"],
        )
        self.assertLessEqual(result["metrics"]["p95_impact_bps_per_leg"], 10.0)

    def test_probe_result_hash_is_deterministic(self) -> None:
        plan_path, plan = self._plan("repeat-plan.json")
        manifest, _ = self._probe_run(plan_path, plan, "repeat-run")
        first = evaluate_execution_probe(plan_path, manifest, self.root / "repeat-first.json")
        second = evaluate_execution_probe(plan_path, manifest, self.root / "repeat-second.json")

        self.assertEqual(first["deterministic_result_hash"], second["deterministic_result_hash"])
        self.assertEqual(first["verdict"], second["verdict"])

    def test_collector_completes_exact_bounded_contract_on_virtual_clock(self) -> None:
        plan_path, plan = self._plan("collector-plan.json")
        clock = _FakeClock()
        output_root = self.root / "collector-output"

        manifest = collect_execution_probe(
            plan_path,
            output_root,
            "collector-run",
            pair_fetcher=lambda base: _valid_pair(base),
            monotonic_fn=clock.monotonic,
            wall_time_fn=clock.wall_time,
            sleep_fn=clock.sleep,
        )

        sample_path = Path(manifest["sample_path"])
        self.assertTrue(manifest["final"])
        self.assertFalse(manifest["incomplete"])
        self.assertEqual(manifest["stop_reason"], "duration_complete")
        self.assertEqual(manifest["attempted_snapshots"], 240)
        self.assertEqual(manifest["valid_snapshots"], 240)
        self.assertEqual(manifest["elapsed_active_sec"], 1200.0)
        self.assertEqual(manifest["plan_hash"], plan["plan_hash"])
        self.assertEqual(len(sample_path.read_text(encoding="utf-8").splitlines()), 240)
        self.assertFalse(manifest["paper_forward"])
        self.assertFalse(manifest["live_orders"])
        self.assertFalse(manifest["api_keys"])

    def test_collector_resumes_same_run_id_without_overwriting_samples(self) -> None:
        plan_path, _ = self._plan("resume-collector-plan.json")
        clock = _FakeClock()
        output_root = self.root / "resume-collector-output"
        calls = {"count": 0}

        def fetch(base: str) -> dict:
            calls["count"] += 1
            return _valid_pair(base)

        first = collect_execution_probe(
            plan_path,
            output_root,
            "resume-run",
            pair_fetcher=fetch,
            monotonic_fn=clock.monotonic,
            wall_time_fn=clock.wall_time,
            sleep_fn=clock.sleep,
            stop_requested=lambda: calls["count"] >= 10,
        )
        self.assertFalse(first["final"])
        self.assertTrue(first["incomplete"])
        self.assertEqual(first["attempted_snapshots"], 10)

        resumed = collect_execution_probe(
            plan_path,
            output_root,
            "resume-run",
            resume=True,
            pair_fetcher=fetch,
            monotonic_fn=clock.monotonic,
            wall_time_fn=clock.wall_time,
            sleep_fn=clock.sleep,
        )

        self.assertTrue(resumed["final"])
        self.assertEqual(resumed["attempted_snapshots"], 240)
        self.assertEqual(resumed["resume_count"], 1)
        sample_path = Path(resumed["sample_path"])
        indices = [json.loads(line)["attempt_index"] for line in sample_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(indices, list(range(240)))


if __name__ == "__main__":
    unittest.main()
