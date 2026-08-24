from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from autopilot_research_backlog import ensure_backlog


CATALOG_SCHEMA = "trading_mvp_autopilot_research_catalog_v1"
AUDIT_SCHEMA = "trading_mvp_paper_product_readiness_audit_v3"
AUDIT_SCHEMA_V4 = "trading_mvp_paper_product_readiness_audit_v4"
AUDIT_SCHEMA_V5 = "trading_mvp_paper_product_readiness_audit_v5"
AUDIT_SCHEMA_V6 = "trading_mvp_paper_product_readiness_audit_v6"
AUDIT_SCHEMA_V8 = "trading_mvp_paper_product_readiness_audit_v8"
AUDIT_SCHEMA_V10 = "trading_mvp_paper_product_readiness_audit_v10"
AUDIT_SCHEMA_V11 = "trading_mvp_paper_product_readiness_audit_v11"
AUDIT_SCHEMA_V12 = "fast_first_paper_product_readiness_audit_v12"
POLICY_SCHEMA = "trading_mvp_autopilot_policy_v1"
BACKLOG_SCHEMA = "trading_mvp_autopilot_research_backlog_v1"
RESEARCH_ROOT = (
    r"E:\ZolotyayLopata-data\exports\trading-mvp\autopilot\research"
)

TASK_TEMPLATES_V12: dict[str, dict[str, Any]] = {
    "funding_directional_momentum_hypothesis_v1": {
        "output_path": rf"{RESEARCH_ROOT}\funding-directional-momentum-hypothesis-v1.json",
        "objective": (
            "Define a directional momentum hypothesis using extreme funding rates "
            "as a signal. Naked positions only (no spot hedging). Explore thresholds "
            "like 15 bps or 20 bps and holding periods like 12h or 24h."
        ),
        "allowed_inputs": [
            "docs/agent-log/trading-mvp-autopilot-state.json",
            "trading_mvp/src/funding_directional_momentum_v1.py"
        ],
    },
    "paper_code_provenance_merkle_v10": {
        "output_path": rf"{RESEARCH_ROOT}\paper-code-provenance-merkle-v10.json",
        "objective": (
            "Freeze the code provenance for funding directional momentum."
        ),
        "allowed_inputs": [
            "trading_mvp/src",
        ],
    },
}

TASK_TEMPLATES_V11: dict[str, dict[str, Any]] = {
    "aggressive_momentum_hypothesis_v1": {
        "output_path": rf"{RESEARCH_ROOT}\aggressive-momentum-hypothesis-v1.json",
        "objective": (
            "Define a high-frequency impulse breakout hypothesis with short lookback, "
            "aggressive trailing stops, and early breakout entries for slow liquidity."
        ),
        "allowed_inputs": [
            "docs/agent-log/trading-mvp-autopilot-state.json",
            "trading_mvp/src/slow_liquidity_feature_normalizer.py"
        ],
    },
    "paper_code_provenance_merkle_v9": {
        "output_path": rf"{RESEARCH_ROOT}\paper-code-provenance-merkle-v9.json",
        "objective": (
            "Freeze the corrected dynamic readiness and same-scope census code "
            "in a deterministic code-only Merkle baseline. No data artifacts "
            "or network access."
        ),
        "allowed_inputs": [
            "trading_mvp/src",
            "trading_mvp/tests",
            "trading_mvp/run_mvp.ps1",
            "tools",
        ],
    },
}


