from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from costs import validate_runtime_sec
    from historical_basis_code_snapshot import require_plan_runtime_code_snapshot
    from historical_basis_v2 import (
        HYPOTHESIS_ID,
        BasisBar,
        FundingEvent,
        evaluate_historical_basis_v2,
        historical_oos_verdict,
        sha256_file,
        sha256_json,
        validate_historical_basis_v2_plan,
    )
except ImportError:  # pragma: no cover - package import fallback
    from .costs import validate_runtime_sec
    from .historical_basis_code_snapshot import require_plan_runtime_code_snapshot
    from .historical_basis_v2 import (
        HYPOTHESIS_ID,
        BasisBar,
        FundingEvent,
        evaluate_historical_basis_v2,
        historical_oos_verdict,
        sha256_file,
        sha256_json,
        validate_historical_basis_v2_plan,
    )


SCHEMA = "trading_mvp_historical_basis_v2_owned_evaluation_v1"
QUALITY_SCHEMA = "trading_mvp_historical_basis_v2_quality_v2"
CANDLE_LEDGER_SCHEMA = "trading_mvp_historical_basis_v2_normalized_candles_v2"
FUNDING_LEDGER_SCHEMA = "trading_mvp_historical_basis_v2_funding_events_v2"
STAGES = ("train_feasibility", "full_evaluation")
HISTORICAL_VERDICTS = frozenset({"ACCEPT_FOR_EXECUTION_PROBE", "INSUFFICIENT_DATA", "REJECT"})


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {target}")
    return payload


def quality_semantic_hash(payload: Mapping[str, Any]) -> str:
    normalized = json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))
    normalized.pop("report_payload_sha256", None)
    normalized.pop("report_file_sha256", None)
    artifacts = normalized.get("output_artifacts")
    if isinstance(artifacts, dict) and isinstance(artifacts.get("report"), dict):
        artifacts["report"]["sha256"] = None
    return sha256_json(normalized)


def _deterministic_artifact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        ignored = {"deterministic_result_hash", "generated_at_utc", "runtime_sec", "path"}
        return {
            key: _deterministic_artifact_value(item)
            for key, item in value.items()
            if key not in ignored and not str(key).endswith("_path")
        }
    if isinstance(value, (list, tuple)):
        return [_deterministic_artifact_value(item) for item in value]
    return value


def _artifact_hash(payload: Mapping[str, Any]) -> str:
    return sha256_json(_deterministic_artifact_value(payload))


