from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import paper_public_reader as public_reader  # noqa: E402
import paper_public_reader_contract as contract_module  # noqa: E402
import paper_public_readonly_probe as probe_module  # noqa: E402


def _build_contract(root: Path) -> dict:
    funding = root / "funding.py"
    observer = root / "observer.py"
    evidence = root / "evidence.json"
    funding.write_text("fixture", encoding="utf-8")
    observer.write_text("fixture", encoding="utf-8")
    evidence.write_text(
        json.dumps(
            {
                "schema": "trading_mvp_venue_api_reliability_evidence_v1",
                "scope": {
                    "venues": ["mexc", "gateio"],
                    "private_api_keys": False,
                    "live_orders": False,
                },
                "historical_rest_collect": {"completion_rate": 1.0},
                "pit_snapshot_collect": {
                    "aggregate": {"dual_venue_success_rate": 1.0}
                },
                "verdict": (
                    "RESEARCH_DATA_PATH_RELIABLE_WITH_GUARDS_"
                    "PRODUCTION_SLA_UNPROVEN"
                ),
            }
        ),
        encoding="utf-8",
    )
    return contract_module.build_public_reader_contract(
        funding_client_path=funding,
        observer_runtime_path=observer,
        reliability_evidence_path=evidence,
        generated_at_utc="2026-07-30T12:00:00+00:00",
    )


def _write_fixture_plan(root: Path) -> tuple[Path, dict]:
    contract_path = root / "contract.json"
    contract_path.write_text(
        json.dumps(_build_contract(root), indent=2) + "\n",
        encoding="utf-8",
    )
    plan = public_reader.build_public_readonly_probe_plan(
        contract_path=contract_path,
        generated_at_utc="2026-07-30T12:01:00+00:00",
    )
    plan["probe"]["output_namespace"] = str((root / "runs").resolve())
    deterministic = {
        key: value
        for key, value in plan.items()
        if key not in {"plan_hash_sha256", "generated_at_utc"}
    }
    plan["plan_hash_sha256"] = contract_module.sha256_json(deterministic)
    plan_path = root / "plan.json"
    plan_path.write_text(
        json.dumps(plan, indent=2) + "\n",
        encoding="utf-8",
    )
    return plan_path, plan


def _migration_files(root: Path) -> tuple[Path, Path]:
    depth_reference = root / "pit_universe_public_probe.py"
    depth_reference.write_text(
        "def parse_mexc_depth_l1(payload):\n"
        "    return payload\n",
        encoding="utf-8",
    )
    errors_path = root / "migration-errors.jsonl"
    errors_path.write_text(
        json.dumps(
            {
                "venue": "mexc",
                "category": "schema_mismatch",
                "endpoint_id": "mexc_tickers",
                "detail": "missing bid1 and ask1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    deterministic = {
        "schema": "trading_mvp_paper_public_readonly_probe_result_v1",
        "run_id": "paper_public_readonly_probe_20260730_142851",
        "status": "STOPPED_INCOMPLETE",
        "final": False,
        "plan": {
            "plan_hash_sha256": (
                "318c6dbd76777cc4cff8f8e4e0ec67df"
                "10b497b33709155c642d2476285527ff"
            )
        },
        "quality": {"hard_stop_reason": "schema_mismatch"},
        "artifacts": {
            "errors_path": str(errors_path.resolve()),
            "errors_file_sha256": contract_module.sha256_file(errors_path),
        },
        "safety": {
            "public_get_only": True,
            "returns_or_pnl_read": False,
            "signals_read": False,
            "oms_mutations": 0,
            "private_api_keys": False,
            "live_orders": False,
            "leverage_or_margin": False,
            "grid_or_retune": False,
            "hypothesis_changed": False,
        },
    }
    manifest_path = root / "migration-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                **deterministic,
                "deterministic_result_hash": contract_module.sha256_json(
                    deterministic
                ),
                "started_at_utc": "2026-07-30T11:28:51+00:00",
                "completed_at_utc": "2026-07-30T11:28:52+00:00",
            }
        ),
        encoding="utf-8",
    )
    return manifest_path, depth_reference


