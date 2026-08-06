from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from gate_momentum_archive import validate_momentum_archive_plan
from gate_momentum_identity import (
    validate_gate_momentum_identity_plan,
    validate_gate_momentum_identity_result,
)


PLAN_SCHEMA = "trading_mvp_gate_momentum_history_plan_v1"
HYPOTHESIS_ID = "cross_sectional_momentum_daily_survivorship_repair_v3_tardis"
EXCHANGE_ID = "gate-io-futures"
GROUPED_SYMBOL = "PERPETUALS"
DATA_TYPES = ("trades", "derivative_ticker")
DATASET_URL_TEMPLATE = (
    "https://datasets.tardis.dev/v1/"
    "{exchange}/{data_type}/{year}/{month}/{day}/{symbol}.csv.gz"
)
DATASET_API_DOC = "https://docs.tardis.dev/downloadable-csv-files/api"
GATE_SOURCE_DOC = "https://docs.tardis.dev/historical-data-details/gate-io-futures"
HISTORY_DAYS = 220
WARMUP_DAYS = 20
TRAIN_DAYS = 100
OOS_DAYS = 100
OOS_FOLDS = 5
OOS_FOLD_DAYS = 20
LOOKBACK_DAYS = 30
MAX_ALLOWED_RUNTIME_SEC = 7200
DEFAULT_MAX_RUNTIME_SEC = 7200
MAX_CONCURRENCY = 4
HASH_CHARS = frozenset("0123456789abcdef")


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _payload_without_hash(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key != "plan_hash"}


def _validate_sha256(value: Any, *, label: str) -> str:
    digest = str(value or "").lower()
    if len(digest) != 64 or any(character not in HASH_CHARS for character in digest):
        raise ValueError(f"invalid {label}")
    return digest