def validate_full_evaluation_result(
    evaluation: Mapping[str, Any],
    *,
    require_accept: bool = False,
) -> dict[str, Any]:
    if evaluation.get("schema") != SCHEMA:
        raise ValueError(f"expected full evaluation schema {SCHEMA}")
    if evaluation.get("stage") != "full_evaluation":
        raise ValueError("expected full_evaluation stage")
    verdict = str(evaluation.get("verdict") or "")
    if verdict not in HISTORICAL_VERDICTS:
        raise ValueError(f"unsupported historical verdict: {verdict}")
    if require_accept and verdict != "ACCEPT_FOR_EXECUTION_PROBE":
        raise ValueError("historical evaluation is not ACCEPT_FOR_EXECUTION_PROBE")
    if not str(evaluation.get("plan_hash") or "").strip():
        raise ValueError("historical evaluation plan hash is missing")
    if evaluation.get("oos_read") is not True:
        raise ValueError("historical full evaluation has no verified OOS read")

    audit = evaluation.get("data_access_audit")
    if not isinstance(audit, Mapping):
        raise ValueError("historical full evaluation has no OOS data access audit")
    if audit.get("oos_files_opened") is not True or audit.get("oos_returns_read") is not True:
        raise ValueError("historical full evaluation OOS access audit is incomplete")
    for key in ("network_access", "grid_search", "retune"):
        if audit.get(key) is not False:
            raise ValueError(f"historical full evaluation safety flag must be false: {key}")

    for key in ("oos_input_hashes", "feasibility_provenance", "code_provenance"):
        if not isinstance(evaluation.get(key), Mapping):
            raise ValueError(f"historical full evaluation provenance is missing: {key}")
    if evaluation.get("deterministic_result_hash") != _artifact_hash(evaluation):
        raise ValueError("historical evaluation deterministic hash mismatch")

    metrics = evaluation.get("metrics")
    if not isinstance(metrics, Mapping):
        raise ValueError("historical full evaluation metrics are missing")
    if verdict == "ACCEPT_FOR_EXECUTION_PROBE":
        recomputed_verdict, recomputed_reasons = historical_oos_verdict(metrics)
        if recomputed_verdict != "ACCEPT_FOR_EXECUTION_PROBE" or recomputed_reasons:
            raise ValueError("historical ACCEPT does not satisfy frozen OOS economics gates")
        if list(evaluation.get("rejection_reasons") or []):
            raise ValueError("historical ACCEPT contains rejection reasons")
        robustness = evaluation.get("four_hour_robustness")
        if not isinstance(robustness, Mapping) or robustness.get("passed") is not True:
            raise ValueError("historical ACCEPT has no passing 4h robustness result")
        if list(robustness.get("rejection_reasons") or []):
            raise ValueError("historical ACCEPT 4h robustness contains rejection reasons")

        normal_trades = evaluation.get("normal_trades")
        stress_trades = evaluation.get("stress_trades")
        if not isinstance(normal_trades, list) or not isinstance(stress_trades, list):
            raise ValueError("historical ACCEPT trade ledgers are missing")
        normal_ids = [str(row.get("episode_id") or "") for row in normal_trades if isinstance(row, Mapping)]
        stress_ids = [str(row.get("episode_id") or "") for row in stress_trades if isinstance(row, Mapping)]
        if (
            len(normal_ids) != len(normal_trades)
            or len(stress_ids) != len(stress_trades)
            or any(not value for value in normal_ids + stress_ids)
            or len(normal_ids) != len(set(normal_ids))
            or len(stress_ids) != len(set(stress_ids))
            or set(normal_ids) != set(stress_ids)
            or len(normal_ids) != int(metrics.get("independent_episode_count") or 0)
        ):
            raise ValueError("historical ACCEPT normal/stress episode provenance mismatch")
    return dict(evaluation)


def _atomic_write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"artifact already exists: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def _artifact_reference(quality: Mapping[str, Any], name: str) -> dict[str, Any]:
    artifacts = quality.get("output_artifacts")
    if not isinstance(artifacts, Mapping):
        raise ValueError("quality report output_artifacts must be an object")
    raw = artifacts.get(name)
    if not isinstance(raw, Mapping):
        raise ValueError(f"quality report is missing output_artifacts.{name}")
    path = str(raw.get("path") or "").strip()
    digest = str(raw.get("sha256") or "").strip()
    if not path:
        raise ValueError(f"quality report is missing {name} artifact path")
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise ValueError(f"quality report has invalid {name} artifact sha256")
    rows = int(raw.get("rows") or 0)
    if rows < 0:
        raise ValueError(f"quality report has negative {name} artifact row count")
    return {**dict(raw), "path": path, "sha256": digest, "rows": rows}


def _validate_flat_artifact_aliases(
    quality: Mapping[str, Any],
    *,
    name: str,
    reference: Mapping[str, Any],
) -> None:
    path_key = f"{name}_output"
    hash_key = f"{name}_output_sha256"
    if quality.get(path_key) is not None and str(quality[path_key]) != str(reference["path"]):
        raise ValueError(f"quality {name} artifact path alias mismatch")
    if quality.get(hash_key) is not None and str(quality[hash_key]) != str(reference["sha256"]):
        raise ValueError(f"quality {name} artifact hash alias mismatch")


