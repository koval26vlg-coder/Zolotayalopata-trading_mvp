from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from listing_event_history_collector import Candle  # noqa: E402
from slow_liquidity_spot_v2_official_page_discovery import (  # noqa: E402
    canonical_hash,
)
import slow_liquidity_listing_momentum_first_days_collector as collector  # noqa: E402
import slow_liquidity_listing_momentum_first_days_collect_plan as plan_module  # noqa: E402


HOUR = 3600


class FakeClient:
    exchange = "fake"
    max_candles_per_request = 500

    def __init__(self, bars_by_symbol: dict[str, list[Candle]]) -> None:
        self.bars_by_symbol = bars_by_symbol
        self.calls: list[tuple[str, int, int, int]] = []

    def fetch_ohlcv(
        self, symbol: str, granularity: str, start_ts: int, end_ts: int, limit: int
    ) -> list[Candle]:
        self.calls.append((symbol, start_ts, end_ts, limit))
        bars = [
            bar
            for bar in self.bars_by_symbol.get(symbol, [])
            if start_ts <= bar.ts <= end_ts
        ]
        return bars[:limit]


def make_bars(start_ts: int, end_ts: int) -> list[Candle]:
    return [
        Candle(ts=ts, open=1.0, high=2.0, low=0.5, close=1.5, volume=10.0, quote_volume=15.0)
        for ts in range(start_ts, end_ts + 1, HOUR)
    ]