def _write_fixture_plan_v2(root: Path) -> tuple[Path, dict]:
    funding = root / "funding-v2.py"
    observer = root / "observer-v2.py"
    evidence = root / "evidence-v2.json"
    funding.write_text("fixture", encoding="utf-8")
    observer.write_text("fixture", encoding="utf-8")
    evidence.write_text(
        json.dumps(
            {
                "schema": "trading_mvp_venue_api_reliability_evidence_v1",
                "scope": {
                    "venues": ["mexc", "gateio"],
                    "private_api_keys": False,
                    "live_orders": False,
                },
                "historical_rest_collect": {"completion_rate": 1.0},
                "pit_snapshot_collect": {
                    "aggregate": {"dual_venue_success_rate": 1.0}
                },
                "verdict": "FIXTURE_RELIABLE_PRODUCTION_SLA_UNPROVEN",
            }
        ),
        encoding="utf-8",
    )
    migration, depth_reference = _migration_files(root)
    contract = contract_module.build_public_reader_contract(
        funding_client_path=funding,
        observer_runtime_path=observer,
        reliability_evidence_path=evidence,
        contract_version="v2",
        migration_probe_manifest_path=migration,
        depth_reference_path=depth_reference,
        generated_at_utc="2026-07-30T15:01:00+00:00",
    )
    contract_path = root / "contract-v2.json"
    contract_path.write_text(
        json.dumps(contract, indent=2) + "\n",
        encoding="utf-8",
    )
    plan = public_reader.build_public_readonly_probe_plan(
        contract_path=contract_path,
        generated_at_utc="2026-07-30T15:02:00+00:00",
    )
    plan["probe"]["output_namespace"] = str((root / "runs-v2").resolve())
    deterministic = {
        key: value
        for key, value in plan.items()
        if key not in {"plan_hash_sha256", "generated_at_utc"}
    }
    plan["plan_hash_sha256"] = contract_module.sha256_json(deterministic)
    plan_path = root / "plan-v2.json"
    plan_path.write_text(
        json.dumps(plan, indent=2) + "\n",
        encoding="utf-8",
    )
    return plan_path, plan