def _validate_quality_report(
    quality: Mapping[str, Any],
    *,
    quality_path: Path,
    plan_hash: str,
    plan: Mapping[str, Any],
) -> None:
    if quality.get("schema") != QUALITY_SCHEMA:
        raise ValueError(f"unexpected quality report schema; expected {QUALITY_SCHEMA}")
    if quality.get("verdict") != "QUALITY_ACCEPTED_NOT_EVALUATED":
        raise ValueError("quality report did not accept the dataset")
    if quality.get("plan_hash") != plan_hash:
        raise ValueError("quality report plan hash mismatch")
    if not quality_path.is_file() or quality_path.stat().st_size <= 0:
        raise ValueError("quality report is missing or empty")
    expected_payload_hash = quality_semantic_hash(quality)
    if quality.get("report_payload_sha256") != expected_payload_hash:
        raise ValueError("quality report payload hash mismatch")
    report_artifact = _artifact_reference(quality, "report")
    if report_artifact["sha256"] != expected_payload_hash:
        raise ValueError("quality report artifact hash mismatch")
    if Path(str(report_artifact["path"])).expanduser().resolve() != quality_path:
        raise ValueError("quality report artifact path mismatch")
    surviving_count = int(quality.get("surviving_asset_count") or 0)
    primary = quality.get("primary_assets")
    reserve = quality.get("reserve_assets")
    if not isinstance(primary, list) or not isinstance(reserve, list):
        raise ValueError("quality primary_assets and reserve_assets must be lists")
    if surviving_count != len(primary) + len(reserve):
        raise ValueError("quality surviving asset count mismatch")
    if surviving_count < 8:
        raise ValueError("quality report has fewer than eight surviving assets")
    references = {
        name: _artifact_reference(quality, name)
        for name in ("candles", "funding", "train", "oos")
    }
    if references["candles"].get("schema") != CANDLE_LEDGER_SCHEMA:
        raise ValueError("unexpected normalized candle ledger schema")
    if references["funding"].get("schema") != FUNDING_LEDGER_SCHEMA:
        raise ValueError("unexpected funding ledger schema")
    for name, reference in references.items():
        _validate_flat_artifact_aliases(quality, name=name, reference=reference)
    if int(quality.get("train_row_count") or 0) != references["train"]["rows"]:
        raise ValueError("quality train row count mismatch")
    if int(quality.get("oos_row_count") or 0) != references["oos"]["rows"]:
        raise ValueError("quality OOS row count mismatch")
    if int(quality.get("funding_event_count") or 0) != references["funding"]["rows"]:
        raise ValueError("quality funding event count mismatch")
    split = plan["split_contract"]
    for name in ("train", "oos"):
        expected = split[name]
        reference = references[name]
        if reference.get("range") != "[start,end)":
            raise ValueError(f"quality {name} artifact range must be [start,end)")
        if int(reference.get("start_sec")) != int(expected["start_ts"]):
            raise ValueError(f"quality {name} artifact start mismatch")
        if int(reference.get("end_sec")) != int(expected["end_ts"]):
            raise ValueError(f"quality {name} artifact end mismatch")
    if references["oos"].get("sealed") is not True:
        raise ValueError("quality OOS artifact is not sealed")


def _verify_artifact(reference: Mapping[str, Any], *, label: str) -> Path:
    target = Path(str(reference["path"])).expanduser().resolve()
    if not target.is_file():
        raise ValueError(f"{label} artifact is missing")
    if sha256_file(target) != reference["sha256"]:
        raise ValueError(f"{label} hash mismatch")
    return target


def _load_bars(path: Path, *, start_ts: int, end_ts: int) -> list[BasisBar]:
    rows: list[BasisBar] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError("row is not an object")
                bar = BasisBar.from_dict(payload)
                if not start_ts <= bar.ts < end_ts:
                    raise ValueError("candle timestamp is outside artifact range")
                rows.append(bar)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid candle row {path}:{line_number}: {exc}") from exc
    return rows


def _load_funding_events(
    path: Path,
    *,
    start_ts: int,
    end_ts: int,
    stop_at_end: bool,
) -> tuple[list[FundingEvent], int]:
    rows: list[FundingEvent] = []
    identities: set[str] = set()
    settlements: set[str] = set()
    previous_ts: int | float | None = None
    source_rows_read = 0
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
                if not isinstance(payload, dict):
                    raise ValueError("row is not an object")
                event = FundingEvent.from_dict(payload)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ValueError(f"invalid funding row {path}:{line_number}: {exc}") from exc
            source_rows_read += 1
            if previous_ts is not None and event.settlement_ts < previous_ts:
                raise ValueError("funding ledger is not ordered by settlement timestamp")
            previous_ts = event.settlement_ts
            if stop_at_end and event.settlement_ts >= end_ts:
                break
            if event.event_id in identities or event.settlement_identity in settlements:
                raise ValueError(f"duplicate funding event in ledger: {event.event_id}")
            identities.add(event.event_id)
            settlements.add(event.settlement_identity)
            if start_ts <= event.settlement_ts < end_ts:
                rows.append(event)
    return rows, source_rows_read