TASK_TEMPLATES: dict[str, dict[str, Any]] = {
    "paper_code_provenance_merkle_v2": {
        "output_path": rf"{RESEARCH_ROOT}\paper-code-provenance-merkle-v2.json",
        "objective": (
            "Refresh the deterministic code-only Merkle baseline after catalog "
            "v2 implementation. Do not stage, revert, commit or copy data artifacts."
        ),
        "allowed_inputs": [
            "trading_mvp/src",
            "trading_mvp/tests",
            "trading_mvp/run_mvp.ps1",
            "tools",
            "AGENTS.md",
        ],
    },
    "paper_public_retry_rate_limit_fixture_v1": {
        "output_path": rf"{RESEARCH_ROOT}\paper-public-retry-rate-limit-fixture-v1.json",
        "objective": (
            "Implement deterministic fixture-only token-bucket, bounded retry "
            "and Retry-After behavior for the frozen public reader. No network requests."
        ),
        "allowed_inputs": [
            "trading_mvp/src/paper_public_reader_contract.py",
            "trading_mvp/src/paper_public_reader.py",
            "trading_mvp/tests",
            rf"{RESEARCH_ROOT}\paper-public-reader-contract-v1.json",
        ],
    },
    "paper_public_snapshot_observer_bridge_v1": {
        "output_path": rf"{RESEARCH_ROOT}\paper-public-snapshot-observer-bridge-v1.json",
        "objective": (
            "Implement a fixture-only bridge from two normalized venue snapshots "
            "to one hash-bound dual-venue observer health sample. No network or OMS mutation."
        ),
        "allowed_inputs": [
            "trading_mvp/src/paper_public_reader.py",
            "trading_mvp/src/paper_observer_runtime.py",
            "trading_mvp/tests",
            rf"{RESEARCH_ROOT}\paper-public-reader-fixture-v1.json",
        ],
    },
    "paper_public_transport_adapter_v1": {
        "output_path": rf"{RESEARCH_ROOT}\paper-public-transport-adapter-v1.json",
        "objective": (
            "Implement and fixture-test a requests-based public GET transport "
            "behind the frozen allowlist, timeout, byte-limit and no-auth boundaries. "
            "Do not make actual network requests."
        ),
        "allowed_inputs": [
            "trading_mvp/src/paper_public_reader_contract.py",
            "trading_mvp/src/paper_public_reader.py",
            "trading_mvp/src/paper_log_redaction.py",
            "trading_mvp/tests",
            rf"{RESEARCH_ROOT}\paper-public-reader-contract-v1.json",
        ],
    },
    "paper_product_readiness_audit_v4": {
        "output_path": rf"{RESEARCH_ROOT}\paper-product-readiness-audit-v4.json",
        "objective": (
            "Re-audit fixture/public-data-plane readiness after catalog v3, "
            "preserve PIT evidence blockers and emit the next bounded gap list. "
            "No hypothesis change, network collection, PnL or returns."
        ),
        "allowed_inputs": [
            "trading_mvp/src",
            "trading_mvp/tests",
            "docs/agent-log",
            RESEARCH_ROOT,
        ],
    },
}
TASK_TEMPLATES_V4: dict[str, dict[str, Any]] = {
    "paper_code_provenance_merkle_v3": {
        "output_path": rf"{RESEARCH_ROOT}\paper-code-provenance-merkle-v3.json",
        "objective": (
            "Refresh the deterministic code-only Merkle baseline after retry, "
            "bridge, transport and v4 audit implementation. Do not stage, "
            "revert, commit or copy data artifacts."
        ),
        "allowed_inputs": [
            "trading_mvp/src",
            "trading_mvp/tests",
            "trading_mvp/run_mvp.ps1",
            "tools",
            "AGENTS.md",
        ],
    },
    "paper_public_reader_transport_wiring_fixture_v1": {
        "output_path": (
            rf"{RESEARCH_ROOT}\paper-public-reader-transport-wiring-fixture-v1.json"
        ),
        "objective": (
            "Wire the requests transport through the normalized public reader "
            "and prove the full path with a fake session only. No network requests."
        ),
        "allowed_inputs": [
            "trading_mvp/src/paper_public_reader_contract.py",
            "trading_mvp/src/paper_public_reader.py",
            "trading_mvp/tests",
            rf"{RESEARCH_ROOT}\paper-public-reader-contract-v1.json",
            rf"{RESEARCH_ROOT}\paper-public-transport-adapter-v1.json",
        ],
    },
    "paper_public_streaming_byte_limit_fixture_v1": {
        "output_path": (
            rf"{RESEARCH_ROOT}\paper-public-streaming-byte-limit-fixture-v1.json"
        ),
        "objective": (
            "Prove the streamed response byte limit without Content-Length, "
            "including response close and fail-closed classification. No network."
        ),
        "allowed_inputs": [
            "trading_mvp/src/paper_public_reader.py",
            "trading_mvp/tests",
            rf"{RESEARCH_ROOT}\paper-public-transport-adapter-v1.json",
        ],
    },
    "paper_public_health_contract_binding_fixture_v1": {
        "output_path": (
            rf"{RESEARCH_ROOT}\paper-public-health-contract-binding-fixture-v1.json"
        ),
        "objective": (
            "Bind the hash-bound public snapshot bridge sample to the frozen "
            "venue-health contract and prove that no OMS transition occurs "
            "without a healthy decision. No network or OMS mutation."
        ),
        "allowed_inputs": [
            "trading_mvp/src/paper_observer_runtime.py",
            "trading_mvp/src/paper_contract_validator.py",
            "trading_mvp/tests",
            rf"{RESEARCH_ROOT}\paper-public-snapshot-observer-bridge-v1.json",
            rf"{RESEARCH_ROOT}\paper-venue-health-gate-contract-v1.json",
        ],
    },
    "paper_product_readiness_audit_v5": {
        "output_path": rf"{RESEARCH_ROOT}\paper-product-readiness-audit-v5.json",
        "objective": (
            "Re-audit public reader runtime wiring and health binding after "
            "catalog v4 while preserving PIT, paper and live evidence blockers. "
            "No network, returns, PnL or hypothesis changes."
        ),
        "allowed_inputs": [
            "trading_mvp/src",
            "trading_mvp/tests",
            "docs/agent-log",
            RESEARCH_ROOT,
        ],
    },
}
TASK_TEMPLATES_V5: dict[str, dict[str, Any]] = {
    "paper_code_provenance_merkle_v4": {
        "output_path": rf"{RESEARCH_ROOT}\paper-code-provenance-merkle-v4.json",
        "objective": (
            "Refresh the deterministic code-only Merkle baseline after "
            "transport wiring, streamed-limit, health binding and v5 audit "
            "implementation. Do not stage, revert, commit or copy data artifacts."
        ),
        "allowed_inputs": [
            "trading_mvp/src",
            "trading_mvp/tests",
            "trading_mvp/run_mvp.ps1",
            "tools",
            "AGENTS.md",
        ],
    },
    "paper_public_system_clock_fixture_v1": {
        "output_path": (
            rf"{RESEARCH_ROOT}\paper-public-system-clock-fixture-v1.json"
        ),
        "objective": (
            "Implement a bounded runtime clock contract for the normalized "
            "public reader and prove sleep, monotonic refill and Retry-After "
            "handling with a fake clock only. No network."
        ),
        "allowed_inputs": [
            "trading_mvp/src/paper_public_reader.py",
            "trading_mvp/tests",
            rf"{RESEARCH_ROOT}\paper-public-reader-contract-v1.json",
        ],
    },
    "paper_public_transport_retry_wiring_fixture_v2": {
        "output_path": (
            rf"{RESEARCH_ROOT}\paper-public-transport-retry-wiring-fixture-v2.json"
        ),
        "objective": (
            "Prove bounded retry and token-bucket behavior through the "
            "requests transport and normalized reader using a fake session. "
            "No network requests."
        ),
        "allowed_inputs": [
            "trading_mvp/src/paper_public_reader.py",
            "trading_mvp/tests",
            rf"{RESEARCH_ROOT}\paper-public-reader-contract-v1.json",
            rf"{RESEARCH_ROOT}\paper-public-reader-transport-wiring-fixture-v1.json",
        ],
    },
    "paper_public_cache_transport_integration_fixture_v1": {
        "output_path": (
            rf"{RESEARCH_ROOT}\paper-public-cache-transport-integration-fixture-v1.json"
        ),
        "objective": (
            "Bind normalized transport output to the content-addressed public "
            "cache and prove deterministic replay with a fake session only. "
            "No network or OMS mutation."
        ),
        "allowed_inputs": [
            "trading_mvp/src/paper_public_reader.py",
            "trading_mvp/src/paper_public_cache.py",
            "trading_mvp/tests",
            rf"{RESEARCH_ROOT}\paper-public-cache-idempotency-v1.json",
            rf"{RESEARCH_ROOT}\paper-public-reader-transport-wiring-fixture-v1.json",
        ],
    },
    "paper_product_readiness_audit_v6": {
        "output_path": rf"{RESEARCH_ROOT}\paper-product-readiness-audit-v6.json",
        "objective": (
            "Re-audit runtime clock, retry and cache transport wiring while "
            "preserving PIT, paper and live evidence blockers. No network, "
            "returns, PnL or hypothesis changes."
        ),
        "allowed_inputs": [
            "trading_mvp/src",
            "trading_mvp/tests",
            "docs/agent-log",
            RESEARCH_ROOT,
        ],
    },
}
TASK_TEMPLATES_V6: dict[str, dict[str, Any]] = {
    "paper_code_provenance_merkle_v5": {
        "output_path": rf"{RESEARCH_ROOT}\paper-code-provenance-merkle-v5.json",
        "objective": (
            "Refresh the deterministic code-only Merkle baseline after runtime "
            "clock, retry, cache integration and v6 audit implementation. Do "
            "not stage, revert, commit or copy data artifacts."
        ),
        "allowed_inputs": [
            "trading_mvp/src",
            "trading_mvp/tests",
            "trading_mvp/run_mvp.ps1",
            "tools",
            "AGENTS.md",
        ],
    },
    "paper_public_runtime_reader_factory_fixture_v1": {
        "output_path": (
            rf"{RESEARCH_ROOT}\paper-public-runtime-reader-factory-fixture-v1.json"
        ),
        "objective": (
            "Bind SystemClock, requests transport and normalized reader behind "
            "one fail-closed factory and prove it with a fake session. No network."
        ),
        "allowed_inputs": [
            "trading_mvp/src/paper_public_reader.py",
            "trading_mvp/tests",
            rf"{RESEARCH_ROOT}\paper-public-reader-contract-v1.json",
            rf"{RESEARCH_ROOT}\paper-public-system-clock-fixture-v1.json",
        ],
    },
    "paper_public_endpoint_contract_parity_fixture_v1": {
        "output_path": (
            rf"{RESEARCH_ROOT}\paper-public-endpoint-contract-parity-fixture-v1.json"
        ),
        "objective": (
            "Prove every frozen MEXC/Gate endpoint maps to its expected "
            "allowlist and normalizer using fixtures only. No network."
        ),
        "allowed_inputs": [
            "trading_mvp/src/paper_public_reader_contract.py",
            "trading_mvp/src/paper_public_reader.py",
            "trading_mvp/tests",
            rf"{RESEARCH_ROOT}\paper-public-reader-contract-v1.json",
        ],
    },
    "paper_public_readonly_probe_plan_v1": {
        "output_path": (
            rf"{RESEARCH_ROOT}\paper-public-readonly-probe-plan-v1.json"
        ),
        "objective": (
            "Freeze a bounded public read-only execution probe plan without "
            "starting network requests, market-data writers or OMS mutations."
        ),
        "allowed_inputs": [
            "trading_mvp/src/paper_public_reader_contract.py",
            "trading_mvp/src/paper_public_reader.py",
            "trading_mvp/tests",
            "docs/agent-log",
            rf"{RESEARCH_ROOT}\paper-public-reader-contract-v1.json",
        ],
    },
    "paper_product_readiness_audit_v7": {
        "output_path": rf"{RESEARCH_ROOT}\paper-product-readiness-audit-v7.json",
        "objective": (
            "Re-audit runtime factory, endpoint parity and read-only probe plan "
            "while preserving PIT, paper and live evidence blockers. No network, "
            "returns, PnL or hypothesis changes."
        ),
        "allowed_inputs": [
            "trading_mvp/src",
            "trading_mvp/tests",
            "docs/agent-log",
            RESEARCH_ROOT,
        ],
    },
}
TASK_TEMPLATES_V8: dict[str, dict[str, Any]] = {
    "paper_code_provenance_merkle_v6": {
        "output_path": rf"{RESEARCH_ROOT}\paper-code-provenance-merkle-v6.json",
        "objective": (
            "Refresh the deterministic code-only Merkle baseline after the v3 "
            "public probe compatibility and v8 audit implementation. Do not "
            "stage, revert, commit or copy data artifacts."
        ),
        "allowed_inputs": [
            "trading_mvp/src",
            "trading_mvp/tests",
            "trading_mvp/run_mvp.ps1",
            "tools",
            "AGENTS.md",
        ],
    },
    "paper_public_probe_evidence_observer_binding_fixture_v1": {
        "output_path": (
            rf"{RESEARCH_ROOT}"
            r"\paper-public-probe-evidence-observer-binding-fixture-v1.json"
        ),
        "objective": (
            "Bind accepted immutable public probe v3 evidence to one fail-closed "
            "observer input and prove no OMS mutation. Offline only; do not read "
            "returns, PnL or OOS."
        ),
        "allowed_inputs": [
            "trading_mvp/src/paper_public_readonly_probe.py",
            "trading_mvp/src/paper_observer_runtime.py",
            "trading_mvp/tests",
            rf"{RESEARCH_ROOT}\paper-public-readonly-probe-evidence-v3.json",
            rf"{RESEARCH_ROOT}\paper-public-readonly-probe-plan-v3.json",
        ],
    },
    "paper_product_readiness_audit_v9": {
        "output_path": rf"{RESEARCH_ROOT}\paper-product-readiness-audit-v9.json",
        "objective": (
            "Re-audit public probe evidence binding after catalog v8 while "
            "preserving PIT, edge, paper-forward and live evidence blockers. "
            "No network, returns, PnL, OOS or hypothesis changes."
        ),
        "allowed_inputs": [
            "trading_mvp/src",
            "trading_mvp/tests",
            "docs/agent-log",
            RESEARCH_ROOT,
        ],
    },
}
TASK_TEMPLATES_V10: dict[str, dict[str, Any]] = {
    "same_scope_strategy_census_v2": {
        "output_path": rf"{RESEARCH_ROOT}\same-scope-strategy-census-v2.json",
        "objective": (
            "Recheck whether any materially distinct strategy can be honestly "
            "tested on current immutable metadata. Do not read market rows, "
            "returns, PnL or OOS and do not create a new hypothesis."
        ),
        "allowed_inputs": [
            rf"{RESEARCH_ROOT}\same-scope-hypothesis-census-v1.json",
            "docs/agent-log/readiness/cross-venue-basis-terminal-currentness-recheck-20260803-v1.json",
            "docs/agent-log/trading-mvp-autopilot-state.json",
        ],
    },
    "paper_code_provenance_merkle_v8": {
        "output_path": rf"{RESEARCH_ROOT}\paper-code-provenance-merkle-v8.json",
        "objective": (
            "Freeze the corrected dynamic readiness and same-scope census code "
            "in a deterministic code-only Merkle baseline. No data artifacts "
            "or network access."
        ),
        "allowed_inputs": [
            "trading_mvp/src",
            "trading_mvp/tests",
            "trading_mvp/run_mvp.ps1",
            "tools",
            "AGENTS.md",
        ],
    },
    "paper_product_readiness_audit_v11": {
        "output_path": rf"{RESEARCH_ROOT}\paper-product-readiness-audit-v11.json",
        "objective": (
            "Bind the corrected dynamic PIT counters, current code provenance "
            "and same-scope strategy census into one immutable readiness audit. "
            "No collector, returns, PnL, OOS, grid or hypothesis change."
        ),
        "allowed_inputs": [
            "trading_mvp/src",
            "trading_mvp/tests",
            "docs/agent-log",
            RESEARCH_ROOT,
        ],
    },
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_json(path: str | Path) -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    payload = json.loads(target.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {target}")
    return payload


def derive_catalog(
    *,
    audit_path: str | Path,
    catalog_id: str,
) -> dict[str, Any]:
    audit_target = Path(audit_path).expanduser().resolve()
    audit = _read_json(audit_target)
    audit_schema = audit.get("schema")
    if audit_schema == AUDIT_SCHEMA:
        templates = TASK_TEMPLATES
        expected_action = (
            "derive_and_install_catalog_v3_then_continue_bounded_offline_work"
        )
    elif audit_schema == AUDIT_SCHEMA_V4:
        templates = TASK_TEMPLATES_V4
        expected_action = (
            "derive_and_install_catalog_v4_then_continue_bounded_offline_work"
        )
    elif audit_schema == AUDIT_SCHEMA_V5:
        templates = TASK_TEMPLATES_V5
        expected_action = (
            "derive_and_install_catalog_v5_then_continue_bounded_offline_work"
        )
    elif audit_schema == AUDIT_SCHEMA_V6:
        templates = TASK_TEMPLATES_V6
        expected_action = (
            "derive_and_install_catalog_v6_then_continue_bounded_offline_work"
        )
    elif audit_schema == AUDIT_SCHEMA_V8:
        templates = TASK_TEMPLATES_V8
        expected_action = (
            "derive_and_install_catalog_v8_then_continue_bounded_offline_work"
        )
    elif audit_schema == AUDIT_SCHEMA_V10:
        templates = TASK_TEMPLATES_V10
        expected_action = (
            "derive_and_install_catalog_v10_then_continue_bounded_offline_work"
        )
    elif audit_schema == AUDIT_SCHEMA_V12:
        templates = TASK_TEMPLATES_V12
        expected_action = (
            "derive_and_install_catalog_v12_then_continue_bounded_offline_work"
        )
    elif audit_schema == AUDIT_SCHEMA_V11:
        templates = TASK_TEMPLATES_V11
        expected_action = (
            "derive_and_install_catalog_v11_then_continue_bounded_offline_work"
        )
    else:
        raise ValueError("unsupported readiness audit schema")
    if audit.get("next_allowed_action") != expected_action:
        raise ValueError("readiness audit does not authorize catalog refresh")
    requirements = audit.get("next_bounded_catalog_requirement")
    if not isinstance(requirements, list) or not requirements:
        raise ValueError("readiness audit has no bounded catalog requirements")
    tasks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for requirement in requirements:
        if not isinstance(requirement, Mapping):
            raise ValueError("catalog requirement must be an object")
        task_id = str(requirement.get("id") or "")
        if task_id in seen or task_id not in templates:
            raise ValueError(f"unknown or duplicate bounded task: {task_id}")
        if requirement.get("network") is not False:
            raise ValueError(f"bounded task unexpectedly permits network: {task_id}")
        runtime = int(requirement.get("maximum_runtime_sec") or 0)
        if runtime <= 0 or runtime > 1800:
            raise ValueError(f"bounded task runtime is invalid: {task_id}")
        tasks.append(
            {
                "id": task_id,
                "max_runtime_sec": runtime,
                **templates[task_id],
            }
        )
        seen.add(task_id)
    catalog = {
        "schema": CATALOG_SCHEMA,
        "catalog_id": catalog_id,
        "project": "trading_mvp",
        "mode": "bounded_offline_public_data_plane_readiness",
        "parent_audit": {
            "path": str(audit_target),
            "file_sha256": sha256_file(audit_target),
            "deterministic_result_hash": audit.get(
                "deterministic_result_hash"
            ),
        },
        "constraints": {
            "max_runtime_sec_per_task": 1800,
            "one_task_at_a_time": True,
            "network_access": False,
            "market_data_writer": False,
            "returns_or_pnl_read": False,
            "new_hypothesis": False,
            "grid_or_retune": False,
            "paper_positions": False,
            "live_orders": False,
            "private_api_keys": False,
            "leverage_or_margin": False,
        },
        "tasks": tasks,
    }
    return catalog


def _write_json_immutable(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"catalog already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _write_or_reuse_catalog(
    path: Path,
    payload: Mapping[str, Any],
    *,
    reuse_existing: bool,
) -> str:
    if not path.exists():
        _write_json_immutable(path, payload)
        return "CATALOG_DERIVED"
    if not reuse_existing:
        raise FileExistsError(f"catalog already exists: {path}")
    existing = _read_json(path)
    if existing != dict(payload):
        raise ValueError(
            "existing catalog does not match the deterministic derivation"
        )
    return "CATALOG_REUSED"


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def activate_catalog(
    *,
    catalog_path: str | Path,
    policy_path: str | Path,
    backlog_path: str | Path,
) -> dict[str, Any]:
    catalog_target = Path(catalog_path).expanduser().resolve()
    policy_target = Path(policy_path).expanduser().resolve()
    backlog_target = Path(backlog_path).expanduser().resolve()
    catalog = _read_json(catalog_target)
    if catalog.get("schema") != CATALOG_SCHEMA:
        raise ValueError("invalid catalog schema")
    policy = _read_json(policy_target)
    backlog = _read_json(backlog_target)
    if policy.get("schema") != POLICY_SCHEMA:
        raise ValueError("invalid autopilot policy schema")
    if backlog.get("schema") != BACKLOG_SCHEMA:
        raise ValueError("invalid autopilot backlog schema")
    if any(
        task.get("status") in {"PENDING", "RUNNING"}
        for task in backlog.get("tasks") or []
    ):
        raise ValueError("cannot replace catalog while backlog has active tasks")
    digest = sha256_file(catalog_target)
    policy["bounded_research_backlog"]["catalog_path"] = str(catalog_target)
    policy["bounded_research_backlog"]["catalog_file_sha256"] = digest
    backlog["catalog_path"] = str(catalog_target)
    backlog["catalog_file_sha256"] = digest
    backlog["updated_at_utc"] = _utc_now()
    _write_json_atomic(policy_target, policy)
    _write_json_atomic(backlog_target, backlog)
    refill = ensure_backlog(backlog_target)
    expected_ids = [str(task["id"]) for task in catalog["tasks"]]
    if refill.get("status") != "REFILLED":
        raise RuntimeError(f"catalog activation did not refill backlog: {refill}")
    if refill.get("added_task_ids") != expected_ids:
        raise RuntimeError("catalog activation added an unexpected task set")
    return {
        "status": "CATALOG_ACTIVATED_AND_BACKLOG_REFILLED",
        "catalog_path": str(catalog_target),
        "catalog_file_sha256": digest,
        "added_task_ids": expected_ids,
        "policy_path": str(policy_target),
        "backlog_path": str(backlog_target),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Derive and activate a bounded research catalog"
    )
    parser.add_argument("--audit", required=True)
    parser.add_argument("--catalog-output", required=True)
    parser.add_argument("--catalog-id", required=True)
    parser.add_argument("--policy")
    parser.add_argument("--backlog")
    parser.add_argument("--activate", action="store_true")
    parser.add_argument("--reuse-existing", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    catalog = derive_catalog(
        audit_path=args.audit,
        catalog_id=args.catalog_id,
    )
    catalog_target = Path(args.catalog_output).expanduser().resolve()
    status = _write_or_reuse_catalog(
        catalog_target,
        catalog,
        reuse_existing=args.reuse_existing,
    )
    result: dict[str, Any] = {
        "status": status,
        "catalog_path": str(catalog_target),
        "catalog_file_sha256": sha256_file(catalog_target),
        "task_ids": [task["id"] for task in catalog["tasks"]],
    }
    if args.activate:
        if not args.policy or not args.backlog:
            raise ValueError("--policy and --backlog are required with --activate")
        result["activation"] = activate_catalog(
            catalog_path=catalog_target,
            policy_path=args.policy,
            backlog_path=args.backlog,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