def _write_fixture_plan_v3(
    root: Path,
) -> tuple[Path, dict, Path]:
    plan_v2_path, plan_v2 = _write_fixture_plan_v2(root)
    contract_v2_path = Path(plan_v2["contract"]["path"])
    errors_path = root / "v2-stale-errors.jsonl"
    errors = [
        {
            "cycle_index": 7,
            "venue": "mexc",
            "category": "stale_quote",
            "endpoint_id": "mexc_tickers",
            "detail": "quote age 5323ms exceeds 5000ms",
        },
        {
            "cycle_index": 19,
            "venue": "mexc",
            "category": "stale_quote",
            "endpoint_id": "mexc_tickers",
            "detail": "quote age 5396ms exceeds 5000ms",
        },
    ]
    errors_path.write_text(
        "".join(json.dumps(row) + "\n" for row in errors),
        encoding="utf-8",
    )
    safety = {
        "public_get_only": True,
        "returns_or_pnl_read": False,
        "signals_read": False,
        "oms_mutations": 0,
        "private_api_keys": False,
        "live_orders": False,
        "leverage_or_margin": False,
        "grid_or_retune": False,
        "hypothesis_changed": False,
    }
    quality = {
        "expected_snapshot_count": 48,
        "snapshot_count": 46,
        "error_count": 2,
        "partial_output": True,
        "hard_stop_reason": None,
        "planned_endpoint_reads": 192,
        "network_requests": 192,
        "retry_count": 0,
    }
    deterministic = {
        "schema": "trading_mvp_paper_public_readonly_probe_result_v2",
        "run_id": "fixture-v2-stale",
        "status": "STOPPED_INCOMPLETE",
        "final": False,
        "verdict": "PUBLIC_READONLY_PROBE_STOPPED_INCOMPLETE",
        "plan": {
            "path": str(plan_v2_path.resolve()),
            "file_sha256": contract_module.sha256_file(plan_v2_path),
            "plan_hash_sha256": plan_v2["plan_hash_sha256"],
        },
        "contract": {
            "path": str(contract_v2_path.resolve()),
            "file_sha256": contract_module.sha256_file(contract_v2_path),
            "contract_hash_sha256": plan_v2["contract"][
                "contract_hash_sha256"
            ],
        },
        "quality": quality,
        "artifacts": {
            "errors_path": str(errors_path.resolve()),
            "errors_file_sha256": contract_module.sha256_file(errors_path),
        },
        "safety": safety,
    }
    manifest = {
        **deterministic,
        "deterministic_result_hash": contract_module.sha256_json(
            deterministic
        ),
        "started_at_utc": "2026-07-30T14:58:19+00:00",
        "completed_at_utc": "2026-07-30T15:00:17+00:00",
    }
    manifest_path = root / "v2-stale-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    audit = {
        "schema": "trading_mvp_public_readonly_probe_failure_audit_v1",
        "status": "USER_REVIEW_REQUIRED",
        "run_id": manifest["run_id"],
        "plan": {
            "plan_hash_sha256": plan_v2["plan_hash_sha256"],
        },
        "result": {
            "path": str(manifest_path.resolve()),
            "file_sha256": contract_module.sha256_file(manifest_path),
            "deterministic_result_hash": manifest[
                "deterministic_result_hash"
            ],
        },
        "quality": {
            "expected_snapshot_count": 48,
            "snapshot_count": 46,
            "error_count": 2,
            "planned_endpoint_reads": 192,
            "network_requests": 192,
            "retry_count": 0,
        },
        "failure": {
            "category": "stale_quote",
            "venue": "mexc",
            "endpoint_id": "mexc_tickers",
            "frozen_max_quote_age_ms": 5000,
            "observed_rejected_quote_ages_ms": [5323, 5396],
        },
        "safety": safety,
        "critical_checkpoint": {
            "recommended_option": (
                "contract_v3_mexc_max_quote_age_ms_6000_"
                "gateio_5000_one_new_visible_bounded_probe"
            )
        },
    }
    audit_path = root / "v2-stale-audit.json"
    audit_path.write_text(
        json.dumps(audit, indent=2) + "\n",
        encoding="utf-8",
    )
    contract_v3 = contract_module.build_public_reader_contract(
        funding_client_path=root / "funding-v2.py",
        observer_runtime_path=root / "observer-v2.py",
        reliability_evidence_path=root / "evidence-v2.json",
        contract_version="v3",
        prior_contract_path=contract_v2_path,
        freshness_failure_audit_path=audit_path,
        generated_at_utc="2026-07-30T15:10:00+00:00",
    )
    contract_v3_path = root / "contract-v3.json"
    contract_v3_path.write_text(
        json.dumps(contract_v3, indent=2) + "\n",
        encoding="utf-8",
    )
    plan_v3 = public_reader.build_public_readonly_probe_plan(
        contract_path=contract_v3_path,
        generated_at_utc="2026-07-30T15:11:00+00:00",
    )
    plan_v3["probe"]["output_namespace"] = str(
        (root / "runs-v3").resolve()
    )
    plan_deterministic = {
        key: value
        for key, value in plan_v3.items()
        if key not in {"plan_hash_sha256", "generated_at_utc"}
    }
    plan_v3["plan_hash_sha256"] = contract_module.sha256_json(
        plan_deterministic
    )
    plan_v3_path = root / "plan-v3.json"
    plan_v3_path.write_text(
        json.dumps(plan_v3, indent=2) + "\n",
        encoding="utf-8",
    )
    return plan_v3_path, plan_v3, audit_path


def _write_policy(root: Path) -> Path:
    policy = {
        "schema": "trading_mvp_autopilot_policy_v1",
        "policy_id": "fixture-policy",
        "thread_id": "fixture-thread",
        "project": "trading_mvp",
        "mode": "research_and_paper_only",
        "routine_actions_without_user_confirmation": [
            probe_module.STANDING_ROUTINE_ACTION
        ],
        "critical_user_checkpoints": [
            "materially new or changed hypothesis",
            "venue, universe, signal, cost, risk or acceptance-contract change",
            "historical or paper terminal verdict",
            "irreversible data-integrity or safety conflict",
            "live orders or private API",
        ],
        "run_policy": {
            "visible_terminal_for_writers": True,
            "single_market_data_writer": True,
            "grid_and_retune_forbidden": True,
        },
    }
    path = root / "policy.json"
    path.write_text(json.dumps(policy, indent=2) + "\n", encoding="utf-8")
    return path