def _load_stage_bars(
    quality: Mapping[str, Any],
    *,
    split: str,
) -> tuple[list[BasisBar], dict[str, Any]]:
    bars_reference = _artifact_reference(quality, split)
    bars_path = _verify_artifact(bars_reference, label=f"{split} candle artifact")
    start_ts = int(bars_reference["start_sec"])
    end_ts = int(bars_reference["end_sec"])
    bars = _load_bars(bars_path, start_ts=start_ts, end_ts=end_ts)
    if len(bars) != int(bars_reference["rows"]):
        raise ValueError(f"{split} candle row count mismatch")
    return bars, {
        "candles_sha256": bars_reference["sha256"],
        "candles_rows": bars_reference["rows"],
    }


def _train_input_hashes(quality: Mapping[str, Any]) -> dict[str, Any]:
    train = _artifact_reference(quality, "train")
    funding = _artifact_reference(quality, "funding")
    return {
        "candles_sha256": train["sha256"],
        "candles_rows": train["rows"],
        "funding_sha256": funding["sha256"],
        "funding_rows": funding["rows"],
        "funding_event_merkle_sha256": quality.get("funding_event_merkle_sha256"),
        "funding_scope": "immutable_full_window_ledger_filtered_to_train_before_core",
    }


def _oos_seal(quality: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]:
    bars = _artifact_reference(quality, "oos")
    candles = _artifact_reference(quality, "candles")
    funding = _artifact_reference(quality, "funding")
    split = plan["split_contract"]["oos"]
    return {
        "bars_sha256": bars["sha256"],
        "bars_rows": bars["rows"],
        "canonical_candles_sha256": candles["sha256"],
        "canonical_candles_rows": candles["rows"],
        "funding_sha256": funding["sha256"],
        "funding_rows": funding["rows"],
        "funding_event_merkle_sha256": quality.get("funding_event_merkle_sha256"),
        "window_start_ts": split["start_ts"],
        "window_end_ts": split["end_ts"],
        "input_file_merkle_sha256": quality.get("input_file_merkle_sha256"),
    }


