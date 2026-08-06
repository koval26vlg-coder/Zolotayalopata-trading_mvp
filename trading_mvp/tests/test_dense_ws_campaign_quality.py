from __future__ import annotations

import base64
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import dense_ws_campaign_quality as quality  # noqa: E402


MEXC_BOOK_TICKER_B64 = (
    "CjVzcG90QHB1YmxpYy5hZ2dyZS5ib29rVGlja2VyLnYzLmFwaS5wYkAxMDBtc0BIWVBFVVNEVBoI"
    "SFlQRVVTRFQw+t6t8+gz2hMtCgU3Mi4yORIENy4wMRoFNzIuMzQiBDgyLjEqCjEzMjAwNDMzNTYw"
    "yt6t8+gz"
)
MEXC_DEPTH_B64 = (
    "Ci1zcG90QHB1YmxpYy5saW1pdC5kZXB0aC52My5hcGkucGJASFlQRVVTRFRAMjAaCEhZUEVVU0RUMIzirfPoM/oSqQUKDgoFNzIuMzYSBTgyLjEwCg4KBTcyLjM2EgU4OS42MQoOCgU3Mi4zOBIFODMuODMKDgoFNzIuMzkSBTgwLjI4Cg4KBTcyLjQxEgU4Mi4xMAoOCgU3Mi40MhIFODIuMjEKDgoFNzIuNDYSBTgyLjEwCg4KBTcyLjQ3EgU4MC40OQoPCgU3Mi40OBIGMTQ2LjA4Cg0KBTcyLjUxEgQwLjA2Cg8KBTcyLjUzEgYxNDUuODQKDQoFNzIuNTUSBDAuNjQKDQoFNzIuNTYSBDAuMzMKDQoFNzIuNTkSBDAuMDIKDQoFNzIuNjASBDAuMDIKDQoFNzIuNjESBDAuMDIKDgoFNzIuNjISBTMyLjE1Cg0KBTcyLjYzEgQwLjUzCg4KBTcyLjY0EgUyNC4zMQoOCgU3Mi42NRIFMjQuNDASDQoFNzIuMjkSBDcuMDESDgoFNzIuMjgSBTEyLjYzEg4KBTcyLjI3EgUxNi4xMxINCgU3Mi4yNhIEOC44NBIOCgU3Mi4yNRIFODkuMTESDgoFNzIuMjQSBTgyLjMyEg8KBTcyLjIyEgYxNDcuODISDQoFNzIuMjASBDAuNjkSDwoFNzIuMTkSBjE3Ni4wNRINCgU3Mi4xOBIEMS4wNBIOCgU3Mi4xNxIFMjAuMDASDQoFNzIuMTYSBDIuMDASDgoFNzIuMTUSBTM2LjU1Eg0KBTcyLjE0EgQyLjAyEg4KBTcyLjEzEgUzMC41NhINCgU3Mi4xMhIEMS41MBIOCgU3Mi4xMRIFNTkuNjMSDQoFNzIuMTASBDIuMDISDQoFNzIuMDkSBDAuMDISDQoFNzIuMDgSBDIuMDIaIXNwb3RAcHVibGljLmxpbWl0LmRlcHRoLnYzLmFwaS5wYiIKMTMyMDA0MzM3Myjv4a3z6DM="
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _mexc_row(ts: float, payload_b64: str) -> dict:
    raw = base64.b64decode(payload_b64)
    return {
        "recv_ts": ts,
        "exchange": "mexc",
        "event_type": "protobuf",
        "channel": None,
        "symbol": None,
        "payload": {
            "encoding": "base64",
            "byte_length": len(raw),
            "data": payload_b64,
        },
    }


def _gate_row(ts: float, channel: str, result: dict) -> dict:
    symbol = str(result.get("s") or result.get("currency_pair") or "HYPE_USDT")
    return {
        "recv_ts": ts,
        "exchange": "gateio",
        "event_type": "update",
        "channel": channel,
        "symbol": symbol,
        "payload": {
            "encoding": "json",
            "data": {
                "time_ms": int(ts * 1000),
                "channel": channel,
                "event": "update",
                "result": result,
            },
        },
    }


def _control_row(exchange: str, ts: float, data: dict) -> dict:
    return {
        "recv_ts": ts,
        "exchange": exchange,
        "event_type": "subscribe_sent",
        "channel": None,
        "symbol": None,
        "payload": {"encoding": "json", "data": data},
    }


class DenseWsCampaignQualityTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[dict, dict, Path, Path, Path]:
        campaign_id = "dense_ws_fixture"
        candidate_hash = "a" * 64
        contract_hash = "b" * 64
        plan_hash = "c" * 64
        universe_hash = "d" * 64
        phase_id = "phase_01"
        run_id = f"{campaign_id}_{phase_id}"
        phase_root = root / run_id
        segment_root = phase_root / "seg_001"
        mexc_path = segment_root / "ws_mexc_fixture.jsonl"
        gate_path = segment_root / "ws_gateio_fixture.jsonl"

        mexc_channels = [
            "spot@public.aggre.bookTicker.v3.api.pb@100ms@HYPEUSDT",
            "spot@public.aggre.deals.v3.api.pb@100ms@HYPEUSDT",
            "spot@public.limit.depth.v3.api.pb@HYPEUSDT@20",
        ]
        mexc_rows = [
            _control_row(
                "mexc",
                1000.0,
                {"method": "SUBSCRIPTION", "params": mexc_channels},
            )
        ]
        gate_rows = [
            _control_row(
                "gateio",
                1000.0,
                {
                    "time": 1000,
                    "channel": "spot.trades",
                    "event": "subscribe",
                    "payload": ["HYPE_USDT"],
                },
            ),
            _control_row(
                "gateio",
                1000.0,
                {
                    "time": 1000,
                    "channel": "spot.book_ticker",
                    "event": "subscribe",
                    "payload": ["HYPE_USDT"],
                },
            ),
            _control_row(
                "gateio",
                1000.0,
                {
                    "time": 1000,
                    "channel": "spot.order_book_update",
                    "event": "subscribe",
                    "payload": ["HYPE_USDT", "100ms"],
                },
            ),
        ]
        for ts in (1000.0 + 300.0 * index for index in range(13)):
            mexc_rows.extend(
                [
                    _mexc_row(ts, MEXC_BOOK_TICKER_B64),
                    _mexc_row(ts, MEXC_DEPTH_B64),
                ]
            )
            gate_rows.extend(
                [
                    _gate_row(
                        ts,
                        "spot.book_ticker",
                        {
                            "s": "HYPE_USDT",
                            "b": "72.7",
                            "B": "2",
                            "a": "72.8",
                            "A": "3",
                            "u": 1,
                        },
                    ),
                    _gate_row(
                        ts,
                        "spot.order_book_update",
                        {
                            "s": "HYPE_USDT",
                            "b": [["72.7", "2"]],
                            "a": [["72.8", "3"]],
                            "U": 1,
                            "u": 2,
                        },
                    ),
                ]
            )
        gate_rows.append(
            _gate_row(
                1001.0,
                "spot.trades",
                {
                    "currency_pair": "HYPE_USDT",
                    "id": 7,
                    "create_time_ms": "1001000",
                    "price": "72.75",
                    "amount": "1.5",
                    "side": "buy",
                },
            )
        )
        _write_jsonl(mexc_path, mexc_rows)
        _write_jsonl(gate_path, gate_rows)

        counters = {
            "transport_rows": len(mexc_rows) + len(gate_rows),
            "market_envelope_rows": 53,
            "normalized_events": 53,
            "control_rows": 4,
            "unclassified_messages": 0,
            "market_silence_events": 0,
            "reconnect_attempts": 0,
        }
        segment_manifest = {
            "completed": True,
            "duration_completed": True,
            "liveness_clean": True,
            "quality_eligible": True,
            "final": True,
            "requested_duration_sec": 3600,
            "actual_duration_sec": 3600.0,
            "segment_index": 1,
            "segment_started_epoch": 1000.0,
            "segment_finished_epoch": 4600.0,
            "total_events": counters["transport_rows"],
            **counters,
            "errors": {},
            "results": [
                {
                    "exchange": "mexc",
                    "symbols": ["HYPEUSDT"],
                    "output": str(mexc_path),
                    "events": len(mexc_rows),
                    "errors": [],
                    "completed": True,
                },
                {
                    "exchange": "gateio",
                    "symbols": ["HYPE_USDT"],
                    "output": str(gate_path),
                    "events": len(gate_rows),
                    "errors": [],
                    "completed": True,
                },
            ],
        }
        segment_manifest_path = segment_root / "manifest.json"
        _write_json(segment_manifest_path, segment_manifest)

        phase_manifest_path = phase_root / f"ws_collect_{run_id}.json"
        phase_manifest = {
            "schema": "ws_collect_stitched_v1",
            "run_id": run_id,
            "runtime_completed": True,
            "duration_completed": True,
            "liveness_clean": True,
            "quality_eligible": True,
            "dirty_segment_ids": [],
            "completed": True,
            "final": True,
            "coverage_ratio": 1.0,
            "requested_duration_sec": 3600,
            "actual_duration_sec": 3600.0,
            "total_events": counters["transport_rows"],
            **counters,
            "segments_total": 1,
            "segments_with_manifest": 1,
            "segments_incomplete": 0,
            "errors": [],
            "segments": [
                {
                    "segment_dir": "seg_001",
                    "has_manifest": True,
                    "completed": True,
                    "duration_completed": True,
                    "liveness_clean": True,
                    "quality_eligible": True,
                    "total_events": counters["transport_rows"],
                    "actual_duration_sec": 3600.0,
                    **counters,
                }
            ],
        }
        _write_json(phase_manifest_path, phase_manifest)

        symbol_plan_path = root / "_control" / "symbol-plan.json"
        symbol_plan = {
            "campaign_id": campaign_id,
            "plan_hash": plan_hash,
            "contract_hash": contract_hash,
            "universe_sha256": universe_hash,
            "symbols_by_exchange": {
                "mexc": ["HYPEUSDT"],
                "gateio": ["HYPE_USDT"],
            },
            "symbols_arg": "gateio:HYPE_USDT;mexc:HYPEUSDT",
        }
        _write_json(symbol_plan_path, symbol_plan)
        symbol_plan_sha = _sha(symbol_plan_path)

        contract = {
            "contract_hash": contract_hash,
            "source_candidate": {"candidate_contract_hash": candidate_hash},
            "universe_contract": {"source": {"sha256": universe_hash}},
            "raw_schema_contract": {
                "outer_fields_exact": [
                    "recv_ts",
                    "exchange",
                    "event_type",
                    "channel",
                    "symbol",
                    "payload",
                ],
                "field_contract": {
                    "exchange": ["mexc", "gateio"],
                    "payload": {
                        "encoding": ["json", "text", "base64"],
                        "json_or_text_fields": ["encoding", "data"],
                        "base64_fields": ["encoding", "byte_length", "data"],
                    },
                },
            },
            "segment_validity_contract": {
                "full_segment_sec": 3600,
                "terminal_partial_segment_min_sec": 900,
                "terminal_partial_counts_toward_min_valid_segments": False,
                "valid_segment_rules": {
                    "manifest_completed": True,
                    "manifest_final": True,
                    "actual_duration_ratio_min": 0.99,
                    "required_venues": ["mexc", "gateio"],
                    "result_errors_max": 0,
                    "raw_files_min_per_venue": 1,
                    "raw_rows_min": 53,
                    "json_parse_error_rate_max": 0.001,
                    "malformed_envelope_rate_max": 0.001,
                    "normalized_required_event_kinds": ["bbo", "depth", "trade"],
                    "market_max_gap_sec": 300,
                    "dual_venue_coverage_min": 0.8,
                    "out_of_order_rows_max": 0,
                },
                "campaign_minimums": {
                    "writer_duration_sec": 3600,
                    "valid_full_segments": 1,
                    "dual_venue_coverage": 0.8,
                    "eligible_execution_snapshots": 180,
                },
            },
        }
        plan = {
            "campaign_id": campaign_id,
            "plan_hash": plan_hash,
            "contract": {
                "contract_hash": contract_hash,
                "candidate_contract_hash": candidate_hash,
            },
            "outputs": {"campaign_root": str(root)},
            "phases": [
                {
                    "phase_id": phase_id,
                    "run_id": run_id,
                    "output_namespace": str(phase_root),
                    "writer_duration_sec": 3600,
                    "full_segments_planned": 1,
                    "terminal_partial_sec": 0,
                }
            ],
        }
        phase_result = {
            "phase_id": phase_id,
            "run_id": run_id,
            "status": "READY",
            "manifest_path": str(phase_manifest_path),
            "manifest_sha256": _sha(phase_manifest_path),
            "actual_duration_sec": 3600.0,
            "total_events": counters["transport_rows"],
            "symbol_plan_path": str(symbol_plan_path),
            "symbol_plan_sha256": symbol_plan_sha,
            "runtime_completed": True,
            "liveness_clean": True,
            "quality_eligible": True,
            "dirty_segment_ids": [],
            **counters,
        }
        campaign_manifest_path = root / "campaign-manifest.json"
        campaign_manifest = {
            "schema": "trading_mvp_dense_ws_campaign_manifest_v1",
            "campaign_id": campaign_id,
            "plan_hash": plan_hash,
            "contract_hash": contract_hash,
            "candidate_contract_hash": candidate_hash,
            "universe_sha256": universe_hash,
            "symbol_plan_path": str(symbol_plan_path),
            "symbol_plan_sha256": symbol_plan_sha,
            "phase_results": [phase_result],
            "phases_completed": 1,
            "writer_duration_requested_sec": 3600,
            "writer_duration_actual_sec": 3600.0,
            "total_events": counters["transport_rows"],
            "runtime_completed": True,
            "liveness_clean": True,
            "quality_eligible": True,
            "dirty_segment_ids": [],
            "completed": True,
            "final": True,
            **counters,
            "returns_read": False,
            "pnl_computed": False,
            "oos_read": False,
        }
        _write_json(campaign_manifest_path, campaign_manifest)
        return plan, contract, campaign_manifest_path, gate_path, mexc_path

    def _evaluate(self, root: Path) -> tuple[dict, dict, dict, Path, Path]:
        plan, contract, manifest, gate_path, mexc_path = self._fixture(root)
        result = quality.evaluate_validated_campaign_quality(
            plan=plan,
            contract=contract,
            campaign_manifest_path=manifest,
        )
        return result, plan, contract, gate_path, mexc_path

    def test_accepts_exact_300_second_gaps_without_opening_returns(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result, _, _, _, _ = self._evaluate(Path(temp_dir))

        self.assertTrue(result["accepted"], result)
        self.assertEqual(result["decision"], "DATA_READY_FOR_TRAIN_ONLY_REVIEW")
        self.assertFalse(result["safety"]["returns_read"])
        self.assertFalse(result["safety"]["pnl_computed"])

    def test_gap_above_300_seconds_rejects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan, contract, manifest, gate_path, _ = self._fixture(Path(temp_dir))
            rows = [json.loads(line) for line in gate_path.read_text(encoding="utf-8").splitlines()]
            first_bbo_after_start = next(
                row
                for row in rows
                if row["channel"] == "spot.book_ticker" and row["recv_ts"] == 1300.0
            )
            first_bbo_after_start["recv_ts"] = 1300.001
            _write_jsonl(gate_path, rows)
            result = quality.evaluate_validated_campaign_quality(
                plan=plan, contract=contract, campaign_manifest_path=manifest
            )

        self.assertIn("market_max_gap_sec", result["segments"][0]["reasons"])

    def test_missing_expected_market_rejects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan, contract, manifest, gate_path, _ = self._fixture(Path(temp_dir))
            rows = [json.loads(line) for line in gate_path.read_text(encoding="utf-8").splitlines()]
            rows = [
                row
                for row in rows
                if row.get("event_type") == "subscribe_sent"
                or row.get("channel") != "spot.order_book_update"
            ]
            _write_jsonl(gate_path, rows)
            result = quality.evaluate_validated_campaign_quality(
                plan=plan, contract=contract, campaign_manifest_path=manifest
            )

        self.assertIn(
            "missing_market:gateio:HYPE_USDT",
            result["segments"][0]["reasons"],
        )

    def test_missing_trade_subscription_rejects(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan, contract, manifest, _, mexc_path = self._fixture(Path(temp_dir))
            rows = [json.loads(line) for line in mexc_path.read_text(encoding="utf-8").splitlines()]
            rows[0]["payload"]["data"]["params"] = [
                channel
                for channel in rows[0]["payload"]["data"]["params"]
                if "aggre.deals" not in channel
            ]
            _write_jsonl(mexc_path, rows)
            result = quality.evaluate_validated_campaign_quality(
                plan=plan, contract=contract, campaign_manifest_path=manifest
            )

        self.assertIn(
            "missing_subscription:mexc:HYPEUSDT:trade",
            result["segments"][0]["reasons"],
        )

    def test_600_control_rows_do_not_satisfy_market_density(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan, contract, manifest, gate_path, _ = self._fixture(Path(temp_dir))
            contract["segment_validity_contract"]["valid_segment_rules"]["raw_rows_min"] = 600
            rows = [json.loads(line) for line in gate_path.read_text(encoding="utf-8").splitlines()]
            rows.extend(
                _control_row(
                    "gateio",
                    1000.0 + (index % 3600),
                    {"channel": "spot.ping", "event": "subscribe"},
                )
                for index in range(600)
            )
            _write_jsonl(gate_path, rows)
            result = quality.evaluate_validated_campaign_quality(
                plan=plan, contract=contract, campaign_manifest_path=manifest
            )

        self.assertIn("raw_rows_min", result["segments"][0]["reasons"])
        self.assertEqual(result["segments"][0]["metrics"]["market_envelope_rows"], 53)

    def test_missing_and_outside_segment_bounds_reject(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan, contract, manifest, gate_path, _ = self._fixture(root)
            segment_manifest_path = Path(plan["phases"][0]["output_namespace"]) / "seg_001" / "manifest.json"
            segment_manifest = json.loads(segment_manifest_path.read_text(encoding="utf-8"))
            segment_manifest.pop("segment_started_epoch")
            _write_json(segment_manifest_path, segment_manifest)
            missing = quality.evaluate_validated_campaign_quality(
                plan=plan, contract=contract, campaign_manifest_path=manifest
            )

            plan, contract, manifest, gate_path, _ = self._fixture(root / "second")
            rows = [json.loads(line) for line in gate_path.read_text(encoding="utf-8").splitlines()]
            rows[3]["recv_ts"] = 999.0
            _write_jsonl(gate_path, rows)
            outside = quality.evaluate_validated_campaign_quality(
                plan=plan, contract=contract, campaign_manifest_path=manifest
            )

        self.assertIn("segment_bounds_invalid", missing["segments"][0]["reasons"])
        self.assertIn("boundary_timestamp_rows", outside["segments"][0]["reasons"])

    def test_phase_manifest_hash_mismatch_is_integrity_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan, contract, campaign_manifest_path, _, _ = self._fixture(Path(temp_dir))
            phase = plan["phases"][0]
            phase_manifest = Path(phase["output_namespace"]) / f"ws_collect_{phase['run_id']}.json"
            phase_manifest.write_text(
                phase_manifest.read_text(encoding="utf-8") + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(quality.CampaignQualityIntegrityError):
                quality.evaluate_validated_campaign_quality(
                    plan=plan,
                    contract=contract,
                    campaign_manifest_path=campaign_manifest_path,
                )

    def test_incomplete_campaign_stops_before_reading_raw_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            plan, contract, campaign_manifest_path, gate_path, _ = self._fixture(Path(temp_dir))
            campaign_manifest = json.loads(campaign_manifest_path.read_text(encoding="utf-8"))
            campaign_manifest["runtime_completed"] = False
            campaign_manifest["completed"] = False
            campaign_manifest["final"] = False
            campaign_manifest["phases_completed"] = 0
            campaign_manifest["phase_results"][0]["status"] = "STOPPED_INCOMPLETE"
            _write_json(campaign_manifest_path, campaign_manifest)
            gate_path.unlink()

            result = quality.evaluate_validated_campaign_quality(
                plan=plan,
                contract=contract,
                campaign_manifest_path=campaign_manifest_path,
            )

        self.assertEqual(result["decision"], "STOPPED_INCOMPLETE")
        self.assertEqual(result["segments"], [])


if __name__ == "__main__":
    unittest.main()