def _read_json_object(path: str | Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _write_json_immutable(path: str | Path, payload: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if target.exists():
        if target.read_text(encoding="utf-8") != encoded:
            raise FileExistsError(f"immutable output already exists: {target}")
        return
    target.write_text(encoded, encoding="utf-8")


def _parse_utc_timestamp(value: str, *, label: str) -> datetime:
    text = str(value or "").strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError(f"invalid {label}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _parse_date(value: str, *, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise ValueError(f"invalid {label}") from exc


def _path_is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _require_disjoint_roots(left: Path, right: Path) -> None:
    if left == right or _path_is_within(left, right) or _path_is_within(right, left):
        raise ValueError("train and OOS cache roots must be disjoint")


def _file_reference(
    path: str | Path,
    *,
    semantic_hash_name: str,
    semantic_hash: str,
) -> dict[str, Any]:
    resolved = Path(path).expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"required input is missing: {resolved}")
    return {
        "path": str(resolved),
        "file_sha256": sha256_file(resolved),
        semantic_hash_name: _validate_sha256(
            semantic_hash,
            label=semantic_hash_name,
        ),
    }


def _partition_for_day(
    current: date,
    *,
    history_start: date,
    warmup_end: date,
    train_end: date,
) -> tuple[str, int | None]:
    if current < warmup_end:
        return "warmup", None
    if current < train_end:
        return "train", None
    oos_offset = (current - train_end).days
    fold = (oos_offset // OOS_FOLD_DAYS) + 1
    if not 1 <= fold <= OOS_FOLDS:
        raise ValueError("OOS fold calculation is out of range")
    return f"oos_fold_{fold}", fold


def _task_path(
    root: Path,
    *,
    data_type: str,
    current: date,
) -> Path:
    return (
        root
        / data_type
        / f"{current.year:04d}"
        / f"{current.month:02d}"
        / f"{current.day:02d}"
        / f"{GROUPED_SYMBOL}.csv.gz"
    )


def _build_download_tasks(
    *,
    history_start: date,
    history_end_exclusive: date,
    warmup_end: date,
    train_end: date,
    train_cache_root: Path,
    oos_cache_root: Path,
) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    current = history_start
    while current < history_end_exclusive:
        partition, fold = _partition_for_day(
            current,
            history_start=history_start,
            warmup_end=warmup_end,
            train_end=train_end,
        )
        cache_root = (
            train_cache_root
            if partition in {"warmup", "train"}
            else oos_cache_root
        )
        for data_type in DATA_TYPES:
            url = DATASET_URL_TEMPLATE.format(
                exchange=EXCHANGE_ID,
                data_type=data_type,
                year=f"{current.year:04d}",
                month=f"{current.month:02d}",
                day=f"{current.day:02d}",
                symbol=GROUPED_SYMBOL,
            )
            task: dict[str, Any] = {
                "exchange": EXCHANGE_ID,
                "data_type": data_type,
                "date": current.isoformat(),
                "symbol": GROUPED_SYMBOL,
                "partition": partition,
                "oos_fold": fold,
                "url": url,
                "cache_path": str(
                    _task_path(
                        cache_root,
                        data_type=data_type,
                        current=current,
                    )
                ),
                "authorization": {
                    "location": "header",
                    "scheme": "Bearer",
                    "credential_env": "TARDIS_API_KEY",
                    "value_persisted": False,
                },
            }
            task["task_hash"] = sha256_json(task)
            tasks.append(task)
        current += timedelta(days=1)
    return tasks


def _folds(train_end: date, history_end_exclusive: date) -> list[dict[str, Any]]:
    folds: list[dict[str, Any]] = []
    for index in range(OOS_FOLDS):
        start = train_end + timedelta(days=index * OOS_FOLD_DAYS)
        end = start + timedelta(days=OOS_FOLD_DAYS)
        if end > history_end_exclusive:
            raise ValueError("OOS folds exceed history boundary")
        folds.append(
            {
                "fold": index + 1,
                "start": start.isoformat(),
                "end_exclusive": end.isoformat(),
                "days": OOS_FOLD_DAYS,
            }
        )
    if folds[-1]["end_exclusive"] != history_end_exclusive.isoformat():
        raise ValueError("OOS folds do not cover the sealed OOS boundary")
    return folds


def build_gate_momentum_history_plan(
    momentum_plan_path: str | Path,
    identity_plan_path: str | Path,
    identity_result_path: str | Path,
    *,
    train_cache_root: str | Path,
    oos_cache_root: str | Path,
    train_normalized_output_path: str | Path,
    oos_normalized_output_path: str | Path,
    history_manifest_output_path: str | Path,
    quality_report_output_path: str | Path,
    history_end_exclusive: str,
    frozen_at_utc: str,
    max_runtime_sec: int = DEFAULT_MAX_RUNTIME_SEC,
) -> dict[str, Any]:
    if not 1 <= max_runtime_sec <= MAX_ALLOWED_RUNTIME_SEC:
        raise ValueError(
            f"max_runtime_sec must be between 1 and {MAX_ALLOWED_RUNTIME_SEC}"
        )

    frozen_at = _parse_utc_timestamp(frozen_at_utc, label="frozen_at_utc")
    history_end = _parse_date(
        history_end_exclusive,
        label="history_end_exclusive",
    )
    if history_end > frozen_at.date() - timedelta(days=1):
        raise ValueError(
            "history_end_exclusive must leave at least one fully exported UTC day"
        )

    momentum_plan = validate_momentum_archive_plan(
        _read_json_object(momentum_plan_path)
    )
    if momentum_plan["hypothesis"]["id"] != HYPOTHESIS_ID:
        raise ValueError("unexpected momentum hypothesis")
    identity_plan = validate_gate_momentum_identity_plan(identity_plan_path)
    identity_result = validate_gate_momentum_identity_result(
        identity_result_path,
        plan_path=identity_plan_path,
    )
    if (
        identity_result.get("verdict")
        != "IDENTITY_ACCEPTED_READY_FOR_HISTORY_PLANONLY"
        or identity_result.get("accepted_for_history_planonly") is not True
        or identity_result.get("history_collect_allowed") is not False
    ):
        raise ValueError("identity result cannot authorize history PlanOnly")
    if (
        identity_plan["inputs"]["momentum_plan"]["plan_hash"]
        != momentum_plan["plan_hash"]
    ):
        raise ValueError("identity and momentum plans are not hash-bound")

    history_start = history_end - timedelta(days=HISTORY_DAYS)
    warmup_end = history_start + timedelta(days=WARMUP_DAYS)
    train_end = warmup_end + timedelta(days=TRAIN_DAYS)
    if train_end + timedelta(days=OOS_DAYS) != history_end:
        raise ValueError("history split does not cover exactly 220 days")
    rebalance_anchor = history_start + timedelta(days=LOOKBACK_DAYS)

    train_root = Path(train_cache_root).expanduser().resolve()
    oos_root = Path(oos_cache_root).expanduser().resolve()
    _require_disjoint_roots(train_root, oos_root)
    outputs = {
        "train_cache_root": str(train_root),
        "sealed_oos_cache_root": str(oos_root),
        "train_normalized_jsonl_path": str(
            Path(train_normalized_output_path).expanduser().resolve()
        ),
        "sealed_oos_normalized_jsonl_path": str(
            Path(oos_normalized_output_path).expanduser().resolve()
        ),
        "history_manifest_json_path": str(
            Path(history_manifest_output_path).expanduser().resolve()
        ),
        "quality_report_json_path": str(
            Path(quality_report_output_path).expanduser().resolve()
        ),
        "immutable": True,
    }
    if len({value for key, value in outputs.items() if key != "immutable"}) != 6:
        raise ValueError("history output paths must be distinct")

    tasks = _build_download_tasks(
        history_start=history_start,
        history_end_exclusive=history_end,
        warmup_end=warmup_end,
        train_end=train_end,
        train_cache_root=train_root,
        oos_cache_root=oos_root,
    )
    expected_task_count = HISTORY_DAYS * len(DATA_TYPES)
    if len(tasks) != expected_task_count:
        raise ValueError("history task count mismatch")

    module_path = Path(__file__).resolve()
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "mode": "PlanOnly",
        "research_only": True,
        "frozen_at_utc": frozen_at.isoformat(),
        "hypothesis_id": HYPOTHESIS_ID,
        "inputs": {
            "momentum_plan": _file_reference(
                momentum_plan_path,
                semantic_hash_name="plan_hash",
                semantic_hash=momentum_plan["plan_hash"],
            ),
            "identity_plan": _file_reference(
                identity_plan_path,
                semantic_hash_name="plan_hash",
                semantic_hash=identity_plan["plan_hash"],
            ),
            "identity_result": _file_reference(
                identity_result_path,
                semantic_hash_name="artifact_hash",
                semantic_hash=identity_result["artifact_hash"],
            ),
            "gate_instruments": _file_reference(
                identity_result["gate_instruments_jsonl_path"],
                semantic_hash_name="content_sha256",
                semantic_hash=identity_result["gate_instruments_sha256"],
            ),
            "binance_instruments": _file_reference(
                identity_result["binance_instruments_jsonl_path"],
                semantic_hash_name="content_sha256",
                semantic_hash=identity_result["binance_instruments_sha256"],
            ),
        },
        "source": {
            "provider": "Tardis.dev",
            "exchange": EXCHANGE_ID,
            "dataset_endpoint_template": DATASET_URL_TEMPLATE,
            "dataset_api_documentation": DATASET_API_DOC,
            "gate_source_documentation": GATE_SOURCE_DOC,
            "daily_interval_basis": "local_timestamp_utc",
            "grouped_symbol": GROUPED_SYMBOL,
            "data_types": list(DATA_TYPES),
            "gzip_required": True,
            "authentication": {
                "location": "header",
                "scheme": "Bearer",
                "credential_env": "TARDIS_API_KEY",
                "query_auth_forbidden": True,
                "value_persisted": False,
            },
        },
        "history": {
            "history_start": history_start.isoformat(),
            "history_end_exclusive": history_end.isoformat(),
            "history_days": HISTORY_DAYS,
            "warmup_start": history_start.isoformat(),
            "warmup_end_exclusive": warmup_end.isoformat(),
            "warmup_days": WARMUP_DAYS,
            "train_start": warmup_end.isoformat(),
            "train_end_exclusive": train_end.isoformat(),
            "train_days": TRAIN_DAYS,
            "oos_start": train_end.isoformat(),
            "oos_end_exclusive": history_end.isoformat(),
            "oos_days": OOS_DAYS,
            "oos_folds": _folds(train_end, history_end),
            "global_rebalance_anchor": rebalance_anchor.isoformat(),
            "open_days_allowed": 0,
        },
        "aggregation": {
            "trades": {
                "day_key": "UTC date of local_timestamp",
                "ordering": ["local_timestamp", "source_row_order"],
                "open": "first_valid_trade_price",
                "close": "last_valid_trade_price",
                "quote_volume": "sum(price*amount)",
                "duplicate_trade_policy": "fail_quality_or_deduplicate_by_frozen_key",
                "interpolation": False,
            },
            "funding": {
                "source": "derivative_ticker",
                "settlement_key": "funding_timestamp",
                "applied_rate": (
                    "last_nonempty_funding_rate_observed_strictly_before_"
                    "funding_timestamp"
                ),
                "predicted_rate_used": False,
                "actual_settlements_only": True,
                "favorable_haircut_in_stress": 1.0,
                "adverse_funding_preserved": True,
            },
            "identity": {
                "join_key": "canonical_asset_id",
                "ticker_only_join_forbidden": True,
                "gate_lifecycle_mask_required": True,
                "binance_spot_lifecycle_exclusion_required": True,
                "non_binance_at_signal_date_required": True,
            },
        },
        "strategy": momentum_plan["strategy"],
        "costs": momentum_plan["costs"],
        "quality_contract": momentum_plan["quality_contract"],
        "acceptance": momentum_plan["acceptance"],
        "download": {
            "tasks": tasks,
            "task_count": expected_task_count,
            "request_concurrency": MAX_CONCURRENCY,
            "bounded_token_buckets": True,
            "cache_key": "task_hash",
            "cache_reuse_requires": [
                "task_hash_match",
                "gzip_decompression_success",
                "nonempty_header",
                "content_sha256_match",
            ],
            "partial_file_suffix": ".partial",
            "atomic_rename_after_validation": True,
            "retry_http_statuses": [408, 409, 425, 429, 500, 502, 503, 504],
            "maximum_attempts_per_task": 4,
        },
        "outputs": outputs,
        "limits": {
            "max_runtime_sec": int(max_runtime_sec),
            "absolute_runtime_cap_sec": MAX_ALLOWED_RUNTIME_SEC,
            "task_count": expected_task_count,
            "request_concurrency": MAX_CONCURRENCY,
        },
        "embargo": {
            "train_evaluator_read_roots": [
                str(train_root),
                outputs["train_normalized_jsonl_path"],
            ],
            "train_evaluator_forbidden_roots": [
                str(oos_root),
                outputs["sealed_oos_normalized_jsonl_path"],
            ],
            "oos_paths_may_be_downloaded_but_not_opened_by_train": True,
            "oos_requires_hash_valid_train_feasible": True,
            "automatic_oos": False,
        },
        "code_provenance": {
            "module_path": str(module_path),
            "module_sha256": sha256_file(module_path),
        },
        "data_access_audit": {
            "network_access": False,
            "market_rows_read": False,
            "market_values_read": False,
            "returns_read": False,
            "signals_computed": False,
            "pnl_read": False,
            "train_read": False,
            "oos_read": False,
        },
        "safety": {
            "history_collect_currently_allowed": False,
            "requires_explicit_visible_collect_approval": True,
            "quality_currently_allowed": False,
            "train_currently_allowed": False,
            "oos_currently_allowed": False,
            "grid_search": False,
            "retune": False,
            "execution_probe": False,
            "paper_forward": False,
            "live_orders": False,
            "private_exchange_api_keys": False,
            "leverage_or_margin": False,
        },
        "decision": "GATE_MOMENTUM_HISTORY_PLAN_READY_AWAITING_VISIBLE_COLLECT",
        "next_allowed_command": "gate-momentum-history-collect-visible",
    }
    plan["plan_hash"] = sha256_json(_payload_without_hash(plan))
    return plan


def _validate_file_reference(
    reference: Mapping[str, Any],
    *,
    semantic_hash_name: str,
) -> Path:
    path = Path(str(reference.get("path") or "")).resolve()
    if not path.is_file():
        raise ValueError(f"history plan input is missing: {path}")
    if sha256_file(path) != _validate_sha256(
        reference.get("file_sha256"),
        label="file_sha256",
    ):
        raise ValueError(f"history plan input file hash mismatch: {path}")
    _validate_sha256(
        reference.get(semantic_hash_name),
        label=semantic_hash_name,
    )
    return path


def validate_gate_momentum_history_plan(path: str | Path) -> dict[str, Any]:
    plan = _read_json_object(path)
    if plan.get("schema") != PLAN_SCHEMA:
        raise ValueError("unexpected Gate momentum history plan schema")
    stored_hash = _validate_sha256(plan.get("plan_hash"), label="plan_hash")
    if stored_hash != sha256_json(_payload_without_hash(plan)):
        raise ValueError("Gate momentum history plan hash mismatch")
    if plan.get("mode") != "PlanOnly" or plan.get("research_only") is not True:
        raise ValueError("history plan must remain research-only PlanOnly")
    if plan.get("hypothesis_id") != HYPOTHESIS_ID:
        raise ValueError("history hypothesis mismatch")

    inputs = plan.get("inputs")
    if not isinstance(inputs, Mapping):
        raise ValueError("history plan inputs are missing")
    momentum_path = _validate_file_reference(
        inputs["momentum_plan"],
        semantic_hash_name="plan_hash",
    )
    identity_plan_path = _validate_file_reference(
        inputs["identity_plan"],
        semantic_hash_name="plan_hash",
    )
    identity_result_path = _validate_file_reference(
        inputs["identity_result"],
        semantic_hash_name="artifact_hash",
    )
    gate_path = _validate_file_reference(
        inputs["gate_instruments"],
        semantic_hash_name="content_sha256",
    )
    binance_path = _validate_file_reference(
        inputs["binance_instruments"],
        semantic_hash_name="content_sha256",
    )

    momentum_plan = validate_momentum_archive_plan(
        _read_json_object(momentum_path)
    )
    identity_plan = validate_gate_momentum_identity_plan(identity_plan_path)
    identity_result = validate_gate_momentum_identity_result(
        identity_result_path,
        plan_path=identity_plan_path,
    )
    if inputs["momentum_plan"]["plan_hash"] != momentum_plan["plan_hash"]:
        raise ValueError("history momentum semantic hash mismatch")
    if inputs["identity_plan"]["plan_hash"] != identity_plan["plan_hash"]:
        raise ValueError("history identity plan semantic hash mismatch")
    if inputs["identity_result"]["artifact_hash"] != identity_result["artifact_hash"]:
        raise ValueError("history identity result semantic hash mismatch")
    if (
        inputs["gate_instruments"]["content_sha256"]
        != identity_result["gate_instruments_sha256"]
        or gate_path
        != Path(identity_result["gate_instruments_jsonl_path"]).resolve()
    ):
        raise ValueError("history Gate identity content mismatch")
    if (
        inputs["binance_instruments"]["content_sha256"]
        != identity_result["binance_instruments_sha256"]
        or binance_path
        != Path(identity_result["binance_instruments_jsonl_path"]).resolve()
    ):
        raise ValueError("history Binance identity content mismatch")
    if identity_result.get("accepted_for_history_planonly") is not True:
        raise ValueError("history plan identity verdict is not accepted")

    source = plan.get("source")
    if not isinstance(source, Mapping):
        raise ValueError("history source contract is missing")
    if (
        source.get("provider") != "Tardis.dev"
        or source.get("exchange") != EXCHANGE_ID
        or source.get("grouped_symbol") != GROUPED_SYMBOL
        or source.get("data_types") != list(DATA_TYPES)
        or source.get("gzip_required") is not True
    ):
        raise ValueError("history source contract mismatch")
    if source.get("authentication") != {
        "location": "header",
        "scheme": "Bearer",
        "credential_env": "TARDIS_API_KEY",
        "query_auth_forbidden": True,
        "value_persisted": False,
    }:
        raise ValueError("history authentication contract mismatch")

    history = plan.get("history")
    if not isinstance(history, Mapping):
        raise ValueError("history split contract is missing")
    start = _parse_date(history["history_start"], label="history_start")
    end = _parse_date(
        history["history_end_exclusive"],
        label="history_end_exclusive",
    )
    warmup_end = _parse_date(
        history["warmup_end_exclusive"],
        label="warmup_end_exclusive",
    )
    train_end = _parse_date(
        history["train_end_exclusive"],
        label="train_end_exclusive",
    )
    if (
        (end - start).days != HISTORY_DAYS
        or (warmup_end - start).days != WARMUP_DAYS
        or (train_end - warmup_end).days != TRAIN_DAYS
        or (end - train_end).days != OOS_DAYS
    ):
        raise ValueError("history split lengths mismatch")
    if history.get("oos_folds") != _folds(train_end, end):
        raise ValueError("history OOS folds mismatch")
    if history.get("global_rebalance_anchor") != (
        start + timedelta(days=LOOKBACK_DAYS)
    ).isoformat():
        raise ValueError("history rebalance anchor mismatch")

    outputs = plan.get("outputs")
    if not isinstance(outputs, Mapping) or outputs.get("immutable") is not True:
        raise ValueError("history outputs are missing")
    train_root = Path(outputs["train_cache_root"]).resolve()
    oos_root = Path(outputs["sealed_oos_cache_root"]).resolve()
    _require_disjoint_roots(train_root, oos_root)
    output_values = [
        str(value)
        for key, value in outputs.items()
        if key != "immutable"
    ]
    if len(output_values) != 6 or len(set(output_values)) != 6:
        raise ValueError("history output paths are not distinct")

    expected_tasks = _build_download_tasks(
        history_start=start,
        history_end_exclusive=end,
        warmup_end=warmup_end,
        train_end=train_end,
        train_cache_root=train_root,
        oos_cache_root=oos_root,
    )
    download = plan.get("download")
    if (
        not isinstance(download, Mapping)
        or download.get("tasks") != expected_tasks
        or download.get("task_count") != HISTORY_DAYS * len(DATA_TYPES)
        or download.get("request_concurrency") != MAX_CONCURRENCY
    ):
        raise ValueError("history download task contract mismatch")
    limits = plan.get("limits")
    if not isinstance(limits, Mapping):
        raise ValueError("history runtime limits are missing")
    max_runtime = limits.get("max_runtime_sec")
    if (
        not isinstance(max_runtime, int)
        or not 1 <= max_runtime <= MAX_ALLOWED_RUNTIME_SEC
        or limits.get("absolute_runtime_cap_sec") != MAX_ALLOWED_RUNTIME_SEC
        or limits.get("task_count") != len(expected_tasks)
    ):
        raise ValueError("history runtime limits mismatch")

    if plan.get("strategy") != momentum_plan["strategy"]:
        raise ValueError("history strategy drift")
    if plan.get("costs") != momentum_plan["costs"]:
        raise ValueError("history cost drift")
    if plan.get("quality_contract") != momentum_plan["quality_contract"]:
        raise ValueError("history quality contract drift")
    if plan.get("acceptance") != momentum_plan["acceptance"]:
        raise ValueError("history acceptance drift")

    audit = plan.get("data_access_audit")
    if not isinstance(audit, Mapping) or any(value is not False for value in audit.values()):
        raise ValueError("history PlanOnly data-access audit mismatch")
    safety = plan.get("safety")
    if (
        not isinstance(safety, Mapping)
        or safety.get("history_collect_currently_allowed") is not False
        or safety.get("requires_explicit_visible_collect_approval") is not True
        or any(
            safety.get(key) is not False
            for key in (
                "quality_currently_allowed",
                "train_currently_allowed",
                "oos_currently_allowed",
                "grid_search",
                "retune",
                "execution_probe",
                "paper_forward",
                "live_orders",
                "private_exchange_api_keys",
                "leverage_or_margin",
            )
        )
    ):
        raise ValueError("history safety contract mismatch")

    provenance = plan.get("code_provenance")
    module_path = Path(str(provenance.get("module_path") or "")).resolve()
    if module_path != Path(__file__).resolve():
        raise ValueError("history module path mismatch")
    if provenance.get("module_sha256") != sha256_file(module_path):
        raise ValueError("history module hash mismatch")
    if (
        plan.get("decision")
        != "GATE_MOMENTUM_HISTORY_PLAN_READY_AWAITING_VISIBLE_COLLECT"
        or plan.get("next_allowed_command")
        != "gate-momentum-history-collect-visible"
    ):
        raise ValueError("history PlanOnly decision mismatch")
    return plan


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build and validate a hash-bound Gate momentum history PlanOnly."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    plan_parser = subparsers.add_parser("plan")
    plan_parser.add_argument("--momentum-plan", required=True)
    plan_parser.add_argument("--identity-plan", required=True)
    plan_parser.add_argument("--identity-result", required=True)
    plan_parser.add_argument("--train-cache-root", required=True)
    plan_parser.add_argument("--oos-cache-root", required=True)
    plan_parser.add_argument("--train-normalized-output", required=True)
    plan_parser.add_argument("--oos-normalized-output", required=True)
    plan_parser.add_argument("--history-manifest-output", required=True)
    plan_parser.add_argument("--quality-report-output", required=True)
    plan_parser.add_argument("--history-end-exclusive", required=True)
    plan_parser.add_argument("--frozen-at-utc", required=True)
    plan_parser.add_argument(
        "--max-runtime-sec",
        type=int,
        default=DEFAULT_MAX_RUNTIME_SEC,
    )
    plan_parser.add_argument("--output", required=True)

    validate_parser = subparsers.add_parser("validate-plan")
    validate_parser.add_argument("--plan", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "plan":
        plan = build_gate_momentum_history_plan(
            args.momentum_plan,
            args.identity_plan,
            args.identity_result,
            train_cache_root=args.train_cache_root,
            oos_cache_root=args.oos_cache_root,
            train_normalized_output_path=args.train_normalized_output,
            oos_normalized_output_path=args.oos_normalized_output,
            history_manifest_output_path=args.history_manifest_output,
            quality_report_output_path=args.quality_report_output,
            history_end_exclusive=args.history_end_exclusive,
            frozen_at_utc=args.frozen_at_utc,
            max_runtime_sec=args.max_runtime_sec,
        )
        _write_json_immutable(args.output, plan)
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "validate-plan":
        plan = validate_gate_momentum_history_plan(args.plan)
        print(
            json.dumps(
                {
                    "decision": "GATE_MOMENTUM_HISTORY_PLAN_VALID",
                    "plan_hash": plan["plan_hash"],
                    "task_count": plan["download"]["task_count"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0
    raise AssertionError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