def _quality_surviving_bases(
    quality: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> list[str]:
    values = [*(quality.get("primary_assets") or []), *(quality.get("reserve_assets") or [])]
    bases = sorted({str(value).strip().upper() for value in values if str(value).strip()})
    if len(bases) != int(quality.get("surviving_asset_count") or 0):
        raise ValueError("quality surviving asset identities are not unique")
    return bases


def _code_provenance(plan: Mapping[str, Any]) -> dict[str, Any]:
    plan_code = plan.get("code_provenance") or {}
    return {
        "plan_core_module_sha256": plan_code.get("module_sha256"),
        "code_snapshot_hash": plan_code.get("code_snapshot_hash"),
        "immutable_snapshot": bool(plan_code.get("immutable_snapshot")),
        "evaluator_sha256": sha256_file(__file__),
    }


def _validate_feasibility_artifact(
    feasibility_path: str | Path,
    *,
    plan_hash: str,
    plan: Mapping[str, Any],
    quality: Mapping[str, Any],
    quality_file_sha256: str,
    train_input_hashes: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    target = Path(feasibility_path).expanduser().resolve()
    feasibility = _read_json(target)
    if feasibility.get("schema") != SCHEMA or feasibility.get("stage") != "train_feasibility":
        raise ValueError("unexpected feasibility artifact")
    if feasibility.get("verdict") != "FEASIBLE_FOR_OOS":
        raise ValueError("feasibility artifact is not FEASIBLE_FOR_OOS")
    if feasibility.get("plan_hash") != plan_hash:
        raise ValueError("feasibility plan hash mismatch")
    if feasibility.get("quality_report_sha256") != quality_file_sha256:
        raise ValueError("feasibility quality provenance mismatch")
    if feasibility.get("quality_semantic_hash") != quality.get("report_payload_sha256"):
        raise ValueError("feasibility quality semantic hash mismatch")
    if feasibility.get("train_input_hashes") != dict(train_input_hashes):
        raise ValueError("feasibility train input binding mismatch")
    if feasibility.get("oos_seal") != _oos_seal(quality, plan):
        raise ValueError("feasibility OOS seal mismatch")
    code = feasibility.get("code_provenance") or {}
    expected_code = _code_provenance(plan)
    if code != expected_code:
        raise ValueError("feasibility code provenance mismatch")
    audit = feasibility.get("data_access_audit") or {}
    if feasibility.get("oos_read") is not False:
        raise ValueError("feasibility artifact violates OOS embargo")
    if audit.get("oos_files_opened") is not False or int(audit.get("oos_rows_read") or 0) != 0:
        raise ValueError("feasibility artifact violates OOS access audit")
    if feasibility.get("deterministic_result_hash") != _artifact_hash(feasibility):
        raise ValueError("feasibility deterministic result hash mismatch")
    return feasibility, {
        "path": str(target),
        "file_sha256": sha256_file(target),
        "deterministic_result_hash": feasibility["deterministic_result_hash"],
    }


def run_hash_bound_evaluation(
    *,
    plan_path: str | Path,
    quality_report_path: str | Path,
    output_path: str | Path,
    stage: str,
    expected_plan_hash: str | None = None,
    feasibility_path: str | Path | None = None,
    max_runtime_sec: int = 1_800,
) -> dict[str, Any]:
    if stage not in STAGES:
        raise ValueError("stage must be train_feasibility or full_evaluation")
    if stage == "train_feasibility" and feasibility_path is not None:
        raise ValueError("--feasibility is only valid for full_evaluation")
    if stage == "full_evaluation" and feasibility_path is None:
        raise ValueError("full_evaluation requires --feasibility")
    if expected_plan_hash is None or not str(expected_plan_hash).strip():
        raise ValueError("expected_plan_hash is required for hash-bound evaluation")
    runtime_limit = validate_runtime_sec(max_runtime_sec)
    started = time.monotonic()

    plan_target = Path(plan_path).expanduser().resolve()
    validation = validate_historical_basis_v2_plan(plan_target, expected_plan_hash)
    plan = _read_json(plan_target)
    require_plan_runtime_code_snapshot(plan, runtime_code_path=__file__)
    frozen_runtime = int((plan.get("runtime") or {}).get("evaluation_max_runtime_sec") or 1_800)
    if runtime_limit > frozen_runtime:
        raise ValueError(f"max_runtime_sec exceeds frozen evaluation limit: {frozen_runtime}")

    quality_target = Path(quality_report_path).expanduser().resolve()
    quality = _read_json(quality_target)
    _validate_quality_report(
        quality,
        quality_path=quality_target,
        plan_hash=str(validation["plan_hash"]),
        plan=plan,
    )
    quality_file_sha256 = sha256_file(quality_target)

    train_bars, _train_bar_hashes = _load_stage_bars(quality, split="train")
    train_hashes = _train_input_hashes(quality)
    if _train_bar_hashes["candles_sha256"] != train_hashes["candles_sha256"]:
        raise ValueError("train candle provenance mismatch")
    if time.monotonic() - started > runtime_limit:
        raise TimeoutError("evaluation max_runtime_sec exceeded before simulation")

    feasibility_provenance: dict[str, Any] | None = None
    oos_bars: list[BasisBar] = []
    oos_hashes: dict[str, Any] | None = None
    split_contract = plan["split_contract"]
    train_split = split_contract["train"]
    oos_split = split_contract["oos"]
    funding_reference = _artifact_reference(quality, "funding")
    funding_events: list[FundingEvent]
    funding_source_rows_read = 0
    if stage == "full_evaluation":
        _feasibility, feasibility_provenance = _validate_feasibility_artifact(
            feasibility_path,
            plan_hash=str(validation["plan_hash"]),
            plan=plan,
            quality=quality,
            quality_file_sha256=quality_file_sha256,
            train_input_hashes=train_hashes,
        )
        candles_reference = _artifact_reference(quality, "candles")
        _verify_artifact(candles_reference, label="canonical candle ledger")
        funding_path = _verify_artifact(funding_reference, label="funding ledger")
        oos_bars, oos_bar_hashes = _load_stage_bars(quality, split="oos")
        funding_events, funding_source_rows_read = _load_funding_events(
            funding_path,
            start_ts=int(train_split["start_ts"]),
            end_ts=int(oos_split["end_ts"]),
            stop_at_end=False,
        )
        if funding_source_rows_read != int(funding_reference["rows"]):
            raise ValueError("funding ledger row count mismatch")
        oos_funding_count = sum(
            int(oos_split["start_ts"]) <= event.settlement_ts < int(oos_split["end_ts"])
            for event in funding_events
        )
        oos_hashes = {
            **oos_bar_hashes,
            "canonical_candles_sha256": candles_reference["sha256"],
            "canonical_candles_rows": candles_reference["rows"],
            "funding_sha256": funding_reference["sha256"],
            "funding_rows": funding_reference["rows"],
            "oos_funding_events_selected": oos_funding_count,
        }
    else:
        funding_path = _verify_artifact(funding_reference, label="funding ledger")
        funding_events, funding_source_rows_read = _load_funding_events(
            funding_path,
            start_ts=int(train_split["start_ts"]),
            end_ts=int(train_split["end_ts"]),
            stop_at_end=True,
        )

    if time.monotonic() - started > runtime_limit:
        raise TimeoutError("evaluation max_runtime_sec exceeded before core evaluation")
    core = evaluate_historical_basis_v2(
        plan,
        [*train_bars, *oos_bars],
        funding_events,
        stage=stage,
        quality_surviving_bases=_quality_surviving_bases(quality, plan),
    )
    elapsed = time.monotonic() - started
    if elapsed > runtime_limit:
        raise TimeoutError("evaluation max_runtime_sec exceeded")

    oos_opened = stage == "full_evaluation"
    result: dict[str, Any] = {
        **core,
        "schema": SCHEMA,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "plan_path": str(plan_target),
        "plan_file_sha256": validation["plan_file_sha256"],
        "plan_hash": validation["plan_hash"],
        "quality_report_path": str(quality_target),
        "quality_report_sha256": quality_file_sha256,
        "quality_semantic_hash": quality["report_payload_sha256"],
        "input_file_merkle_sha256": quality.get("input_file_merkle_sha256"),
        "train_input_hashes": train_hashes,
        "oos_seal": _oos_seal(quality, plan),
        "oos_input_hashes": oos_hashes,
        "feasibility_provenance": feasibility_provenance,
        "code_provenance": _code_provenance(plan),
        "data_access_audit": {
            "train_candle_file_opened": True,
            "funding_ledger_file_opened": True,
            "funding_ledger_hash_checked": True,
            "funding_ledger_source_rows_read": funding_source_rows_read,
            "canonical_candle_file_hash_checked": oos_opened,
            "oos_files_opened": oos_opened,
            "oos_rows_read": (
                int((oos_hashes or {}).get("candles_rows") or 0)
                + int((oos_hashes or {}).get("oos_funding_events_selected") or 0)
            ),
            "oos_returns_read": oos_opened,
            "paths_derived_from_quality_report": True,
            "network_access": False,
            "grid_search": False,
            "retune": False,
        },
        "runtime_sec": round(elapsed, 6),
    }
    result["deterministic_result_hash"] = _artifact_hash(result)
    _atomic_write_json(output_path, result)
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Hash-bound historical basis v2 evaluator")
    parser.add_argument("--plan", required=True)
    parser.add_argument("--expected-plan-hash", required=True)
    parser.add_argument("--quality-report", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--stage", choices=STAGES, required=True)
    parser.add_argument("--feasibility")
    parser.add_argument("--max-runtime-sec", type=int, default=1_800)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    if args.stage == "train_feasibility" and args.feasibility is not None:
        parser.error("--feasibility is only valid for --stage full_evaluation")
    if args.stage == "full_evaluation" and args.feasibility is None:
        parser.error("--feasibility is required for --stage full_evaluation")
    result = run_hash_bound_evaluation(
        plan_path=args.plan,
        expected_plan_hash=args.expected_plan_hash,
        quality_report_path=args.quality_report,
        output_path=args.output,
        stage=args.stage,
        feasibility_path=args.feasibility,
        max_runtime_sec=args.max_runtime_sec,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