class DeriveJobsTests(unittest.TestCase):
    def test_derives_per_venue_jobs_with_aligned_bounds(self) -> None:
        records = [
            {
                "base": "AAA",
                "mexc_listed_ts": 1_700_000_100.0,
                "gateio_listed_ts": 1_700_050_000.0,
            },
            {"base": "BBB", "mexc_listed_ts": None, "gateio_listed_ts": 1_600_000_000},
        ]
        jobs = collector.derive_first_days_jobs(records)
        self.assertEqual(len(jobs), 3)
        by_key = {(job["exchange"], job["base"]): job for job in jobs}
        mexc_aaa = by_key[("mexc", "AAA")]
        self.assertEqual(mexc_aaa["symbol"], "AAAUSDT")
        self.assertEqual(mexc_aaa["proxy_ts"], 1_700_000_100)
        self.assertEqual(mexc_aaa["probe_start_ts"] % HOUR, 0)
        self.assertLess(mexc_aaa["probe_start_ts"], mexc_aaa["proxy_ts"])
        self.assertEqual(
            mexc_aaa["window_end_ts"],
            ((1_700_000_100 + collector.WINDOW_SEC) // HOUR) * HOUR,
        )
        gate_bbb = by_key[("gateio", "BBB")]
        self.assertEqual(gate_bbb["symbol"], "BBB_USDT")

    def test_jobs_sha256_is_deterministic(self) -> None:
        records = [
            {
                "base": "AAA",
                "mexc_listed_ts": 1_700_000_000,
                "gateio_listed_ts": 1_700_000_000,
            }
        ]
        first = collector.jobs_sha256(collector.derive_first_days_jobs(records))
        second = collector.jobs_sha256(collector.derive_first_days_jobs(records))
        self.assertEqual(first, second)


class ClassifyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.proxy_ts = 1_700_000_000 - (1_700_000_000 % HOUR)
        self.job = {
            "exchange": "mexc",
            "base": "AAA",
            "symbol": "AAAUSDT",
            "proxy_ts": self.proxy_ts,
            "probe_start_ts": self.proxy_ts - collector.PROBE_BEFORE_SEC,
            "window_end_ts": self.proxy_ts + collector.WINDOW_SEC,
        }

    def test_no_data(self) -> None:
        summary = collector.classify_job_bars(self.job, [])
        self.assertIn("no_data", summary["flags"])
        self.assertEqual(summary["window_bar_count"], 0)

    def test_clean_full_window_has_no_flags(self) -> None:
        bars = make_bars(self.proxy_ts, self.proxy_ts + 71 * HOUR)
        summary = collector.classify_job_bars(self.job, bars)
        self.assertEqual(summary["flags"], [])
        self.assertEqual(summary["window_bar_count"], 72)

    def test_history_truncated_when_first_window_bar_is_late(self) -> None:
        bars = make_bars(
            self.proxy_ts + 5 * HOUR, self.proxy_ts + collector.WINDOW_SEC
        )
        summary = collector.classify_job_bars(self.job, bars)
        self.assertIn("history_truncated", summary["flags"])

    def test_proxy_ts_after_first_bar_when_pre_bars_are_old(self) -> None:
        bars = make_bars(
            self.proxy_ts - 5 * 86400, self.proxy_ts + 71 * HOUR
        )
        summary = collector.classify_job_bars(self.job, bars)
        self.assertIn("proxy_ts_after_first_bar", summary["flags"])

    def test_short_window(self) -> None:
        bars = make_bars(self.proxy_ts, self.proxy_ts + 10 * HOUR)
        summary = collector.classify_job_bars(self.job, bars)
        self.assertIn("short_window", summary["flags"])


class CollectWindowBarsTests(unittest.TestCase):
    def test_paging_and_dedup(self) -> None:
        proxy_ts = 1_700_000_000 - (1_700_000_000 % HOUR)
        job = {
            "exchange": "mexc",
            "base": "AAA",
            "symbol": "AAAUSDT",
            "proxy_ts": proxy_ts,
            "probe_start_ts": proxy_ts - 3 * HOUR,
            "window_end_ts": proxy_ts + 3 * HOUR,
        }
        client = FakeClient({"AAAUSDT": make_bars(proxy_ts - 3 * HOUR, proxy_ts + 3 * HOUR)})
        bars, requests = collector.collect_window_bars(
            client, job, candles_per_request=2, sleep_sec=0.0
        )
        self.assertEqual(len(bars), 7)
        self.assertGreaterEqual(requests, 4)
        covered: set[int] = set()
        for symbol, start, end, limit in client.calls:
            self.assertEqual(symbol, "AAAUSDT")
            self.assertLessEqual((end - start) // HOUR + 1, limit)
            covered.update(range(start, end + 1, HOUR))
        self.assertEqual(
            covered,
            set(range(proxy_ts - 3 * HOUR, proxy_ts + 3 * HOUR + 1, HOUR)),
        )


class RunCollectTests(unittest.TestCase):
    def _materialization(self, proxy_ts: int) -> dict:
        return {
            "materialization_hash": "irrelevant-for-run-collect",
            "authorized_by_receipt": {"receipt_hash": "r"},
            "records": [
                {
                    "base": "AAA",
                    "mexc_listed_ts": float(proxy_ts),
                    "gateio_listed_ts": float(proxy_ts),
                }
            ],
        }

    def _plan(self, jobs_sha: str, **overrides) -> dict:
        execution = {
            "output_root": "",
            "timeout_sec": 5,
            "max_retries": 0,
            "sleep_sec": 0.0,
            "max_runtime_sec": 600,
            "claim_path": "",
            "jobs_sha256": jobs_sha,
            "effective_page_sizes": {"mexc": 500, "gateio": 1000},
        }
        execution.update(overrides)
        return {"plan_hash": "phash", "execution": execution}

    def test_run_collect_writes_rows_manifest_and_releases_claim(self) -> None:
        proxy_ts = 1_700_000_000 - (1_700_000_000 % HOUR)
        materialization = self._materialization(proxy_ts)
        jobs = collector.derive_first_days_jobs(materialization["records"])
        bars = {"AAAUSDT": make_bars(proxy_ts, proxy_ts + 71 * HOUR), "AAA_USDT": []}
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "out"
            claim_path = Path(tmp) / "claim" / "writer-claim.json"
            plan = self._plan(
                collector.jobs_sha256(jobs),
                output_root=str(output_root),
                claim_path=str(claim_path),
            )
            fake_mexc = FakeClient(bars)
            fake_gate = FakeClient(bars)
            fake_gate.max_candles_per_request = 1000
            with mock.patch.object(
                collector, "CLIENTS", {"mexc": lambda **kw: fake_mexc, "gateio": lambda **kw: fake_gate}
            ):
                manifest = collector.run_collect(
                    plan, materialization, output_root=output_root, claim_path=claim_path
                )
            self.assertEqual(manifest["status"], "COMPLETED")
            self.assertEqual(manifest["jobs_processed"], 2)
            rows = [
                json.loads(line)
                for line in (output_root / "ohlcv.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(rows), 72)
            for row in rows:
                self.assertEqual(row["exchange"], "mexc")
                self.assertEqual(row["window_role"], "first_days")
            self.assertFalse(claim_path.exists())
            archive = Path(tmp) / "claim" / "global-writer-claim-archive"
            self.assertTrue(any(archive.iterdir()))
            self.assertEqual(manifest["flag_census"]["no_data"], 1)

    def test_run_collect_stops_on_deadline(self) -> None:
        proxy_ts = 1_700_000_000 - (1_700_000_000 % HOUR)
        materialization = self._materialization(proxy_ts)
        jobs = collector.derive_first_days_jobs(materialization["records"])
        with tempfile.TemporaryDirectory() as tmp:
            plan = self._plan(
                collector.jobs_sha256(jobs),
                output_root=str(Path(tmp) / "out"),
                claim_path=str(Path(tmp) / "claim.json"),
                max_runtime_sec=0,
            )
            with mock.patch.object(
                collector, "CLIENTS", {"mexc": lambda **kw: FakeClient({}), "gateio": lambda **kw: FakeClient({})}
            ):
                manifest = collector.run_collect(
                    plan,
                    materialization,
                    output_root=Path(plan["execution"]["output_root"]),
                    claim_path=Path(plan["execution"]["claim_path"]),
                )
            self.assertEqual(manifest["status"], "STOPPED_INCOMPLETE")
            self.assertEqual(
                manifest["stop_reason"], "max_runtime_sec_exceeded"
            )

    def test_run_collect_flags_request_error_and_continues(self) -> None:
        proxy_ts = 1_700_000_000 - (1_700_000_000 % HOUR)
        materialization = self._materialization(proxy_ts)
        jobs = collector.derive_first_days_jobs(materialization["records"])

        class ExplodingClient:
            max_candles_per_request = 500

            def fetch_ohlcv(self, *args: object) -> list[Candle]:
                raise RuntimeError("boom")

        class ExplodingFirstClient(ExplodingClient):
            # gateio sorts before mexc, so this job is processed first and
            # exercises the unbound-requests edge in the error branch
            pass

        with tempfile.TemporaryDirectory() as tmp:
            plan = self._plan(
                collector.jobs_sha256(jobs),
                output_root=str(Path(tmp) / "out"),
                claim_path=str(Path(tmp) / "claim.json"),
            )
            fake_mexc = FakeClient(
                {"AAAUSDT": make_bars(proxy_ts, proxy_ts + 71 * HOUR)}
            )
            with mock.patch.object(
                collector,
                "CLIENTS",
                {"mexc": lambda **kw: fake_mexc, "gateio": lambda **kw: ExplodingFirstClient()},
            ):
                manifest = collector.run_collect(
                    plan,
                    materialization,
                    output_root=Path(plan["execution"]["output_root"]),
                    claim_path=Path(plan["execution"]["claim_path"]),
                )
            self.assertEqual(manifest["status"], "COMPLETED")
            self.assertEqual(manifest["jobs_processed"], 2)
            self.assertEqual(manifest["flag_census"]["request_error"], 1)
            rows = (
                Path(plan["execution"]["output_root"]) / "ohlcv.jsonl"
            ).read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 72)
            self.assertTrue(all('"mexc"' in row for row in rows))

    def test_run_collect_writes_failed_manifest_on_fatal_error(self) -> None:
        proxy_ts = 1_700_000_000 - (1_700_000_000 % HOUR)
        materialization = self._materialization(proxy_ts)
        jobs = collector.derive_first_days_jobs(materialization["records"])

        class ExplodingClient:
            max_candles_per_request = 500

            def fetch_ohlcv(self, *args: object) -> list[Candle]:
                raise RuntimeError("boom")

        with tempfile.TemporaryDirectory() as tmp:
            plan = self._plan(
                collector.jobs_sha256(jobs),
                output_root=str(Path(tmp) / "out"),
                claim_path=str(Path(tmp) / "claim.json"),
            )
            with mock.patch.object(
                collector,
                "CLIENTS",
                {"mexc": lambda **kw: FakeClient({"AAAUSDT": make_bars(proxy_ts, proxy_ts + 71 * HOUR)}), "gateio": lambda **kw: FakeClient({"AAA_USDT": make_bars(proxy_ts, proxy_ts + 71 * HOUR)})},
            ), mock.patch.object(
                collector,
                "classify_job_bars",
                side_effect=RuntimeError("classification exploded"),
            ):
                manifest = collector.run_collect(
                    plan,
                    materialization,
                    output_root=Path(plan["execution"]["output_root"]),
                    claim_path=Path(plan["execution"]["claim_path"]),
                )
            self.assertEqual(manifest["status"], "FAILED")
            self.assertEqual(manifest["stop_reason"], "fatal_error")
            self.assertIn("classification exploded", manifest["fatal_error"])
            self.assertFalse(Path(plan["execution"]["claim_path"]).exists())

    def test_run_collect_refuses_second_writer_in_same_namespace(self) -> None:
        proxy_ts = 1_700_000_000 - (1_700_000_000 % HOUR)
        materialization = self._materialization(proxy_ts)
        jobs = collector.derive_first_days_jobs(materialization["records"])
        with tempfile.TemporaryDirectory() as tmp:
            output_root = Path(tmp) / "out"
            (output_root).mkdir(parents=True)
            (output_root / "ohlcv.jsonl").write_text("x\n", encoding="utf-8")
            plan = self._plan(
                collector.jobs_sha256(jobs),
                output_root=str(output_root),
                claim_path=str(Path(tmp) / "claim.json"),
            )
            with self.assertRaisesRegex(
                collector.FirstDaysCollectError, "second writer"
            ):
                collector.run_collect(
                    plan,
                    materialization,
                    output_root=output_root,
                    claim_path=Path(plan["execution"]["claim_path"]),
                )


class PlanModuleTests(unittest.TestCase):
    def test_plan_is_guarded_and_bound(self) -> None:
        plan = plan_module.build_first_days_collect_plan("2026-08-16T20:40:00Z")
        plan_module.validate_first_days_collect_plan(plan)
        self.assertEqual(plan["universe"]["job_count"], 795)
        self.assertEqual(
            plan["universe"]["jobs_by_venue"], {"mexc": 393, "gateio": 402}
        )
        self.assertFalse(plan["actual_collection_allowed"])
        self.assertFalse(plan["replay_allowed"])
        self.assertFalse(plan["evaluator_or_oos_allowed"])
        self.assertEqual(
            plan["source_bindings"]["proxy_acceptance_receipt"]["status"],
            "PROXY_LISTING_DATE_SOURCE_ACCEPTED",
        )
        self.assertLessEqual(plan["execution"]["max_runtime_sec"], 1800)

    def test_plan_authorizing_collection_without_guards_is_rejected(self) -> None:
        plan = plan_module.build_first_days_collect_plan("2026-08-16T20:40:00Z")
        plan["actual_collection_allowed"] = True
        plan["plan_hash"] = canonical_hash(plan)
        with self.assertRaisesRegex(
            plan_module.FirstDaysCollectPlanError, "guards"
        ):
            plan_module.validate_first_days_collect_plan(plan)

    def test_checked_in_plan_remains_immutable_after_writer_runtime_drift(self) -> None:
        if not plan_module.COLLECT_PLAN_PATH.is_file():
            raise FileNotFoundError(plan_module.COLLECT_PLAN_PATH)
        checked_in = json.loads(
            plan_module.COLLECT_PLAN_PATH.read_text(encoding="utf-8")
        )
        rebuilt = plan_module.build_first_days_collect_plan(
            checked_in["generated_at_utc"]
        )
        checked_bindings = {
            item["role"]: item for item in checked_in["implementation"]["files"]
        }
        rebuilt_bindings = {
            item["role"]: item for item in rebuilt["implementation"]["files"]
        }
        frozen_binding_sha256 = {
            "collector": (
                "b24cbc368082b0a8ade446fc906052629f8edfc2f65783d33cfe276c4c8f1941"
            ),
            "global_writer_claim": (
                "6c57b5612d8dc972ebb94941c514bae7333c1cb21b13dd4487e2fe6a2569ea2e"
            ),
            "visible_launcher": (
                "67d8749369ff3fadb1cef0d8fed7ab9edf7a88d1172ac98d900b5a0316042873"
            ),
        }
        for role, frozen_sha256 in frozen_binding_sha256.items():
            with self.subTest(role=role):
                self.assertEqual(
                    checked_bindings[role]["sha256"],
                    frozen_sha256,
                )
                self.assertNotEqual(
                    rebuilt_bindings[role]["sha256"],
                    frozen_sha256,
                )

        normalized_rebuilt = json.loads(json.dumps(rebuilt))
        for binding in normalized_rebuilt["implementation"]["files"]:
            frozen_sha256 = frozen_binding_sha256.get(binding["role"])
            if frozen_sha256:
                binding["sha256"] = frozen_sha256
        normalized_rebuilt["plan_hash"] = canonical_hash(normalized_rebuilt)
        self.assertEqual(checked_in, normalized_rebuilt)

    def test_collector_rejects_frozen_plan_after_writer_runtime_drift(self) -> None:
        plan = plan_module.build_first_days_collect_plan(
            "2026-08-16T20:40:00Z"
        )
        writer_binding = next(
            item
            for item in plan["implementation"]["files"]
            if item["role"] == "global_writer_claim"
        )
        stale_writer_sha256 = (
            "6c57b5612d8dc972ebb94941c514bae7333c1cb21b13dd4487e2fe6a2569ea2e"
        )
        self.assertNotEqual(writer_binding["sha256"], stale_writer_sha256)
        writer_binding["sha256"] = stale_writer_sha256

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            plan["execution"]["launch_record_path"] = str(
                root / "absent-launch-record.json"
            )
            plan["plan_hash"] = canonical_hash(plan)
            plan_path = root / "plan.json"
            plan_path.write_text(
                json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                collector.FirstDaysCollectError,
                "implementation global_writer_claim sha256 mismatch",
            ):
                collector.load_and_validate_plan(plan_path)

    def test_launcher_blocks_completed_stale_plan_when_output_is_absent(
        self,
    ) -> None:
        pwsh = shutil.which("pwsh")
        if not pwsh:
            self.skipTest("pwsh is not available")

        checked_in = json.loads(
            plan_module.COLLECT_PLAN_PATH.read_text(encoding="utf-8")
        )
        writer_binding = next(
            item
            for item in checked_in["implementation"]["files"]
            if item["role"] == "global_writer_claim"
        )
        current_writer_sha256 = hashlib.sha256(
            Path(writer_binding["path"]).read_bytes()
        ).hexdigest()
        self.assertNotEqual(writer_binding["sha256"], current_writer_sha256)

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output_root = root / "absent-output"
            plan_path = root / "plan.json"
            plan = json.loads(json.dumps(checked_in))
            execution = plan["execution"]
            execution["output_root"] = str(output_root)
            execution["output_jsonl"] = str(output_root / "ohlcv.jsonl")
            execution["manifest_path"] = str(output_root / "manifest.json")
            execution["stdout_path"] = str(output_root / "stdout.log")
            execution["stderr_path"] = str(output_root / "stderr.log")
            plan["plan_hash"] = canonical_hash(plan)
            plan_bytes = (
                json.dumps(plan, ensure_ascii=False, indent=2) + "\n"
            ).encode("utf-8")
            plan_path.write_bytes(plan_bytes)

            result = subprocess.run(
                [
                    pwsh,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(plan_module.LAUNCHER_PATH),
                    "-PlanPath",
                    str(plan_path),
                    "-ExpectedPlanHash",
                    plan["plan_hash"],
                    "-ExpectedPlanFileSha256",
                    hashlib.sha256(plan_bytes).hexdigest(),
                    "-PreflightOnly",
                    "-Json",
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=60,
                check=False,
            )
            self.assertFalse(output_root.exists())

        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        payload = json.loads(result.stdout)
        self.assertFalse(payload["ok"])
        self.assertIn(
            "implementation_global_writer_claim_sha256_mismatch",
            payload["reasons"],
        )
        self.assertIn(
            "completed_planonly_cannot_be_relaunched",
            payload["reasons"],
        )

    def test_plan_execution_covers_collector_contract(self) -> None:
        plan = plan_module.build_first_days_collect_plan("2026-08-16T20:40:00Z")
        missing = [
            key
            for key in collector.REQUIRED_EXECUTION_KEYS
            if key not in plan["execution"]
        ]
        self.assertEqual(missing, [])
        self.assertEqual(
            plan["execution"]["effective_page_sizes"],
            {
                "mexc": plan["implementation"]["page_caps"][
                    "mexc_max_candles_per_request"
                ],
                "gateio": plan["implementation"]["page_caps"][
                    "gateio_max_candles_per_request"
                ],
            },
        )

    def test_collector_loads_frozen_plan_and_materialization(self) -> None:
        generated_plan = plan_module.build_first_days_collect_plan(
            "2026-08-16T20:40:00Z"
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            generated_plan["execution"]["launch_record_path"] = str(
                root / "absent-launch-record.json"
            )
            generated_plan["plan_hash"] = canonical_hash(generated_plan)
            plan_path = root / "plan.json"
            plan_path.write_text(
                json.dumps(generated_plan, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            plan = collector.load_and_validate_plan(plan_path)
        materialization = collector.load_and_validate_materialization(
            collector.MATERIALIZATION_PATH, plan
        )
        jobs = collector.derive_first_days_jobs(materialization["records"])
        self.assertEqual(collector.jobs_sha256(jobs), plan["execution"]["jobs_sha256"])
        self.assertEqual(len(jobs), 795)


if __name__ == "__main__":
    unittest.main()
