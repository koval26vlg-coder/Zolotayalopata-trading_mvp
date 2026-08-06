from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from funding import FundingContract, FundingSnapshot  # noqa: E402
from pit_cross_venue_forward_probe import (  # noqa: E402
    ForwardProbeConfig,
    _depth_fill,
    evaluate_pair_evidence,
    run_forward_probe,
)


def _venue(exchange: str, *, index_price: float = 100.0, exchange_ts: float = 1_700_000_000.0) -> dict:
    return {
        "exchange": exchange,
        "symbol": "HYPE_USDT",
        "base": "HYPE",
        "quote": "USDT",
        "status": "trading",
        "contract_size": 0.1,
        "contract_type": "linear_perp",
        "metadata_hash": "a" * 64,
        "metadata_snapshot_ts": exchange_ts,
        "request_started_ts": exchange_ts + 0.1,
        "recv_ts": exchange_ts + 0.5,
        "exchange_ts": exchange_ts,
        "bid_price": 99.9,
        "bid_qty": 10.0,
        "ask_price": 100.1,
        "ask_qty": 10.0,
        "bids": [[99.9, 10.0]],
        "asks": [[100.1, 10.0]],
        "mark_price": 100.0,
        "index_price": index_price,
        "funding_rate": 0.0001,
        "funding_interval_sec": 28_800,
        "next_funding_ts": exchange_ts + 28_800,
        "maker_fee_rate": 0.0002,
        "taker_fee_rate": 0.0006,
        "error": None,
    }


class _FakeFundingClient:
    def __init__(self, exchange: str, contract: FundingContract, snapshot: FundingSnapshot) -> None:
        self.exchange_id = exchange
        self.contract = contract
        self.snapshot = snapshot

    def fetch_contracts(self) -> list[FundingContract]:
        return [self.contract]

    def fetch_snapshot(self, symbol: str) -> FundingSnapshot:
        if symbol != self.contract.symbol:
            raise KeyError(symbol)
        return self.snapshot


class _FakeRestClient:
    def __init__(self, exchange: str, depth: dict) -> None:
        self.exchange_id = exchange
        self.depth = depth

    def fetch_depth(self, contract: FundingContract, depth_limit: int) -> dict:
        return self.depth

    def normalized_depth(self, contract: FundingContract, depth: dict):
        return depth["bids"], depth["asks"], depth["ts"], depth.get("version")


def _contract(exchange: str) -> FundingContract:
    raw = {
        "contractSize": "0.1",
        "quoteCoin": "USDT",
        "settleCoin": "USDT",
        "state": 0,
    }
    if exchange == "gateio":
        raw = {
            "quanto_multiplier": "0.1",
            "type": "direct",
            "status": "trading",
            "settle": "usdt",
        }
    return FundingContract(
        exchange=exchange,
        symbol="HYPE_USDT",
        base="HYPE",
        quote="USDT",
        status="trading",
        maker_fee_rate=0.0002,
        taker_fee_rate=0.0006,
        raw=raw,
    )


def _snapshot(exchange: str) -> FundingSnapshot:
    return FundingSnapshot(
        exchange=exchange,
        symbol="HYPE_USDT",
        base="HYPE",
        quote="USDT",
        ts=1_700_000_000.0,
        funding_rate=0.0001,
        next_funding_ts=1_700_028_800.0,
        funding_interval_sec=28_800,
        mark_price=100.0,
        index_price=100.0,
        perp_bid=99.9,
        perp_ask=100.1,
        maker_fee_rate=0.0002,
        taker_fee_rate=0.0006,
    )


class PitCrossVenueForwardProbeTests(unittest.TestCase):
    def test_depth_fill_requires_target_notional(self) -> None:
        fill = _depth_fill([[100.0, 0.4], [101.0, 0.7]], target_notional_quote=100.0)

        self.assertTrue(fill["complete"])
        self.assertAlmostEqual(fill["filled_base_qty"], 0.4 + (60.0 / 101.0))
        self.assertAlmostEqual(fill["filled_quote_notional"], 100.0)
        self.assertAlmostEqual(fill["vwap"], 100.0 / (0.4 + (60.0 / 101.0)))

    def test_pair_evidence_accepts_complete_synchronous_pair(self) -> None:
        cfg = ForwardProbeConfig(
            target_notional_quote=100.0,
            max_index_divergence_bps=100.0,
            max_mark_index_divergence_bps=200.0,
            max_quote_age_sec=5.0,
            max_cross_venue_skew_sec=2.0,
            min_provisional_identity_pairs=1,
            min_fully_valid_pairs=1,
        )

        result = evaluate_pair_evidence("HYPE", _venue("mexc"), _venue("gateio", exchange_ts=1_700_000_001.0), cfg)

        self.assertTrue(result["provisional_identity_match"])
        self.assertTrue(result["fully_valid"])
        self.assertEqual(result["invalid_reasons"], [])

    def test_pair_evidence_rejects_symbol_collision_by_index_parity(self) -> None:
        cfg = ForwardProbeConfig(min_provisional_identity_pairs=1, min_fully_valid_pairs=1)

        result = evaluate_pair_evidence("HYPE", _venue("mexc", index_price=0.001), _venue("gateio", index_price=100.0), cfg)

        self.assertFalse(result["provisional_identity_match"])
        self.assertFalse(result["fully_valid"])
        self.assertIn("index_price_divergence", result["identity_reasons"])

    def test_run_probe_binds_discovery_universe_and_stays_research_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            availability = root / "availability.json"
            output = root / "probe.json"
            availability.write_text(
                json.dumps(
                    {
                        "schema": "pit_linear_perp_cross_venue_availability_preflight_v1",
                        "mode": "pit_linear_perp_cross_venue_availability_preflight_planonly",
                        "decision": "PIT_LINEAR_PERP_CURRENT_DATASET_REJECTED_FOR_EDGE_VALIDATION_MISSING_HISTORICAL_EVIDENCE",
                        "historical_retrofit_possible": False,
                        "raw_observations": {"events": 10, "bases": ["HYPE"]},
                        "source": {"run_id": "discovery-run", "mask_sha256": "b" * 64},
                    }
                ),
                encoding="utf-8",
            )
            clients = {
                exchange: _FakeFundingClient(exchange, _contract(exchange), _snapshot(exchange))
                for exchange in ("mexc", "gateio")
            }
            rest_clients = {
                exchange: _FakeRestClient(
                    exchange,
                    {
                        "bids": [[99.9, 10.0]],
                        "asks": [[100.1, 10.0]],
                        "ts": 1_700_000_000.0,
                        "version": 1,
                    },
                )
                for exchange in ("mexc", "gateio")
            }
            cfg = ForwardProbeConfig(
                target_notional_quote=100.0,
                min_provisional_identity_pairs=1,
                min_fully_valid_pairs=1,
                progress=False,
            )

            report = run_forward_probe(
                availability_path=availability,
                output_path=output,
                config=cfg,
                funding_clients=clients,
                rest_clients=rest_clients,
                now_fn=lambda: 1_700_000_000.5,
            )

            self.assertEqual(report["decision"], "PIT_LINEAR_PERP_FORWARD_PROBE_ACCEPTED_READY_FOR_OOS_APPROVAL_PACKET")
            self.assertEqual(report["discovery_universe"]["bases"], ["HYPE"])
            self.assertEqual(report["summary"]["fully_valid_pairs"], 1)
            self.assertFalse(report["strategy_accepted"])
            self.assertFalse(report["collect_started"])
            self.assertFalse(report["replay_allowed"])
            self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
