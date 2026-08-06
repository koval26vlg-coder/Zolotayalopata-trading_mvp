from __future__ import annotations

import base64
import hashlib
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from dense_ws_campaign_contract import (  # noqa: E402
    _frozen_execution_contract,
    _frozen_regime_contract,
)
from dense_ws_causal_materializer import (  # noqa: E402
    CausalMaterializer,
    CausalMaterializationIntegrityError,
    CausalMaterializationRuntimeError,
    _publish_immutable_outputs,
    materialize_normalized_bbo_events,
    run_causal_materialization,
)


MEXC_BOOK_TICKER_B64 = (
    "CjVzcG90QHB1YmxpYy5hZ2dyZS5ib29rVGlja2VyLnYzLmFwaS5wYkAxMDBtc0BIWVBFVVNEVBoI"
    "SFlQRVVTRFQw+t6t8+gz2hMtCgU3Mi4yORIENy4wMRoFNzIuMzQiBDgyLjEqCjEzMjAwNDMzNTYw"
    "yt6t8+gz"
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _result_hash(payload: dict) -> str:
    body = {
        key: value
        for key, value in payload.items()
        if key != "deterministic_result_hash"
    }
    canonical = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )


def _raw_mexc_row(ts: float) -> dict:
    raw = base64.b64decode(MEXC_BOOK_TICKER_B64).replace(b"72.34", b"72.30")
    encoded = base64.b64encode(raw).decode("ascii")
    return {
        "recv_ts": ts,
        "exchange": "mexc",
        "event_type": "protobuf",
        "channel": None,
        "symbol": None,
        "payload": {
            "encoding": "base64",
            "byte_length": len(raw),
            "data": encoded,
        },
    }


def _raw_gate_row(ts: float) -> dict:
    return {
        "recv_ts": ts,
        "exchange": "gateio",
        "event_type": "message",
        "channel": "spot.book_ticker",
        "symbol": "HYPE_USDT",
        "payload": {
            "encoding": "json",
            "data": {
                "time_ms": int(ts * 1_000),
                "channel": "spot.book_ticker",
                "event": "update",
                "result": {
                    "s": "HYPE_USDT",
                    "b": "72.29",
                    "B": "7.01",
                    "a": "72.30",
                    "A": "82.1",
                    "u": int(ts),
                },
            },
        },
    }


def _file_materialization_fixture(
    root: Path,
) -> tuple[dict, dict, Path, Path, Path, Path]:
    campaign_root = root / "campaign"
    segment_root = campaign_root / "phase_01" / "seg_001"
    mexc_path = segment_root / "ws_mexc.jsonl"
    gate_path = segment_root / "ws_gateio.jsonl"
    timestamps = [float(value) for value in range(0, 3_901, 5)]
    _write_jsonl(mexc_path, [_raw_mexc_row(ts) for ts in timestamps])
    _write_jsonl(gate_path, [_raw_gate_row(ts) for ts in timestamps])

    segment_manifest_path = segment_root / "manifest.json"
    _write_json(
        segment_manifest_path,
        {
            "completed": True,
            "final": True,
            "segment_started_epoch": 0.0,
            "segment_finished_epoch": 3_900.0,
            "total_events": len(timestamps) * 2,
        },
    )
    plan = {
        "campaign_id": "dense_ws_materializer_fixture",
        "plan_hash": "c" * 64,
        "contract": {"candidate_contract_hash": "a" * 64},
        "outputs": {"campaign_root": str(campaign_root.resolve())},
    }
    contract = {
        "contract_hash": "b" * 64,
        "causal_regime_contract": _frozen_regime_contract(),
        "execution_sampling_contract": _frozen_execution_contract(),
        "segment_validity_contract": {
            "campaign_minimums": {"eligible_execution_snapshots": 60}
        },
    }
    quality_path = campaign_root / "quality-report.json"
    quality = {
        "schema": "trading_mvp_dense_ws_campaign_quality_v1",
        "campaign_id": plan["campaign_id"],
        "plan_hash": plan["plan_hash"],
        "contract_hash": contract["contract_hash"],
        "accepted": True,
        "decision": "DATA_READY_FOR_TRAIN_ONLY_REVIEW",
        "segments": [
            {
                "segment_dir": "seg_001",
                "valid": True,
                "manifest": {
                    "path": str(segment_manifest_path.resolve()),
                    "sha256": _sha(segment_manifest_path),
                },
                "raw_files": [
                    {"path": str(mexc_path.resolve()), "sha256": _sha(mexc_path)},
                    {"path": str(gate_path.resolve()), "sha256": _sha(gate_path)},
                ],
                "metrics": {
                    "bases_by_venue": {
                        "mexc": ["HYPE"],
                        "gateio": ["HYPE"],
                    }
                },
            }
        ],
        "safety": {
            "network_access": False,
            "returns_read": False,
            "pnl_computed": False,
            "oos_read": False,
            "grid_or_retune": False,
            "paper_forward": False,
            "live_orders": False,
            "private_api_keys": False,
            "real_capital": False,
            "leverage_or_margin": False,
        },
    }
    quality["deterministic_result_hash"] = _result_hash(quality)
    _write_json(quality_path, quality)
    return (
        plan,
        contract,
        quality_path,
        campaign_root / "regime-labels.jsonl",
        campaign_root / "execution-snapshots.jsonl",
        campaign_root / "causal-materialization.json",
    )