class ManualClock:
    def __init__(self) -> None:
        self.seconds = 0.0
        self.base_ms = 1_800_000_000_000

    def monotonic(self) -> float:
        return self.seconds

    def sleep(self, seconds: float) -> None:
        self.seconds += float(seconds)

    def wall_time_ms(self) -> int:
        return self.base_ms + int(self.seconds * 1000)

    def utc_now(self) -> str:
        return f"2026-07-30T12:00:{int(self.seconds) % 60:02d}+00:00"


class FakeTransport:
    def __init__(self) -> None:
        self.network_requests = 0


class FakeReader:
    def __init__(self, venue: str, *, fail: bool = False) -> None:
        self.venue = venue
        self.fail = fail
        self.transport = FakeTransport()
        self.retry_trace: list[dict] = []
        self.rate_limit_trace: list[dict] = []
        self.maximum_quote_ages_ms: list[int] = []

    def read_market_snapshot(self, **kwargs: object) -> dict:
        self.maximum_quote_ages_ms.append(
            int(kwargs["maximum_quote_age_ms"])
        )
        self.transport.network_requests += 4
        if self.fail:
            raise public_reader.PublicReaderError(
                "schema_mismatch",
                f"{self.venue}_tickers",
                "fixture mismatch",
            )
        observer_ms = int(kwargs["observer_received_ts_ms"])
        deterministic = {
            "schema": public_reader.SNAPSHOT_SCHEMA,
            "venue": self.venue,
            "symbol": "HYPE_USDT",
            "canonical_base": "hype",
            "observer_received_ts_ms": observer_ms,
            "observed_ts_ms": observer_ms - 100,
            "quote_age_ms": 100,
            "best_bid": 10.0,
            "best_ask": 10.1,
            "mark_price": 10.05,
            "index_price": 10.04,
            "funding_rate": 0.0001,
            "bid_depth": [{"price": 10.0, "quantity": 100.0}],
            "ask_depth": [{"price": 10.1, "quantity": 100.0}],
            "contract_trading": True,
            "raw_payload_hash_sha256": "a" * 64,
            "network_request_performed": True,
        }
        return {
            **deterministic,
            "snapshot_hash_sha256": contract_module.sha256_json(
                deterministic
            ),
        }


class PaperPublicReadonlyProbeTests(unittest.TestCase):
    def _authorization(
        self,
        root: Path,
        plan_path: Path,
        plan: dict,
        run_id: str,
    ) -> tuple[Path, dict]:
        path = root / "authorization.json"
        authorization = probe_module.build_user_authorization(
            plan_path=plan_path,
            expected_plan_hash=plan["plan_hash_sha256"],
            run_id=run_id,
            user_instruction="давай приступать к работе!",
            thread_id="fixture-thread",
            output_path=path,
            generated_at_utc="2026-07-30T12:02:00+00:00",
        )
        return path, authorization

    def test_plan_and_external_authorization_are_hash_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _write_fixture_plan(root)
            authorization_path, authorization = self._authorization(
                root,
                plan_path,
                plan,
                "fixture-run",
            )
            validated, contract = probe_module.validate_probe_plan(
                plan_path,
                plan["plan_hash_sha256"],
            )
            observed = probe_module.validate_user_authorization(
                authorization_path,
                expected_authorization_hash=authorization[
                    "authorization_hash_sha256"
                ],
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash_sha256"],
                run_id="fixture-run",
            )
        self.assertEqual(
            validated["plan_hash_sha256"],
            plan["plan_hash_sha256"],
        )
        self.assertEqual(
            contract["contract_hash_sha256"],
            plan["contract"]["contract_hash_sha256"],
        )
        self.assertEqual(observed["decision"], "AUTHORIZED")

    def test_v2_standing_authorization_is_hash_bound_and_least_privilege(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy_path = _write_policy(root)
            plan_path, plan = _write_fixture_plan_v2(root)
            standing_path = root / "standing.json"
            standing = probe_module.build_standing_authorization(
                policy_path=policy_path,
                project_root=root,
                user_instruction="давай минимизируем все разрешения",
                contract_authorization_text=(
                    "Разрешаю contract v2 с MEXC depth L1 и один новый "
                    "видимый bounded probe."
                ),
                output_path=standing_path,
                generated_at_utc="2026-07-30T15:03:00+00:00",
            )
            validated_plan, _, validated_standing = (
                probe_module.validate_plan_under_standing_authorization(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash_sha256"],
                    standing_authorization_path=standing_path,
                    expected_standing_authorization_hash=standing[
                        "authorization_hash_sha256"
                    ],
                )
            )
            run_authorization_path = root / "run-authorization.json"
            run_authorization = probe_module.build_user_authorization(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash_sha256"],
                run_id="fixture-v2",
                user_instruction="standing-policy automatic run authorization",
                thread_id="fixture-thread",
                standing_authorization_path=standing_path,
                expected_standing_authorization_hash=standing[
                    "authorization_hash_sha256"
                ],
                output_path=run_authorization_path,
                generated_at_utc="2026-07-30T15:04:00+00:00",
            )
            validated_run_authorization = (
                probe_module.validate_user_authorization(
                    run_authorization_path,
                    expected_authorization_hash=run_authorization[
                        "authorization_hash_sha256"
                    ],
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash_sha256"],
                    run_id="fixture-v2",
                )
            )
            policy = json.loads(policy_path.read_text(encoding="utf-8"))
            policy["run_policy"]["single_market_data_writer"] = False
            policy_path.write_text(json.dumps(policy), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "policy file hash"):
                probe_module.validate_standing_authorization(
                    standing_path,
                    expected_authorization_hash=standing[
                        "authorization_hash_sha256"
                    ],
                )
        self.assertEqual(
            validated_plan["schema"],
            probe_module.PLAN_SCHEMAS["v2"],
        )
        self.assertTrue(
            validated_run_authorization["scope"]["automatic_start"]
        )
        self.assertFalse(validated_standing["scope"]["private_api_keys"])
        self.assertEqual(
            validated_standing["scope"][
                "maximum_runs_per_distinct_plan_hash"
            ],
            1,
        )

    def test_v2_probe_and_evidence_preserve_version_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy_path = _write_policy(root)
            plan_path, plan = _write_fixture_plan_v2(root)
            standing_path = root / "standing.json"
            standing = probe_module.build_standing_authorization(
                policy_path=policy_path,
                project_root=root,
                user_instruction="давай минимизируем все разрешения",
                contract_authorization_text=(
                    "Разрешаю contract v2 с MEXC depth L1 и один новый "
                    "видимый bounded probe."
                ),
                output_path=standing_path,
            )
            run_id = "fixture-v2-success"
            authorization_path = root / "authorization-v2.json"
            authorization = probe_module.build_user_authorization(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash_sha256"],
                run_id=run_id,
                user_instruction="standing-policy automatic run authorization",
                thread_id="fixture-thread",
                standing_authorization_path=standing_path,
                expected_standing_authorization_hash=standing[
                    "authorization_hash_sha256"
                ],
                output_path=authorization_path,
            )
            clock = ManualClock()

            def factory(_contract: dict, venue: str) -> FakeReader:
                return FakeReader(venue)

            output_dir = root / "runs-v2" / run_id
            result = probe_module.run_probe(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash_sha256"],
                authorization_path=authorization_path,
                expected_authorization_hash=authorization[
                    "authorization_hash_sha256"
                ],
                output_dir=output_dir,
                run_id=run_id,
                max_runtime_sec=180,
                reader_factory=factory,
                monotonic=clock.monotonic,
                wall_time_ms=clock.wall_time_ms,
                sleep=clock.sleep,
                utc_now=clock.utc_now,
                progress=lambda _message: None,
            )
            evidence = probe_module.build_probe_evidence(
                manifest_path=output_dir / "manifest.json",
                expected_plan_hash=plan["plan_hash_sha256"],
                output_path=root / "evidence-v2-result.json",
            )
            probe_module.validate_probe_evidence(
                root / "evidence-v2-result.json",
                manifest_path=output_dir / "manifest.json",
                expected_plan_hash=plan["plan_hash_sha256"],
            )
        self.assertEqual(result["schema"], probe_module.RESULT_SCHEMAS["v2"])
        self.assertEqual(
            evidence["schema"],
            probe_module.EVIDENCE_SCHEMAS["v2"],
        )

    def test_v3_requires_one_time_critical_authorization_and_uses_venue_limits(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy_path = _write_policy(root)
            plan_path, plan, audit_path = _write_fixture_plan_v3(root)
            standing_path = root / "standing-v3.json"
            standing = probe_module.build_standing_authorization(
                policy_path=policy_path,
                project_root=root,
                user_instruction="least privilege",
                contract_authorization_text="contract v2 fixture approval",
                output_path=standing_path,
            )
            critical_path = root / "critical-v3.json"
            critical = probe_module.build_v3_critical_authorization(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash_sha256"],
                standing_authorization_path=standing_path,
                expected_standing_authorization_hash=standing[
                    "authorization_hash_sha256"
                ],
                failure_audit_path=audit_path,
                user_instruction=probe_module.V3_APPROVED_USER_INSTRUCTION,
                thread_id="fixture-thread",
                output_path=critical_path,
            )
            probe_module.validate_v3_critical_authorization(
                critical_path,
                expected_authorization_hash=critical[
                    "authorization_hash_sha256"
                ],
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash_sha256"],
                standing_authorization_path=standing_path,
                expected_standing_authorization_hash=standing[
                    "authorization_hash_sha256"
                ],
                failure_audit_path=audit_path,
            )
            run_id = "fixture-v3-success"
            authorization_path = root / "authorization-v3.json"
            authorization = probe_module.build_user_authorization(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash_sha256"],
                run_id=run_id,
                user_instruction="execute exact approved v3 plan once",
                thread_id="fixture-thread",
                standing_authorization_path=standing_path,
                expected_standing_authorization_hash=standing[
                    "authorization_hash_sha256"
                ],
                critical_authorization_path=critical_path,
                expected_critical_authorization_hash=critical[
                    "authorization_hash_sha256"
                ],
                freshness_failure_audit_path=audit_path,
                output_path=authorization_path,
            )
            readers: dict[str, FakeReader] = {}

            def factory(_contract: dict, venue: str) -> FakeReader:
                readers[venue] = FakeReader(venue)
                return readers[venue]

            clock = ManualClock()
            output_dir = root / "runs-v3" / run_id
            result = probe_module.run_probe(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash_sha256"],
                authorization_path=authorization_path,
                expected_authorization_hash=authorization[
                    "authorization_hash_sha256"
                ],
                output_dir=output_dir,
                run_id=run_id,
                max_runtime_sec=180,
                reader_factory=factory,
                monotonic=clock.monotonic,
                wall_time_ms=clock.wall_time_ms,
                sleep=clock.sleep,
                utc_now=clock.utc_now,
                progress=lambda _message: None,
            )
            evidence = probe_module.build_probe_evidence(
                manifest_path=output_dir / "manifest.json",
                expected_plan_hash=plan["plan_hash_sha256"],
                output_path=root / "evidence-v3.json",
            )
            probe_module.validate_probe_evidence(
                root / "evidence-v3.json",
                manifest_path=output_dir / "manifest.json",
                expected_plan_hash=plan["plan_hash_sha256"],
            )
        self.assertEqual(result["schema"], probe_module.RESULT_SCHEMAS["v3"])
        self.assertEqual(
            result["quality"]["maximum_quote_age_ms_by_venue"],
            {"mexc": 6000, "gateio": 5000},
        )
        self.assertEqual(set(readers["mexc"].maximum_quote_ages_ms), {6000})
        self.assertEqual(set(readers["gateio"].maximum_quote_ages_ms), {5000})
        self.assertEqual(
            evidence["schema"],
            probe_module.EVIDENCE_SCHEMAS["v3"],
        )

    def test_successful_probe_writes_full_immutable_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _write_fixture_plan(root)
            run_id = "fixture-success"
            authorization_path, authorization = self._authorization(
                root,
                plan_path,
                plan,
                run_id,
            )
            clock = ManualClock()
            output_dir = root / "runs" / run_id
            readers: dict[str, FakeReader] = {}

            def factory(_contract: dict, venue: str) -> FakeReader:
                reader = FakeReader(venue)
                readers[venue] = reader
                return reader

            result = probe_module.run_probe(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash_sha256"],
                authorization_path=authorization_path,
                expected_authorization_hash=authorization[
                    "authorization_hash_sha256"
                ],
                output_dir=output_dir,
                run_id=run_id,
                max_runtime_sec=180,
                reader_factory=factory,
                monotonic=clock.monotonic,
                wall_time_ms=clock.wall_time_ms,
                sleep=clock.sleep,
                utc_now=clock.utc_now,
                progress=lambda _message: None,
            )
            validated = probe_module.validate_probe_result(
                output_dir / "manifest.json",
                expected_plan_hash=plan["plan_hash_sha256"],
            )
            evidence = probe_module.build_probe_evidence(
                manifest_path=output_dir / "manifest.json",
                expected_plan_hash=plan["plan_hash_sha256"],
                output_path=root / "probe-evidence.json",
                generated_at_utc="2026-07-30T12:03:00+00:00",
            )
            validated_evidence = probe_module.validate_probe_evidence(
                root / "probe-evidence.json",
                manifest_path=output_dir / "manifest.json",
                expected_plan_hash=plan["plan_hash_sha256"],
            )

        self.assertTrue(result["final"])
        self.assertEqual(result["verdict"], probe_module.ACCEPTED_VERDICT)
        self.assertEqual(result["quality"]["snapshot_count"], 48)
        self.assertEqual(result["quality"]["network_requests"], 192)
        self.assertEqual(validated["deterministic_result_hash"], result["deterministic_result_hash"])
        self.assertEqual(
            evidence["verdict"],
            "PUBLIC_READONLY_PROBE_EVIDENCE_ACCEPTED",
        )
        self.assertEqual(
            validated_evidence["deterministic_result_hash"],
            evidence["deterministic_result_hash"],
        )
        self.assertEqual(
            {venue: reader.transport.network_requests for venue, reader in readers.items()},
            {"mexc": 96, "gateio": 96},
        )

    def test_schema_mismatch_stops_incomplete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _write_fixture_plan(root)
            run_id = "fixture-schema-stop"
            authorization_path, authorization = self._authorization(
                root,
                plan_path,
                plan,
                run_id,
            )
            clock = ManualClock()

            def factory(_contract: dict, venue: str) -> FakeReader:
                return FakeReader(venue, fail=venue == "mexc")

            result = probe_module.run_probe(
                plan_path=plan_path,
                expected_plan_hash=plan["plan_hash_sha256"],
                authorization_path=authorization_path,
                expected_authorization_hash=authorization[
                    "authorization_hash_sha256"
                ],
                output_dir=root / "runs" / run_id,
                run_id=run_id,
                max_runtime_sec=180,
                reader_factory=factory,
                monotonic=clock.monotonic,
                wall_time_ms=clock.wall_time_ms,
                sleep=clock.sleep,
                utc_now=clock.utc_now,
                progress=lambda _message: None,
            )

        self.assertFalse(result["final"])
        self.assertEqual(result["status"], "STOPPED_INCOMPLETE")
        self.assertEqual(
            result["quality"]["hard_stop_reason"],
            "schema_mismatch",
        )
        self.assertEqual(result["runtime"]["cycles_attempted"], 1)

    def test_output_namespace_escape_is_rejected_before_reader_creation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan_path, plan = _write_fixture_plan(root)
            run_id = "fixture-escape"
            authorization_path, authorization = self._authorization(
                root,
                plan_path,
                plan,
                run_id,
            )

            with self.assertRaisesRegex(
                ValueError,
                "escapes the frozen namespace",
            ):
                probe_module.run_probe(
                    plan_path=plan_path,
                    expected_plan_hash=plan["plan_hash_sha256"],
                    authorization_path=authorization_path,
                    expected_authorization_hash=authorization[
                        "authorization_hash_sha256"
                    ],
                    output_dir=root / "outside",
                    run_id=run_id,
                    max_runtime_sec=180,
                    reader_factory=lambda _contract, venue: FakeReader(
                        venue
                    ),
                )

    def test_runtime_reader_uses_post_response_receive_time(self) -> None:
        now_ms = 1_800_000_000_000
        clock = public_reader.FixtureClock(now_ms=now_ms)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            contract = _build_contract(root)
            transport = public_reader.FixturePublicGetTransport(
                public_reader._valid_fixture_outcomes(now_ms)
            )
            reader = probe_module.RuntimeReceivedAtPublicMarketReader(
                contract,
                transport,
                clock=clock,
            )
            snapshot = reader.read_market_snapshot(
                venue="mexc",
                symbol="HYPE_USDT",
                canonical_base="hype",
                observer_received_ts_ms=now_ms - 5000,
            )
        self.assertEqual(snapshot["observer_received_ts_ms"], now_ms)
        self.assertEqual(snapshot["quote_age_ms"], 1000)


if __name__ == "__main__":
    unittest.main()