def _bbo(ts: float, venue: str, *, qty_step: int = 0) -> dict:
    symbol = "HYPEUSDT" if venue == "mexc" else "HYPE_USDT"
    return {
        "recv_ts": ts,
        "exchange": venue,
        "symbol": symbol,
        "event_kind": "bbo",
        "bid_price": 100.0,
        "bid_qty": 101.0 + qty_step,
        "ask_price": 100.01,
        "ask_qty": 100.0,
    }


def _dense_events(end_ts: int) -> list[dict]:
    rows: list[dict] = []
    for ts in range(0, end_ts + 1, 5):
        step = (ts // 5) % 2
        rows.append(_bbo(float(ts), "mexc", qty_step=step))
        rows.append(_bbo(float(ts), "gateio", qty_step=step))
    return sorted(rows, key=lambda row: (row["recv_ts"], row["exchange"]))


class DenseWsCausalMaterializerTests(unittest.TestCase):
    def test_materializes_causal_dense_labels_and_execution_snapshots(self) -> None:
        result = materialize_normalized_bbo_events(
            _dense_events(3_900),
            bases=["HYPE"],
            start_ts=0.0,
            end_ts=3_900.0,
            regime_contract=_frozen_regime_contract(),
            execution_contract=_frozen_execution_contract(),
        )

        dense_labels = [
            row for row in result["labels"] if row["label"] == "DENSE_BOTH"
        ]
        self.assertTrue(dense_labels)
        self.assertGreaterEqual(len(result["snapshots"]), 60)
        self.assertTrue(
            all(row["regime_label"] == "DENSE_BOTH" for row in result["snapshots"])
        )
        first_dense = dense_labels[0]
        self.assertEqual(first_dense["label_ts"], 3_600)
        self.assertEqual(
            first_dense["venues"]["mexc"]["reference_observations"],
            720,
        )

    def test_stale_venue_cannot_create_dense_snapshot(self) -> None:
        rows: list[dict] = []
        for ts in range(0, 3_901, 5):
            rows.append(_bbo(float(ts), "mexc", qty_step=(ts // 5) % 2))
            if ts % 20 == 0:
                rows.append(_bbo(float(ts), "gateio", qty_step=(ts // 20) % 2))
        rows.sort(key=lambda row: (row["recv_ts"], row["exchange"]))

        result = materialize_normalized_bbo_events(
            rows,
            bases=["HYPE"],
            start_ts=0.0,
            end_ts=3_900.0,
            regime_contract=_frozen_regime_contract(),
            execution_contract=_frozen_execution_contract(),
        )

        post_warmup = [row for row in result["labels"] if row["label_ts"] >= 3_600]
        self.assertTrue(post_warmup)
        self.assertTrue(
            all(row["label"] == "STALE_OR_INCOMPLETE" for row in post_warmup)
        )
        self.assertEqual(result["snapshots"], [])

    def test_out_of_order_bbo_stream_fails_closed(self) -> None:
        rows = [
            _bbo(5.0, "mexc"),
            _bbo(5.0, "gateio"),
            _bbo(4.0, "mexc"),
        ]
        with self.assertRaisesRegex(
            CausalMaterializationIntegrityError,
            "globally ordered",
        ):
            materialize_normalized_bbo_events(
                rows,
                bases=["HYPE"],
                start_ts=0.0,
                end_ts=10.0,
                regime_contract=_frozen_regime_contract(),
                execution_contract=_frozen_execution_contract(),
            )

    def test_consumes_causal_tail_between_grid_boundary_and_segment_end(self) -> None:
        engine = CausalMaterializer(
            bases=["HYPE"],
            regime_contract=_frozen_regime_contract(),
            execution_contract=_frozen_execution_contract(),
        )
        events = [
            _bbo(0.0, "mexc"),
            _bbo(0.0, "gateio"),
            _bbo(4.0, "mexc", qty_step=1),
            _bbo(4.0, "gateio", qty_step=1),
        ]

        engine.process_segment(
            events,
            start_ts=0.0,
            end_ts=4.5,
            label_sink=lambda _row: None,
            snapshot_sink=lambda _row: None,
        )

        self.assertEqual(engine.last_event_ts, 4.0)

    def test_streams_hash_bound_raw_jsonl_to_immutable_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (
                plan,
                contract,
                quality_path,
                labels_path,
                snapshots_path,
                manifest_path,
            ) = _file_materialization_fixture(Path(temp_dir))

            result = run_causal_materialization(
                plan=plan,
                contract=contract,
                quality_report_path=quality_path,
                labels_output_path=labels_path,
                snapshots_output_path=snapshots_path,
                manifest_output_path=manifest_path,
                max_runtime_sec=30,
            )

            persisted = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(persisted, result)
            self.assertTrue(result["accepted"], result)
            self.assertEqual(
                result["decision"],
                "DATA_READY_FOR_SIGNAL_CONTRACT_REVIEW",
            )
            self.assertGreaterEqual(result["execution_snapshots"]["rows"], 60)
            self.assertEqual(result["labels"]["sha256"], _sha(labels_path))
            self.assertEqual(
                result["execution_snapshots"]["sha256"],
                _sha(snapshots_path),
            )
            self.assertEqual(result["runtime"]["max_runtime_sec"], 30)
            self.assertEqual(
                result["deterministic_result_hash"],
                _result_hash(result),
            )
            self.assertEqual(list(Path(temp_dir).rglob("*.tmp.*")), [])

    def test_incomplete_quality_stops_before_reading_raw_or_creating_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (
                plan,
                contract,
                quality_path,
                labels_path,
                snapshots_path,
                manifest_path,
            ) = _file_materialization_fixture(Path(temp_dir))
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            quality["accepted"] = False
            quality["decision"] = "STOPPED_INCOMPLETE"
            quality["deterministic_result_hash"] = _result_hash(quality)
            _write_json(quality_path, quality)
            for segment in quality["segments"]:
                for raw_file in segment["raw_files"]:
                    Path(raw_file["path"]).unlink()

            with self.assertRaisesRegex(
                CausalMaterializationIntegrityError,
                "quality.accepted",
            ):
                run_causal_materialization(
                    plan=plan,
                    contract=contract,
                    quality_report_path=quality_path,
                    labels_output_path=labels_path,
                    snapshots_output_path=snapshots_path,
                    manifest_output_path=manifest_path,
                    max_runtime_sec=30,
                )

            self.assertFalse(labels_path.exists())
            self.assertFalse(snapshots_path.exists())
            self.assertFalse(manifest_path.exists())
            self.assertEqual(list(Path(temp_dir).rglob("*.tmp.*")), [])

    def test_partial_immutable_publish_rolls_back_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            temporary = tuple(root / f"item-{index}.tmp" for index in range(3))
            targets = tuple(root / f"item-{index}.out" for index in range(3))
            for index, path in enumerate(temporary):
                path.write_text(f"new-{index}", encoding="utf-8")
            targets[1].write_text("pre-existing", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                _publish_immutable_outputs(tuple(zip(temporary, targets)))

            self.assertFalse(targets[0].exists())
            self.assertEqual(targets[1].read_text(encoding="utf-8"), "pre-existing")
            self.assertFalse(targets[2].exists())
            self.assertTrue(all(not path.exists() for path in temporary))

    def test_expired_deadline_fails_before_creating_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            (
                plan,
                contract,
                quality_path,
                labels_path,
                snapshots_path,
                manifest_path,
            ) = _file_materialization_fixture(Path(temp_dir))

            with self.assertRaises(CausalMaterializationRuntimeError):
                run_causal_materialization(
                    plan=plan,
                    contract=contract,
                    quality_report_path=quality_path,
                    labels_output_path=labels_path,
                    snapshots_output_path=snapshots_path,
                    manifest_output_path=manifest_path,
                    max_runtime_sec=30,
                    _deadline_monotonic=0.0,
                )

            self.assertFalse(labels_path.exists())
            self.assertFalse(snapshots_path.exists())
            self.assertFalse(manifest_path.exists())

    def test_rehashed_quality_cannot_escape_campaign_raw_namespace(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (
                plan,
                contract,
                quality_path,
                labels_path,
                snapshots_path,
                manifest_path,
            ) = _file_materialization_fixture(root)
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            original = Path(quality["segments"][0]["raw_files"][0]["path"])
            outside = root / "outside-campaign.jsonl"
            shutil.copyfile(original, outside)
            quality["segments"][0]["raw_files"][0]["path"] = str(outside)
            quality["deterministic_result_hash"] = _result_hash(quality)
            _write_json(quality_path, quality)

            with self.assertRaisesRegex(
                CausalMaterializationIntegrityError,
                "raw file escapes campaign root",
            ):
                run_causal_materialization(
                    plan=plan,
                    contract=contract,
                    quality_report_path=quality_path,
                    labels_output_path=labels_path,
                    snapshots_output_path=snapshots_path,
                    manifest_output_path=manifest_path,
                    max_runtime_sec=30,
                )

            self.assertFalse(labels_path.exists())
            self.assertFalse(snapshots_path.exists())
            self.assertFalse(manifest_path.exists())


if __name__ == "__main__":
    unittest.main()
