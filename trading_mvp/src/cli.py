from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

from basis import (
    BasisScanConfig,
    FundingAcceptanceConfig,
    FundingBacktestConfig,
    FundingDataQualityConfig,
    FundingOosConfig,
    FundingRankConfig,
    FundingSensitivityConfig,
    FundingStressConfig,
    FundingWalkForwardConfig,
    collect_funding_file,
    create_funding_paper_forward_plan_file,
    default_funding_backtest_path,
    default_funding_collect_path,
    default_funding_coverage_path,
    default_funding_collect_diagnostics_path,
    default_funding_decision_report_path,
    default_funding_final_review_path,
    default_funding_frontier_report_path,
    default_funding_gate_report_path,
    default_funding_goal_audit_path,
    default_funding_oos_backtest_path,
    default_funding_paper_decision_report_path,
    default_funding_paper_forward_plan_path,
    default_funding_postprocess_output,
    default_funding_progress_report_path,
    default_funding_postprocess_summary_path,
    default_funding_rank_path,
    default_funding_regime_report_path,
    default_funding_sensitivity_path,
    default_funding_wait_ready_path,
    default_funding_walk_forward_path,
    funding_collect_status,
    funding_collect_diagnostics_file,
    funding_decision_report,
    funding_frontier_report_file,
    funding_gate_report_file,
    funding_goal_audit,
    funding_paper_decision_report,
    funding_progress_report_file,
    funding_regime_report_file,
    rank_funding_file,
    run_funding_backtest_file,
    run_funding_coverage_file,
    run_funding_oos_backtest_file,
    run_funding_paper_forward_file,
    run_funding_postprocess_file,
    run_funding_final_review_file,
    run_funding_research_finalize_file,
    run_funding_scan_file,
    run_funding_sensitivity_file,
    run_funding_walk_forward_backtest_file,
    wait_funding_ready,
    write_funding_quality_universe_file,
)
from collector import BinanceCollector
from config import AppConfig, load_config
from experiments import (
    append_experiment_record,
    default_experiment_ledger_path,
    default_setup_registry_path,
    extract_metrics_from_artifact,
    make_experiment_record,
    parse_json_object,
    summarize_experiment_ledger,
    write_setup_registry,
)
from funding_pressure_reversal import (
    evaluate_plan as evaluate_funding_pressure_plan,
    validate_evaluator_readiness as validate_funding_pressure_readiness,
)
from wick_rejection_reversal import (
    evaluate_plan as evaluate_wick_rejection_plan,
    validate_evaluator_readiness as validate_wick_rejection_readiness,
)
from event_labeler import (
    EventQualityConfig,
    default_event_quality_path,
    run_event_quality_report_file,
)
from event_slicer import (
    EventSliceConfig,
    default_event_slice_path,
    run_event_slice_optimizer_file,
)
from event_validation import (
    EventValidationConfig,
    default_event_validation_path,
    run_event_validation_file,
)
from cross_venue_dislocation import (
    CrossVenueDislocationConfig,
    default_cross_venue_dislocation_path,
    run_cross_venue_dislocation_file,
)
from perp_replay import (
    default_perp_grid_path,
    default_perp_replay_path,
    run_perp_grid_search_file,
    run_perp_replay_file,
)
from perp_collector import (
    PerpCollectConfig,
    collect_perp_rest_file,
    default_perp_collect_path,
)
from perp_report import (
    default_perp_report_path,
    run_perp_report_file,
)
from perp_postprocess import (
    PerpPostprocessConfig,
    default_perp_postprocess_output,
    default_perp_postprocess_replay_config,
    run_perp_postprocess_file,
)
from multi_bot import (
    MultiExchangePaperBot,
    build_pairs_for_universe,
    multi_run_output_path,
    save_multi_run,
)
from trading import (
    Backtester,
    load_snapshots,
    save_json,
    utc_stamp,
)
from universe import (
    BINANCE_EXCHANGE_INFO_URL,
    COINPAPRIKA_TICKERS_URL,
    binance_assets_from_exchange_info,
    fetch_json,
    no_binance_rows,
    write_universe_files,
)
from ws_collector import (
    WS_ADAPTERS,
    collect_ws_markets,
    save_ws_manifest,
    ws_manifest_path,
)
from ws_grid_search import (
    default_grid_path,
    parse_float_list,
    parse_int_list,
    parse_str_list,
    run_grid_search_file,
)
from ws_normalizer import (
    default_normalized_path,
    normalize_ws_files,
)
from ws_data_quality import (
    WsDataQualityConfig,
    default_ws_data_quality_path,
    run_ws_data_quality_file,
)
from ws_postprocess import (
    default_ws_postprocess_normalized_path,
    default_ws_postprocess_quality_path,
    default_ws_postprocess_report_path,
    run_ws_postprocess_file,
)
from ws_replay import (
    EventDrivenReplayBacktester,
    ReplayConfig,
    default_replay_path,
    load_normalized_events,
    save_replay_result,
)

AUTO_FUNDING_OOS_OUTPUT = "__auto__"
AUTO_FUNDING_WALK_FORWARD_OUTPUT = "__auto__"
FUNDING_STRICT_REQUIRED_ROW_FIELDS = "spot_bid_qty,spot_ask_qty,spot_top_min_notional_quote"
FUNDING_STRICT_RESEARCH_PRESET = {
    "allow_partial": False,
    "min_basis_bps": 0.0,
    "min_expected_net_carry_bps": 0.0,
    "min_risk_adjusted_edge_bps": 0.0,
    "basis_risk_multiplier": 1.0,
    "spread_risk_multiplier": 0.5,
    "max_break_even_hours": 24.0,
    "min_spot_top_notional_quote": 500.0,
    "quality_required_row_fields": FUNDING_STRICT_REQUIRED_ROW_FIELDS,
    "quality_min_required_row_field_presence": 1.0,
    "stress_enabled": True,
    "stress_adverse_basis_bps": 5.0,
    "stress_spread_widen_bps": 2.0,
    "stress_funding_flip_bps": 2.0,
    "stress_min_net_pnl_quote": 0.0,
    "stress_max_drawdown_quote": 5.0,
    "sensitivity_oos": True,
    "sensitivity_walk_forward": True,
    "oos_min_train_span_hours": 6.0,
    "oos_min_span_hours": 6.0,
    "walk_min_windows": 3,
    "walk_min_accepted_windows": 3,
    "walk_min_accepted_ratio": 1.0,
    "walk_min_train_span_hours": 6.0,
    "walk_min_test_span_hours": 6.0,
    "quality_min_rows": 1000,
    "quality_min_markets": 5,
    "quality_min_completed_cycles": 250,
    "quality_min_unique_cycles": 250,
    "quality_min_avg_rows_per_cycle": 20.0,
    "quality_min_min_rows_per_cycle": 20,
    "quality_max_error_rate": 0.30,
    "quality_max_cycle_market_duplicate_rate": 0.01,
    "accept_min_markets": 2,
    "accept_max_market_trade_share": 0.65,
    "accept_min_exchanges": 2,
    "accept_max_exchange_trade_share": 0.75,
    "accept_min_profitable_windows": 3,
    "accept_max_window_pnl_share": 0.60,
    "min_forward_hours": 24.0,
    "min_forward_rows": 100,
    "min_forward_markets": 2,
}


def _ensure_dir(path: str) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _parse_optional_csv(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _apply_funding_strict_research_preset(args: argparse.Namespace) -> argparse.Namespace:
    if args.command not in {"funding-status", "funding-collect-diagnostics", "funding-rank", "funding-gate-report", "funding-regime-report", "funding-frontier-report", "funding-decision-report", "funding-progress-report", "funding-sensitivity", "funding-walk-forward", "funding-postprocess", "funding-finalize", "funding-final-review", "funding-goal-audit", "funding-wait-ready"}:
        return args
    if not getattr(args, "strict_research", False):
        return args
    for key, value in FUNDING_STRICT_RESEARCH_PRESET.items():
        if hasattr(args, key):
            setattr(args, key, value)
    if args.command == "funding-postprocess" and not getattr(args, "oos_output", None):
        args.oos_output = AUTO_FUNDING_OOS_OUTPUT
    if args.command == "funding-postprocess" and not getattr(args, "walk_forward_output", None):
        args.walk_forward_output = AUTO_FUNDING_WALK_FORWARD_OUTPUT
    return args


def _latest_jsonl(raw_dir: Path, symbol: str) -> Path:
    files = list(raw_dir.glob(f"{symbol}_*.jsonl"))
    if not files:
        raise FileNotFoundError(f"В {raw_dir} нет файлов {symbol}_*.jsonl")
    return max(files, key=lambda p: p.stat().st_mtime)


def cmd_collect(cfg: AppConfig, seconds: int) -> None:
    out_dir = _ensure_dir(cfg.paths.raw_dir)
    filename = f"{cfg.exchange.symbol}_{utc_stamp()}.jsonl"
    out = out_dir / filename
    collector = BinanceCollector(cfg.exchange)
    result = collector.collect(duration_sec=seconds, out_path=out)
    print(json.dumps({"ok": True, "collected_file": str(result)}, ensure_ascii=False))


def cmd_backtest(cfg: AppConfig, input_path: str | None, qty: float) -> None:
    raw_dir = _ensure_dir(cfg.paths.raw_dir)
    bt_dir = _ensure_dir(cfg.paths.backtest_dir)
    src = Path(input_path) if input_path else _latest_jsonl(raw_dir, cfg.exchange.symbol)
    snapshots = load_snapshots(src)
    bt = Backtester(cfg.strategy, cfg.risk)
    payload = bt.run(snapshots=snapshots, qty=qty)
    out_file = bt_dir / f"backtest_{cfg.exchange.symbol}_{utc_stamp()}.json"
    save_json(out_file, payload)
    print(json.dumps({"ok": True, "input": str(src), "output": str(out_file), "metrics": payload["metrics"]}, ensure_ascii=False))


def cmd_run(cfg: AppConfig, mode: str, cycles: int, qty: float) -> None:
    run_dir = _ensure_dir(cfg.paths.run_dir)
    collector = BinanceCollector(cfg.exchange)
    bt = Backtester(cfg.strategy, cfg.risk)

    snapshots = []
    for _ in range(cycles):
        depth = collector._fetch_depth()  # noqa: SLF001
        trades = collector._fetch_trades()  # noqa: SLF001
        snapshots.append(
            {
                "ts": __import__("time").time(),
                "symbol": cfg.exchange.symbol,
                **depth,
                **trades,
            }
        )
        __import__("time").sleep(cfg.exchange.poll_interval_sec)

    backtest_payload = bt.run(snapshots=snapshots, qty=qty)

    execution_log = {"mode": mode, "orders": []}
    execution_log["orders"].append({"info": "paper mode: ордера не отправлялись"})

    payload = {
        "metrics": backtest_payload["metrics"],
        "trade_count": len(backtest_payload["trades"]),
        "execution": execution_log,
    }
    out_file = run_dir / f"run_{cfg.exchange.symbol}_{mode}_{utc_stamp()}.json"
    save_json(out_file, payload)
    print(json.dumps({"ok": True, "output": str(out_file), "metrics": payload["metrics"]}, ensure_ascii=False))


def cmd_universe(cfg: AppConfig, date_stamp: str | None, top_preview: int) -> None:
    out_dir = _ensure_dir(cfg.paths.universe_dir)
    exchange_info = fetch_json(BINANCE_EXCHANGE_INFO_URL, timeout_sec=cfg.exchange.timeout_sec)
    binance_assets = binance_assets_from_exchange_info(exchange_info)
    tickers = fetch_json(COINPAPRIKA_TICKERS_URL, timeout_sec=cfg.exchange.timeout_sec)
    rows = no_binance_rows(tickers, binance_assets)
    result = write_universe_files(
        rows,
        out_dir=out_dir,
        date_stamp=date_stamp,
        top_preview=top_preview,
    )
    result["binance_assets"] = len(binance_assets)
    result["source_ranked_coins"] = len(tickers)
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))


def _latest_universe_csv(universe_dir: Path) -> Path:
    files = list(universe_dir.glob("no_binance_focus_*.csv"))
    if not files:
        raise FileNotFoundError(f"В {universe_dir} нет no_binance_focus_*.csv")
    return max(files, key=lambda p: p.stat().st_mtime)


def cmd_multi_run(
    cfg: AppConfig,
    exchanges: str,
    universe_path: str | None,
    quote: str,
    max_symbols: int,
    max_pairs_per_exchange: int,
    cycles: int | None,
    duration_sec: int | None,
    paper_notional_quote: float,
) -> None:
    if cycles is None and duration_sec is None:
        cycles = 20
    exchange_ids = [item.strip().lower() for item in exchanges.split(",") if item.strip()]
    universe_csv = Path(universe_path) if universe_path else _latest_universe_csv(Path(cfg.paths.universe_dir))
    clients, pairs_by_exchange, discovery = build_pairs_for_universe(
        exchange_ids=exchange_ids,
        universe_csv=universe_csv,
        quote=quote.upper(),
        max_symbols=max_symbols,
        max_pairs_per_exchange=max_pairs_per_exchange,
        timeout_sec=cfg.exchange.timeout_sec,
    )
    bot = MultiExchangePaperBot(
        clients=clients,
        pairs_by_exchange=pairs_by_exchange,
        strategy_cfg=cfg.strategy,
        risk_cfg=cfg.risk,
        paper_notional_quote=paper_notional_quote,
        depth_limit=cfg.exchange.depth_limit,
        trades_limit=cfg.exchange.trades_limit,
        poll_interval_sec=cfg.exchange.poll_interval_sec,
    )
    result = bot.run(cycles=cycles, duration_sec=duration_sec)
    result["discovery"] = discovery
    result["universe_csv"] = str(universe_csv)
    result["mode"] = "paper"
    out_file = multi_run_output_path(cfg.paths.run_dir)
    save_multi_run(out_file, result)
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(out_file),
                "metrics": result["metrics"],
                "discovery": discovery,
            },
            ensure_ascii=False,
        )
    )


def cmd_ws_collect(
    cfg: AppConfig,
    exchanges: str,
    universe_path: str | None,
    quote: str,
    max_symbols: int,
    max_pairs_per_exchange: int,
    duration_sec: int,
    update_interval: str,
) -> None:
    raw_dir = _ensure_dir(cfg.paths.raw_dir)
    exchange_ids = [item.strip().lower() for item in exchanges.split(",") if item.strip()]
    unsupported = [item for item in exchange_ids if item not in WS_ADAPTERS]
    if unsupported:
        raise ValueError(
            f"WebSocket collector пока поддерживает только {', '.join(sorted(WS_ADAPTERS))}; "
            f"получено: {', '.join(unsupported)}"
        )
    universe_csv = Path(universe_path) if universe_path else _latest_universe_csv(Path(cfg.paths.universe_dir))
    _clients, pairs_by_exchange, discovery = build_pairs_for_universe(
        exchange_ids=exchange_ids,
        universe_csv=universe_csv,
        quote=quote.upper(),
        max_symbols=max_symbols,
        max_pairs_per_exchange=max_pairs_per_exchange,
        timeout_sec=cfg.exchange.timeout_sec,
    )
    symbols_by_exchange = {
        exchange_id: [pair.symbol for pair in pairs]
        for exchange_id, pairs in pairs_by_exchange.items()
    }
    result = collect_ws_markets(
        symbols_by_exchange=symbols_by_exchange,
        out_dir=raw_dir,
        duration_sec=duration_sec,
        update_interval=update_interval,
        depth_levels=cfg.exchange.depth_limit,
    )
    result["discovery"] = discovery
    result["universe_csv"] = str(universe_csv)
    result["mode"] = "public_ws_collect"
    manifest = ws_manifest_path(raw_dir)
    save_ws_manifest(manifest, result)
    print(
        json.dumps(
            {
                "ok": True,
                "manifest": str(manifest),
                "total_events": result["total_events"],
                "results": result["results"],
                "discovery": discovery,
            },
            ensure_ascii=False,
        )
    )


def _latest_ws_input(raw_dir: Path, freshness_slack_sec: float = 60.0) -> Path:
    """Автовыбор последнего WS-входа с защитой от stale manifest.

    Отказывается выбирать автоматически, если найден raw новее последнего
    manifest (признак partial run без manifest) или последний manifest помечен
    completed=false. В этих случаях вход нужно указать явно.
    """
    manifests = list(raw_dir.glob("ws_collect_*.json"))
    raw_files = list(raw_dir.glob("ws_*.jsonl"))
    if manifests:
        chosen = max(manifests, key=lambda p: p.stat().st_mtime)
        if raw_files:
            newest_raw = max(raw_files, key=lambda p: p.stat().st_mtime)
            if newest_raw.stat().st_mtime > chosen.stat().st_mtime + freshness_slack_sec:
                raise RuntimeError(
                    f"Автовыбор запрещен: raw {newest_raw.name} новее последнего manifest "
                    f"{chosen.name}. Похоже, последний сбор завершился без manifest "
                    "(partial run). Укажите вход явно или выполните finalize через "
                    "ws_durable_collector."
                )
        try:
            completed = json.loads(chosen.read_text(encoding="utf-8")).get("completed")
        except (OSError, json.JSONDecodeError):
            completed = None
        if completed is False:
            raise RuntimeError(
                f"Автовыбор запрещен: последний manifest {chosen.name} помечен "
                "completed=false (неполный dataset). Укажите вход явно, если это "
                "осознанный QA-прогон по partial данным."
            )
        return chosen
    if raw_files:
        return max(raw_files, key=lambda p: p.stat().st_mtime)
    raise FileNotFoundError(f"В {raw_dir} нет ws_collect_*.json или ws_*.jsonl")


def cmd_ws_normalize(cfg: AppConfig, input_path: str | None, output_path: str | None) -> None:
    raw_dir = _ensure_dir(cfg.paths.raw_dir)
    normalized_dir = _ensure_dir(cfg.paths.normalized_dir)
    src = Path(input_path) if input_path else _latest_ws_input(raw_dir)
    out = Path(output_path) if output_path else default_normalized_path(normalized_dir)
    result = normalize_ws_files(src, out)
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))


def cmd_ws_data_quality(
    cfg: AppConfig,
    input_path: str | None,
    manifest_path: str | None,
    output_path: str | None,
    min_rows: int,
    min_exchanges: int,
    min_markets: int,
    min_span_hours: float,
    min_duration_ratio: float,
    max_parse_error_rate: float,
    required_event_kinds: str,
    min_markets_with_required_kinds: int,
    max_market_event_share: float,
    max_gap_sec: float,
    max_manifest_error_count: int,
) -> None:
    normalized_dir = _ensure_dir(cfg.paths.normalized_dir)
    backtest_dir = _ensure_dir(cfg.paths.backtest_dir)
    src = Path(input_path) if input_path else _latest_normalized_jsonl(normalized_dir)
    out = Path(output_path) if output_path else default_ws_data_quality_path(backtest_dir)
    result = run_ws_data_quality_file(
        src,
        out,
        manifest_path=manifest_path,
        config=WsDataQualityConfig(
            min_rows=min_rows,
            min_exchanges=min_exchanges,
            min_markets=min_markets,
            min_span_hours=min_span_hours,
            min_duration_ratio=min_duration_ratio,
            max_parse_error_rate=max_parse_error_rate,
            required_event_kinds=_parse_optional_csv(required_event_kinds) or ("bbo", "depth", "trade"),
            min_markets_with_required_kinds=min_markets_with_required_kinds,
            max_market_event_share=max_market_event_share,
            max_gap_sec=max_gap_sec,
            max_manifest_error_count=max_manifest_error_count,
        ),
    )
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(src),
                "output": str(out),
                "accepted": result["accepted"],
                "reasons": result["reasons"],
                "metrics": result["metrics"],
            },
            ensure_ascii=False,
        )
    )


def cmd_ws_postprocess(
    cfg: AppConfig,
    input_path: str | None,
    manifest_path: str | None,
    normalized_output_path: str | None,
    quality_output_path: str | None,
    report_output_path: str | None,
    min_rows: int,
    min_exchanges: int,
    min_markets: int,
    min_span_hours: float,
    min_duration_ratio: float,
    max_parse_error_rate: float,
    required_event_kinds: str,
    min_markets_with_required_kinds: int,
    max_market_event_share: float,
    max_gap_sec: float,
    max_manifest_error_count: int,
) -> None:
    raw_dir = _ensure_dir(cfg.paths.raw_dir)
    normalized_dir = _ensure_dir(cfg.paths.normalized_dir)
    backtest_dir = _ensure_dir(cfg.paths.backtest_dir)
    src = Path(input_path) if input_path else _latest_ws_input(raw_dir)
    normalized_out = Path(normalized_output_path) if normalized_output_path else default_ws_postprocess_normalized_path(normalized_dir)
    quality_out = Path(quality_output_path) if quality_output_path else default_ws_postprocess_quality_path(backtest_dir)
    report_out = Path(report_output_path) if report_output_path else default_ws_postprocess_report_path(backtest_dir)
    result = run_ws_postprocess_file(
        src,
        normalized_output_path=normalized_out,
        quality_output_path=quality_out,
        report_output_path=report_out,
        manifest_path=manifest_path,
        quality_config=WsDataQualityConfig(
            min_rows=min_rows,
            min_exchanges=min_exchanges,
            min_markets=min_markets,
            min_span_hours=min_span_hours,
            min_duration_ratio=min_duration_ratio,
            max_parse_error_rate=max_parse_error_rate,
            required_event_kinds=_parse_optional_csv(required_event_kinds) or ("bbo", "depth", "trade"),
            min_markets_with_required_kinds=min_markets_with_required_kinds,
            max_market_event_share=max_market_event_share,
            max_gap_sec=max_gap_sec,
            max_manifest_error_count=max_manifest_error_count,
        ),
    )
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(src),
                "output": str(report_out),
                "normalized_output": str(normalized_out),
                "quality_output": str(quality_out),
                "replay_allowed": result["replay_allowed"],
                "data_quality_accepted": result["data_quality"]["accepted"],
                "data_quality_reasons": result["data_quality"]["reasons"],
                "normalization": result["normalization"],
                "metrics": result["data_quality"]["metrics"],
            },
            ensure_ascii=False,
        )
    )


def _latest_normalized_jsonl(normalized_dir: Path) -> Path:
    files = list(normalized_dir.glob("ws_normalized_*.jsonl")) + list(normalized_dir.glob("*_normalized.jsonl"))
    if not files:
        raise FileNotFoundError(f"В {normalized_dir} нет normalized JSONL файлов")
    return max(files, key=lambda p: p.stat().st_mtime)


def _latest_perp_normalized_jsonl(normalized_dir: Path) -> Path:
    files = list(normalized_dir.glob("perp_normalized_*.jsonl"))
    if not files:
        return _latest_normalized_jsonl(normalized_dir)
    return max(files, key=lambda p: p.stat().st_mtime)


def _latest_event_quality_report(backtest_dir: Path) -> Path:
    files = list(backtest_dir.glob("event_quality_*.json")) + list(backtest_dir.glob("event_quality_report_*.json"))
    if not files:
        raise FileNotFoundError(f"В {backtest_dir} нет event_quality_*.json")
    return max(files, key=lambda p: p.stat().st_mtime)


def _parse_venue_costs(raw: str) -> dict[str, dict[str, float]]:
    if not raw.strip():
        return {}
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("venue_costs_json must be a JSON object keyed by exchange")
    result: dict[str, dict[str, float]] = {}
    for exchange, values in payload.items():
        if not isinstance(values, dict):
            raise ValueError(f"venue_costs_json[{exchange!r}] must be an object")
        result[str(exchange).strip().lower()] = {str(name): float(value) for name, value in values.items()}
    return result


def _venue_cost_map(costs: dict[str, dict[str, float]], field_name: str) -> dict[str, float]:
    return {exchange: values[field_name] for exchange, values in costs.items() if field_name in values}


def cmd_ws_replay(
    cfg: AppConfig,
    input_path: str | None,
    output_path: str | None,
    signal_type: str,
    notional_quote: float,
    execution_mode: str,
    taker_fee_bps: float,
    maker_fee_bps: float,
    slippage_bps: float,
    latency_ms: int,
    flow_window_sec: float,
    allow_short: bool,
    max_open_positions: int,
    maker_queue_ahead_qty: float,
    maker_queue_model: str,
    maker_queue_ahead_fraction: float,
    maker_order_ttl_sec: float,
    quality_filter_enabled: bool,
    quality_window_sec: float,
    quality_min_trade_count: int,
    quality_min_trade_notional: float,
    quality_max_avg_spread_bps: float,
    quality_min_quote_updates: int,
    quality_min_top_qty: float,
    min_net_take_profit_bps: float,
    sweep_v2_allowed_markets: str,
    sweep_v2_side: str,
    sweep_v2_min_trade_notional_quote: float,
    sweep_v2_min_intensity_bps: float,
    sweep_v2_max_pre_spread_bps: float,
    sweep_v2_max_reclaim_sec: float,
    sweep_v2_event_cooldown_sec: float,
    breakout_lookback_sec: float,
    breakout_bps: float,
    breakout_min_samples: int,
    venue_costs_json: str = "",
    max_quote_age_sec: float = 2.0,
) -> None:
    normalized_dir = _ensure_dir(cfg.paths.normalized_dir)
    backtest_dir = _ensure_dir(cfg.paths.backtest_dir)
    src = Path(input_path) if input_path else _latest_normalized_jsonl(normalized_dir)
    out = Path(output_path) if output_path else default_replay_path(backtest_dir)
    venue_costs = _parse_venue_costs(venue_costs_json)
    replay_cfg = ReplayConfig(
        notional_quote=notional_quote,
        execution_mode=execution_mode,
        taker_fee_bps=taker_fee_bps,
        maker_fee_bps=maker_fee_bps,
        slippage_bps=slippage_bps,
        taker_fee_bps_by_exchange=_venue_cost_map(venue_costs, "taker_fee_bps"),
        maker_fee_bps_by_exchange=_venue_cost_map(venue_costs, "maker_fee_bps"),
        slippage_bps_by_exchange=_venue_cost_map(venue_costs, "slippage_bps"),
        max_quote_age_sec=max_quote_age_sec,
        latency_ms=latency_ms,
        flow_window_sec=flow_window_sec,
        allow_short=allow_short,
        max_open_positions=max_open_positions,
        maker_queue_ahead_qty=maker_queue_ahead_qty,
        maker_queue_model=maker_queue_model,
        maker_queue_ahead_fraction=maker_queue_ahead_fraction,
        maker_order_ttl_sec=maker_order_ttl_sec,
        quality_filter_enabled=quality_filter_enabled,
        quality_window_sec=quality_window_sec,
        quality_min_trade_count=quality_min_trade_count,
        quality_min_trade_notional=quality_min_trade_notional,
        quality_max_avg_spread_bps=quality_max_avg_spread_bps,
        quality_min_quote_updates=quality_min_quote_updates,
        quality_min_top_qty=quality_min_top_qty,
        min_net_take_profit_bps=min_net_take_profit_bps,
    )
    events = load_normalized_events(src)
    strategy = replace(
        cfg.strategy,
        signal_type=signal_type,
        sweep_v2_allowed_markets=sweep_v2_allowed_markets,
        sweep_v2_side=sweep_v2_side,
        sweep_v2_min_trade_notional_quote=sweep_v2_min_trade_notional_quote,
        sweep_v2_min_intensity_bps=sweep_v2_min_intensity_bps,
        sweep_v2_max_pre_spread_bps=sweep_v2_max_pre_spread_bps,
        sweep_v2_max_reclaim_sec=sweep_v2_max_reclaim_sec,
        sweep_v2_event_cooldown_sec=sweep_v2_event_cooldown_sec,
        breakout_lookback_sec=breakout_lookback_sec,
        breakout_bps=breakout_bps,
        breakout_min_samples=breakout_min_samples,
    )
    backtester = EventDrivenReplayBacktester(strategy, cfg.risk, replay_cfg)
    result = backtester.run(events)
    result["input"] = str(src)
    result["output"] = str(out)
    save_replay_result(out, result)
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(src),
                "output": str(out),
                "metrics": result["metrics"],
                "events_by_kind": result["events_by_kind"],
                "skipped_signals": result["skipped_signals"],
            },
            ensure_ascii=False,
        )
    )


def cmd_ws_grid_search(
    cfg: AppConfig,
    input_path: str | None,
    output_path: str | None,
    notional_quote: float,
    execution_mode: str,
    taker_fee_bps: float,
    maker_fee_bps: float,
    slippage_bps: float,
    latency_ms: int,
    flow_window_sec: float,
    allow_short: bool,
    max_open_positions: int,
    maker_queue_ahead_qty: float,
    maker_queue_model: str,
    maker_queue_ahead_fraction: float,
    maker_order_ttl_sec: float,
    quality_filter_enabled: bool,
    quality_window_sec: float,
    quality_min_trade_count: int,
    quality_min_trade_notional: float,
    quality_max_avg_spread_bps: float,
    quality_min_quote_updates: int,
    quality_min_top_qty: float,
    entry_imbalance_abs: str,
    entry_signed_flow_notional: str,
    max_spread_bps: str,
    take_profit_bps: str,
    stop_loss_bps: str,
    max_hold_sec: str,
    grid_signal_type: str,
    min_trades: int,
    min_win_rate: float,
    min_expectancy_quote: float,
    min_net_pnl_quote: float,
    min_profit_factor: float,
    max_drawdown_quote: float,
    min_net_take_profit_bps: float,
    sweep_v2_allowed_markets: str,
    sweep_v2_side: str,
    sweep_v2_min_trade_notional_quote: float,
    sweep_v2_min_intensity_bps: float,
    sweep_v2_max_pre_spread_bps: float,
    sweep_v2_max_reclaim_sec: float,
    sweep_v2_event_cooldown_sec: float,
    grid_breakout_bps: str | None,
    grid_breakout_lookback_sec: str | None,
    grid_breakout_min_samples: str | None,
    top_n: int,
    max_grid_combinations: int = 10_000,
    venue_costs_json: str = "",
    max_quote_age_sec: float = 2.0,
) -> None:
    normalized_dir = _ensure_dir(cfg.paths.normalized_dir)
    backtest_dir = _ensure_dir(cfg.paths.backtest_dir)
    src = Path(input_path) if input_path else _latest_normalized_jsonl(normalized_dir)
    out = Path(output_path) if output_path else default_grid_path(backtest_dir)
    venue_costs = _parse_venue_costs(venue_costs_json)
    replay_cfg = ReplayConfig(
        notional_quote=notional_quote,
        execution_mode=execution_mode,
        taker_fee_bps=taker_fee_bps,
        maker_fee_bps=maker_fee_bps,
        slippage_bps=slippage_bps,
        taker_fee_bps_by_exchange=_venue_cost_map(venue_costs, "taker_fee_bps"),
        maker_fee_bps_by_exchange=_venue_cost_map(venue_costs, "maker_fee_bps"),
        slippage_bps_by_exchange=_venue_cost_map(venue_costs, "slippage_bps"),
        max_quote_age_sec=max_quote_age_sec,
        latency_ms=latency_ms,
        flow_window_sec=flow_window_sec,
        allow_short=allow_short,
        max_open_positions=max_open_positions,
        maker_queue_ahead_qty=maker_queue_ahead_qty,
        maker_queue_model=maker_queue_model,
        maker_queue_ahead_fraction=maker_queue_ahead_fraction,
        maker_order_ttl_sec=maker_order_ttl_sec,
        quality_filter_enabled=quality_filter_enabled,
        quality_window_sec=quality_window_sec,
        quality_min_trade_count=quality_min_trade_count,
        quality_min_trade_notional=quality_min_trade_notional,
        quality_max_avg_spread_bps=quality_max_avg_spread_bps,
        quality_min_quote_updates=quality_min_quote_updates,
        quality_min_top_qty=quality_min_top_qty,
        min_net_take_profit_bps=min_net_take_profit_bps,
    )
    grid = {
        "signal_type": parse_str_list(grid_signal_type),
        "entry_imbalance_abs": parse_float_list(entry_imbalance_abs),
        "entry_signed_flow_notional": parse_float_list(entry_signed_flow_notional),
        "max_spread_bps": parse_float_list(max_spread_bps),
        "take_profit_bps": parse_float_list(take_profit_bps),
        "stop_loss_bps": parse_float_list(stop_loss_bps),
        "max_hold_sec": parse_int_list(max_hold_sec),
    }
    # Опциональные breakout-измерения (для large_move_breakout).
    if grid_breakout_bps:
        grid["breakout_bps"] = parse_float_list(grid_breakout_bps)
    if grid_breakout_lookback_sec:
        grid["breakout_lookback_sec"] = parse_float_list(grid_breakout_lookback_sec)
    if grid_breakout_min_samples:
        grid["breakout_min_samples"] = parse_int_list(grid_breakout_min_samples)
    result = run_grid_search_file(
        input_path=src,
        output_path=out,
        base_strategy=replace(
            cfg.strategy,
            sweep_v2_allowed_markets=sweep_v2_allowed_markets,
            sweep_v2_side=sweep_v2_side,
            sweep_v2_min_trade_notional_quote=sweep_v2_min_trade_notional_quote,
            sweep_v2_min_intensity_bps=sweep_v2_min_intensity_bps,
            sweep_v2_max_pre_spread_bps=sweep_v2_max_pre_spread_bps,
            sweep_v2_max_reclaim_sec=sweep_v2_max_reclaim_sec,
            sweep_v2_event_cooldown_sec=sweep_v2_event_cooldown_sec,
        ),
        risk_cfg=cfg.risk,
        replay_cfg=replay_cfg,
        grid=grid,
        min_trades=min_trades,
        top_n=top_n,
        min_win_rate=min_win_rate,
        min_expectancy_quote=min_expectancy_quote,
        min_net_pnl_quote=min_net_pnl_quote,
        min_profit_factor=min_profit_factor,
        max_drawdown_quote=max_drawdown_quote,
        max_combinations=max_grid_combinations,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(src),
                "output": str(out),
                "events": result["events"],
                "total_combinations": result["total_combinations"],
                "eligible_combinations": result["eligible_combinations"],
                "best_by_signal_type": result.get("best_by_signal_type", {}),
                "top_results": [
                    {
                        "rank": item["rank"],
                        "eligible": item["eligible"],
                        "eligibility_reasons": item.get("eligibility_reasons", []),
                        "strategy_config": item["strategy_config"],
                        "metrics": item["metrics"],
                    }
                    for item in result["top_results"][: min(5, len(result["top_results"]))]
                ],
            },
            ensure_ascii=False,
        )
    )


def cmd_perp_replay(
    cfg: AppConfig,
    input_path: str | None,
    output_path: str | None,
    signal_type: str,
    notional_quote: float,
    execution_mode: str,
    taker_fee_bps: float,
    maker_fee_bps: float,
    slippage_bps: float,
    latency_ms: int,
    flow_window_sec: float,
    max_open_positions: int,
    maker_queue_ahead_qty: float,
    maker_queue_model: str,
    maker_queue_ahead_fraction: float,
    maker_order_ttl_sec: float,
    quality_filter_enabled: bool,
    quality_window_sec: float,
    quality_min_trade_count: int,
    quality_min_trade_notional: float,
    quality_max_avg_spread_bps: float,
    quality_min_quote_updates: int,
    quality_min_top_qty: float,
    min_net_take_profit_bps: float,
    sweep_v2_allowed_markets: str,
    sweep_v2_side: str,
    sweep_v2_min_trade_notional_quote: float,
    sweep_v2_min_intensity_bps: float,
    sweep_v2_max_pre_spread_bps: float,
    sweep_v2_max_reclaim_sec: float,
    sweep_v2_event_cooldown_sec: float,
    venue_costs_json: str = "",
    max_quote_age_sec: float = 2.0,
) -> None:
    normalized_dir = _ensure_dir(cfg.paths.normalized_dir)
    backtest_dir = _ensure_dir(cfg.paths.backtest_dir)
    src = Path(input_path) if input_path else _latest_perp_normalized_jsonl(normalized_dir)
    out = Path(output_path) if output_path else default_perp_replay_path(backtest_dir)
    venue_costs = _parse_venue_costs(venue_costs_json)
    replay_cfg = ReplayConfig(
        notional_quote=notional_quote,
        execution_mode=execution_mode,
        taker_fee_bps=taker_fee_bps,
        maker_fee_bps=maker_fee_bps,
        slippage_bps=slippage_bps,
        taker_fee_bps_by_exchange=_venue_cost_map(venue_costs, "taker_fee_bps"),
        maker_fee_bps_by_exchange=_venue_cost_map(venue_costs, "maker_fee_bps"),
        slippage_bps_by_exchange=_venue_cost_map(venue_costs, "slippage_bps"),
        max_quote_age_sec=max_quote_age_sec,
        latency_ms=latency_ms,
        flow_window_sec=flow_window_sec,
        allow_short=True,
        max_open_positions=max_open_positions,
        maker_queue_ahead_qty=maker_queue_ahead_qty,
        maker_queue_model=maker_queue_model,
        maker_queue_ahead_fraction=maker_queue_ahead_fraction,
        maker_order_ttl_sec=maker_order_ttl_sec,
        quality_filter_enabled=quality_filter_enabled,
        quality_window_sec=quality_window_sec,
        quality_min_trade_count=quality_min_trade_count,
        quality_min_trade_notional=quality_min_trade_notional,
        quality_max_avg_spread_bps=quality_max_avg_spread_bps,
        quality_min_quote_updates=quality_min_quote_updates,
        quality_min_top_qty=quality_min_top_qty,
        min_net_take_profit_bps=min_net_take_profit_bps,
    )
    strategy = replace(
        cfg.strategy,
        signal_type=signal_type,
        sweep_v2_allowed_markets=sweep_v2_allowed_markets,
        sweep_v2_side=sweep_v2_side,
        sweep_v2_min_trade_notional_quote=sweep_v2_min_trade_notional_quote,
        sweep_v2_min_intensity_bps=sweep_v2_min_intensity_bps,
        sweep_v2_max_pre_spread_bps=sweep_v2_max_pre_spread_bps,
        sweep_v2_max_reclaim_sec=sweep_v2_max_reclaim_sec,
        sweep_v2_event_cooldown_sec=sweep_v2_event_cooldown_sec,
    )
    result = run_perp_replay_file(
        input_path=src,
        output_path=out,
        strategy_cfg=strategy,
        risk_cfg=cfg.risk,
        replay_cfg=replay_cfg,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(src),
                "output": str(out),
                "metrics": result["metrics"],
                "events_by_kind": result["events_by_kind"],
                "skipped_signals": result["skipped_signals"],
            },
            ensure_ascii=False,
        )
    )


def cmd_perp_grid_search(
    cfg: AppConfig,
    input_path: str | None,
    output_path: str | None,
    notional_quote: float,
    execution_mode: str,
    taker_fee_bps: float,
    maker_fee_bps: float,
    slippage_bps: float,
    latency_ms: int,
    flow_window_sec: float,
    max_open_positions: int,
    maker_queue_ahead_qty: float,
    maker_queue_model: str,
    maker_queue_ahead_fraction: float,
    maker_order_ttl_sec: float,
    quality_filter_enabled: bool,
    quality_window_sec: float,
    quality_min_trade_count: int,
    quality_min_trade_notional: float,
    quality_max_avg_spread_bps: float,
    quality_min_quote_updates: int,
    quality_min_top_qty: float,
    entry_imbalance_abs: str,
    entry_signed_flow_notional: str,
    max_spread_bps: str,
    take_profit_bps: str,
    stop_loss_bps: str,
    max_hold_sec: str,
    grid_signal_type: str,
    min_trades: int,
    min_win_rate: float,
    min_expectancy_quote: float,
    min_net_pnl_quote: float,
    min_profit_factor: float,
    max_drawdown_quote: float,
    min_net_take_profit_bps: float,
    sweep_v2_allowed_markets: str,
    sweep_v2_side: str,
    sweep_v2_min_trade_notional_quote: float,
    sweep_v2_min_intensity_bps: float,
    sweep_v2_max_pre_spread_bps: float,
    sweep_v2_max_reclaim_sec: float,
    sweep_v2_event_cooldown_sec: float,
    top_n: int,
    max_grid_combinations: int = 10_000,
    venue_costs_json: str = "",
    max_quote_age_sec: float = 2.0,
) -> None:
    normalized_dir = _ensure_dir(cfg.paths.normalized_dir)
    backtest_dir = _ensure_dir(cfg.paths.backtest_dir)
    src = Path(input_path) if input_path else _latest_perp_normalized_jsonl(normalized_dir)
    out = Path(output_path) if output_path else default_perp_grid_path(backtest_dir)
    venue_costs = _parse_venue_costs(venue_costs_json)
    replay_cfg = ReplayConfig(
        notional_quote=notional_quote,
        execution_mode=execution_mode,
        taker_fee_bps=taker_fee_bps,
        maker_fee_bps=maker_fee_bps,
        slippage_bps=slippage_bps,
        taker_fee_bps_by_exchange=_venue_cost_map(venue_costs, "taker_fee_bps"),
        maker_fee_bps_by_exchange=_venue_cost_map(venue_costs, "maker_fee_bps"),
        slippage_bps_by_exchange=_venue_cost_map(venue_costs, "slippage_bps"),
        max_quote_age_sec=max_quote_age_sec,
        latency_ms=latency_ms,
        flow_window_sec=flow_window_sec,
        allow_short=True,
        max_open_positions=max_open_positions,
        maker_queue_ahead_qty=maker_queue_ahead_qty,
        maker_queue_model=maker_queue_model,
        maker_queue_ahead_fraction=maker_queue_ahead_fraction,
        maker_order_ttl_sec=maker_order_ttl_sec,
        quality_filter_enabled=quality_filter_enabled,
        quality_window_sec=quality_window_sec,
        quality_min_trade_count=quality_min_trade_count,
        quality_min_trade_notional=quality_min_trade_notional,
        quality_max_avg_spread_bps=quality_max_avg_spread_bps,
        quality_min_quote_updates=quality_min_quote_updates,
        quality_min_top_qty=quality_min_top_qty,
        min_net_take_profit_bps=min_net_take_profit_bps,
    )
    grid = {
        "signal_type": parse_str_list(grid_signal_type),
        "entry_imbalance_abs": parse_float_list(entry_imbalance_abs),
        "entry_signed_flow_notional": parse_float_list(entry_signed_flow_notional),
        "max_spread_bps": parse_float_list(max_spread_bps),
        "take_profit_bps": parse_float_list(take_profit_bps),
        "stop_loss_bps": parse_float_list(stop_loss_bps),
        "max_hold_sec": parse_int_list(max_hold_sec),
    }
    result = run_perp_grid_search_file(
        input_path=src,
        output_path=out,
        base_strategy=replace(
            cfg.strategy,
            sweep_v2_allowed_markets=sweep_v2_allowed_markets,
            sweep_v2_side=sweep_v2_side,
            sweep_v2_min_trade_notional_quote=sweep_v2_min_trade_notional_quote,
            sweep_v2_min_intensity_bps=sweep_v2_min_intensity_bps,
            sweep_v2_max_pre_spread_bps=sweep_v2_max_pre_spread_bps,
            sweep_v2_max_reclaim_sec=sweep_v2_max_reclaim_sec,
            sweep_v2_event_cooldown_sec=sweep_v2_event_cooldown_sec,
        ),
        risk_cfg=cfg.risk,
        replay_cfg=replay_cfg,
        grid=grid,
        min_trades=min_trades,
        top_n=top_n,
        min_win_rate=min_win_rate,
        min_expectancy_quote=min_expectancy_quote,
        min_net_pnl_quote=min_net_pnl_quote,
        min_profit_factor=min_profit_factor,
        max_drawdown_quote=max_drawdown_quote,
        max_combinations=max_grid_combinations,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(src),
                "output": str(out),
                "events": result["events"],
                "total_combinations": result["total_combinations"],
                "eligible_combinations": result["eligible_combinations"],
                "best_by_signal_type": result.get("best_by_signal_type", {}),
                "top_results": [
                    {
                        "rank": item["rank"],
                        "eligible": item["eligible"],
                        "eligibility_reasons": item.get("eligibility_reasons", []),
                        "strategy_config": item["strategy_config"],
                        "metrics": item["metrics"],
                    }
                    for item in result["top_results"][: min(5, len(result["top_results"]))]
                ],
            },
            ensure_ascii=False,
        )
    )


def cmd_perp_collect(
    cfg: AppConfig,
    exchanges: str,
    universe_path: str | None,
    quote: str,
    max_symbols: int,
    max_pairs_per_exchange: int,
    cycles: int,
    duration_sec: int | None,
    poll_interval_sec: float,
    depth_limit: int,
    trades_limit: int,
    output_path: str | None,
) -> None:
    normalized_dir = _ensure_dir(cfg.paths.normalized_dir)
    universe_dir = _ensure_dir(cfg.paths.universe_dir)
    universe_csv = Path(universe_path) if universe_path else _latest_universe_csv(universe_dir)
    out = Path(output_path) if output_path else default_perp_collect_path(normalized_dir)
    collect_cfg = PerpCollectConfig(
        cycles=cycles,
        duration_sec=duration_sec,
        poll_interval_sec=poll_interval_sec,
        depth_limit=depth_limit,
        trades_limit=trades_limit,
        max_symbols=max_symbols,
        max_pairs_per_exchange=max_pairs_per_exchange,
        quote=quote,
    )
    result = collect_perp_rest_file(
        output_path=out,
        exchange_ids=_funding_exchange_ids(exchanges),
        universe_csv=universe_csv,
        cfg=collect_cfg,
        timeout_sec=cfg.exchange.timeout_sec,
    )
    result["universe_csv"] = str(universe_csv)
    print(json.dumps(result, ensure_ascii=False))


def cmd_perp_report(cfg: AppConfig, input_path: str | None, output_path: str | None) -> None:
    normalized_dir = _ensure_dir(cfg.paths.normalized_dir)
    backtest_dir = _ensure_dir(cfg.paths.backtest_dir)
    src = Path(input_path) if input_path else _latest_perp_normalized_jsonl(normalized_dir)
    out = Path(output_path) if output_path else default_perp_report_path(backtest_dir)
    result = run_perp_report_file(src, out)
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(src),
                "output": str(out),
                "rows": result["rows"],
                "market_count": result["market_count"],
                "cycles_seen": result["cycles_seen"],
                "events_by_kind": result["events_by_kind"],
                "events_by_exchange": result["events_by_exchange"],
                "field_coverage": result["field_coverage"],
                "warnings": result["warnings"][:20],
            },
            ensure_ascii=False,
        )
    )


def cmd_event_quality_report(
    cfg: AppConfig,
    input_path: str | None,
    output_path: str | None,
    lookback_sec: float,
    horizon_sec: float,
    min_sweep_notional_quote: float,
    reclaim_bps: float,
    target_bps: float,
    stop_bps: float,
    max_pre_spread_bps: float,
    event_cooldown_sec: float,
    max_events: int,
) -> None:
    normalized_dir = _ensure_dir(cfg.paths.normalized_dir)
    backtest_dir = _ensure_dir(cfg.paths.backtest_dir)
    src = Path(input_path) if input_path else _latest_perp_normalized_jsonl(normalized_dir)
    out = Path(output_path) if output_path else default_event_quality_path(backtest_dir)
    report = run_event_quality_report_file(
        input_path=src,
        output_path=out,
        cfg=EventQualityConfig(
            lookback_sec=lookback_sec,
            horizon_sec=horizon_sec,
            min_sweep_notional_quote=min_sweep_notional_quote,
            reclaim_bps=reclaim_bps,
            target_bps=target_bps,
            stop_bps=stop_bps,
            max_pre_spread_bps=max_pre_spread_bps,
            event_cooldown_sec=event_cooldown_sec,
            max_events=max_events,
        ),
    )
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(src),
                "output": str(out),
                "rows": report["rows"],
                "market_count": report["market_count"],
                "total_sweeps": report["total_sweeps"],
                "summary": report["summary"],
                "events_truncated": report["events_truncated"],
            },
            ensure_ascii=False,
        )
    )


def cmd_event_slice_optimizer(
    cfg: AppConfig,
    input_path: str | None,
    output_path: str | None,
    min_events: int,
    min_reclaimed: int,
    min_target_before_stop_rate: float,
    min_target_rate_all: float,
    max_false_sweep_rate: float,
    max_avg_adverse_bps: float,
    min_favorable_to_adverse: float,
    min_sweep_intensity_bps: str,
    max_time_to_reclaim_sec: str,
    max_pre_spread_bps: str,
    max_abs_basis_bps: str,
    min_trade_notional_quote: str,
    top_n: int,
) -> None:
    backtest_dir = _ensure_dir(cfg.paths.backtest_dir)
    src = Path(input_path) if input_path else _latest_event_quality_report(backtest_dir)
    out = Path(output_path) if output_path else default_event_slice_path(backtest_dir)
    report = run_event_slice_optimizer_file(
        input_path=src,
        output_path=out,
        cfg=EventSliceConfig(
            min_events=min_events,
            min_reclaimed=min_reclaimed,
            min_target_before_stop_rate=min_target_before_stop_rate,
            min_target_rate_all=min_target_rate_all,
            max_false_sweep_rate=max_false_sweep_rate,
            max_avg_adverse_bps=max_avg_adverse_bps,
            min_favorable_to_adverse=min_favorable_to_adverse,
            min_sweep_intensity_bps=tuple(parse_float_list(min_sweep_intensity_bps)),
            max_time_to_reclaim_sec=tuple(parse_float_list(max_time_to_reclaim_sec)),
            max_pre_spread_bps=tuple(parse_float_list(max_pre_spread_bps)),
            max_abs_basis_bps=tuple(parse_float_list(max_abs_basis_bps)),
            min_trade_notional_quote=tuple(parse_float_list(min_trade_notional_quote)),
            top_n=top_n,
        ),
    )
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(src),
                "output": str(out),
                "events_analyzed": report["events_analyzed"],
                "generated_slices": report["generated_slices"],
                "eligible_slices": report["eligible_slices"],
                "top_slices": report["top_slices"][: min(top_n, 10)],
            },
            ensure_ascii=False,
        )
    )


def cmd_event_validation_report(
    cfg: AppConfig,
    input_path: str | None,
    output_path: str | None,
    train_fraction: float,
    walk_forward_windows: int,
    walk_forward_min_pass_ratio: float,
    min_events: int,
    min_reclaimed: int,
    min_target_before_stop_rate: float,
    min_target_rate_all: float,
    max_false_sweep_rate: float,
    max_avg_adverse_bps: float,
    min_favorable_to_adverse: float,
    min_sweep_intensity_bps: str,
    max_time_to_reclaim_sec: str,
    max_pre_spread_bps: str,
    max_abs_basis_bps: str,
    min_trade_notional_quote: str,
    stress_favorable_haircut_bps: float,
    stress_adverse_widen_bps: float,
    stress_target_bps: float,
    stress_stop_bps: float,
    top_n: int,
) -> None:
    backtest_dir = _ensure_dir(cfg.paths.backtest_dir)
    src = Path(input_path) if input_path else _latest_event_quality_report(backtest_dir)
    out = Path(output_path) if output_path else default_event_validation_path(backtest_dir)
    report = run_event_validation_file(
        input_path=src,
        output_path=out,
        cfg=EventValidationConfig(
            train_fraction=train_fraction,
            walk_forward_windows=walk_forward_windows,
            walk_forward_min_pass_ratio=walk_forward_min_pass_ratio,
            min_events=min_events,
            min_reclaimed=min_reclaimed,
            min_target_before_stop_rate=min_target_before_stop_rate,
            min_target_rate_all=min_target_rate_all,
            max_false_sweep_rate=max_false_sweep_rate,
            max_avg_adverse_bps=max_avg_adverse_bps,
            min_favorable_to_adverse=min_favorable_to_adverse,
            min_sweep_intensity_bps=tuple(parse_float_list(min_sweep_intensity_bps)),
            max_time_to_reclaim_sec=tuple(parse_float_list(max_time_to_reclaim_sec)),
            max_pre_spread_bps=tuple(parse_float_list(max_pre_spread_bps)),
            max_abs_basis_bps=tuple(parse_float_list(max_abs_basis_bps)),
            min_trade_notional_quote=tuple(parse_float_list(min_trade_notional_quote)),
            stress_favorable_haircut_bps=stress_favorable_haircut_bps,
            stress_adverse_widen_bps=stress_adverse_widen_bps,
            stress_target_bps=stress_target_bps,
            stress_stop_bps=stress_stop_bps,
            top_n=top_n,
        ),
    )
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(src),
                "output": str(out),
                "accepted": report["accepted"],
                "decision": report["decision"],
                "rejection_reasons": report["rejection_reasons"],
                "split": report["split"],
                "selected_slice": report["selected_slice"],
                "oos": report["oos"],
                "walk_forward": {
                    "accepted": report["walk_forward"]["accepted"],
                    "accepted_windows": report["walk_forward"]["accepted_windows"],
                    "accepted_ratio": report["walk_forward"]["accepted_ratio"],
                },
                "stress": report["stress"],
            },
            ensure_ascii=False,
        )
    )


def cmd_perp_postprocess(
    cfg: AppConfig,
    input_path: str | None,
    manifest_path: str | None,
    report_output_path: str | None,
    grid_output_path: str | None,
    require_final: bool,
) -> None:
    normalized_dir = _ensure_dir(cfg.paths.normalized_dir)
    backtest_dir = _ensure_dir(cfg.paths.backtest_dir)
    src = Path(input_path) if input_path else _latest_perp_normalized_jsonl(normalized_dir)
    default_report, default_grid = default_perp_postprocess_output(src, backtest_dir)
    report_out = Path(report_output_path) if report_output_path else default_report
    grid_out = Path(grid_output_path) if grid_output_path else default_grid
    result = run_perp_postprocess_file(
        input_path=src,
        manifest_path=manifest_path,
        report_output_path=report_out,
        grid_output_path=grid_out,
        base_strategy=cfg.strategy,
        risk_cfg=cfg.risk,
        replay_cfg=default_perp_postprocess_replay_config(),
        cfg=PerpPostprocessConfig(require_final=require_final),
    )
    print(json.dumps({"ok": result["ok"], **result}, ensure_ascii=False))


def _funding_exchange_ids(exchanges: str) -> list[str]:
    return [item.strip().lower() for item in exchanges.split(",") if item.strip()]


def _latest_funding_input(funding_dir: Path) -> Path:
    files = list(funding_dir.glob("funding_collect_*.jsonl")) + list(funding_dir.glob("funding_scan_*.json"))
    if not files:
        raise FileNotFoundError(f"В {funding_dir} нет funding_collect_*.jsonl или funding_scan_*.json")
    return max(files, key=lambda p: p.stat().st_mtime)


def cmd_funding_scan(
    cfg: AppConfig,
    exchanges: str,
    universe_path: str | None,
    quote: str,
    max_symbols: int,
    max_pairs_per_exchange: int,
    notional_quote: float,
    max_spot_spread_bps: float,
    max_perp_spread_bps: float,
    max_abs_basis_bps: float,
    min_basis_bps: float,
    min_funding_rate: float,
    min_volume_24h_quote: float,
    min_spot_top_notional_quote: float,
    spot_fee_bps: float,
    perp_fee_bps: float,
    slippage_bps: float,
    target_hold_intervals: float,
    min_expected_net_carry_bps: float,
    max_break_even_hours: float,
    output_path: str | None,
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    scan_cfg = BasisScanConfig(
        notional_quote=notional_quote,
        max_spot_spread_bps=max_spot_spread_bps,
        max_perp_spread_bps=max_perp_spread_bps,
        max_abs_basis_bps=max_abs_basis_bps,
        min_basis_bps=min_basis_bps,
        min_funding_rate=min_funding_rate,
        min_volume_24h_quote=min_volume_24h_quote,
        min_spot_top_notional_quote=min_spot_top_notional_quote,
        spot_fee_bps=spot_fee_bps,
        perp_fee_bps=perp_fee_bps,
        slippage_bps=slippage_bps,
        target_hold_intervals=target_hold_intervals,
        min_expected_net_carry_bps=min_expected_net_carry_bps,
        max_break_even_hours=max_break_even_hours,
    )
    result = run_funding_scan_file(
        funding_dir=funding_dir,
        universe_dir=cfg.paths.universe_dir,
        universe_path=universe_path,
        exchange_ids=_funding_exchange_ids(exchanges),
        quote=quote.upper(),
        max_symbols=max_symbols,
        max_pairs_per_exchange=max_pairs_per_exchange,
        timeout_sec=cfg.exchange.timeout_sec,
        depth_limit=cfg.exchange.depth_limit,
        trades_limit=cfg.exchange.trades_limit,
        cfg=scan_cfg,
        output_path=output_path,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "output": result["output"],
                "summary": result["summary"],
                "top": result["rows"][: min(5, len(result["rows"]))],
                "errors": result["errors"][: min(5, len(result["errors"]))],
            },
            ensure_ascii=False,
        )
    )


def cmd_funding_coverage(
    cfg: AppConfig,
    exchanges: str,
    universe_path: str | None,
    quote: str,
    max_symbols: int,
    output_path: str | None,
    matched_universe_output_path: str | None,
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    output = Path(output_path) if output_path else default_funding_coverage_path(funding_dir)
    matched_output = Path(matched_universe_output_path) if matched_universe_output_path else None
    result = run_funding_coverage_file(
        funding_dir=funding_dir,
        universe_dir=cfg.paths.universe_dir,
        universe_path=universe_path,
        exchange_ids=_funding_exchange_ids(exchanges),
        quote=quote.upper(),
        max_symbols=max_symbols,
        timeout_sec=cfg.exchange.timeout_sec,
        output_path=output,
        matched_universe_output_path=matched_output,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "output": result["output"],
                "matched_universe_output": result.get("matched_universe_output"),
                "matched_universe_summary": result.get("matched_universe_summary"),
                "summary": result["summary"],
                "per_exchange": result["per_exchange"],
                "errors": result["errors"][: min(5, len(result["errors"]))],
            },
            ensure_ascii=False,
        )
    )


def cmd_funding_collect(
    cfg: AppConfig,
    exchanges: str,
    universe_path: str | None,
    quote: str,
    max_symbols: int,
    max_pairs_per_exchange: int,
    cycles: int,
    poll_interval_sec: float,
    notional_quote: float,
    max_spot_spread_bps: float,
    max_perp_spread_bps: float,
    max_abs_basis_bps: float,
    min_basis_bps: float,
    min_funding_rate: float,
    min_volume_24h_quote: float,
    min_spot_top_notional_quote: float,
    spot_fee_bps: float,
    perp_fee_bps: float,
    slippage_bps: float,
    target_hold_intervals: float,
    min_expected_net_carry_bps: float,
    max_break_even_hours: float,
    resume: bool,
    output_path: str | None,
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    universe_csv = Path(universe_path) if universe_path else _latest_universe_csv(Path(cfg.paths.universe_dir))
    output = Path(output_path) if output_path else default_funding_collect_path(funding_dir)
    scan_cfg = BasisScanConfig(
        notional_quote=notional_quote,
        max_spot_spread_bps=max_spot_spread_bps,
        max_perp_spread_bps=max_perp_spread_bps,
        max_abs_basis_bps=max_abs_basis_bps,
        min_basis_bps=min_basis_bps,
        min_funding_rate=min_funding_rate,
        min_volume_24h_quote=min_volume_24h_quote,
        min_spot_top_notional_quote=min_spot_top_notional_quote,
        spot_fee_bps=spot_fee_bps,
        perp_fee_bps=perp_fee_bps,
        slippage_bps=slippage_bps,
        target_hold_intervals=target_hold_intervals,
        min_expected_net_carry_bps=min_expected_net_carry_bps,
        max_break_even_hours=max_break_even_hours,
    )
    result = collect_funding_file(
        output_path=output,
        cycles=cycles,
        poll_interval_sec=poll_interval_sec,
        exchange_ids=_funding_exchange_ids(exchanges),
        universe_csv=universe_csv,
        quote=quote.upper(),
        max_symbols=max_symbols,
        max_pairs_per_exchange=max_pairs_per_exchange,
        timeout_sec=cfg.exchange.timeout_sec,
        depth_limit=cfg.exchange.depth_limit,
        trades_limit=cfg.exchange.trades_limit,
        cfg=scan_cfg,
        resume=resume,
    )
    print(json.dumps(result, ensure_ascii=False))


def cmd_funding_status(
    cfg: AppConfig,
    input_path: str | None,
    manifest_path: str | None,
    stale_after_sec: float,
    quality_min_rows: int | None,
    quality_min_markets: int | None,
    quality_min_completed_cycles: int | None,
    quality_min_unique_cycles: int | None,
    quality_min_avg_rows_per_cycle: float | None,
    quality_min_min_rows_per_cycle: int | None,
    quality_max_error_rate: float | None,
    quality_max_cycle_market_duplicate_rate: float | None,
    quality_required_row_fields: str | None,
    quality_min_required_row_field_presence: float | None,
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    src = Path(input_path) if input_path else _latest_funding_input(funding_dir)
    manifest = Path(manifest_path) if manifest_path else src.with_suffix(".manifest.json")
    quality_values = [
        quality_min_rows,
        quality_min_markets,
        quality_min_completed_cycles,
        quality_min_unique_cycles,
        quality_min_avg_rows_per_cycle,
        quality_min_min_rows_per_cycle,
        quality_max_error_rate,
        quality_max_cycle_market_duplicate_rate,
        quality_required_row_fields,
        quality_min_required_row_field_presence,
    ]
    data_quality_cfg = None
    if any(value is not None for value in quality_values):
        defaults = FundingDataQualityConfig()
        data_quality_cfg = FundingDataQualityConfig(
            min_rows=quality_min_rows if quality_min_rows is not None else defaults.min_rows,
            min_markets=quality_min_markets if quality_min_markets is not None else defaults.min_markets,
            min_completed_cycles=quality_min_completed_cycles
            if quality_min_completed_cycles is not None
            else defaults.min_completed_cycles,
            min_unique_cycles=quality_min_unique_cycles if quality_min_unique_cycles is not None else defaults.min_unique_cycles,
            min_avg_rows_per_cycle=quality_min_avg_rows_per_cycle
            if quality_min_avg_rows_per_cycle is not None
            else defaults.min_avg_rows_per_cycle,
            min_min_rows_per_cycle=quality_min_min_rows_per_cycle
            if quality_min_min_rows_per_cycle is not None
            else defaults.min_min_rows_per_cycle,
            max_error_rate=quality_max_error_rate if quality_max_error_rate is not None else defaults.max_error_rate,
            max_cycle_market_duplicate_rate=quality_max_cycle_market_duplicate_rate
            if quality_max_cycle_market_duplicate_rate is not None
            else defaults.max_cycle_market_duplicate_rate,
            required_row_fields=_parse_optional_csv(quality_required_row_fields),
            min_required_row_field_presence=quality_min_required_row_field_presence
            if quality_min_required_row_field_presence is not None
            else defaults.min_required_row_field_presence,
        )
    result = funding_collect_status(
        src,
        manifest_path=manifest,
        stale_after_sec=stale_after_sec,
        data_quality_cfg=data_quality_cfg,
    )
    print(json.dumps(result, ensure_ascii=False))


def cmd_funding_rank(
    cfg: AppConfig,
    input_path: str | None,
    output_path: str | None,
    top_n: int,
    min_funding_observations: int,
    min_funding_positive_ratio: float,
    min_funding_persistence_score: float,
    funding_persistence_weight: float,
    min_funding_rate: float,
    max_spot_spread_bps: float,
    max_perp_spread_bps: float,
    max_abs_basis_bps: float,
    min_basis_bps: float,
    min_expected_net_carry_bps: float,
    min_risk_adjusted_edge_bps: float,
    basis_risk_multiplier: float,
    spread_risk_multiplier: float,
    max_break_even_hours: float,
    min_regime_observations: int,
    min_perp_volume_24h_quote: float,
    min_spot_top_notional_quote: float,
    max_basis_std_bps: float,
    max_avg_spot_spread_bps: float,
    max_avg_perp_spread_bps: float,
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    src = Path(input_path) if input_path else _latest_funding_input(funding_dir)
    out = Path(output_path) if output_path else default_funding_rank_path(funding_dir)
    rank_cfg = FundingRankConfig(
        min_funding_rate=min_funding_rate,
        min_funding_observations=min_funding_observations,
        min_funding_positive_ratio=min_funding_positive_ratio,
        min_funding_persistence_score=min_funding_persistence_score,
        persistence_weight=funding_persistence_weight,
        max_spot_spread_bps=max_spot_spread_bps,
        max_perp_spread_bps=max_perp_spread_bps,
        max_abs_basis_bps=max_abs_basis_bps,
        min_basis_bps=min_basis_bps,
        min_expected_net_carry_bps=min_expected_net_carry_bps,
        min_risk_adjusted_edge_bps=min_risk_adjusted_edge_bps,
        basis_risk_multiplier=basis_risk_multiplier,
        spread_risk_multiplier=spread_risk_multiplier,
        max_break_even_hours=max_break_even_hours,
        min_regime_observations=min_regime_observations,
        min_perp_volume_24h_quote=min_perp_volume_24h_quote,
        min_spot_top_notional_quote=min_spot_top_notional_quote,
        max_basis_std_bps=max_basis_std_bps,
        max_avg_spot_spread_bps=max_avg_spot_spread_bps,
        max_avg_perp_spread_bps=max_avg_perp_spread_bps,
    )
    result = rank_funding_file(src, output_path=out, top_n=top_n, cfg=rank_cfg)
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(src),
                "output": str(out),
                "summary": result["summary"],
                "top": result["rows"][: min(5, len(result["rows"]))],
            },
            ensure_ascii=False,
        )
    )


def cmd_funding_gate_report(
    cfg: AppConfig,
    input_path: str | None,
    output_path: str | None,
    quality_universe_output_path: str | None,
    top_n: int,
    min_funding_observations: int,
    min_funding_positive_ratio: float,
    min_funding_persistence_score: float,
    funding_persistence_weight: float,
    min_funding_rate: float,
    max_spot_spread_bps: float,
    max_perp_spread_bps: float,
    max_abs_basis_bps: float,
    min_basis_bps: float,
    min_expected_net_carry_bps: float,
    min_risk_adjusted_edge_bps: float,
    basis_risk_multiplier: float,
    spread_risk_multiplier: float,
    max_break_even_hours: float,
    min_regime_observations: int,
    min_perp_volume_24h_quote: float,
    min_spot_top_notional_quote: float,
    max_basis_std_bps: float,
    max_avg_spot_spread_bps: float,
    max_avg_perp_spread_bps: float,
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    src = Path(input_path) if input_path else _latest_funding_input(funding_dir)
    out = Path(output_path) if output_path else default_funding_gate_report_path(funding_dir)
    rank_cfg = FundingRankConfig(
        min_funding_rate=min_funding_rate,
        min_funding_observations=min_funding_observations,
        min_funding_positive_ratio=min_funding_positive_ratio,
        min_funding_persistence_score=min_funding_persistence_score,
        persistence_weight=funding_persistence_weight,
        max_spot_spread_bps=max_spot_spread_bps,
        max_perp_spread_bps=max_perp_spread_bps,
        max_abs_basis_bps=max_abs_basis_bps,
        min_basis_bps=min_basis_bps,
        min_expected_net_carry_bps=min_expected_net_carry_bps,
        min_risk_adjusted_edge_bps=min_risk_adjusted_edge_bps,
        basis_risk_multiplier=basis_risk_multiplier,
        spread_risk_multiplier=spread_risk_multiplier,
        max_break_even_hours=max_break_even_hours,
        min_regime_observations=min_regime_observations,
        min_perp_volume_24h_quote=min_perp_volume_24h_quote,
        min_spot_top_notional_quote=min_spot_top_notional_quote,
        max_basis_std_bps=max_basis_std_bps,
        max_avg_spot_spread_bps=max_avg_spot_spread_bps,
        max_avg_perp_spread_bps=max_avg_perp_spread_bps,
    )
    result = funding_gate_report_file(src, output_path=out, top_n=top_n, cfg=rank_cfg)
    quality_universe_summary = None
    if quality_universe_output_path:
        quality_universe_summary = write_funding_quality_universe_file(
            src,
            output_path=quality_universe_output_path,
            cfg=rank_cfg,
            top_n=0,
        )
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(src),
                "output": str(out),
                "quality_universe_output": quality_universe_output_path,
                "quality_universe_summary": quality_universe_summary,
                "summary": result["summary"],
                "top_by_risk_adjusted_edge": result["top_by_risk_adjusted_edge"][: min(5, len(result["top_by_risk_adjusted_edge"]))],
            },
            ensure_ascii=False,
        )
    )


def cmd_funding_regime_report(
    cfg: AppConfig,
    input_path: str | None,
    output_path: str | None,
    top_n: int,
    min_funding_observations: int,
    min_funding_positive_ratio: float,
    min_funding_persistence_score: float,
    funding_persistence_weight: float,
    min_funding_rate: float,
    max_spot_spread_bps: float,
    max_perp_spread_bps: float,
    max_abs_basis_bps: float,
    min_basis_bps: float,
    min_expected_net_carry_bps: float,
    min_risk_adjusted_edge_bps: float,
    basis_risk_multiplier: float,
    spread_risk_multiplier: float,
    max_break_even_hours: float,
    min_regime_observations: int,
    min_perp_volume_24h_quote: float,
    min_spot_top_notional_quote: float,
    max_basis_std_bps: float,
    max_avg_spot_spread_bps: float,
    max_avg_perp_spread_bps: float,
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    src = Path(input_path) if input_path else _latest_funding_input(funding_dir)
    out = Path(output_path) if output_path else default_funding_regime_report_path(funding_dir)
    rank_cfg = FundingRankConfig(
        min_funding_rate=min_funding_rate,
        min_funding_observations=min_funding_observations,
        min_funding_positive_ratio=min_funding_positive_ratio,
        min_funding_persistence_score=min_funding_persistence_score,
        persistence_weight=funding_persistence_weight,
        max_spot_spread_bps=max_spot_spread_bps,
        max_perp_spread_bps=max_perp_spread_bps,
        max_abs_basis_bps=max_abs_basis_bps,
        min_basis_bps=min_basis_bps,
        min_expected_net_carry_bps=min_expected_net_carry_bps,
        min_risk_adjusted_edge_bps=min_risk_adjusted_edge_bps,
        basis_risk_multiplier=basis_risk_multiplier,
        spread_risk_multiplier=spread_risk_multiplier,
        max_break_even_hours=max_break_even_hours,
        min_regime_observations=min_regime_observations,
        min_perp_volume_24h_quote=min_perp_volume_24h_quote,
        min_spot_top_notional_quote=min_spot_top_notional_quote,
        max_basis_std_bps=max_basis_std_bps,
        max_avg_spot_spread_bps=max_avg_spot_spread_bps,
        max_avg_perp_spread_bps=max_avg_perp_spread_bps,
    )
    result = funding_regime_report_file(src, output_path=out, top_n=top_n, cfg=rank_cfg)
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(src),
                "output": str(out),
                "summary": result["summary"],
                "top_markets": result["top_markets"][: min(5, len(result["top_markets"]))],
            },
            ensure_ascii=False,
        )
    )


def cmd_funding_frontier_report(
    cfg: AppConfig,
    input_path: str | None,
    output_path: str | None,
    top_n: int,
    min_funding_observations: int,
    min_funding_positive_ratio: float,
    min_funding_persistence_score: float,
    funding_persistence_weight: float,
    min_funding_rate: float,
    max_spot_spread_bps: float,
    max_perp_spread_bps: float,
    max_abs_basis_bps: float,
    min_basis_bps: float,
    min_expected_net_carry_bps: float,
    min_risk_adjusted_edge_bps: float,
    basis_risk_multiplier: float,
    spread_risk_multiplier: float,
    max_break_even_hours: float,
    min_regime_observations: int,
    min_perp_volume_24h_quote: float,
    min_spot_top_notional_quote: float,
    max_basis_std_bps: float,
    max_avg_spot_spread_bps: float,
    max_avg_perp_spread_bps: float,
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    src = Path(input_path) if input_path else _latest_funding_input(funding_dir)
    out = Path(output_path) if output_path else default_funding_frontier_report_path(funding_dir)
    rank_cfg = FundingRankConfig(
        min_funding_rate=min_funding_rate,
        min_funding_observations=min_funding_observations,
        min_funding_positive_ratio=min_funding_positive_ratio,
        min_funding_persistence_score=min_funding_persistence_score,
        persistence_weight=funding_persistence_weight,
        max_spot_spread_bps=max_spot_spread_bps,
        max_perp_spread_bps=max_perp_spread_bps,
        max_abs_basis_bps=max_abs_basis_bps,
        min_basis_bps=min_basis_bps,
        min_expected_net_carry_bps=min_expected_net_carry_bps,
        min_risk_adjusted_edge_bps=min_risk_adjusted_edge_bps,
        basis_risk_multiplier=basis_risk_multiplier,
        spread_risk_multiplier=spread_risk_multiplier,
        max_break_even_hours=max_break_even_hours,
        min_regime_observations=min_regime_observations,
        min_perp_volume_24h_quote=min_perp_volume_24h_quote,
        min_spot_top_notional_quote=min_spot_top_notional_quote,
        max_basis_std_bps=max_basis_std_bps,
        max_avg_spot_spread_bps=max_avg_spot_spread_bps,
        max_avg_perp_spread_bps=max_avg_perp_spread_bps,
    )
    result = funding_frontier_report_file(src, output_path=out, top_n=top_n, cfg=rank_cfg)
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(src),
                "output": str(out),
                "summary": result["summary"],
                "top_frontier": result["top_frontier"][: min(5, len(result["top_frontier"]))],
            },
            ensure_ascii=False,
        )
    )


def cmd_funding_decision_report(
    cfg: AppConfig,
    input_path: str | None,
    manifest_path: str | None,
    postprocess_report_path: str | None,
    gate_report_path: str | None,
    regime_report_path: str | None,
    frontier_report_path: str | None,
    sensitivity_report_path: str | None,
    output_path: str | None,
    stale_after_sec: float,
    quality_min_rows: int | None,
    quality_min_markets: int | None,
    quality_min_completed_cycles: int | None,
    quality_min_unique_cycles: int | None,
    quality_min_avg_rows_per_cycle: float | None,
    quality_min_min_rows_per_cycle: int | None,
    quality_max_error_rate: float | None,
    quality_max_cycle_market_duplicate_rate: float | None,
    quality_required_row_fields: str | None,
    quality_min_required_row_field_presence: float | None,
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    src = Path(input_path) if input_path else _latest_funding_input(funding_dir)
    out = Path(output_path) if output_path else default_funding_decision_report_path(funding_dir)
    quality_values = [
        quality_min_rows,
        quality_min_markets,
        quality_min_completed_cycles,
        quality_min_unique_cycles,
        quality_min_avg_rows_per_cycle,
        quality_min_min_rows_per_cycle,
        quality_max_error_rate,
        quality_max_cycle_market_duplicate_rate,
        quality_required_row_fields,
        quality_min_required_row_field_presence,
    ]
    data_quality_cfg = None
    if any(value is not None for value in quality_values):
        defaults = FundingDataQualityConfig()
        data_quality_cfg = FundingDataQualityConfig(
            min_rows=quality_min_rows if quality_min_rows is not None else defaults.min_rows,
            min_markets=quality_min_markets if quality_min_markets is not None else defaults.min_markets,
            min_completed_cycles=quality_min_completed_cycles
            if quality_min_completed_cycles is not None
            else defaults.min_completed_cycles,
            min_unique_cycles=quality_min_unique_cycles if quality_min_unique_cycles is not None else defaults.min_unique_cycles,
            min_avg_rows_per_cycle=quality_min_avg_rows_per_cycle
            if quality_min_avg_rows_per_cycle is not None
            else defaults.min_avg_rows_per_cycle,
            min_min_rows_per_cycle=quality_min_min_rows_per_cycle
            if quality_min_min_rows_per_cycle is not None
            else defaults.min_min_rows_per_cycle,
            max_error_rate=quality_max_error_rate if quality_max_error_rate is not None else defaults.max_error_rate,
            max_cycle_market_duplicate_rate=quality_max_cycle_market_duplicate_rate
            if quality_max_cycle_market_duplicate_rate is not None
            else defaults.max_cycle_market_duplicate_rate,
            required_row_fields=_parse_optional_csv(quality_required_row_fields),
            min_required_row_field_presence=quality_min_required_row_field_presence
            if quality_min_required_row_field_presence is not None
            else defaults.min_required_row_field_presence,
        )
    result = funding_decision_report(
        src,
        manifest_path=manifest_path,
        postprocess_report_path=postprocess_report_path,
        gate_report_path=gate_report_path,
        regime_report_path=regime_report_path,
        frontier_report_path=frontier_report_path,
        sensitivity_report_path=sensitivity_report_path,
        output_path=out,
        stale_after_sec=stale_after_sec,
        data_quality_cfg=data_quality_cfg,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(src),
                "output": str(out),
                "summary": result["summary"],
            },
            ensure_ascii=False,
        )
    )


def cmd_funding_progress_report(
    cfg: AppConfig,
    input_path: str | None,
    manifest_path: str | None,
    output_path: str | None,
    top_n: int,
    min_funding_observations: int,
    min_funding_positive_ratio: float,
    min_funding_persistence_score: float,
    funding_persistence_weight: float,
    min_funding_rate: float,
    max_spot_spread_bps: float,
    max_perp_spread_bps: float,
    max_abs_basis_bps: float,
    min_basis_bps: float,
    min_expected_net_carry_bps: float,
    min_risk_adjusted_edge_bps: float,
    basis_risk_multiplier: float,
    spread_risk_multiplier: float,
    max_break_even_hours: float,
    min_regime_observations: int,
    min_perp_volume_24h_quote: float,
    min_spot_top_notional_quote: float,
    max_basis_std_bps: float,
    max_avg_spot_spread_bps: float,
    max_avg_perp_spread_bps: float,
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    src = Path(input_path) if input_path else _latest_funding_input(funding_dir)
    out = Path(output_path) if output_path else default_funding_progress_report_path(funding_dir)
    rank_cfg = FundingRankConfig(
        min_funding_rate=min_funding_rate,
        min_funding_observations=min_funding_observations,
        min_funding_positive_ratio=min_funding_positive_ratio,
        min_funding_persistence_score=min_funding_persistence_score,
        persistence_weight=funding_persistence_weight,
        max_spot_spread_bps=max_spot_spread_bps,
        max_perp_spread_bps=max_perp_spread_bps,
        max_abs_basis_bps=max_abs_basis_bps,
        min_basis_bps=min_basis_bps,
        min_expected_net_carry_bps=min_expected_net_carry_bps,
        min_risk_adjusted_edge_bps=min_risk_adjusted_edge_bps,
        basis_risk_multiplier=basis_risk_multiplier,
        spread_risk_multiplier=spread_risk_multiplier,
        max_break_even_hours=max_break_even_hours,
        min_regime_observations=min_regime_observations,
        min_perp_volume_24h_quote=min_perp_volume_24h_quote,
        min_spot_top_notional_quote=min_spot_top_notional_quote,
        max_basis_std_bps=max_basis_std_bps,
        max_avg_spot_spread_bps=max_avg_spot_spread_bps,
        max_avg_perp_spread_bps=max_avg_perp_spread_bps,
    )
    result = funding_progress_report_file(
        src,
        manifest_path=manifest_path,
        output_path=out,
        top_n=top_n,
        cfg=rank_cfg,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(src),
                "output": str(out),
                "summary": result["summary"],
                "latest_cycle": result["cycles"][-1] if result["cycles"] else None,
            },
            ensure_ascii=False,
        )
    )


def cmd_funding_collect_diagnostics(
    cfg: AppConfig,
    input_path: str | None,
    manifest_path: str | None,
    output_path: str | None,
    top_n: int,
    required_row_fields: str | None,
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    src = Path(input_path) if input_path else _latest_funding_input(funding_dir)
    out = Path(output_path) if output_path else default_funding_collect_diagnostics_path(funding_dir)
    result = funding_collect_diagnostics_file(
        src,
        manifest_path=manifest_path,
        output_path=out,
        top_n=top_n,
        required_fields=_parse_optional_csv(required_row_fields) or None,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(src),
                "manifest": result.get("manifest"),
                "output": str(out),
                "summary": result["summary"],
                "manifest_error_breakdown": result["manifest_error_breakdown"],
            },
            ensure_ascii=False,
        )
    )


def cmd_funding_backtest(
    cfg: AppConfig,
    input_path: str | None,
    output_path: str | None,
    notional_quote: float,
    spot_fee_bps: float,
    perp_fee_bps: float,
    slippage_bps: float,
    min_funding_rate: float,
    min_total_score: float,
    max_spot_spread_bps: float,
    max_perp_spread_bps: float,
    max_abs_basis_bps: float,
    min_basis_bps: float,
    min_expected_net_carry_bps: float,
    min_risk_adjusted_edge_bps: float,
    basis_risk_multiplier: float,
    spread_risk_multiplier: float,
    max_break_even_hours: float,
    min_funding_observations: int,
    min_funding_positive_ratio: float,
    min_funding_persistence_score: float,
    min_regime_observations: int,
    min_perp_volume_24h_quote: float,
    min_spot_top_notional_quote: float,
    max_basis_std_bps: float,
    max_avg_spot_spread_bps: float,
    max_avg_perp_spread_bps: float,
    venue_costs_json: str = "",
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    backtest_dir = _ensure_dir(cfg.paths.backtest_dir)
    src = Path(input_path) if input_path else _latest_funding_input(funding_dir)
    out = Path(output_path) if output_path else default_funding_backtest_path(backtest_dir)
    venue_costs = _parse_venue_costs(venue_costs_json)
    bt_cfg = FundingBacktestConfig(
        notional_quote=notional_quote,
        spot_fee_bps=spot_fee_bps,
        perp_fee_bps=perp_fee_bps,
        slippage_bps=slippage_bps,
        spot_fee_bps_by_exchange=_venue_cost_map(venue_costs, "spot_fee_bps"),
        perp_fee_bps_by_exchange=_venue_cost_map(venue_costs, "perp_fee_bps"),
        slippage_bps_by_exchange=_venue_cost_map(venue_costs, "slippage_bps"),
        min_funding_rate=min_funding_rate,
        min_total_score=min_total_score,
        max_spot_spread_bps=max_spot_spread_bps,
        max_perp_spread_bps=max_perp_spread_bps,
        max_abs_basis_bps=max_abs_basis_bps,
        min_basis_bps=min_basis_bps,
        min_expected_net_carry_bps=min_expected_net_carry_bps,
        min_risk_adjusted_edge_bps=min_risk_adjusted_edge_bps,
        basis_risk_multiplier=basis_risk_multiplier,
        spread_risk_multiplier=spread_risk_multiplier,
        max_break_even_hours=max_break_even_hours,
        min_funding_observations=min_funding_observations,
        min_funding_positive_ratio=min_funding_positive_ratio,
        min_funding_persistence_score=min_funding_persistence_score,
        min_regime_observations=min_regime_observations,
        min_perp_volume_24h_quote=min_perp_volume_24h_quote,
        min_spot_top_notional_quote=min_spot_top_notional_quote,
        max_basis_std_bps=max_basis_std_bps,
        max_avg_spot_spread_bps=max_avg_spot_spread_bps,
        max_avg_perp_spread_bps=max_avg_perp_spread_bps,
    )
    result = run_funding_backtest_file(src, out, bt_cfg)
    print(json.dumps({"ok": True, "input": str(src), "output": str(out), "metrics": result["metrics"]}, ensure_ascii=False))


def cmd_funding_sensitivity(
    cfg: AppConfig,
    input_path: str | None,
    output_path: str | None,
    spot_fee_bps_list: str,
    perp_fee_bps_list: str,
    slippage_bps_list: str,
    target_hold_intervals_list: str,
    max_break_even_hours_list: str,
    top_n: int,
    notional_quote: float,
    min_funding_rate: float,
    min_total_score: float,
    max_spot_spread_bps: float,
    max_perp_spread_bps: float,
    max_abs_basis_bps: float,
    min_basis_bps: float,
    min_expected_net_carry_bps: float,
    min_risk_adjusted_edge_bps: float,
    basis_risk_multiplier: float,
    spread_risk_multiplier: float,
    min_funding_observations: int,
    min_funding_positive_ratio: float,
    min_funding_persistence_score: float,
    min_regime_observations: int,
    min_perp_volume_24h_quote: float,
    min_spot_top_notional_quote: float,
    max_basis_std_bps: float,
    max_avg_spot_spread_bps: float,
    max_avg_perp_spread_bps: float,
    accept_min_trades: int,
    accept_min_win_rate: float,
    accept_min_expectancy_quote: float,
    accept_min_net_pnl_quote: float,
    accept_max_drawdown_quote: float,
    accept_min_profit_factor: float,
    accept_min_markets: int,
    accept_max_market_trade_share: float,
    accept_min_exchanges: int,
    accept_max_exchange_trade_share: float,
    accept_min_profitable_windows: int,
    accept_max_window_pnl_share: float,
    stress_enabled: bool,
    stress_adverse_basis_bps: float,
    stress_spread_widen_bps: float,
    stress_funding_flip_bps: float,
    stress_min_net_pnl_quote: float,
    stress_max_drawdown_quote: float,
    sensitivity_oos: bool,
    oos_train_fraction: float,
    oos_min_train_rows: int,
    oos_min_rows: int,
    oos_min_train_span_hours: float,
    oos_min_span_hours: float,
    sensitivity_walk_forward: bool,
    walk_train_rows: int,
    walk_test_rows: int,
    walk_step_rows: int,
    walk_min_windows: int,
    walk_min_accepted_windows: int,
    walk_min_accepted_ratio: float,
    walk_min_train_span_hours: float,
    walk_min_test_span_hours: float,
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    backtest_dir = _ensure_dir(cfg.paths.backtest_dir)
    src = Path(input_path) if input_path else _latest_funding_input(funding_dir)
    out = Path(output_path) if output_path else default_funding_sensitivity_path(backtest_dir)
    sensitivity_cfg = FundingSensitivityConfig(
        spot_fee_bps_values=tuple(parse_float_list(spot_fee_bps_list)),
        perp_fee_bps_values=tuple(parse_float_list(perp_fee_bps_list)),
        slippage_bps_values=tuple(parse_float_list(slippage_bps_list)),
        target_hold_intervals_values=tuple(parse_float_list(target_hold_intervals_list)),
        max_break_even_hours_values=tuple(parse_float_list(max_break_even_hours_list)),
        top_n=top_n,
    )
    bt_cfg = FundingBacktestConfig(
        notional_quote=notional_quote,
        min_funding_rate=min_funding_rate,
        min_total_score=min_total_score,
        max_spot_spread_bps=max_spot_spread_bps,
        max_perp_spread_bps=max_perp_spread_bps,
        max_abs_basis_bps=max_abs_basis_bps,
        min_basis_bps=min_basis_bps,
        min_expected_net_carry_bps=min_expected_net_carry_bps,
        min_risk_adjusted_edge_bps=min_risk_adjusted_edge_bps,
        basis_risk_multiplier=basis_risk_multiplier,
        spread_risk_multiplier=spread_risk_multiplier,
        min_funding_observations=min_funding_observations,
        min_funding_positive_ratio=min_funding_positive_ratio,
        min_funding_persistence_score=min_funding_persistence_score,
        min_regime_observations=min_regime_observations,
        min_perp_volume_24h_quote=min_perp_volume_24h_quote,
        min_spot_top_notional_quote=min_spot_top_notional_quote,
        max_basis_std_bps=max_basis_std_bps,
        max_avg_spot_spread_bps=max_avg_spot_spread_bps,
        max_avg_perp_spread_bps=max_avg_perp_spread_bps,
    )
    acceptance_cfg = FundingAcceptanceConfig(
        min_trades=accept_min_trades,
        min_win_rate=accept_min_win_rate,
        min_expectancy_quote=accept_min_expectancy_quote,
        min_net_pnl_quote=accept_min_net_pnl_quote,
        max_drawdown_quote=accept_max_drawdown_quote,
        min_profit_factor=accept_min_profit_factor,
        min_markets=accept_min_markets,
        max_market_trade_share=accept_max_market_trade_share,
        min_exchanges=accept_min_exchanges,
        max_exchange_trade_share=accept_max_exchange_trade_share,
        min_profitable_windows=accept_min_profitable_windows,
        max_window_pnl_share=accept_max_window_pnl_share,
    )
    stress_cfg = FundingStressConfig(
        enabled=stress_enabled,
        adverse_basis_bps=stress_adverse_basis_bps,
        spread_widen_bps=stress_spread_widen_bps,
        funding_flip_bps=stress_funding_flip_bps,
        min_stress_net_pnl_quote=stress_min_net_pnl_quote,
        max_stress_drawdown_quote=stress_max_drawdown_quote,
    )
    result = run_funding_sensitivity_file(
        src,
        out,
        sensitivity_cfg=sensitivity_cfg,
        backtest_cfg=bt_cfg,
        acceptance_cfg=acceptance_cfg,
        stress_cfg=stress_cfg,
        oos_cfg=FundingOosConfig(
            train_fraction=oos_train_fraction,
            min_train_rows=oos_min_train_rows,
            min_oos_rows=oos_min_rows,
            min_train_span_hours=oos_min_train_span_hours,
            min_oos_span_hours=oos_min_span_hours,
        )
        if sensitivity_oos
        else None,
        walk_forward_cfg=FundingWalkForwardConfig(
            train_rows=walk_train_rows,
            test_rows=walk_test_rows,
            step_rows=walk_step_rows,
            min_windows=walk_min_windows,
            min_accepted_windows=walk_min_accepted_windows,
            min_accepted_ratio=walk_min_accepted_ratio,
            min_train_span_hours=walk_min_train_span_hours,
            min_test_span_hours=walk_min_test_span_hours,
        )
        if sensitivity_walk_forward
        else None,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "input": str(src),
                "output": str(out),
                "summary": result["summary"],
                "top_scenarios": result["scenarios"][: min(5, len(result["scenarios"]))],
            },
            ensure_ascii=False,
        )
    )


def cmd_funding_oos_backtest(
    cfg: AppConfig,
    input_path: str | None,
    output_path: str | None,
    notional_quote: float,
    spot_fee_bps: float,
    perp_fee_bps: float,
    slippage_bps: float,
    min_funding_rate: float,
    min_total_score: float,
    max_spot_spread_bps: float,
    max_perp_spread_bps: float,
    max_abs_basis_bps: float,
    min_basis_bps: float,
    min_expected_net_carry_bps: float,
    min_risk_adjusted_edge_bps: float,
    basis_risk_multiplier: float,
    spread_risk_multiplier: float,
    max_break_even_hours: float,
    min_funding_observations: int,
    min_funding_positive_ratio: float,
    min_funding_persistence_score: float,
    min_regime_observations: int,
    min_perp_volume_24h_quote: float,
    min_spot_top_notional_quote: float,
    max_basis_std_bps: float,
    max_avg_spot_spread_bps: float,
    max_avg_perp_spread_bps: float,
    train_fraction: float,
    min_train_rows: int,
    min_oos_rows: int,
    min_train_span_hours: float,
    min_oos_span_hours: float,
    accept_min_trades: int,
    accept_min_win_rate: float,
    accept_min_expectancy_quote: float,
    accept_min_net_pnl_quote: float,
    accept_max_drawdown_quote: float,
    accept_min_profit_factor: float,
    accept_min_markets: int,
    accept_max_market_trade_share: float,
    accept_min_exchanges: int,
    accept_max_exchange_trade_share: float,
    accept_min_profitable_windows: int,
    accept_max_window_pnl_share: float,
    stress_enabled: bool,
    stress_adverse_basis_bps: float,
    stress_spread_widen_bps: float,
    stress_funding_flip_bps: float,
    stress_min_net_pnl_quote: float,
    stress_max_drawdown_quote: float,
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    backtest_dir = _ensure_dir(cfg.paths.backtest_dir)
    src = Path(input_path) if input_path else _latest_funding_input(funding_dir)
    out = Path(output_path) if output_path else default_funding_oos_backtest_path(backtest_dir)
    bt_cfg = FundingBacktestConfig(
        notional_quote=notional_quote,
        spot_fee_bps=spot_fee_bps,
        perp_fee_bps=perp_fee_bps,
        slippage_bps=slippage_bps,
        min_funding_rate=min_funding_rate,
        min_total_score=min_total_score,
        max_spot_spread_bps=max_spot_spread_bps,
        max_perp_spread_bps=max_perp_spread_bps,
        max_abs_basis_bps=max_abs_basis_bps,
        min_basis_bps=min_basis_bps,
        min_expected_net_carry_bps=min_expected_net_carry_bps,
        min_risk_adjusted_edge_bps=min_risk_adjusted_edge_bps,
        basis_risk_multiplier=basis_risk_multiplier,
        spread_risk_multiplier=spread_risk_multiplier,
        max_break_even_hours=max_break_even_hours,
        min_funding_observations=min_funding_observations,
        min_funding_positive_ratio=min_funding_positive_ratio,
        min_funding_persistence_score=min_funding_persistence_score,
        min_regime_observations=min_regime_observations,
        min_perp_volume_24h_quote=min_perp_volume_24h_quote,
        min_spot_top_notional_quote=min_spot_top_notional_quote,
        max_basis_std_bps=max_basis_std_bps,
        max_avg_spot_spread_bps=max_avg_spot_spread_bps,
        max_avg_perp_spread_bps=max_avg_perp_spread_bps,
    )
    result = run_funding_oos_backtest_file(
        src,
        out,
        backtest_cfg=bt_cfg,
        acceptance_cfg=FundingAcceptanceConfig(
            min_trades=accept_min_trades,
            min_win_rate=accept_min_win_rate,
            min_expectancy_quote=accept_min_expectancy_quote,
            min_net_pnl_quote=accept_min_net_pnl_quote,
            max_drawdown_quote=accept_max_drawdown_quote,
            min_profit_factor=accept_min_profit_factor,
            min_markets=accept_min_markets,
            max_market_trade_share=accept_max_market_trade_share,
            min_exchanges=accept_min_exchanges,
            max_exchange_trade_share=accept_max_exchange_trade_share,
            min_profitable_windows=accept_min_profitable_windows,
            max_window_pnl_share=accept_max_window_pnl_share,
        ),
        oos_cfg=FundingOosConfig(
            train_fraction=train_fraction,
            min_train_rows=min_train_rows,
            min_oos_rows=min_oos_rows,
            min_train_span_hours=min_train_span_hours,
            min_oos_span_hours=min_oos_span_hours,
        ),
        stress_cfg=FundingStressConfig(
            enabled=stress_enabled,
            adverse_basis_bps=stress_adverse_basis_bps,
            spread_widen_bps=stress_spread_widen_bps,
            funding_flip_bps=stress_funding_flip_bps,
            min_stress_net_pnl_quote=stress_min_net_pnl_quote,
            max_stress_drawdown_quote=stress_max_drawdown_quote,
        ),
    )
    print(
        json.dumps(
            {
                "ok": result["ok"],
                "status": result["status"],
                "accepted": result["accepted"],
                "input": str(src),
                "output": str(out),
                "split": result["split"],
                "in_sample_acceptance": result.get("in_sample_acceptance"),
                "out_of_sample_acceptance": result.get("out_of_sample_acceptance"),
            },
            ensure_ascii=False,
        )
    )


def cmd_funding_walk_forward(
    cfg: AppConfig,
    input_path: str | None,
    output_path: str | None,
    notional_quote: float,
    spot_fee_bps: float,
    perp_fee_bps: float,
    slippage_bps: float,
    min_funding_rate: float,
    min_total_score: float,
    max_spot_spread_bps: float,
    max_perp_spread_bps: float,
    max_abs_basis_bps: float,
    min_basis_bps: float,
    min_expected_net_carry_bps: float,
    min_risk_adjusted_edge_bps: float,
    basis_risk_multiplier: float,
    spread_risk_multiplier: float,
    max_break_even_hours: float,
    min_funding_observations: int,
    min_funding_positive_ratio: float,
    min_funding_persistence_score: float,
    min_regime_observations: int,
    min_perp_volume_24h_quote: float,
    min_spot_top_notional_quote: float,
    max_basis_std_bps: float,
    max_avg_spot_spread_bps: float,
    max_avg_perp_spread_bps: float,
    walk_train_rows: int,
    walk_test_rows: int,
    walk_step_rows: int,
    walk_min_windows: int,
    walk_min_accepted_windows: int,
    walk_min_accepted_ratio: float,
    walk_min_train_span_hours: float,
    walk_min_test_span_hours: float,
    accept_min_trades: int,
    accept_min_win_rate: float,
    accept_min_expectancy_quote: float,
    accept_min_net_pnl_quote: float,
    accept_max_drawdown_quote: float,
    accept_min_profit_factor: float,
    accept_min_markets: int,
    accept_max_market_trade_share: float,
    accept_min_exchanges: int,
    accept_max_exchange_trade_share: float,
    accept_min_profitable_windows: int,
    accept_max_window_pnl_share: float,
    stress_enabled: bool,
    stress_adverse_basis_bps: float,
    stress_spread_widen_bps: float,
    stress_funding_flip_bps: float,
    stress_min_net_pnl_quote: float,
    stress_max_drawdown_quote: float,
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    backtest_dir = _ensure_dir(cfg.paths.backtest_dir)
    src = Path(input_path) if input_path else _latest_funding_input(funding_dir)
    out = Path(output_path) if output_path else default_funding_walk_forward_path(backtest_dir)
    bt_cfg = FundingBacktestConfig(
        notional_quote=notional_quote,
        spot_fee_bps=spot_fee_bps,
        perp_fee_bps=perp_fee_bps,
        slippage_bps=slippage_bps,
        min_funding_rate=min_funding_rate,
        min_total_score=min_total_score,
        max_spot_spread_bps=max_spot_spread_bps,
        max_perp_spread_bps=max_perp_spread_bps,
        max_abs_basis_bps=max_abs_basis_bps,
        min_basis_bps=min_basis_bps,
        min_expected_net_carry_bps=min_expected_net_carry_bps,
        min_risk_adjusted_edge_bps=min_risk_adjusted_edge_bps,
        basis_risk_multiplier=basis_risk_multiplier,
        spread_risk_multiplier=spread_risk_multiplier,
        max_break_even_hours=max_break_even_hours,
        min_funding_observations=min_funding_observations,
        min_funding_positive_ratio=min_funding_positive_ratio,
        min_funding_persistence_score=min_funding_persistence_score,
        min_regime_observations=min_regime_observations,
        min_perp_volume_24h_quote=min_perp_volume_24h_quote,
        min_spot_top_notional_quote=min_spot_top_notional_quote,
        max_basis_std_bps=max_basis_std_bps,
        max_avg_spot_spread_bps=max_avg_spot_spread_bps,
        max_avg_perp_spread_bps=max_avg_perp_spread_bps,
    )
    result = run_funding_walk_forward_backtest_file(
        src,
        out,
        backtest_cfg=bt_cfg,
        acceptance_cfg=FundingAcceptanceConfig(
            min_trades=accept_min_trades,
            min_win_rate=accept_min_win_rate,
            min_expectancy_quote=accept_min_expectancy_quote,
            min_net_pnl_quote=accept_min_net_pnl_quote,
            max_drawdown_quote=accept_max_drawdown_quote,
            min_profit_factor=accept_min_profit_factor,
            min_markets=accept_min_markets,
            max_market_trade_share=accept_max_market_trade_share,
            min_exchanges=accept_min_exchanges,
            max_exchange_trade_share=accept_max_exchange_trade_share,
            min_profitable_windows=accept_min_profitable_windows,
            max_window_pnl_share=accept_max_window_pnl_share,
        ),
        walk_cfg=FundingWalkForwardConfig(
            train_rows=walk_train_rows,
            test_rows=walk_test_rows,
            step_rows=walk_step_rows,
            min_windows=walk_min_windows,
            min_accepted_windows=walk_min_accepted_windows,
            min_accepted_ratio=walk_min_accepted_ratio,
            min_train_span_hours=walk_min_train_span_hours,
            min_test_span_hours=walk_min_test_span_hours,
        ),
        stress_cfg=FundingStressConfig(
            enabled=stress_enabled,
            adverse_basis_bps=stress_adverse_basis_bps,
            spread_widen_bps=stress_spread_widen_bps,
            funding_flip_bps=stress_funding_flip_bps,
            min_stress_net_pnl_quote=stress_min_net_pnl_quote,
            max_stress_drawdown_quote=stress_max_drawdown_quote,
        ),
    )
    print(
        json.dumps(
            {
                "ok": result["ok"],
                "status": result["status"],
                "accepted": result["accepted"],
                "input": str(src),
                "output": str(out),
                "summary": result["summary"],
                "reasons": result.get("reasons", []),
                "windows_preview": result.get("windows", [])[:3],
            },
            ensure_ascii=False,
        )
    )


def cmd_funding_postprocess(
    cfg: AppConfig,
    input_path: str | None,
    manifest_path: str | None,
    rank_output_path: str | None,
    backtest_output_path: str | None,
    oos_output_path: str | None,
    walk_forward_output_path: str | None,
    postprocess_output_path: str | None,
    allow_partial: bool,
    top_n: int,
    min_funding_observations: int,
    min_funding_positive_ratio: float,
    min_funding_persistence_score: float,
    funding_persistence_weight: float,
    notional_quote: float,
    spot_fee_bps: float,
    perp_fee_bps: float,
    slippage_bps: float,
    min_funding_rate: float,
    min_total_score: float,
    max_spot_spread_bps: float,
    max_perp_spread_bps: float,
    max_abs_basis_bps: float,
    min_basis_bps: float,
    min_expected_net_carry_bps: float,
    min_risk_adjusted_edge_bps: float,
    basis_risk_multiplier: float,
    spread_risk_multiplier: float,
    max_break_even_hours: float,
    min_regime_observations: int,
    min_perp_volume_24h_quote: float,
    min_spot_top_notional_quote: float,
    max_basis_std_bps: float,
    max_avg_spot_spread_bps: float,
    max_avg_perp_spread_bps: float,
    accept_min_trades: int,
    accept_min_win_rate: float,
    accept_min_expectancy_quote: float,
    accept_min_net_pnl_quote: float,
    accept_max_drawdown_quote: float,
    accept_min_profit_factor: float,
    accept_min_markets: int,
    accept_max_market_trade_share: float,
    accept_min_exchanges: int,
    accept_max_exchange_trade_share: float,
    accept_min_profitable_windows: int,
    accept_max_window_pnl_share: float,
    stress_enabled: bool,
    stress_adverse_basis_bps: float,
    stress_spread_widen_bps: float,
    stress_funding_flip_bps: float,
    stress_min_net_pnl_quote: float,
    stress_max_drawdown_quote: float,
    oos_train_fraction: float,
    oos_min_train_rows: int,
    oos_min_rows: int,
    oos_min_train_span_hours: float,
    oos_min_span_hours: float,
    walk_train_rows: int,
    walk_test_rows: int,
    walk_step_rows: int,
    walk_min_windows: int,
    walk_min_accepted_windows: int,
    walk_min_accepted_ratio: float,
    walk_min_train_span_hours: float,
    walk_min_test_span_hours: float,
    quality_min_rows: int,
    quality_min_markets: int,
    quality_min_completed_cycles: int,
    quality_min_unique_cycles: int,
    quality_min_avg_rows_per_cycle: float,
    quality_min_min_rows_per_cycle: int,
    quality_max_error_rate: float,
    quality_max_cycle_market_duplicate_rate: float,
    quality_required_row_fields: str,
    quality_min_required_row_field_presence: float,
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    backtest_dir = _ensure_dir(cfg.paths.backtest_dir)
    src = Path(input_path) if input_path else _latest_funding_input(funding_dir)
    default_rank, default_backtest = default_funding_postprocess_output(src, funding_dir, backtest_dir)
    rank_out = Path(rank_output_path) if rank_output_path else default_rank
    backtest_out = Path(backtest_output_path) if backtest_output_path else default_backtest
    if oos_output_path == AUTO_FUNDING_OOS_OUTPUT:
        oos_out = backtest_dir / f"funding_oos_{src.stem}.json"
    else:
        oos_out = Path(oos_output_path) if oos_output_path else None
    if walk_forward_output_path == AUTO_FUNDING_WALK_FORWARD_OUTPUT:
        walk_out = backtest_dir / f"funding_walk_forward_{src.stem}.json"
    else:
        walk_out = Path(walk_forward_output_path) if walk_forward_output_path else None
    postprocess_out = Path(postprocess_output_path) if postprocess_output_path else default_funding_postprocess_summary_path(src, funding_dir)
    manifest = Path(manifest_path) if manifest_path else src.with_suffix(".manifest.json")
    rank_cfg = FundingRankConfig(
        min_funding_rate=min_funding_rate,
        min_funding_observations=min_funding_observations,
        min_funding_positive_ratio=min_funding_positive_ratio,
        min_funding_persistence_score=min_funding_persistence_score,
        persistence_weight=funding_persistence_weight,
        max_spot_spread_bps=max_spot_spread_bps,
        max_perp_spread_bps=max_perp_spread_bps,
        max_abs_basis_bps=max_abs_basis_bps,
        min_basis_bps=min_basis_bps,
        min_expected_net_carry_bps=min_expected_net_carry_bps,
        min_risk_adjusted_edge_bps=min_risk_adjusted_edge_bps,
        basis_risk_multiplier=basis_risk_multiplier,
        spread_risk_multiplier=spread_risk_multiplier,
        max_break_even_hours=max_break_even_hours,
        min_regime_observations=min_regime_observations,
        min_perp_volume_24h_quote=min_perp_volume_24h_quote,
        min_spot_top_notional_quote=min_spot_top_notional_quote,
        max_basis_std_bps=max_basis_std_bps,
        max_avg_spot_spread_bps=max_avg_spot_spread_bps,
        max_avg_perp_spread_bps=max_avg_perp_spread_bps,
    )
    bt_cfg = FundingBacktestConfig(
        notional_quote=notional_quote,
        spot_fee_bps=spot_fee_bps,
        perp_fee_bps=perp_fee_bps,
        slippage_bps=slippage_bps,
        min_funding_rate=min_funding_rate,
        min_total_score=min_total_score,
        max_spot_spread_bps=max_spot_spread_bps,
        max_perp_spread_bps=max_perp_spread_bps,
        max_abs_basis_bps=max_abs_basis_bps,
        min_basis_bps=min_basis_bps,
        min_expected_net_carry_bps=min_expected_net_carry_bps,
        min_risk_adjusted_edge_bps=min_risk_adjusted_edge_bps,
        basis_risk_multiplier=basis_risk_multiplier,
        spread_risk_multiplier=spread_risk_multiplier,
        max_break_even_hours=max_break_even_hours,
        min_funding_observations=min_funding_observations,
        min_funding_positive_ratio=min_funding_positive_ratio,
        min_funding_persistence_score=min_funding_persistence_score,
        min_regime_observations=min_regime_observations,
        min_perp_volume_24h_quote=min_perp_volume_24h_quote,
        min_spot_top_notional_quote=min_spot_top_notional_quote,
        max_basis_std_bps=max_basis_std_bps,
        max_avg_spot_spread_bps=max_avg_spot_spread_bps,
        max_avg_perp_spread_bps=max_avg_perp_spread_bps,
    )
    acceptance_cfg = FundingAcceptanceConfig(
        min_trades=accept_min_trades,
        min_win_rate=accept_min_win_rate,
        min_expectancy_quote=accept_min_expectancy_quote,
        min_net_pnl_quote=accept_min_net_pnl_quote,
        max_drawdown_quote=accept_max_drawdown_quote,
        min_profit_factor=accept_min_profit_factor,
        min_markets=accept_min_markets,
        max_market_trade_share=accept_max_market_trade_share,
        min_exchanges=accept_min_exchanges,
        max_exchange_trade_share=accept_max_exchange_trade_share,
        min_profitable_windows=accept_min_profitable_windows,
        max_window_pnl_share=accept_max_window_pnl_share,
    )
    stress_cfg = FundingStressConfig(
        enabled=stress_enabled,
        adverse_basis_bps=stress_adverse_basis_bps,
        spread_widen_bps=stress_spread_widen_bps,
        funding_flip_bps=stress_funding_flip_bps,
        min_stress_net_pnl_quote=stress_min_net_pnl_quote,
        max_stress_drawdown_quote=stress_max_drawdown_quote,
    )
    result = run_funding_postprocess_file(
        input_path=src,
        manifest_path=manifest,
        rank_output_path=rank_out,
        backtest_output_path=backtest_out,
        rank_cfg=rank_cfg,
        backtest_cfg=bt_cfg,
        acceptance_cfg=acceptance_cfg,
        stress_cfg=stress_cfg,
        oos_output_path=oos_out,
        oos_cfg=FundingOosConfig(
            train_fraction=oos_train_fraction,
            min_train_rows=oos_min_train_rows,
            min_oos_rows=oos_min_rows,
            min_train_span_hours=oos_min_train_span_hours,
            min_oos_span_hours=oos_min_span_hours,
        )
        if oos_out is not None
        else None,
        walk_forward_output_path=walk_out,
        walk_forward_cfg=FundingWalkForwardConfig(
            train_rows=walk_train_rows,
            test_rows=walk_test_rows,
            step_rows=walk_step_rows,
            min_windows=walk_min_windows,
            min_accepted_windows=walk_min_accepted_windows,
            min_accepted_ratio=walk_min_accepted_ratio,
            min_train_span_hours=walk_min_train_span_hours,
            min_test_span_hours=walk_min_test_span_hours,
        )
        if walk_out is not None
        else None,
        data_quality_cfg=FundingDataQualityConfig(
            min_rows=quality_min_rows,
            min_markets=quality_min_markets,
            min_completed_cycles=quality_min_completed_cycles,
            min_unique_cycles=quality_min_unique_cycles,
            min_avg_rows_per_cycle=quality_min_avg_rows_per_cycle,
            min_min_rows_per_cycle=quality_min_min_rows_per_cycle,
            max_error_rate=quality_max_error_rate,
            max_cycle_market_duplicate_rate=quality_max_cycle_market_duplicate_rate,
            required_row_fields=_parse_optional_csv(quality_required_row_fields),
            min_required_row_field_presence=quality_min_required_row_field_presence,
        ),
        top_n=top_n,
        require_final=not allow_partial,
    )
    result["postprocess_output"] = str(postprocess_out)
    postprocess_out.parent.mkdir(parents=True, exist_ok=True)
    postprocess_out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


def cmd_funding_finalize(
    cfg: AppConfig,
    input_path: str | None,
    manifest_path: str | None,
    rank_output_path: str | None,
    backtest_output_path: str | None,
    oos_output_path: str | None,
    walk_forward_output_path: str | None,
    postprocess_output_path: str | None,
    paper_plan_output_path: str | None,
    paper_output_path: str | None,
    top_n: int,
    min_funding_observations: int,
    min_funding_positive_ratio: float,
    min_funding_persistence_score: float,
    funding_persistence_weight: float,
    notional_quote: float,
    spot_fee_bps: float,
    perp_fee_bps: float,
    slippage_bps: float,
    min_funding_rate: float,
    min_total_score: float,
    max_spot_spread_bps: float,
    max_perp_spread_bps: float,
    max_abs_basis_bps: float,
    min_basis_bps: float,
    min_expected_net_carry_bps: float,
    min_risk_adjusted_edge_bps: float,
    basis_risk_multiplier: float,
    spread_risk_multiplier: float,
    max_break_even_hours: float,
    min_regime_observations: int,
    min_perp_volume_24h_quote: float,
    min_spot_top_notional_quote: float,
    max_basis_std_bps: float,
    max_avg_spot_spread_bps: float,
    max_avg_perp_spread_bps: float,
    accept_min_trades: int,
    accept_min_win_rate: float,
    accept_min_expectancy_quote: float,
    accept_min_net_pnl_quote: float,
    accept_max_drawdown_quote: float,
    accept_min_profit_factor: float,
    accept_min_markets: int,
    accept_max_market_trade_share: float,
    accept_min_exchanges: int,
    accept_max_exchange_trade_share: float,
    accept_min_profitable_windows: int,
    accept_max_window_pnl_share: float,
    stress_enabled: bool,
    stress_adverse_basis_bps: float,
    stress_spread_widen_bps: float,
    stress_funding_flip_bps: float,
    stress_min_net_pnl_quote: float,
    stress_max_drawdown_quote: float,
    oos_train_fraction: float,
    oos_min_train_rows: int,
    oos_min_rows: int,
    oos_min_train_span_hours: float,
    oos_min_span_hours: float,
    walk_train_rows: int,
    walk_test_rows: int,
    walk_step_rows: int,
    walk_min_windows: int,
    walk_min_accepted_windows: int,
    walk_min_accepted_ratio: float,
    walk_min_train_span_hours: float,
    walk_min_test_span_hours: float,
    quality_min_rows: int,
    quality_min_markets: int,
    quality_min_completed_cycles: int,
    quality_min_unique_cycles: int,
    quality_min_avg_rows_per_cycle: float,
    quality_min_min_rows_per_cycle: int,
    quality_max_error_rate: float,
    quality_max_cycle_market_duplicate_rate: float,
    quality_required_row_fields: str,
    quality_min_required_row_field_presence: float,
    min_forward_hours: float,
    min_forward_rows: int,
    min_forward_markets: int,
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    backtest_dir = _ensure_dir(cfg.paths.backtest_dir)
    src = Path(input_path) if input_path else _latest_funding_input(funding_dir)
    manifest = Path(manifest_path) if manifest_path else src.with_suffix(".manifest.json")
    default_rank, default_backtest = default_funding_postprocess_output(src, funding_dir, backtest_dir)
    rank_out = Path(rank_output_path) if rank_output_path else default_rank
    backtest_out = Path(backtest_output_path) if backtest_output_path else default_backtest
    oos_out = Path(oos_output_path) if oos_output_path else backtest_dir / f"funding_oos_{src.stem}.json"
    walk_out = Path(walk_forward_output_path) if walk_forward_output_path else backtest_dir / f"funding_walk_forward_{src.stem}.json"
    postprocess_out = Path(postprocess_output_path) if postprocess_output_path else default_funding_postprocess_summary_path(src, funding_dir)
    paper_plan_out = Path(paper_plan_output_path) if paper_plan_output_path else default_funding_paper_forward_plan_path(funding_dir)
    rank_cfg = FundingRankConfig(
        min_funding_rate=min_funding_rate,
        min_funding_observations=min_funding_observations,
        min_funding_positive_ratio=min_funding_positive_ratio,
        min_funding_persistence_score=min_funding_persistence_score,
        persistence_weight=funding_persistence_weight,
        max_spot_spread_bps=max_spot_spread_bps,
        max_perp_spread_bps=max_perp_spread_bps,
        max_abs_basis_bps=max_abs_basis_bps,
        min_basis_bps=min_basis_bps,
        min_expected_net_carry_bps=min_expected_net_carry_bps,
        min_risk_adjusted_edge_bps=min_risk_adjusted_edge_bps,
        basis_risk_multiplier=basis_risk_multiplier,
        spread_risk_multiplier=spread_risk_multiplier,
        max_break_even_hours=max_break_even_hours,
        min_regime_observations=min_regime_observations,
        min_perp_volume_24h_quote=min_perp_volume_24h_quote,
        min_spot_top_notional_quote=min_spot_top_notional_quote,
        max_basis_std_bps=max_basis_std_bps,
        max_avg_spot_spread_bps=max_avg_spot_spread_bps,
        max_avg_perp_spread_bps=max_avg_perp_spread_bps,
    )
    bt_cfg = FundingBacktestConfig(
        notional_quote=notional_quote,
        spot_fee_bps=spot_fee_bps,
        perp_fee_bps=perp_fee_bps,
        slippage_bps=slippage_bps,
        min_funding_rate=min_funding_rate,
        min_total_score=min_total_score,
        max_spot_spread_bps=max_spot_spread_bps,
        max_perp_spread_bps=max_perp_spread_bps,
        max_abs_basis_bps=max_abs_basis_bps,
        min_basis_bps=min_basis_bps,
        min_expected_net_carry_bps=min_expected_net_carry_bps,
        min_risk_adjusted_edge_bps=min_risk_adjusted_edge_bps,
        basis_risk_multiplier=basis_risk_multiplier,
        spread_risk_multiplier=spread_risk_multiplier,
        max_break_even_hours=max_break_even_hours,
        min_funding_observations=min_funding_observations,
        min_funding_positive_ratio=min_funding_positive_ratio,
        min_funding_persistence_score=min_funding_persistence_score,
        min_regime_observations=min_regime_observations,
        min_perp_volume_24h_quote=min_perp_volume_24h_quote,
        min_spot_top_notional_quote=min_spot_top_notional_quote,
        max_basis_std_bps=max_basis_std_bps,
        max_avg_spot_spread_bps=max_avg_spot_spread_bps,
        max_avg_perp_spread_bps=max_avg_perp_spread_bps,
    )
    acceptance_cfg = FundingAcceptanceConfig(
        min_trades=accept_min_trades,
        min_win_rate=accept_min_win_rate,
        min_expectancy_quote=accept_min_expectancy_quote,
        min_net_pnl_quote=accept_min_net_pnl_quote,
        max_drawdown_quote=accept_max_drawdown_quote,
        min_profit_factor=accept_min_profit_factor,
        min_markets=accept_min_markets,
        max_market_trade_share=accept_max_market_trade_share,
        min_exchanges=accept_min_exchanges,
        max_exchange_trade_share=accept_max_exchange_trade_share,
        min_profitable_windows=accept_min_profitable_windows,
        max_window_pnl_share=accept_max_window_pnl_share,
    )
    stress_cfg = FundingStressConfig(
        enabled=stress_enabled,
        adverse_basis_bps=stress_adverse_basis_bps,
        spread_widen_bps=stress_spread_widen_bps,
        funding_flip_bps=stress_funding_flip_bps,
        min_stress_net_pnl_quote=stress_min_net_pnl_quote,
        max_stress_drawdown_quote=stress_max_drawdown_quote,
    )
    result = run_funding_research_finalize_file(
        input_path=src,
        manifest_path=manifest,
        postprocess_output_path=postprocess_out,
        rank_output_path=rank_out,
        backtest_output_path=backtest_out,
        oos_output_path=oos_out,
        walk_forward_output_path=walk_out,
        paper_plan_output_path=paper_plan_out,
        paper_output_path=paper_output_path,
        rank_cfg=rank_cfg,
        backtest_cfg=bt_cfg,
        acceptance_cfg=acceptance_cfg,
        stress_cfg=stress_cfg,
        oos_cfg=FundingOosConfig(
            train_fraction=oos_train_fraction,
            min_train_rows=oos_min_train_rows,
            min_oos_rows=oos_min_rows,
            min_train_span_hours=oos_min_train_span_hours,
            min_oos_span_hours=oos_min_span_hours,
        ),
        walk_forward_cfg=FundingWalkForwardConfig(
            train_rows=walk_train_rows,
            test_rows=walk_test_rows,
            step_rows=walk_step_rows,
            min_windows=walk_min_windows,
            min_accepted_windows=walk_min_accepted_windows,
            min_accepted_ratio=walk_min_accepted_ratio,
            min_train_span_hours=walk_min_train_span_hours,
            min_test_span_hours=walk_min_test_span_hours,
        ),
        data_quality_cfg=FundingDataQualityConfig(
            min_rows=quality_min_rows,
            min_markets=quality_min_markets,
            min_completed_cycles=quality_min_completed_cycles,
            min_unique_cycles=quality_min_unique_cycles,
            min_avg_rows_per_cycle=quality_min_avg_rows_per_cycle,
            min_min_rows_per_cycle=quality_min_min_rows_per_cycle,
            max_error_rate=quality_max_error_rate,
            max_cycle_market_duplicate_rate=quality_max_cycle_market_duplicate_rate,
            required_row_fields=_parse_optional_csv(quality_required_row_fields),
            min_required_row_field_presence=quality_min_required_row_field_presence,
        ),
        top_n=top_n,
        min_forward_hours=min_forward_hours,
        min_forward_rows=min_forward_rows,
        min_forward_markets=min_forward_markets,
    )
    print(json.dumps(result, ensure_ascii=False))


def cmd_funding_final_review(cfg: AppConfig, args: argparse.Namespace) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    backtest_dir = _ensure_dir(cfg.paths.backtest_dir)
    src = Path(args.input) if args.input else _latest_funding_input(funding_dir)
    manifest = Path(args.manifest) if args.manifest else src.with_suffix(".manifest.json")
    default_rank, default_backtest = default_funding_postprocess_output(src, funding_dir, backtest_dir)
    rank_out = Path(args.rank_output) if args.rank_output else default_rank
    backtest_out = Path(args.backtest_output) if args.backtest_output else default_backtest
    oos_out = Path(args.oos_output) if args.oos_output else backtest_dir / f"funding_oos_{src.stem}.json"
    walk_out = Path(args.walk_forward_output) if args.walk_forward_output else backtest_dir / f"funding_walk_forward_{src.stem}.json"
    postprocess_out = Path(args.postprocess_output) if args.postprocess_output else default_funding_postprocess_summary_path(src, funding_dir)
    paper_plan_out = Path(args.paper_plan_output) if args.paper_plan_output else default_funding_paper_forward_plan_path(funding_dir)
    review_out = Path(args.output) if args.output else default_funding_final_review_path(funding_dir)
    gate_out = Path(args.gate_report_output) if args.gate_report_output else default_funding_gate_report_path(funding_dir)
    regime_out = Path(args.regime_report_output) if args.regime_report_output else default_funding_regime_report_path(funding_dir)
    frontier_out = Path(args.frontier_report_output) if args.frontier_report_output else default_funding_frontier_report_path(funding_dir)
    sensitivity_out = Path(args.sensitivity_output) if args.sensitivity_output else default_funding_sensitivity_path(backtest_dir)
    decision_out = Path(args.decision_report_output) if args.decision_report_output else default_funding_decision_report_path(funding_dir)
    data_quality_cfg = FundingDataQualityConfig(
        min_rows=args.quality_min_rows,
        min_markets=args.quality_min_markets,
        min_completed_cycles=args.quality_min_completed_cycles,
        min_unique_cycles=args.quality_min_unique_cycles,
        min_avg_rows_per_cycle=args.quality_min_avg_rows_per_cycle,
        min_min_rows_per_cycle=args.quality_min_min_rows_per_cycle,
        max_error_rate=args.quality_max_error_rate,
        max_cycle_market_duplicate_rate=args.quality_max_cycle_market_duplicate_rate,
        required_row_fields=_parse_optional_csv(args.quality_required_row_fields),
        min_required_row_field_presence=args.quality_min_required_row_field_presence,
    )
    if args.wait_timeout_sec > 0:
        wait_out = Path(args.wait_output) if args.wait_output else None
        wait_funding_ready(
            src,
            manifest_path=manifest,
            output_path=wait_out,
            timeout_sec=args.wait_timeout_sec,
            poll_interval_sec=args.wait_poll_interval_sec,
            stale_after_sec=args.wait_stale_after_sec,
            data_quality_cfg=data_quality_cfg,
        )
    rank_cfg = FundingRankConfig(
        min_funding_rate=args.min_funding_rate,
        min_funding_observations=args.min_funding_observations,
        min_funding_positive_ratio=args.min_funding_positive_ratio,
        min_funding_persistence_score=args.min_funding_persistence_score,
        persistence_weight=args.funding_persistence_weight,
        max_spot_spread_bps=args.max_spot_spread_bps,
        max_perp_spread_bps=args.max_perp_spread_bps,
        max_abs_basis_bps=args.max_abs_basis_bps,
        min_basis_bps=args.min_basis_bps,
        min_expected_net_carry_bps=args.min_expected_net_carry_bps,
        min_risk_adjusted_edge_bps=args.min_risk_adjusted_edge_bps,
        basis_risk_multiplier=args.basis_risk_multiplier,
        spread_risk_multiplier=args.spread_risk_multiplier,
        max_break_even_hours=args.max_break_even_hours,
        min_regime_observations=args.min_regime_observations,
        min_perp_volume_24h_quote=args.min_perp_volume_24h_quote,
        min_spot_top_notional_quote=args.min_spot_top_notional_quote,
        max_basis_std_bps=args.max_basis_std_bps,
        max_avg_spot_spread_bps=args.max_avg_spot_spread_bps,
        max_avg_perp_spread_bps=args.max_avg_perp_spread_bps,
    )
    backtest_cfg = FundingBacktestConfig(
        notional_quote=args.notional_quote,
        spot_fee_bps=args.spot_fee_bps,
        perp_fee_bps=args.perp_fee_bps,
        slippage_bps=args.slippage_bps,
        min_funding_rate=args.min_funding_rate,
        min_total_score=args.min_total_score,
        max_spot_spread_bps=args.max_spot_spread_bps,
        max_perp_spread_bps=args.max_perp_spread_bps,
        max_abs_basis_bps=args.max_abs_basis_bps,
        min_basis_bps=args.min_basis_bps,
        min_expected_net_carry_bps=args.min_expected_net_carry_bps,
        min_risk_adjusted_edge_bps=args.min_risk_adjusted_edge_bps,
        basis_risk_multiplier=args.basis_risk_multiplier,
        spread_risk_multiplier=args.spread_risk_multiplier,
        max_break_even_hours=args.max_break_even_hours,
        min_funding_observations=args.min_funding_observations,
        min_funding_positive_ratio=args.min_funding_positive_ratio,
        min_funding_persistence_score=args.min_funding_persistence_score,
        min_regime_observations=args.min_regime_observations,
        min_perp_volume_24h_quote=args.min_perp_volume_24h_quote,
        min_spot_top_notional_quote=args.min_spot_top_notional_quote,
        max_basis_std_bps=args.max_basis_std_bps,
        max_avg_spot_spread_bps=args.max_avg_spot_spread_bps,
        max_avg_perp_spread_bps=args.max_avg_perp_spread_bps,
    )
    acceptance_cfg = FundingAcceptanceConfig(
        min_trades=args.accept_min_trades,
        min_win_rate=args.accept_min_win_rate,
        min_expectancy_quote=args.accept_min_expectancy_quote,
        min_net_pnl_quote=args.accept_min_net_pnl_quote,
        max_drawdown_quote=args.accept_max_drawdown_quote,
        min_profit_factor=args.accept_min_profit_factor,
        min_markets=args.accept_min_markets,
        max_market_trade_share=args.accept_max_market_trade_share,
        min_exchanges=args.accept_min_exchanges,
        max_exchange_trade_share=args.accept_max_exchange_trade_share,
        min_profitable_windows=args.accept_min_profitable_windows,
        max_window_pnl_share=args.accept_max_window_pnl_share,
    )
    stress_cfg = FundingStressConfig(
        enabled=args.stress_enabled,
        adverse_basis_bps=args.stress_adverse_basis_bps,
        spread_widen_bps=args.stress_spread_widen_bps,
        funding_flip_bps=args.stress_funding_flip_bps,
        min_stress_net_pnl_quote=args.stress_min_net_pnl_quote,
        max_stress_drawdown_quote=args.stress_max_drawdown_quote,
    )
    sensitivity_cfg = FundingSensitivityConfig(
        spot_fee_bps_values=tuple(parse_float_list(args.sensitivity_spot_fee_bps)),
        perp_fee_bps_values=tuple(parse_float_list(args.sensitivity_perp_fee_bps)),
        slippage_bps_values=tuple(parse_float_list(args.sensitivity_slippage_bps)),
        target_hold_intervals_values=tuple(parse_float_list(args.sensitivity_target_hold_intervals)),
        max_break_even_hours_values=tuple(parse_float_list(args.sensitivity_max_break_even_hours)),
        top_n=args.top_n,
    )
    result = run_funding_final_review_file(
        input_path=src,
        manifest_path=manifest,
        output_path=review_out,
        postprocess_output_path=postprocess_out,
        rank_output_path=rank_out,
        backtest_output_path=backtest_out,
        oos_output_path=oos_out,
        walk_forward_output_path=walk_out,
        paper_plan_output_path=paper_plan_out,
        paper_output_path=args.paper_output,
        gate_report_output_path=gate_out,
        regime_report_output_path=regime_out,
        frontier_report_output_path=frontier_out,
        sensitivity_output_path=sensitivity_out,
        decision_report_output_path=decision_out,
        rank_cfg=rank_cfg,
        backtest_cfg=backtest_cfg,
        acceptance_cfg=acceptance_cfg,
        stress_cfg=stress_cfg,
        sensitivity_cfg=sensitivity_cfg,
        oos_cfg=FundingOosConfig(
            train_fraction=args.oos_train_fraction,
            min_train_rows=args.oos_min_train_rows,
            min_oos_rows=args.oos_min_rows,
            min_train_span_hours=args.oos_min_train_span_hours,
            min_oos_span_hours=args.oos_min_span_hours,
        ),
        walk_forward_cfg=FundingWalkForwardConfig(
            train_rows=args.walk_train_rows,
            test_rows=args.walk_test_rows,
            step_rows=args.walk_step_rows,
            min_windows=args.walk_min_windows,
            min_accepted_windows=args.walk_min_accepted_windows,
            min_accepted_ratio=args.walk_min_accepted_ratio,
            min_train_span_hours=args.walk_min_train_span_hours,
            min_test_span_hours=args.walk_min_test_span_hours,
        ),
        data_quality_cfg=data_quality_cfg,
        top_n=args.top_n,
        min_forward_hours=args.min_forward_hours,
        min_forward_rows=args.min_forward_rows,
        min_forward_markets=args.min_forward_markets,
    )
    print(json.dumps(result, ensure_ascii=False))


def cmd_funding_paper_plan(
    cfg: AppConfig,
    postprocess_path: str,
    decision_report_path: str,
    output_path: str | None,
    paper_output_path: str | None,
    min_forward_hours: float,
    min_forward_rows: int,
    min_forward_markets: int,
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    out = Path(output_path) if output_path else default_funding_paper_forward_plan_path(funding_dir)
    result = create_funding_paper_forward_plan_file(
        postprocess_path,
        out,
        paper_output_path=paper_output_path,
        decision_report_path=decision_report_path,
        min_forward_hours=min_forward_hours,
        min_forward_rows=min_forward_rows,
        min_forward_markets=min_forward_markets,
    )
    print(
        json.dumps(
            {
                "ok": result["ok"],
                "status": result["status"],
                "ready_for_paper_forward": result["ready_for_paper_forward"],
                "output": str(out),
                "paper_output_path": result["paper_output_path"],
            },
            ensure_ascii=False,
        )
    )


def cmd_funding_paper_forward(
    cfg: AppConfig,
    plan_path: str,
    input_path: str,
    output_path: str | None,
    summary_output_path: str | None,
    allow_source_input: bool,
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    result = run_funding_paper_forward_file(
        plan_path,
        input_path,
        output_path=output_path,
        summary_output_path=summary_output_path,
        allow_source_input=allow_source_input,
    )
    out = result.get("output") or output_path or str(funding_dir / f"funding_paper_forward_{utc_stamp()}.jsonl")
    print(
        json.dumps(
            {
                "ok": result["ok"],
                "status": result["status"],
                "output": str(out),
                "summary_output": result.get("summary_output"),
                "input": result["input"],
                "plan": result["plan"],
                "metrics": result.get("metrics", {}),
                "paper_acceptance": result.get("paper_acceptance"),
                "live_orders": result["live_orders"],
            },
            ensure_ascii=False,
        )
    )


def cmd_funding_paper_decision_report(
    cfg: AppConfig,
    summary_path: str,
    plan_path: str | None,
    output_path: str | None,
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    out = Path(output_path) if output_path else default_funding_paper_decision_report_path(funding_dir)
    result = funding_paper_decision_report(
        summary_path,
        plan_path=plan_path,
        output_path=out,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(out),
                "summary": result["summary"],
                "research_only": result["research_only"],
                "live_orders": result["live_orders"],
            },
            ensure_ascii=False,
        )
    )


def cmd_funding_goal_audit(
    cfg: AppConfig,
    input_path: str | None,
    manifest_path: str | None,
    final_review_path: str | None,
    paper_plan_path: str | None,
    paper_summary_path: str | None,
    paper_decision_path: str | None,
    output_path: str | None,
    stale_after_sec: float,
    quality_min_rows: int | None,
    quality_min_markets: int | None,
    quality_min_completed_cycles: int | None,
    quality_min_unique_cycles: int | None,
    quality_min_avg_rows_per_cycle: float | None,
    quality_min_min_rows_per_cycle: int | None,
    quality_max_error_rate: float | None,
    quality_max_cycle_market_duplicate_rate: float | None,
    quality_required_row_fields: str | None,
    quality_min_required_row_field_presence: float | None,
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    src = Path(input_path) if input_path else _latest_funding_input(funding_dir)
    manifest = Path(manifest_path) if manifest_path else src.with_suffix(".manifest.json")
    out = Path(output_path) if output_path else default_funding_goal_audit_path(funding_dir)
    quality_values = [
        quality_min_rows,
        quality_min_markets,
        quality_min_completed_cycles,
        quality_min_unique_cycles,
        quality_min_avg_rows_per_cycle,
        quality_min_min_rows_per_cycle,
        quality_max_error_rate,
        quality_max_cycle_market_duplicate_rate,
        quality_required_row_fields,
        quality_min_required_row_field_presence,
    ]
    data_quality_cfg = None
    if any(value is not None for value in quality_values):
        defaults = FundingDataQualityConfig()
        data_quality_cfg = FundingDataQualityConfig(
            min_rows=quality_min_rows if quality_min_rows is not None else defaults.min_rows,
            min_markets=quality_min_markets if quality_min_markets is not None else defaults.min_markets,
            min_completed_cycles=quality_min_completed_cycles
            if quality_min_completed_cycles is not None
            else defaults.min_completed_cycles,
            min_unique_cycles=quality_min_unique_cycles if quality_min_unique_cycles is not None else defaults.min_unique_cycles,
            min_avg_rows_per_cycle=quality_min_avg_rows_per_cycle
            if quality_min_avg_rows_per_cycle is not None
            else defaults.min_avg_rows_per_cycle,
            min_min_rows_per_cycle=quality_min_min_rows_per_cycle
            if quality_min_min_rows_per_cycle is not None
            else defaults.min_min_rows_per_cycle,
            max_error_rate=quality_max_error_rate if quality_max_error_rate is not None else defaults.max_error_rate,
            max_cycle_market_duplicate_rate=quality_max_cycle_market_duplicate_rate
            if quality_max_cycle_market_duplicate_rate is not None
            else defaults.max_cycle_market_duplicate_rate,
            required_row_fields=_parse_optional_csv(quality_required_row_fields),
            min_required_row_field_presence=quality_min_required_row_field_presence
            if quality_min_required_row_field_presence is not None
            else defaults.min_required_row_field_presence,
        )
    result = funding_goal_audit(
        src,
        manifest_path=manifest,
        final_review_path=final_review_path,
        paper_plan_path=paper_plan_path,
        paper_summary_path=paper_summary_path,
        paper_decision_path=paper_decision_path,
        output_path=out,
        stale_after_sec=stale_after_sec,
        data_quality_cfg=data_quality_cfg,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "output": str(out),
                "summary": result["summary"],
                "research_only": result["research_only"],
                "live_orders": result["live_orders"],
            },
            ensure_ascii=False,
        )
    )


def cmd_funding_wait_ready(
    cfg: AppConfig,
    input_path: str | None,
    manifest_path: str | None,
    output_path: str | None,
    timeout_sec: float,
    poll_interval_sec: float,
    stale_after_sec: float,
    quality_min_rows: int | None,
    quality_min_markets: int | None,
    quality_min_completed_cycles: int | None,
    quality_min_unique_cycles: int | None,
    quality_min_avg_rows_per_cycle: float | None,
    quality_min_min_rows_per_cycle: int | None,
    quality_max_error_rate: float | None,
    quality_max_cycle_market_duplicate_rate: float | None,
    quality_required_row_fields: str | None,
    quality_min_required_row_field_presence: float | None,
) -> None:
    funding_dir = _ensure_dir(cfg.paths.funding_dir)
    src = Path(input_path) if input_path else _latest_funding_input(funding_dir)
    manifest = Path(manifest_path) if manifest_path else src.with_suffix(".manifest.json")
    out = Path(output_path) if output_path else default_funding_wait_ready_path(funding_dir)
    quality_values = [
        quality_min_rows,
        quality_min_markets,
        quality_min_completed_cycles,
        quality_min_unique_cycles,
        quality_min_avg_rows_per_cycle,
        quality_min_min_rows_per_cycle,
        quality_max_error_rate,
        quality_max_cycle_market_duplicate_rate,
        quality_required_row_fields,
        quality_min_required_row_field_presence,
    ]
    data_quality_cfg = None
    if any(value is not None for value in quality_values):
        defaults = FundingDataQualityConfig()
        data_quality_cfg = FundingDataQualityConfig(
            min_rows=quality_min_rows if quality_min_rows is not None else defaults.min_rows,
            min_markets=quality_min_markets if quality_min_markets is not None else defaults.min_markets,
            min_completed_cycles=quality_min_completed_cycles
            if quality_min_completed_cycles is not None
            else defaults.min_completed_cycles,
            min_unique_cycles=quality_min_unique_cycles if quality_min_unique_cycles is not None else defaults.min_unique_cycles,
            min_avg_rows_per_cycle=quality_min_avg_rows_per_cycle
            if quality_min_avg_rows_per_cycle is not None
            else defaults.min_avg_rows_per_cycle,
            min_min_rows_per_cycle=quality_min_min_rows_per_cycle
            if quality_min_min_rows_per_cycle is not None
            else defaults.min_min_rows_per_cycle,
            max_error_rate=quality_max_error_rate if quality_max_error_rate is not None else defaults.max_error_rate,
            max_cycle_market_duplicate_rate=quality_max_cycle_market_duplicate_rate
            if quality_max_cycle_market_duplicate_rate is not None
            else defaults.max_cycle_market_duplicate_rate,
            required_row_fields=_parse_optional_csv(quality_required_row_fields),
            min_required_row_field_presence=quality_min_required_row_field_presence
            if quality_min_required_row_field_presence is not None
            else defaults.min_required_row_field_presence,
        )
    result = wait_funding_ready(
        src,
        manifest_path=manifest,
        output_path=out,
        timeout_sec=timeout_sec,
        poll_interval_sec=poll_interval_sec,
        stale_after_sec=stale_after_sec,
        data_quality_cfg=data_quality_cfg,
    )
    print(
        json.dumps(
            {
                "ok": result["ok"],
                "status": result["status"],
                "output": str(out),
                "ready_for_postprocess": result["ready_for_postprocess"],
                "final_status": {
                    "status": (result.get("final_status") or {}).get("status"),
                    "completed_cycles": (result.get("final_status") or {}).get("completed_cycles"),
                    "cycles": (result.get("final_status") or {}).get("cycles"),
                    "line_count": (result.get("final_status") or {}).get("line_count"),
                    "errors": (result.get("final_status") or {}).get("errors"),
                    "readiness_reasons": (result.get("final_status") or {}).get("readiness", {}).get("reasons", []),
                },
                "research_only": result["research_only"],
                "live_orders": result["live_orders"],
            },
            ensure_ascii=False,
        )
    )


def cmd_setup_registry(cfg: AppConfig, output_path: str | None) -> None:
    experiment_dir = _ensure_dir(cfg.paths.experiment_dir)
    out = Path(output_path) if output_path else default_setup_registry_path(experiment_dir)
    result = write_setup_registry(out)
    print(json.dumps({"ok": True, **result}, ensure_ascii=False))


def cmd_experiment_record(
    cfg: AppConfig,
    source_video_id: str,
    source_url: str,
    source_channel: str,
    participant: str,
    claim_family: str,
    hypothesis: str,
    setup_id: str,
    dataset: str,
    config_json: str | None,
    result_path: str | None,
    metrics_json: str | None,
    verdict: str,
    verdict_reason: str,
    tags: str | None,
    notes: str,
    fee_schedule_revision: str,
    evaluation_scope: str,
    oos_status: str,
    output_path: str | None,
) -> None:
    experiment_dir = _ensure_dir(cfg.paths.experiment_dir)
    ledger = Path(output_path) if output_path else default_experiment_ledger_path(experiment_dir)
    config = parse_json_object(config_json, "config_json")
    metrics = parse_json_object(metrics_json, "metrics_json")
    if not metrics and result_path:
        metrics = extract_metrics_from_artifact(result_path, setup_id=setup_id)
    record = make_experiment_record(
        source_video_id=source_video_id,
        source_url=source_url,
        source_channel=source_channel,
        participant=participant,
        claim_family=claim_family,
        hypothesis=hypothesis,
        setup_id=setup_id,
        dataset=dataset,
        config=config,
        result_artifact=result_path or "",
        metrics=metrics,
        verdict=verdict,
        verdict_reason=verdict_reason,
        tags=[item.strip() for item in tags.split(",") if item.strip()] if tags else [],
        notes=notes,
        fee_schedule_revision=fee_schedule_revision,
        evaluation_scope=evaluation_scope,
        oos_status=oos_status,
    )
    result = append_experiment_record(ledger, record)
    print(
        json.dumps(
            {
                "ok": True,
                "output": result["output"],
                "record": result["record"],
            },
            ensure_ascii=False,
        )
    )


def cmd_experiment_list(
    cfg: AppConfig,
    input_path: str | None,
    verdict: str | None,
    setup_id: str | None,
    top_n: int,
    output_path: str | None,
) -> None:
    experiment_dir = _ensure_dir(cfg.paths.experiment_dir)
    ledger = Path(input_path) if input_path else default_experiment_ledger_path(experiment_dir)
    summary = summarize_experiment_ledger(ledger, verdict=verdict, setup_id=setup_id, top_n=top_n)
    if output_path:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"ok": True, **summary}, ensure_ascii=False))


def _add_funding_risk_adjusted_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--min-risk-adjusted-edge-bps", type=float, default=-1e9)
    parser.add_argument("--basis-risk-multiplier", type=float, default=1.0)
    parser.add_argument("--spread-risk-multiplier", type=float, default=1.0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MVP алготрейдинга")
    default_config = Path(__file__).resolve().parents[1] / "config.json"
    parser.add_argument(
        "--config",
        default=str(default_config),
        help="Путь к JSON-конфигу",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    collect = sub.add_parser("collect", help="Собрать рыночные снапшоты")
    collect.add_argument("--seconds", type=int, default=60)

    backtest = sub.add_parser("backtest", help="Запустить бэктест")
    backtest.add_argument("--input", type=str, default=None)
    backtest.add_argument("--qty", type=float, default=0.001)

    run = sub.add_parser("run", help="Paper-запуск без реальных ордеров")
    run.add_argument("--mode", choices=["paper"], default="paper")
    run.add_argument("--cycles", type=int, default=120)
    run.add_argument("--qty", type=float, default=0.001)

    universe = sub.add_parser("universe", help="Собрать universe монет вне Binance")
    universe.add_argument("--date-stamp", type=str, default=None)
    universe.add_argument("--top-preview", type=int, default=100)

    multi_run = sub.add_parser("multi-run", help="Paper-бот по стакану на нескольких spot-биржах")
    multi_run.add_argument("--exchanges", default="mexc,gateio,kucoin,bingx")
    multi_run.add_argument("--universe", type=str, default=None)
    multi_run.add_argument("--quote", type=str, default="USDT")
    multi_run.add_argument("--max-symbols", type=int, default=200)
    multi_run.add_argument("--max-pairs-per-exchange", type=int, default=5)
    multi_run.add_argument("--cycles", type=int, default=None)
    multi_run.add_argument("--duration-sec", type=int, default=None)
    multi_run.add_argument("--paper-notional-quote", type=float, default=25.0)

    ws_collect = sub.add_parser("ws-collect", help="Собрать raw WebSocket L2/trades market data")
    ws_collect.add_argument("--exchanges", default="mexc,gateio")
    ws_collect.add_argument("--universe", type=str, default=None)
    ws_collect.add_argument("--quote", type=str, default="USDT")
    ws_collect.add_argument("--max-symbols", type=int, default=200)
    ws_collect.add_argument("--max-pairs-per-exchange", type=int, default=3)
    ws_collect.add_argument("--duration-sec", type=int, default=30)
    ws_collect.add_argument("--update-interval", choices=["100ms", "10ms"], default="100ms")

    ws_normalize = sub.add_parser("ws-normalize", help="Нормализовать raw WebSocket events в общий JSONL")
    ws_normalize.add_argument("--input", type=str, default=None)
    ws_normalize.add_argument("--output", type=str, default=None)

    ws_quality = sub.add_parser("ws-data-quality", help="Проверить coverage/quality normalized WS JSONL перед replay/grid")
    ws_quality.add_argument("--input", type=str, default=None)
    ws_quality.add_argument("--manifest", type=str, default=None)
    ws_quality.add_argument("--output", type=str, default=None)
    ws_quality.add_argument("--min-rows", type=int, default=1)
    ws_quality.add_argument("--min-exchanges", type=int, default=1)
    ws_quality.add_argument("--min-markets", type=int, default=1)
    ws_quality.add_argument("--min-span-hours", type=float, default=0.0)
    ws_quality.add_argument("--min-duration-ratio", type=float, default=0.0)
    ws_quality.add_argument("--max-parse-error-rate", type=float, default=1.0)
    ws_quality.add_argument("--required-event-kinds", default="bbo,depth,trade")
    ws_quality.add_argument("--min-markets-with-required-kinds", type=int, default=0)
    ws_quality.add_argument("--max-market-event-share", type=float, default=1.0)
    ws_quality.add_argument("--max-gap-sec", type=float, default=0.0)
    ws_quality.add_argument("--max-manifest-error-count", type=int, default=1000000)

    ws_postprocess = sub.add_parser("ws-postprocess", help="Guarded WS normalize + data-quality gate before replay/grid")
    ws_postprocess.add_argument("--input", type=str, default=None)
    ws_postprocess.add_argument("--manifest", type=str, default=None)
    ws_postprocess.add_argument("--normalized-output", type=str, default=None)
    ws_postprocess.add_argument("--quality-output", type=str, default=None)
    ws_postprocess.add_argument("--output", type=str, default=None)
    ws_postprocess.add_argument("--min-rows", type=int, default=1)
    ws_postprocess.add_argument("--min-exchanges", type=int, default=1)
    ws_postprocess.add_argument("--min-markets", type=int, default=1)
    ws_postprocess.add_argument("--min-span-hours", type=float, default=0.0)
    ws_postprocess.add_argument("--min-duration-ratio", type=float, default=0.0)
    ws_postprocess.add_argument("--max-parse-error-rate", type=float, default=1.0)
    ws_postprocess.add_argument("--required-event-kinds", default="bbo,depth,trade")
    ws_postprocess.add_argument("--min-markets-with-required-kinds", type=int, default=0)
    ws_postprocess.add_argument("--max-market-event-share", type=float, default=1.0)
    ws_postprocess.add_argument("--max-gap-sec", type=float, default=0.0)
    ws_postprocess.add_argument("--max-manifest-error-count", type=int, default=1000000)

    perp_collect = sub.add_parser("perp-collect", help="Собрать public REST perp depth/trades/mark/funding в normalized JSONL")
    perp_collect.add_argument("--exchanges", default="mexc,gateio")
    perp_collect.add_argument("--universe", type=str, default=None)
    perp_collect.add_argument("--quote", type=str, default="USDT")
    perp_collect.add_argument("--max-symbols", type=int, default=200)
    perp_collect.add_argument("--max-pairs-per-exchange", type=int, default=3)
    perp_collect.add_argument("--cycles", type=int, default=3)
    perp_collect.add_argument("--duration-sec", type=int, default=None)
    perp_collect.add_argument("--poll-interval-sec", type=float, default=10.0)
    perp_collect.add_argument("--depth-limit", type=int, default=20)
    perp_collect.add_argument("--trades-limit", type=int, default=50)
    perp_collect.add_argument("--output", type=str, default=None)

    perp_report = sub.add_parser("perp-report", help="Проверить coverage/quality normalized perp JSONL перед replay/grid")
    perp_report.add_argument("--input", type=str, default=None)
    perp_report.add_argument("--output", type=str, default=None)

    event_quality = sub.add_parser("event-quality-report", help="Label sweep/reclaim events and score event quality")
    event_quality.add_argument("--input", type=str, default=None)
    event_quality.add_argument("--output", type=str, default=None)
    event_quality.add_argument("--lookback-sec", type=float, default=120.0)
    event_quality.add_argument("--horizon-sec", type=float, default=300.0)
    event_quality.add_argument("--min-sweep-notional-quote", type=float, default=1000.0)
    event_quality.add_argument("--reclaim-bps", type=float, default=0.0)
    event_quality.add_argument("--target-bps", type=float, default=6.0)
    event_quality.add_argument("--stop-bps", type=float, default=3.0)
    event_quality.add_argument("--max-pre-spread-bps", type=float, default=0.0)
    event_quality.add_argument("--event-cooldown-sec", type=float, default=10.0)
    event_quality.add_argument("--max-events", type=int, default=5000)

    event_slice = sub.add_parser("event-slice-optimizer", help="Rank sweep/reclaim event slices before replay v2")
    event_slice.add_argument("--input", type=str, default=None)
    event_slice.add_argument("--output", type=str, default=None)
    event_slice.add_argument("--min-events", type=int, default=20)
    event_slice.add_argument("--min-reclaimed", type=int, default=10)
    event_slice.add_argument("--min-target-before-stop-rate", type=float, default=0.60)
    event_slice.add_argument("--min-target-rate-all", type=float, default=0.20)
    event_slice.add_argument("--max-false-sweep-rate", type=float, default=1.0)
    event_slice.add_argument("--max-avg-adverse-bps", type=float, default=0.0)
    event_slice.add_argument("--min-favorable-to-adverse", type=float, default=0.0)
    event_slice.add_argument("--min-sweep-intensity-bps", type=str, default="0,2,5,10")
    event_slice.add_argument("--max-time-to-reclaim-sec", type=str, default="0,30,60,120,300")
    event_slice.add_argument("--max-pre-spread-bps", type=str, default="0,1,3,6")
    event_slice.add_argument("--max-abs-basis-bps", type=str, default="0,5,10,25,100")
    event_slice.add_argument("--min-trade-notional-quote", type=str, default="0,2500,5000,10000")
    event_slice.add_argument("--top-n", type=int, default=50)

    event_validation = sub.add_parser("event-validation-report", help="Validate sweep/reclaim slices with train/OOS, walk-forward, and stress gates")
    event_validation.add_argument("--input", type=str, default=None)
    event_validation.add_argument("--output", type=str, default=None)
    event_validation.add_argument("--train-fraction", type=float, default=0.70)
    event_validation.add_argument("--walk-forward-windows", type=int, default=4)
    event_validation.add_argument("--walk-forward-min-pass-ratio", type=float, default=0.75)
    event_validation.add_argument("--min-events", type=int, default=20)
    event_validation.add_argument("--min-reclaimed", type=int, default=10)
    event_validation.add_argument("--min-target-before-stop-rate", type=float, default=0.60)
    event_validation.add_argument("--min-target-rate-all", type=float, default=0.20)
    event_validation.add_argument("--max-false-sweep-rate", type=float, default=0.50)
    event_validation.add_argument("--max-avg-adverse-bps", type=float, default=0.0)
    event_validation.add_argument("--min-favorable-to-adverse", type=float, default=1.0)
    event_validation.add_argument("--min-sweep-intensity-bps", type=str, default="0,2,5,10")
    event_validation.add_argument("--max-time-to-reclaim-sec", type=str, default="0,30,60,120,300")
    event_validation.add_argument("--max-pre-spread-bps", type=str, default="0,1,3,6")
    event_validation.add_argument("--max-abs-basis-bps", type=str, default="0,5,10,25,100")
    event_validation.add_argument("--min-trade-notional-quote", type=str, default="0,2500,5000,10000")
    event_validation.add_argument("--stress-favorable-haircut-bps", type=float, default=1.0)
    event_validation.add_argument("--stress-adverse-widen-bps", type=float, default=1.0)
    event_validation.add_argument("--stress-target-bps", type=float, default=6.0)
    event_validation.add_argument("--stress-stop-bps", type=float, default=3.0)
    event_validation.add_argument("--top-n", type=int, default=50)

    cross_venue = sub.add_parser(
        "cross-venue-dislocation",
        help="Research-only PlanOnly detector for MEXC/Gate spot BBO dislocations after base-tier costs",
    )
    cross_venue.add_argument("--input", type=str, required=True)
    cross_venue.add_argument("--output", type=str, default=None)
    cross_venue.add_argument("--quote", type=str, default="USDT")
    cross_venue.add_argument("--stale-quote-sec", type=float, default=2.0)
    cross_venue.add_argument("--min-top-notional-quote", type=float, default=25.0)
    cross_venue.add_argument("--round-trip-fee-bps", type=float, default=39.0)
    cross_venue.add_argument("--slippage-bps", type=float, default=10.0)
    cross_venue.add_argument("--inventory-rebalance-buffer-bps", type=float, default=20.0)
    cross_venue.add_argument("--min-net-edge-bps", type=float, default=0.0)
    cross_venue.add_argument("--cooldown-sec", type=float, default=60.0)
    cross_venue.add_argument("--max-rows", type=int, default=0)
    cross_venue.add_argument("--max-events", type=int, default=1000)
    cross_venue.add_argument("--progress-every-rows", type=int, default=0)
    cross_venue.add_argument("--include-bases", type=str, default="")

    perp_postprocess = sub.add_parser("perp-postprocess", help="QA report + strict perp grid-search after final collect")
    perp_postprocess.add_argument("--input", type=str, default=None)
    perp_postprocess.add_argument("--manifest", type=str, default=None)
    perp_postprocess.add_argument("--report-output", type=str, default=None)
    perp_postprocess.add_argument("--grid-output", type=str, default=None)
    perp_postprocess.add_argument("--allow-partial", action="store_true")

    ws_replay = sub.add_parser("ws-replay", help="Event-driven replay-backtest по normalized WebSocket events")
    ws_replay.add_argument("--input", type=str, default=None)
    ws_replay.add_argument("--output", type=str, default=None)
    ws_replay.add_argument("--signal-type", default="flow_continue")
    ws_replay.add_argument("--notional-quote", type=float, default=25.0)
    ws_replay.add_argument("--execution-mode", choices=["taker", "maker"], default="taker")
    ws_replay.add_argument("--taker-fee-bps", type=float, default=10.0)
    ws_replay.add_argument("--maker-fee-bps", type=float, default=0.0)
    ws_replay.add_argument("--slippage-bps", type=float, default=1.0)
    ws_replay.add_argument("--venue-costs-json", type=str, default="")
    ws_replay.add_argument("--max-quote-age-sec", type=float, default=2.0)
    ws_replay.add_argument("--latency-ms", type=int, default=250)
    ws_replay.add_argument("--flow-window-sec", type=float, default=5.0)
    ws_replay.add_argument("--allow-short", action="store_true")
    ws_replay.add_argument("--max-open-positions", type=int, default=1)
    ws_replay.add_argument("--maker-queue-ahead-qty", type=float, default=0.0)
    ws_replay.add_argument("--maker-queue-model", choices=["fixed", "top_qty_fraction"], default="fixed")
    ws_replay.add_argument("--maker-queue-ahead-fraction", type=float, default=1.0)
    ws_replay.add_argument("--maker-order-ttl-sec", type=float, default=5.0)
    ws_replay.add_argument("--quality-filter", action="store_true")
    ws_replay.add_argument("--quality-window-sec", type=float, default=60.0)
    ws_replay.add_argument("--quality-min-trade-count", type=int, default=0)
    ws_replay.add_argument("--quality-min-trade-notional", type=float, default=0.0)
    ws_replay.add_argument("--quality-max-avg-spread-bps", type=float, default=0.0)
    ws_replay.add_argument("--quality-min-quote-updates", type=int, default=0)
    ws_replay.add_argument("--quality-min-top-qty", type=float, default=0.0)
    ws_replay.add_argument("--min-net-take-profit-bps", type=float, default=-1e9)
    ws_replay.add_argument("--sweep-v2-allowed-markets", type=str, default="")
    ws_replay.add_argument("--sweep-v2-side", type=str, default="")
    ws_replay.add_argument("--sweep-v2-min-trade-notional-quote", type=float, default=0.0)
    ws_replay.add_argument("--sweep-v2-min-intensity-bps", type=float, default=0.0)
    ws_replay.add_argument("--sweep-v2-max-pre-spread-bps", type=float, default=0.0)
    ws_replay.add_argument("--sweep-v2-max-reclaim-sec", type=float, default=0.0)
    ws_replay.add_argument("--sweep-v2-event-cooldown-sec", type=float, default=0.0)
    ws_replay.add_argument("--breakout-lookback-sec", type=float, default=30.0)
    ws_replay.add_argument("--breakout-bps", type=float, default=5.0)
    ws_replay.add_argument("--breakout-min-samples", type=int, default=5)

    ws_grid = sub.add_parser("ws-grid-search", help="Grid-search replay parameters over normalized events")
    ws_grid.add_argument("--input", type=str, default=None)
    ws_grid.add_argument("--output", type=str, default=None)
    ws_grid.add_argument("--notional-quote", type=float, default=25.0)
    ws_grid.add_argument("--execution-mode", choices=["taker", "maker"], default="taker")
    ws_grid.add_argument("--taker-fee-bps", type=float, default=10.0)
    ws_grid.add_argument("--maker-fee-bps", type=float, default=0.0)
    ws_grid.add_argument("--slippage-bps", type=float, default=1.0)
    ws_grid.add_argument("--venue-costs-json", type=str, default="")
    ws_grid.add_argument("--max-quote-age-sec", type=float, default=2.0)
    ws_grid.add_argument("--latency-ms", type=int, default=250)
    ws_grid.add_argument("--flow-window-sec", type=float, default=5.0)
    ws_grid.add_argument("--allow-short", action="store_true")
    ws_grid.add_argument("--max-open-positions", type=int, default=1)
    ws_grid.add_argument("--maker-queue-ahead-qty", type=float, default=0.0)
    ws_grid.add_argument("--maker-queue-model", choices=["fixed", "top_qty_fraction"], default="fixed")
    ws_grid.add_argument("--maker-queue-ahead-fraction", type=float, default=1.0)
    ws_grid.add_argument("--maker-order-ttl-sec", type=float, default=5.0)
    ws_grid.add_argument("--quality-filter", action="store_true")
    ws_grid.add_argument("--quality-window-sec", type=float, default=60.0)
    ws_grid.add_argument("--quality-min-trade-count", type=int, default=0)
    ws_grid.add_argument("--quality-min-trade-notional", type=float, default=0.0)
    ws_grid.add_argument("--quality-max-avg-spread-bps", type=float, default=0.0)
    ws_grid.add_argument("--quality-min-quote-updates", type=int, default=0)
    ws_grid.add_argument("--quality-min-top-qty", type=float, default=0.0)
    ws_grid.add_argument("--min-net-take-profit-bps", type=float, default=-1e9)
    ws_grid.add_argument("--sweep-v2-allowed-markets", type=str, default="")
    ws_grid.add_argument("--sweep-v2-side", type=str, default="")
    ws_grid.add_argument("--sweep-v2-min-trade-notional-quote", type=float, default=0.0)
    ws_grid.add_argument("--sweep-v2-min-intensity-bps", type=float, default=0.0)
    ws_grid.add_argument("--sweep-v2-max-pre-spread-bps", type=float, default=0.0)
    ws_grid.add_argument("--sweep-v2-max-reclaim-sec", type=float, default=0.0)
    ws_grid.add_argument("--sweep-v2-event-cooldown-sec", type=float, default=0.0)
    ws_grid.add_argument("--entry-imbalance-abs", default="0.1,0.25")
    ws_grid.add_argument("--entry-signed-flow-notional", default="50,250,1000")
    ws_grid.add_argument("--max-spread-bps", default="1.5,3")
    ws_grid.add_argument("--take-profit-bps", default="3,6")
    ws_grid.add_argument("--stop-loss-bps", default="3,6")
    ws_grid.add_argument("--max-hold-sec", default="5,25")
    ws_grid.add_argument("--grid-signal-type", default="flow_continue")
    ws_grid.add_argument("--min-trades", type=int, default=1)
    ws_grid.add_argument("--min-win-rate", type=float, default=0.0)
    ws_grid.add_argument("--min-expectancy-quote", type=float, default=-1e9)
    ws_grid.add_argument("--min-net-pnl-quote", type=float, default=-1e9)
    ws_grid.add_argument("--min-profit-factor", type=float, default=0.0)
    ws_grid.add_argument("--max-drawdown-quote", type=float, default=0.0)
    ws_grid.add_argument("--grid-breakout-bps", type=str, default=None)
    ws_grid.add_argument("--grid-breakout-lookback-sec", type=str, default=None)
    ws_grid.add_argument("--grid-breakout-min-samples", type=str, default=None)
    ws_grid.add_argument("--top-n", type=int, default=20)
    ws_grid.add_argument("--max-grid-combinations", type=int, default=10_000)

    perp_replay = sub.add_parser("perp-replay", help="Perp replay-backtest with funding/short support")
    perp_replay.add_argument("--input", type=str, default=None)
    perp_replay.add_argument("--output", type=str, default=None)
    perp_replay.add_argument("--signal-type", default="flow_continue")
    perp_replay.add_argument("--notional-quote", type=float, default=25.0)
    perp_replay.add_argument("--execution-mode", choices=["taker", "maker"], default="taker")
    perp_replay.add_argument("--taker-fee-bps", type=float, default=10.0)
    perp_replay.add_argument("--maker-fee-bps", type=float, default=0.0)
    perp_replay.add_argument("--slippage-bps", type=float, default=1.0)
    perp_replay.add_argument("--venue-costs-json", type=str, default="")
    perp_replay.add_argument("--max-quote-age-sec", type=float, default=2.0)
    perp_replay.add_argument("--latency-ms", type=int, default=250)
    perp_replay.add_argument("--flow-window-sec", type=float, default=5.0)
    perp_replay.add_argument("--max-open-positions", type=int, default=1)
    perp_replay.add_argument("--maker-queue-ahead-qty", type=float, default=0.0)
    perp_replay.add_argument("--maker-queue-model", choices=["fixed", "top_qty_fraction"], default="fixed")
    perp_replay.add_argument("--maker-queue-ahead-fraction", type=float, default=1.0)
    perp_replay.add_argument("--maker-order-ttl-sec", type=float, default=5.0)
    perp_replay.add_argument("--quality-filter", action="store_true")
    perp_replay.add_argument("--quality-window-sec", type=float, default=60.0)
    perp_replay.add_argument("--quality-min-trade-count", type=int, default=0)
    perp_replay.add_argument("--quality-min-trade-notional", type=float, default=0.0)
    perp_replay.add_argument("--quality-max-avg-spread-bps", type=float, default=0.0)
    perp_replay.add_argument("--quality-min-quote-updates", type=int, default=0)
    perp_replay.add_argument("--quality-min-top-qty", type=float, default=0.0)
    perp_replay.add_argument("--min-net-take-profit-bps", type=float, default=-1e9)
    perp_replay.add_argument("--sweep-v2-allowed-markets", type=str, default="")
    perp_replay.add_argument("--sweep-v2-side", type=str, default="")
    perp_replay.add_argument("--sweep-v2-min-trade-notional-quote", type=float, default=0.0)
    perp_replay.add_argument("--sweep-v2-min-intensity-bps", type=float, default=0.0)
    perp_replay.add_argument("--sweep-v2-max-pre-spread-bps", type=float, default=0.0)
    perp_replay.add_argument("--sweep-v2-max-reclaim-sec", type=float, default=0.0)
    perp_replay.add_argument("--sweep-v2-event-cooldown-sec", type=float, default=0.0)

    perp_grid = sub.add_parser("perp-grid-search", help="Grid-search perp replay parameters over normalized events")
    perp_grid.add_argument("--input", type=str, default=None)
    perp_grid.add_argument("--output", type=str, default=None)
    perp_grid.add_argument("--notional-quote", type=float, default=25.0)
    perp_grid.add_argument("--execution-mode", choices=["taker", "maker"], default="taker")
    perp_grid.add_argument("--taker-fee-bps", type=float, default=10.0)
    perp_grid.add_argument("--maker-fee-bps", type=float, default=0.0)
    perp_grid.add_argument("--slippage-bps", type=float, default=1.0)
    perp_grid.add_argument("--venue-costs-json", type=str, default="")
    perp_grid.add_argument("--max-quote-age-sec", type=float, default=2.0)
    perp_grid.add_argument("--latency-ms", type=int, default=250)
    perp_grid.add_argument("--flow-window-sec", type=float, default=5.0)
    perp_grid.add_argument("--max-open-positions", type=int, default=1)
    perp_grid.add_argument("--maker-queue-ahead-qty", type=float, default=0.0)
    perp_grid.add_argument("--maker-queue-model", choices=["fixed", "top_qty_fraction"], default="fixed")
    perp_grid.add_argument("--maker-queue-ahead-fraction", type=float, default=1.0)
    perp_grid.add_argument("--maker-order-ttl-sec", type=float, default=5.0)
    perp_grid.add_argument("--quality-filter", action="store_true")
    perp_grid.add_argument("--quality-window-sec", type=float, default=60.0)
    perp_grid.add_argument("--quality-min-trade-count", type=int, default=0)
    perp_grid.add_argument("--quality-min-trade-notional", type=float, default=0.0)
    perp_grid.add_argument("--quality-max-avg-spread-bps", type=float, default=0.0)
    perp_grid.add_argument("--quality-min-quote-updates", type=int, default=0)
    perp_grid.add_argument("--quality-min-top-qty", type=float, default=0.0)
    perp_grid.add_argument("--entry-imbalance-abs", type=str, default="0.1,0.25")
    perp_grid.add_argument("--entry-signed-flow-notional", type=str, default="50,250,1000")
    perp_grid.add_argument("--max-spread-bps", type=str, default="1.5,3")
    perp_grid.add_argument("--take-profit-bps", type=str, default="3,6")
    perp_grid.add_argument("--stop-loss-bps", type=str, default="3,6")
    perp_grid.add_argument("--max-hold-sec", type=str, default="5,25")
    perp_grid.add_argument("--grid-signal-type", default="flow_continue")
    perp_grid.add_argument("--min-trades", type=int, default=1)
    perp_grid.add_argument("--min-win-rate", type=float, default=0.0)
    perp_grid.add_argument("--min-expectancy-quote", type=float, default=-1e9)
    perp_grid.add_argument("--min-net-pnl-quote", type=float, default=-1e9)
    perp_grid.add_argument("--min-profit-factor", type=float, default=0.0)
    perp_grid.add_argument("--max-drawdown-quote", type=float, default=0.0)
    perp_grid.add_argument("--min-net-take-profit-bps", type=float, default=-1e9)
    perp_grid.add_argument("--sweep-v2-allowed-markets", type=str, default="")
    perp_grid.add_argument("--sweep-v2-side", type=str, default="")
    perp_grid.add_argument("--sweep-v2-min-trade-notional-quote", type=float, default=0.0)
    perp_grid.add_argument("--sweep-v2-min-intensity-bps", type=float, default=0.0)
    perp_grid.add_argument("--sweep-v2-max-pre-spread-bps", type=float, default=0.0)
    perp_grid.add_argument("--sweep-v2-max-reclaim-sec", type=float, default=0.0)
    perp_grid.add_argument("--sweep-v2-event-cooldown-sec", type=float, default=0.0)
    perp_grid.add_argument("--top-n", type=int, default=20)
    perp_grid.add_argument("--max-grid-combinations", type=int, default=10_000)

    funding_scan = sub.add_parser("funding-scan", help="Сканировать spot/perp funding basis opportunities")
    funding_scan.add_argument("--exchanges", default="mexc,gateio")
    funding_scan.add_argument("--universe", type=str, default=None)
    funding_scan.add_argument("--quote", type=str, default="USDT")
    funding_scan.add_argument("--max-symbols", type=int, default=200)
    funding_scan.add_argument("--max-pairs-per-exchange", type=int, default=5)
    funding_scan.add_argument("--notional-quote", type=float, default=25.0)
    funding_scan.add_argument("--max-spot-spread-bps", type=float, default=30.0)
    funding_scan.add_argument("--max-perp-spread-bps", type=float, default=30.0)
    funding_scan.add_argument("--max-abs-basis-bps", type=float, default=500.0)
    funding_scan.add_argument("--min-basis-bps", type=float, default=-1e9)
    funding_scan.add_argument("--min-funding-rate", type=float, default=0.0)
    funding_scan.add_argument("--min-volume-24h-quote", type=float, default=0.0)
    funding_scan.add_argument("--min-spot-top-notional-quote", type=float, default=0.0)
    funding_scan.add_argument("--spot-fee-bps", type=float, default=10.0)
    funding_scan.add_argument("--perp-fee-bps", type=float, default=7.5)
    funding_scan.add_argument("--slippage-bps", type=float, default=1.0)
    funding_scan.add_argument("--target-hold-intervals", type=float, default=1.0)
    funding_scan.add_argument("--min-expected-net-carry-bps", type=float, default=-1e9)
    funding_scan.add_argument("--max-break-even-hours", type=float, default=1e9)
    funding_scan.add_argument("--output", type=str, default=None)

    funding_coverage = sub.add_parser("funding-coverage", help="Проверить покрытие no-Binance universe связкой spot+perp")
    funding_coverage.add_argument("--exchanges", default="mexc,gateio")
    funding_coverage.add_argument("--universe", type=str, default=None)
    funding_coverage.add_argument("--quote", type=str, default="USDT")
    funding_coverage.add_argument("--max-symbols", type=int, default=200)
    funding_coverage.add_argument("--output", type=str, default=None)
    funding_coverage.add_argument("--matched-universe-output", type=str, default=None)

    funding_collect = sub.add_parser("funding-collect", help="Периодически собирать funding/basis snapshots в JSONL")
    funding_collect.add_argument("--exchanges", default="mexc,gateio")
    funding_collect.add_argument("--universe", type=str, default=None)
    funding_collect.add_argument("--quote", type=str, default="USDT")
    funding_collect.add_argument("--max-symbols", type=int, default=200)
    funding_collect.add_argument("--max-pairs-per-exchange", type=int, default=5)
    funding_collect.add_argument("--cycles", type=int, default=3)
    funding_collect.add_argument("--poll-interval-sec", type=float, default=60.0)
    funding_collect.add_argument("--notional-quote", type=float, default=25.0)
    funding_collect.add_argument("--max-spot-spread-bps", type=float, default=30.0)
    funding_collect.add_argument("--max-perp-spread-bps", type=float, default=30.0)
    funding_collect.add_argument("--max-abs-basis-bps", type=float, default=500.0)
    funding_collect.add_argument("--min-basis-bps", type=float, default=-1e9)
    funding_collect.add_argument("--min-funding-rate", type=float, default=0.0)
    funding_collect.add_argument("--min-volume-24h-quote", type=float, default=0.0)
    funding_collect.add_argument("--min-spot-top-notional-quote", type=float, default=0.0)
    funding_collect.add_argument("--spot-fee-bps", type=float, default=10.0)
    funding_collect.add_argument("--perp-fee-bps", type=float, default=7.5)
    funding_collect.add_argument("--slippage-bps", type=float, default=1.0)
    funding_collect.add_argument("--target-hold-intervals", type=float, default=1.0)
    funding_collect.add_argument("--min-expected-net-carry-bps", type=float, default=-1e9)
    funding_collect.add_argument("--max-break-even-hours", type=float, default=1e9)
    funding_collect.add_argument("--resume", action="store_true")
    funding_collect.add_argument("--output", type=str, default=None)

    funding_status = sub.add_parser("funding-status", help="Проверить manifest/output status для funding collect")
    funding_status.add_argument("--input", type=str, default=None)
    funding_status.add_argument("--manifest", type=str, default=None)
    funding_status.add_argument("--stale-after-sec", type=float, default=900.0)
    funding_status.add_argument("--strict-research", action="store_true")
    funding_status.add_argument("--quality-min-rows", type=int, default=None)
    funding_status.add_argument("--quality-min-markets", type=int, default=None)
    funding_status.add_argument("--quality-min-completed-cycles", type=int, default=None)
    funding_status.add_argument("--quality-min-unique-cycles", type=int, default=None)
    funding_status.add_argument("--quality-min-avg-rows-per-cycle", type=float, default=None)
    funding_status.add_argument("--quality-min-min-rows-per-cycle", type=int, default=None)
    funding_status.add_argument("--quality-max-error-rate", type=float, default=None)
    funding_status.add_argument("--quality-max-cycle-market-duplicate-rate", type=float, default=None)
    funding_status.add_argument("--quality-required-row-fields", type=str, default=None)
    funding_status.add_argument("--quality-min-required-row-field-presence", type=float, default=None)

    funding_collect_diagnostics = sub.add_parser("funding-collect-diagnostics", help="Build funding collect data-quality/economics diagnostics artifact")
    funding_collect_diagnostics.add_argument("--input", type=str, default=None)
    funding_collect_diagnostics.add_argument("--manifest", type=str, default=None)
    funding_collect_diagnostics.add_argument("--output", type=str, default=None)
    funding_collect_diagnostics.add_argument("--top-n", type=int, default=20)
    funding_collect_diagnostics.add_argument("--required-row-fields", type=str, default=None)
    funding_collect_diagnostics.add_argument("--strict-research", action="store_true")

    funding_wait_ready = sub.add_parser("funding-wait-ready", help="Condition-poll funding collect until strict postprocess readiness or timeout")
    funding_wait_ready.add_argument("--input", type=str, default=None)
    funding_wait_ready.add_argument("--manifest", type=str, default=None)
    funding_wait_ready.add_argument("--output", type=str, default=None)
    funding_wait_ready.add_argument("--timeout-sec", type=float, default=0.0)
    funding_wait_ready.add_argument("--poll-interval-sec", type=float, default=60.0)
    funding_wait_ready.add_argument("--stale-after-sec", type=float, default=900.0)
    funding_wait_ready.add_argument("--strict-research", action="store_true")
    funding_wait_ready.add_argument("--quality-min-rows", type=int, default=None)
    funding_wait_ready.add_argument("--quality-min-markets", type=int, default=None)
    funding_wait_ready.add_argument("--quality-min-completed-cycles", type=int, default=None)
    funding_wait_ready.add_argument("--quality-min-unique-cycles", type=int, default=None)
    funding_wait_ready.add_argument("--quality-min-avg-rows-per-cycle", type=float, default=None)
    funding_wait_ready.add_argument("--quality-min-min-rows-per-cycle", type=int, default=None)
    funding_wait_ready.add_argument("--quality-max-error-rate", type=float, default=None)
    funding_wait_ready.add_argument("--quality-max-cycle-market-duplicate-rate", type=float, default=None)
    funding_wait_ready.add_argument("--quality-required-row-fields", type=str, default=None)
    funding_wait_ready.add_argument("--quality-min-required-row-field-presence", type=float, default=None)

    funding_rank = sub.add_parser("funding-rank", help="Ранжировать funding/basis opportunities")
    funding_rank.add_argument("--input", type=str, default=None)
    funding_rank.add_argument("--output", type=str, default=None)
    funding_rank.add_argument("--strict-research", action="store_true")
    funding_rank.add_argument("--top-n", type=int, default=20)
    funding_rank.add_argument("--min-funding-observations", type=int, default=1)
    funding_rank.add_argument("--min-funding-positive-ratio", type=float, default=0.0)
    funding_rank.add_argument("--min-funding-persistence-score", type=float, default=-1e9)
    funding_rank.add_argument("--funding-persistence-weight", type=float, default=1.0)
    funding_rank.add_argument("--min-funding-rate", type=float, default=0.0)
    funding_rank.add_argument("--max-spot-spread-bps", type=float, default=30.0)
    funding_rank.add_argument("--max-perp-spread-bps", type=float, default=30.0)
    funding_rank.add_argument("--max-abs-basis-bps", type=float, default=500.0)
    funding_rank.add_argument("--min-basis-bps", type=float, default=-1e9)
    funding_rank.add_argument("--min-expected-net-carry-bps", type=float, default=-1e9)
    _add_funding_risk_adjusted_args(funding_rank)
    funding_rank.add_argument("--max-break-even-hours", type=float, default=1e9)
    funding_rank.add_argument("--min-regime-observations", type=int, default=1)
    funding_rank.add_argument("--min-perp-volume-24h-quote", type=float, default=0.0)
    funding_rank.add_argument("--min-spot-top-notional-quote", type=float, default=0.0)
    funding_rank.add_argument("--max-basis-std-bps", type=float, default=1e9)
    funding_rank.add_argument("--max-avg-spot-spread-bps", type=float, default=1e9)
    funding_rank.add_argument("--max-avg-perp-spread-bps", type=float, default=1e9)

    funding_gate_report = sub.add_parser("funding-gate-report", help="Diagnose why funding opportunities pass/fail research gates")
    funding_gate_report.add_argument("--input", type=str, default=None)
    funding_gate_report.add_argument("--output", type=str, default=None)
    funding_gate_report.add_argument("--quality-universe-output", type=str, default=None)
    funding_gate_report.add_argument("--strict-research", action="store_true")
    funding_gate_report.add_argument("--top-n", type=int, default=20)
    funding_gate_report.add_argument("--min-funding-observations", type=int, default=1)
    funding_gate_report.add_argument("--min-funding-positive-ratio", type=float, default=0.0)
    funding_gate_report.add_argument("--min-funding-persistence-score", type=float, default=-1e9)
    funding_gate_report.add_argument("--funding-persistence-weight", type=float, default=1.0)
    funding_gate_report.add_argument("--min-funding-rate", type=float, default=0.0)
    funding_gate_report.add_argument("--max-spot-spread-bps", type=float, default=30.0)
    funding_gate_report.add_argument("--max-perp-spread-bps", type=float, default=30.0)
    funding_gate_report.add_argument("--max-abs-basis-bps", type=float, default=500.0)
    funding_gate_report.add_argument("--min-basis-bps", type=float, default=-1e9)
    funding_gate_report.add_argument("--min-expected-net-carry-bps", type=float, default=-1e9)
    _add_funding_risk_adjusted_args(funding_gate_report)
    funding_gate_report.add_argument("--max-break-even-hours", type=float, default=1e9)
    funding_gate_report.add_argument("--min-regime-observations", type=int, default=1)
    funding_gate_report.add_argument("--min-perp-volume-24h-quote", type=float, default=0.0)
    funding_gate_report.add_argument("--min-spot-top-notional-quote", type=float, default=0.0)
    funding_gate_report.add_argument("--max-basis-std-bps", type=float, default=1e9)
    funding_gate_report.add_argument("--max-avg-spot-spread-bps", type=float, default=1e9)
    funding_gate_report.add_argument("--max-avg-perp-spread-bps", type=float, default=1e9)

    funding_regime_report_parser = sub.add_parser("funding-regime-report", help="Summarize per-market funding carry regime, volume, and liquidity gates")
    funding_regime_report_parser.add_argument("--input", type=str, default=None)
    funding_regime_report_parser.add_argument("--output", type=str, default=None)
    funding_regime_report_parser.add_argument("--strict-research", action="store_true")
    funding_regime_report_parser.add_argument("--top-n", type=int, default=20)
    funding_regime_report_parser.add_argument("--min-funding-observations", type=int, default=1)
    funding_regime_report_parser.add_argument("--min-funding-positive-ratio", type=float, default=0.0)
    funding_regime_report_parser.add_argument("--min-funding-persistence-score", type=float, default=-1e9)
    funding_regime_report_parser.add_argument("--funding-persistence-weight", type=float, default=1.0)
    funding_regime_report_parser.add_argument("--min-funding-rate", type=float, default=0.0)
    funding_regime_report_parser.add_argument("--max-spot-spread-bps", type=float, default=30.0)
    funding_regime_report_parser.add_argument("--max-perp-spread-bps", type=float, default=30.0)
    funding_regime_report_parser.add_argument("--max-abs-basis-bps", type=float, default=500.0)
    funding_regime_report_parser.add_argument("--min-basis-bps", type=float, default=-1e9)
    funding_regime_report_parser.add_argument("--min-expected-net-carry-bps", type=float, default=-1e9)
    _add_funding_risk_adjusted_args(funding_regime_report_parser)
    funding_regime_report_parser.add_argument("--max-break-even-hours", type=float, default=1e9)
    funding_regime_report_parser.add_argument("--min-regime-observations", type=int, default=1)
    funding_regime_report_parser.add_argument("--min-perp-volume-24h-quote", type=float, default=0.0)
    funding_regime_report_parser.add_argument("--min-spot-top-notional-quote", type=float, default=0.0)
    funding_regime_report_parser.add_argument("--max-basis-std-bps", type=float, default=1e9)
    funding_regime_report_parser.add_argument("--max-avg-spot-spread-bps", type=float, default=1e9)
    funding_regime_report_parser.add_argument("--max-avg-perp-spread-bps", type=float, default=1e9)

    funding_frontier_report = sub.add_parser("funding-frontier-report", help="Show edge/liquidity frontier for funding carry candidates")
    funding_frontier_report.add_argument("--input", type=str, default=None)
    funding_frontier_report.add_argument("--output", type=str, default=None)
    funding_frontier_report.add_argument("--strict-research", action="store_true")
    funding_frontier_report.add_argument("--top-n", type=int, default=20)
    funding_frontier_report.add_argument("--min-funding-observations", type=int, default=1)
    funding_frontier_report.add_argument("--min-funding-positive-ratio", type=float, default=0.0)
    funding_frontier_report.add_argument("--min-funding-persistence-score", type=float, default=-1e9)
    funding_frontier_report.add_argument("--funding-persistence-weight", type=float, default=1.0)
    funding_frontier_report.add_argument("--min-funding-rate", type=float, default=0.0)
    funding_frontier_report.add_argument("--max-spot-spread-bps", type=float, default=30.0)
    funding_frontier_report.add_argument("--max-perp-spread-bps", type=float, default=30.0)
    funding_frontier_report.add_argument("--max-abs-basis-bps", type=float, default=500.0)
    funding_frontier_report.add_argument("--min-basis-bps", type=float, default=-1e9)
    funding_frontier_report.add_argument("--min-expected-net-carry-bps", type=float, default=-1e9)
    _add_funding_risk_adjusted_args(funding_frontier_report)
    funding_frontier_report.add_argument("--max-break-even-hours", type=float, default=1e9)
    funding_frontier_report.add_argument("--min-regime-observations", type=int, default=1)
    funding_frontier_report.add_argument("--min-perp-volume-24h-quote", type=float, default=0.0)
    funding_frontier_report.add_argument("--min-spot-top-notional-quote", type=float, default=0.0)
    funding_frontier_report.add_argument("--max-basis-std-bps", type=float, default=1e9)
    funding_frontier_report.add_argument("--max-avg-spot-spread-bps", type=float, default=1e9)
    funding_frontier_report.add_argument("--max-avg-perp-spread-bps", type=float, default=1e9)

    funding_decision_report_parser = sub.add_parser("funding-decision-report", help="Combine funding status/gates into a research acceptance verdict")
    funding_decision_report_parser.add_argument("--input", type=str, default=None)
    funding_decision_report_parser.add_argument("--manifest", type=str, default=None)
    funding_decision_report_parser.add_argument("--postprocess-report", type=str, default=None)
    funding_decision_report_parser.add_argument("--gate-report", type=str, default=None)
    funding_decision_report_parser.add_argument("--regime-report", type=str, default=None)
    funding_decision_report_parser.add_argument("--frontier-report", type=str, default=None)
    funding_decision_report_parser.add_argument("--sensitivity-report", type=str, default=None)
    funding_decision_report_parser.add_argument("--output", type=str, default=None)
    funding_decision_report_parser.add_argument("--stale-after-sec", type=float, default=900.0)
    funding_decision_report_parser.add_argument("--strict-research", action="store_true")
    funding_decision_report_parser.add_argument("--quality-min-rows", type=int, default=None)
    funding_decision_report_parser.add_argument("--quality-min-markets", type=int, default=None)
    funding_decision_report_parser.add_argument("--quality-min-completed-cycles", type=int, default=None)
    funding_decision_report_parser.add_argument("--quality-min-unique-cycles", type=int, default=None)
    funding_decision_report_parser.add_argument("--quality-min-avg-rows-per-cycle", type=float, default=None)
    funding_decision_report_parser.add_argument("--quality-min-min-rows-per-cycle", type=int, default=None)
    funding_decision_report_parser.add_argument("--quality-max-error-rate", type=float, default=None)
    funding_decision_report_parser.add_argument("--quality-max-cycle-market-duplicate-rate", type=float, default=None)
    funding_decision_report_parser.add_argument("--quality-required-row-fields", type=str, default=None)
    funding_decision_report_parser.add_argument("--quality-min-required-row-field-presence", type=float, default=None)

    funding_progress_report = sub.add_parser("funding-progress-report", help="Показать cycle-level progress/trend для funding collect")
    funding_progress_report.add_argument("--input", type=str, default=None)
    funding_progress_report.add_argument("--manifest", type=str, default=None)
    funding_progress_report.add_argument("--output", type=str, default=None)
    funding_progress_report.add_argument("--strict-research", action="store_true")
    funding_progress_report.add_argument("--top-n", type=int, default=5)
    funding_progress_report.add_argument("--min-funding-observations", type=int, default=1)
    funding_progress_report.add_argument("--min-funding-positive-ratio", type=float, default=0.0)
    funding_progress_report.add_argument("--min-funding-persistence-score", type=float, default=-1e9)
    funding_progress_report.add_argument("--funding-persistence-weight", type=float, default=1.0)
    funding_progress_report.add_argument("--min-funding-rate", type=float, default=0.0)
    funding_progress_report.add_argument("--max-spot-spread-bps", type=float, default=30.0)
    funding_progress_report.add_argument("--max-perp-spread-bps", type=float, default=30.0)
    funding_progress_report.add_argument("--max-abs-basis-bps", type=float, default=500.0)
    funding_progress_report.add_argument("--min-basis-bps", type=float, default=-1e9)
    funding_progress_report.add_argument("--min-expected-net-carry-bps", type=float, default=-1e9)
    _add_funding_risk_adjusted_args(funding_progress_report)
    funding_progress_report.add_argument("--max-break-even-hours", type=float, default=1e9)
    funding_progress_report.add_argument("--min-regime-observations", type=int, default=1)
    funding_progress_report.add_argument("--min-perp-volume-24h-quote", type=float, default=0.0)
    funding_progress_report.add_argument("--min-spot-top-notional-quote", type=float, default=0.0)
    funding_progress_report.add_argument("--max-basis-std-bps", type=float, default=1e9)
    funding_progress_report.add_argument("--max-avg-spot-spread-bps", type=float, default=1e9)
    funding_progress_report.add_argument("--max-avg-perp-spread-bps", type=float, default=1e9)

    funding_backtest = sub.add_parser("funding-backtest", help="Backtest long spot + short perp funding carry")
    funding_backtest.add_argument("--input", type=str, default=None)
    funding_backtest.add_argument("--output", type=str, default=None)
    funding_backtest.add_argument("--notional-quote", type=float, default=100.0)
    funding_backtest.add_argument("--spot-fee-bps", type=float, default=10.0)
    funding_backtest.add_argument("--perp-fee-bps", type=float, default=7.5)
    funding_backtest.add_argument("--slippage-bps", type=float, default=1.0)
    funding_backtest.add_argument("--venue-costs-json", type=str, default="")
    funding_backtest.add_argument("--min-funding-rate", type=float, default=0.0)
    funding_backtest.add_argument("--min-total-score", type=float, default=0.0)
    funding_backtest.add_argument("--max-spot-spread-bps", type=float, default=30.0)
    funding_backtest.add_argument("--max-perp-spread-bps", type=float, default=30.0)
    funding_backtest.add_argument("--max-abs-basis-bps", type=float, default=500.0)
    funding_backtest.add_argument("--min-basis-bps", type=float, default=-1e9)
    funding_backtest.add_argument("--min-expected-net-carry-bps", type=float, default=-1e9)
    _add_funding_risk_adjusted_args(funding_backtest)
    funding_backtest.add_argument("--max-break-even-hours", type=float, default=1e9)
    funding_backtest.add_argument("--min-funding-observations", type=int, default=1)
    funding_backtest.add_argument("--min-funding-positive-ratio", type=float, default=0.0)
    funding_backtest.add_argument("--min-funding-persistence-score", type=float, default=-1e9)
    funding_backtest.add_argument("--min-regime-observations", type=int, default=1)
    funding_backtest.add_argument("--min-perp-volume-24h-quote", type=float, default=0.0)
    funding_backtest.add_argument("--min-spot-top-notional-quote", type=float, default=0.0)
    funding_backtest.add_argument("--max-basis-std-bps", type=float, default=1e9)
    funding_backtest.add_argument("--max-avg-spot-spread-bps", type=float, default=1e9)
    funding_backtest.add_argument("--max-avg-perp-spread-bps", type=float, default=1e9)

    funding_sensitivity = sub.add_parser("funding-sensitivity", help="Grid sensitivity for funding carry economics")
    funding_sensitivity.add_argument("--input", type=str, default=None)
    funding_sensitivity.add_argument("--output", type=str, default=None)
    funding_sensitivity.add_argument("--strict-research", action="store_true")
    funding_sensitivity.add_argument("--spot-fee-bps-list", type=str, default="0,5,10")
    funding_sensitivity.add_argument("--perp-fee-bps-list", type=str, default="0,2.5,7.5")
    funding_sensitivity.add_argument("--slippage-bps-list", type=str, default="0,0.5,1")
    funding_sensitivity.add_argument("--target-hold-intervals-list", type=str, default="1,3,6")
    funding_sensitivity.add_argument("--max-break-even-hours-list", type=str, default="24,72,168")
    funding_sensitivity.add_argument("--top-n", type=int, default=20)
    funding_sensitivity.add_argument("--notional-quote", type=float, default=100.0)
    funding_sensitivity.add_argument("--min-funding-rate", type=float, default=0.0)
    funding_sensitivity.add_argument("--min-total-score", type=float, default=0.0)
    funding_sensitivity.add_argument("--max-spot-spread-bps", type=float, default=30.0)
    funding_sensitivity.add_argument("--max-perp-spread-bps", type=float, default=30.0)
    funding_sensitivity.add_argument("--max-abs-basis-bps", type=float, default=500.0)
    funding_sensitivity.add_argument("--min-basis-bps", type=float, default=-1e9)
    funding_sensitivity.add_argument("--min-expected-net-carry-bps", type=float, default=-1e9)
    _add_funding_risk_adjusted_args(funding_sensitivity)
    funding_sensitivity.add_argument("--min-funding-observations", type=int, default=1)
    funding_sensitivity.add_argument("--min-funding-positive-ratio", type=float, default=0.0)
    funding_sensitivity.add_argument("--min-funding-persistence-score", type=float, default=-1e9)
    funding_sensitivity.add_argument("--min-regime-observations", type=int, default=1)
    funding_sensitivity.add_argument("--min-perp-volume-24h-quote", type=float, default=0.0)
    funding_sensitivity.add_argument("--min-spot-top-notional-quote", type=float, default=0.0)
    funding_sensitivity.add_argument("--max-basis-std-bps", type=float, default=1e9)
    funding_sensitivity.add_argument("--max-avg-spot-spread-bps", type=float, default=1e9)
    funding_sensitivity.add_argument("--max-avg-perp-spread-bps", type=float, default=1e9)
    funding_sensitivity.add_argument("--accept-min-trades", type=int, default=20)
    funding_sensitivity.add_argument("--accept-min-win-rate", type=float, default=0.6)
    funding_sensitivity.add_argument("--accept-min-expectancy-quote", type=float, default=0.0)
    funding_sensitivity.add_argument("--accept-min-net-pnl-quote", type=float, default=0.0)
    funding_sensitivity.add_argument("--accept-max-drawdown-quote", type=float, default=5.0)
    funding_sensitivity.add_argument("--accept-min-profit-factor", type=float, default=1.2)
    funding_sensitivity.add_argument("--accept-min-markets", type=int, default=1)
    funding_sensitivity.add_argument("--accept-max-market-trade-share", type=float, default=1.0)
    funding_sensitivity.add_argument("--accept-min-exchanges", type=int, default=1)
    funding_sensitivity.add_argument("--accept-max-exchange-trade-share", type=float, default=1.0)
    funding_sensitivity.add_argument("--accept-min-profitable-windows", type=int, default=0)
    funding_sensitivity.add_argument("--accept-max-window-pnl-share", type=float, default=1.0)
    funding_sensitivity.add_argument("--stress-enabled", action="store_true")
    funding_sensitivity.add_argument("--stress-adverse-basis-bps", type=float, default=0.0)
    funding_sensitivity.add_argument("--stress-spread-widen-bps", type=float, default=0.0)
    funding_sensitivity.add_argument("--stress-funding-flip-bps", type=float, default=0.0)
    funding_sensitivity.add_argument("--stress-min-net-pnl-quote", type=float, default=0.0)
    funding_sensitivity.add_argument("--stress-max-drawdown-quote", type=float, default=5.0)
    funding_sensitivity.add_argument("--sensitivity-oos", action="store_true")
    funding_sensitivity.add_argument("--oos-train-fraction", type=float, default=0.7)
    funding_sensitivity.add_argument("--oos-min-train-rows", type=int, default=20)
    funding_sensitivity.add_argument("--oos-min-rows", type=int, default=20)
    funding_sensitivity.add_argument("--oos-min-train-span-hours", type=float, default=0.0)
    funding_sensitivity.add_argument("--oos-min-span-hours", type=float, default=0.0)
    funding_sensitivity.add_argument("--sensitivity-walk-forward", action="store_true")
    funding_sensitivity.add_argument("--walk-train-rows", type=int, default=200)
    funding_sensitivity.add_argument("--walk-test-rows", type=int, default=50)
    funding_sensitivity.add_argument("--walk-step-rows", type=int, default=50)
    funding_sensitivity.add_argument("--walk-min-windows", type=int, default=3)
    funding_sensitivity.add_argument("--walk-min-accepted-windows", type=int, default=3)
    funding_sensitivity.add_argument("--walk-min-accepted-ratio", type=float, default=1.0)
    funding_sensitivity.add_argument("--walk-min-train-span-hours", type=float, default=0.0)
    funding_sensitivity.add_argument("--walk-min-test-span-hours", type=float, default=0.0)

    funding_oos = sub.add_parser("funding-oos-backtest", help="In-sample/out-of-sample funding carry backtest gate")
    funding_oos.add_argument("--input", type=str, default=None)
    funding_oos.add_argument("--output", type=str, default=None)
    funding_oos.add_argument("--notional-quote", type=float, default=100.0)
    funding_oos.add_argument("--spot-fee-bps", type=float, default=10.0)
    funding_oos.add_argument("--perp-fee-bps", type=float, default=7.5)
    funding_oos.add_argument("--slippage-bps", type=float, default=1.0)
    funding_oos.add_argument("--min-funding-rate", type=float, default=0.0)
    funding_oos.add_argument("--min-total-score", type=float, default=0.0)
    funding_oos.add_argument("--max-spot-spread-bps", type=float, default=30.0)
    funding_oos.add_argument("--max-perp-spread-bps", type=float, default=30.0)
    funding_oos.add_argument("--max-abs-basis-bps", type=float, default=500.0)
    funding_oos.add_argument("--min-basis-bps", type=float, default=-1e9)
    funding_oos.add_argument("--min-expected-net-carry-bps", type=float, default=-1e9)
    _add_funding_risk_adjusted_args(funding_oos)
    funding_oos.add_argument("--max-break-even-hours", type=float, default=1e9)
    funding_oos.add_argument("--min-funding-observations", type=int, default=1)
    funding_oos.add_argument("--min-funding-positive-ratio", type=float, default=0.0)
    funding_oos.add_argument("--min-funding-persistence-score", type=float, default=-1e9)
    funding_oos.add_argument("--min-regime-observations", type=int, default=1)
    funding_oos.add_argument("--min-perp-volume-24h-quote", type=float, default=0.0)
    funding_oos.add_argument("--min-spot-top-notional-quote", type=float, default=0.0)
    funding_oos.add_argument("--max-basis-std-bps", type=float, default=1e9)
    funding_oos.add_argument("--max-avg-spot-spread-bps", type=float, default=1e9)
    funding_oos.add_argument("--max-avg-perp-spread-bps", type=float, default=1e9)
    funding_oos.add_argument("--train-fraction", type=float, default=0.7)
    funding_oos.add_argument("--min-train-rows", type=int, default=20)
    funding_oos.add_argument("--min-oos-rows", type=int, default=20)
    funding_oos.add_argument("--min-train-span-hours", type=float, default=0.0)
    funding_oos.add_argument("--min-oos-span-hours", type=float, default=0.0)
    funding_oos.add_argument("--accept-min-trades", type=int, default=20)
    funding_oos.add_argument("--accept-min-win-rate", type=float, default=0.6)
    funding_oos.add_argument("--accept-min-expectancy-quote", type=float, default=0.0)
    funding_oos.add_argument("--accept-min-net-pnl-quote", type=float, default=0.0)
    funding_oos.add_argument("--accept-max-drawdown-quote", type=float, default=5.0)
    funding_oos.add_argument("--accept-min-profit-factor", type=float, default=1.2)
    funding_oos.add_argument("--accept-min-markets", type=int, default=1)
    funding_oos.add_argument("--accept-max-market-trade-share", type=float, default=1.0)
    funding_oos.add_argument("--accept-min-exchanges", type=int, default=1)
    funding_oos.add_argument("--accept-max-exchange-trade-share", type=float, default=1.0)
    funding_oos.add_argument("--accept-min-profitable-windows", type=int, default=0)
    funding_oos.add_argument("--accept-max-window-pnl-share", type=float, default=1.0)
    funding_oos.add_argument("--stress-enabled", action="store_true")
    funding_oos.add_argument("--stress-adverse-basis-bps", type=float, default=0.0)
    funding_oos.add_argument("--stress-spread-widen-bps", type=float, default=0.0)
    funding_oos.add_argument("--stress-funding-flip-bps", type=float, default=0.0)
    funding_oos.add_argument("--stress-min-net-pnl-quote", type=float, default=0.0)
    funding_oos.add_argument("--stress-max-drawdown-quote", type=float, default=5.0)

    funding_walk = sub.add_parser("funding-walk-forward", help="Rolling train/test walk-forward funding carry gate")
    funding_walk.add_argument("--input", type=str, default=None)
    funding_walk.add_argument("--output", type=str, default=None)
    funding_walk.add_argument("--strict-research", action="store_true")
    funding_walk.add_argument("--notional-quote", type=float, default=100.0)
    funding_walk.add_argument("--spot-fee-bps", type=float, default=10.0)
    funding_walk.add_argument("--perp-fee-bps", type=float, default=7.5)
    funding_walk.add_argument("--slippage-bps", type=float, default=1.0)
    funding_walk.add_argument("--min-funding-rate", type=float, default=0.0)
    funding_walk.add_argument("--min-total-score", type=float, default=0.0)
    funding_walk.add_argument("--max-spot-spread-bps", type=float, default=30.0)
    funding_walk.add_argument("--max-perp-spread-bps", type=float, default=30.0)
    funding_walk.add_argument("--max-abs-basis-bps", type=float, default=500.0)
    funding_walk.add_argument("--min-basis-bps", type=float, default=-1e9)
    funding_walk.add_argument("--min-expected-net-carry-bps", type=float, default=-1e9)
    _add_funding_risk_adjusted_args(funding_walk)
    funding_walk.add_argument("--max-break-even-hours", type=float, default=1e9)
    funding_walk.add_argument("--min-funding-observations", type=int, default=1)
    funding_walk.add_argument("--min-funding-positive-ratio", type=float, default=0.0)
    funding_walk.add_argument("--min-funding-persistence-score", type=float, default=-1e9)
    funding_walk.add_argument("--min-regime-observations", type=int, default=1)
    funding_walk.add_argument("--min-perp-volume-24h-quote", type=float, default=0.0)
    funding_walk.add_argument("--min-spot-top-notional-quote", type=float, default=0.0)
    funding_walk.add_argument("--max-basis-std-bps", type=float, default=1e9)
    funding_walk.add_argument("--max-avg-spot-spread-bps", type=float, default=1e9)
    funding_walk.add_argument("--max-avg-perp-spread-bps", type=float, default=1e9)
    funding_walk.add_argument("--walk-train-rows", type=int, default=200)
    funding_walk.add_argument("--walk-test-rows", type=int, default=50)
    funding_walk.add_argument("--walk-step-rows", type=int, default=50)
    funding_walk.add_argument("--walk-min-windows", type=int, default=3)
    funding_walk.add_argument("--walk-min-accepted-windows", type=int, default=3)
    funding_walk.add_argument("--walk-min-accepted-ratio", type=float, default=1.0)
    funding_walk.add_argument("--walk-min-train-span-hours", type=float, default=0.0)
    funding_walk.add_argument("--walk-min-test-span-hours", type=float, default=0.0)
    funding_walk.add_argument("--accept-min-trades", type=int, default=20)
    funding_walk.add_argument("--accept-min-win-rate", type=float, default=0.6)
    funding_walk.add_argument("--accept-min-expectancy-quote", type=float, default=0.0)
    funding_walk.add_argument("--accept-min-net-pnl-quote", type=float, default=0.0)
    funding_walk.add_argument("--accept-max-drawdown-quote", type=float, default=5.0)
    funding_walk.add_argument("--accept-min-profit-factor", type=float, default=1.2)
    funding_walk.add_argument("--accept-min-markets", type=int, default=1)
    funding_walk.add_argument("--accept-max-market-trade-share", type=float, default=1.0)
    funding_walk.add_argument("--accept-min-exchanges", type=int, default=1)
    funding_walk.add_argument("--accept-max-exchange-trade-share", type=float, default=1.0)
    funding_walk.add_argument("--accept-min-profitable-windows", type=int, default=0)
    funding_walk.add_argument("--accept-max-window-pnl-share", type=float, default=1.0)
    funding_walk.add_argument("--stress-enabled", action="store_true")
    funding_walk.add_argument("--stress-adverse-basis-bps", type=float, default=0.0)
    funding_walk.add_argument("--stress-spread-widen-bps", type=float, default=0.0)
    funding_walk.add_argument("--stress-funding-flip-bps", type=float, default=0.0)
    funding_walk.add_argument("--stress-min-net-pnl-quote", type=float, default=0.0)
    funding_walk.add_argument("--stress-max-drawdown-quote", type=float, default=5.0)

    funding_postprocess = sub.add_parser("funding-postprocess", help="Guarded rank + backtest for completed funding collect")
    funding_postprocess.add_argument("--input", type=str, default=None)
    funding_postprocess.add_argument("--manifest", type=str, default=None)
    funding_postprocess.add_argument("--rank-output", type=str, default=None)
    funding_postprocess.add_argument("--backtest-output", type=str, default=None)
    funding_postprocess.add_argument("--oos-output", type=str, default=None)
    funding_postprocess.add_argument("--walk-forward-output", type=str, default=None)
    funding_postprocess.add_argument("--postprocess-output", type=str, default=None)
    funding_postprocess.add_argument("--allow-partial", action="store_true")
    funding_postprocess.add_argument("--strict-research", action="store_true")
    funding_postprocess.add_argument("--top-n", type=int, default=20)
    funding_postprocess.add_argument("--min-funding-observations", type=int, default=1)
    funding_postprocess.add_argument("--min-funding-positive-ratio", type=float, default=0.0)
    funding_postprocess.add_argument("--min-funding-persistence-score", type=float, default=-1e9)
    funding_postprocess.add_argument("--funding-persistence-weight", type=float, default=1.0)
    funding_postprocess.add_argument("--min-regime-observations", type=int, default=1)
    funding_postprocess.add_argument("--min-perp-volume-24h-quote", type=float, default=0.0)
    funding_postprocess.add_argument("--min-spot-top-notional-quote", type=float, default=0.0)
    funding_postprocess.add_argument("--max-basis-std-bps", type=float, default=1e9)
    funding_postprocess.add_argument("--max-avg-spot-spread-bps", type=float, default=1e9)
    funding_postprocess.add_argument("--max-avg-perp-spread-bps", type=float, default=1e9)
    funding_postprocess.add_argument("--notional-quote", type=float, default=100.0)
    funding_postprocess.add_argument("--spot-fee-bps", type=float, default=10.0)
    funding_postprocess.add_argument("--perp-fee-bps", type=float, default=7.5)
    funding_postprocess.add_argument("--slippage-bps", type=float, default=1.0)
    funding_postprocess.add_argument("--min-funding-rate", type=float, default=0.0)
    funding_postprocess.add_argument("--min-total-score", type=float, default=0.0)
    funding_postprocess.add_argument("--max-spot-spread-bps", type=float, default=30.0)
    funding_postprocess.add_argument("--max-perp-spread-bps", type=float, default=30.0)
    funding_postprocess.add_argument("--max-abs-basis-bps", type=float, default=500.0)
    funding_postprocess.add_argument("--min-basis-bps", type=float, default=-1e9)
    funding_postprocess.add_argument("--min-expected-net-carry-bps", type=float, default=-1e9)
    _add_funding_risk_adjusted_args(funding_postprocess)
    funding_postprocess.add_argument("--max-break-even-hours", type=float, default=1e9)
    funding_postprocess.add_argument("--accept-min-trades", type=int, default=20)
    funding_postprocess.add_argument("--accept-min-win-rate", type=float, default=0.6)
    funding_postprocess.add_argument("--accept-min-expectancy-quote", type=float, default=0.0)
    funding_postprocess.add_argument("--accept-min-net-pnl-quote", type=float, default=0.0)
    funding_postprocess.add_argument("--accept-max-drawdown-quote", type=float, default=5.0)
    funding_postprocess.add_argument("--accept-min-profit-factor", type=float, default=1.2)
    funding_postprocess.add_argument("--accept-min-markets", type=int, default=1)
    funding_postprocess.add_argument("--accept-max-market-trade-share", type=float, default=1.0)
    funding_postprocess.add_argument("--accept-min-exchanges", type=int, default=1)
    funding_postprocess.add_argument("--accept-max-exchange-trade-share", type=float, default=1.0)
    funding_postprocess.add_argument("--accept-min-profitable-windows", type=int, default=0)
    funding_postprocess.add_argument("--accept-max-window-pnl-share", type=float, default=1.0)
    funding_postprocess.add_argument("--stress-enabled", action="store_true")
    funding_postprocess.add_argument("--stress-adverse-basis-bps", type=float, default=0.0)
    funding_postprocess.add_argument("--stress-spread-widen-bps", type=float, default=0.0)
    funding_postprocess.add_argument("--stress-funding-flip-bps", type=float, default=0.0)
    funding_postprocess.add_argument("--stress-min-net-pnl-quote", type=float, default=0.0)
    funding_postprocess.add_argument("--stress-max-drawdown-quote", type=float, default=5.0)
    funding_postprocess.add_argument("--oos-train-fraction", type=float, default=0.7)
    funding_postprocess.add_argument("--oos-min-train-rows", type=int, default=20)
    funding_postprocess.add_argument("--oos-min-rows", type=int, default=20)
    funding_postprocess.add_argument("--oos-min-train-span-hours", type=float, default=0.0)
    funding_postprocess.add_argument("--oos-min-span-hours", type=float, default=0.0)
    funding_postprocess.add_argument("--walk-train-rows", type=int, default=200)
    funding_postprocess.add_argument("--walk-test-rows", type=int, default=50)
    funding_postprocess.add_argument("--walk-step-rows", type=int, default=50)
    funding_postprocess.add_argument("--walk-min-windows", type=int, default=3)
    funding_postprocess.add_argument("--walk-min-accepted-windows", type=int, default=3)
    funding_postprocess.add_argument("--walk-min-accepted-ratio", type=float, default=1.0)
    funding_postprocess.add_argument("--walk-min-train-span-hours", type=float, default=0.0)
    funding_postprocess.add_argument("--walk-min-test-span-hours", type=float, default=0.0)
    funding_postprocess.add_argument("--quality-min-rows", type=int, default=1)
    funding_postprocess.add_argument("--quality-min-markets", type=int, default=1)
    funding_postprocess.add_argument("--quality-min-completed-cycles", type=int, default=1)
    funding_postprocess.add_argument("--quality-min-unique-cycles", type=int, default=0)
    funding_postprocess.add_argument("--quality-min-avg-rows-per-cycle", type=float, default=0.0)
    funding_postprocess.add_argument("--quality-min-min-rows-per-cycle", type=int, default=0)
    funding_postprocess.add_argument("--quality-max-error-rate", type=float, default=1.0)
    funding_postprocess.add_argument("--quality-max-cycle-market-duplicate-rate", type=float, default=1.0)
    funding_postprocess.add_argument("--quality-required-row-fields", type=str, default="")
    funding_postprocess.add_argument("--quality-min-required-row-field-presence", type=float, default=1.0)

    funding_finalize = sub.add_parser("funding-finalize", help="Guarded final postprocess + paper-plan for completed funding collect")
    funding_finalize.add_argument("--input", type=str, default=None)
    funding_finalize.add_argument("--manifest", type=str, default=None)
    funding_finalize.add_argument("--rank-output", type=str, default=None)
    funding_finalize.add_argument("--backtest-output", type=str, default=None)
    funding_finalize.add_argument("--oos-output", type=str, default=None)
    funding_finalize.add_argument("--walk-forward-output", type=str, default=None)
    funding_finalize.add_argument("--postprocess-output", type=str, default=None)
    funding_finalize.add_argument("--paper-plan-output", type=str, default=None)
    funding_finalize.add_argument("--paper-output", type=str, default=None)
    funding_finalize.add_argument("--strict-research", action="store_true")
    funding_finalize.add_argument("--top-n", type=int, default=20)
    funding_finalize.add_argument("--min-funding-observations", type=int, default=1)
    funding_finalize.add_argument("--min-funding-positive-ratio", type=float, default=0.0)
    funding_finalize.add_argument("--min-funding-persistence-score", type=float, default=-1e9)
    funding_finalize.add_argument("--funding-persistence-weight", type=float, default=1.0)
    funding_finalize.add_argument("--min-regime-observations", type=int, default=1)
    funding_finalize.add_argument("--min-perp-volume-24h-quote", type=float, default=0.0)
    funding_finalize.add_argument("--min-spot-top-notional-quote", type=float, default=0.0)
    funding_finalize.add_argument("--max-basis-std-bps", type=float, default=1e9)
    funding_finalize.add_argument("--max-avg-spot-spread-bps", type=float, default=1e9)
    funding_finalize.add_argument("--max-avg-perp-spread-bps", type=float, default=1e9)
    funding_finalize.add_argument("--notional-quote", type=float, default=100.0)
    funding_finalize.add_argument("--spot-fee-bps", type=float, default=10.0)
    funding_finalize.add_argument("--perp-fee-bps", type=float, default=7.5)
    funding_finalize.add_argument("--slippage-bps", type=float, default=1.0)
    funding_finalize.add_argument("--min-funding-rate", type=float, default=0.0)
    funding_finalize.add_argument("--min-total-score", type=float, default=0.0)
    funding_finalize.add_argument("--max-spot-spread-bps", type=float, default=30.0)
    funding_finalize.add_argument("--max-perp-spread-bps", type=float, default=30.0)
    funding_finalize.add_argument("--max-abs-basis-bps", type=float, default=500.0)
    funding_finalize.add_argument("--min-basis-bps", type=float, default=-1e9)
    funding_finalize.add_argument("--min-expected-net-carry-bps", type=float, default=-1e9)
    _add_funding_risk_adjusted_args(funding_finalize)
    funding_finalize.add_argument("--max-break-even-hours", type=float, default=1e9)
    funding_finalize.add_argument("--accept-min-trades", type=int, default=20)
    funding_finalize.add_argument("--accept-min-win-rate", type=float, default=0.6)
    funding_finalize.add_argument("--accept-min-expectancy-quote", type=float, default=0.0)
    funding_finalize.add_argument("--accept-min-net-pnl-quote", type=float, default=0.0)
    funding_finalize.add_argument("--accept-max-drawdown-quote", type=float, default=5.0)
    funding_finalize.add_argument("--accept-min-profit-factor", type=float, default=1.2)
    funding_finalize.add_argument("--accept-min-markets", type=int, default=1)
    funding_finalize.add_argument("--accept-max-market-trade-share", type=float, default=1.0)
    funding_finalize.add_argument("--accept-min-exchanges", type=int, default=1)
    funding_finalize.add_argument("--accept-max-exchange-trade-share", type=float, default=1.0)
    funding_finalize.add_argument("--accept-min-profitable-windows", type=int, default=0)
    funding_finalize.add_argument("--accept-max-window-pnl-share", type=float, default=1.0)
    funding_finalize.add_argument("--stress-enabled", action="store_true")
    funding_finalize.add_argument("--stress-adverse-basis-bps", type=float, default=0.0)
    funding_finalize.add_argument("--stress-spread-widen-bps", type=float, default=0.0)
    funding_finalize.add_argument("--stress-funding-flip-bps", type=float, default=0.0)
    funding_finalize.add_argument("--stress-min-net-pnl-quote", type=float, default=0.0)
    funding_finalize.add_argument("--stress-max-drawdown-quote", type=float, default=5.0)
    funding_finalize.add_argument("--oos-train-fraction", type=float, default=0.7)
    funding_finalize.add_argument("--oos-min-train-rows", type=int, default=20)
    funding_finalize.add_argument("--oos-min-rows", type=int, default=20)
    funding_finalize.add_argument("--oos-min-train-span-hours", type=float, default=0.0)
    funding_finalize.add_argument("--oos-min-span-hours", type=float, default=0.0)
    funding_finalize.add_argument("--walk-train-rows", type=int, default=200)
    funding_finalize.add_argument("--walk-test-rows", type=int, default=50)
    funding_finalize.add_argument("--walk-step-rows", type=int, default=50)
    funding_finalize.add_argument("--walk-min-windows", type=int, default=3)
    funding_finalize.add_argument("--walk-min-accepted-windows", type=int, default=3)
    funding_finalize.add_argument("--walk-min-accepted-ratio", type=float, default=1.0)
    funding_finalize.add_argument("--walk-min-train-span-hours", type=float, default=0.0)
    funding_finalize.add_argument("--walk-min-test-span-hours", type=float, default=0.0)
    funding_finalize.add_argument("--quality-min-rows", type=int, default=1)
    funding_finalize.add_argument("--quality-min-markets", type=int, default=1)
    funding_finalize.add_argument("--quality-min-completed-cycles", type=int, default=1)
    funding_finalize.add_argument("--quality-min-unique-cycles", type=int, default=0)
    funding_finalize.add_argument("--quality-min-avg-rows-per-cycle", type=float, default=0.0)
    funding_finalize.add_argument("--quality-min-min-rows-per-cycle", type=int, default=0)
    funding_finalize.add_argument("--quality-max-error-rate", type=float, default=1.0)
    funding_finalize.add_argument("--quality-max-cycle-market-duplicate-rate", type=float, default=1.0)
    funding_finalize.add_argument("--quality-required-row-fields", type=str, default="")
    funding_finalize.add_argument("--quality-min-required-row-field-presence", type=float, default=1.0)
    funding_finalize.add_argument("--min-forward-hours", type=float, default=24.0)
    funding_finalize.add_argument("--min-forward-rows", type=int, default=20)
    funding_finalize.add_argument("--min-forward-markets", type=int, default=1)

    funding_final_review = sub.add_parser("funding-final-review", help="Guarded final funding review: finalize + gates + decision")
    funding_final_review.add_argument("--input", type=str, default=None)
    funding_final_review.add_argument("--manifest", type=str, default=None)
    funding_final_review.add_argument("--output", type=str, default=None)
    funding_final_review.add_argument("--rank-output", type=str, default=None)
    funding_final_review.add_argument("--backtest-output", type=str, default=None)
    funding_final_review.add_argument("--oos-output", type=str, default=None)
    funding_final_review.add_argument("--walk-forward-output", type=str, default=None)
    funding_final_review.add_argument("--postprocess-output", type=str, default=None)
    funding_final_review.add_argument("--paper-plan-output", type=str, default=None)
    funding_final_review.add_argument("--paper-output", type=str, default=None)
    funding_final_review.add_argument("--gate-report-output", type=str, default=None)
    funding_final_review.add_argument("--regime-report-output", type=str, default=None)
    funding_final_review.add_argument("--frontier-report-output", type=str, default=None)
    funding_final_review.add_argument("--sensitivity-output", type=str, default=None)
    funding_final_review.add_argument("--decision-report-output", type=str, default=None)
    funding_final_review.add_argument("--wait-timeout-sec", type=float, default=0.0)
    funding_final_review.add_argument("--wait-poll-interval-sec", type=float, default=60.0)
    funding_final_review.add_argument("--wait-stale-after-sec", type=float, default=900.0)
    funding_final_review.add_argument("--wait-output", type=str, default=None)
    funding_final_review.add_argument("--strict-research", action="store_true")
    funding_final_review.add_argument("--top-n", type=int, default=20)
    funding_final_review.add_argument("--min-funding-observations", type=int, default=1)
    funding_final_review.add_argument("--min-funding-positive-ratio", type=float, default=0.0)
    funding_final_review.add_argument("--min-funding-persistence-score", type=float, default=-1e9)
    funding_final_review.add_argument("--funding-persistence-weight", type=float, default=1.0)
    funding_final_review.add_argument("--min-regime-observations", type=int, default=1)
    funding_final_review.add_argument("--min-perp-volume-24h-quote", type=float, default=0.0)
    funding_final_review.add_argument("--min-spot-top-notional-quote", type=float, default=0.0)
    funding_final_review.add_argument("--max-basis-std-bps", type=float, default=1e9)
    funding_final_review.add_argument("--max-avg-spot-spread-bps", type=float, default=1e9)
    funding_final_review.add_argument("--max-avg-perp-spread-bps", type=float, default=1e9)
    funding_final_review.add_argument("--notional-quote", type=float, default=100.0)
    funding_final_review.add_argument("--spot-fee-bps", type=float, default=10.0)
    funding_final_review.add_argument("--perp-fee-bps", type=float, default=7.5)
    funding_final_review.add_argument("--slippage-bps", type=float, default=1.0)
    funding_final_review.add_argument("--min-funding-rate", type=float, default=0.0)
    funding_final_review.add_argument("--min-total-score", type=float, default=0.0)
    funding_final_review.add_argument("--max-spot-spread-bps", type=float, default=30.0)
    funding_final_review.add_argument("--max-perp-spread-bps", type=float, default=30.0)
    funding_final_review.add_argument("--max-abs-basis-bps", type=float, default=500.0)
    funding_final_review.add_argument("--min-basis-bps", type=float, default=-1e9)
    funding_final_review.add_argument("--min-expected-net-carry-bps", type=float, default=-1e9)
    _add_funding_risk_adjusted_args(funding_final_review)
    funding_final_review.add_argument("--max-break-even-hours", type=float, default=1e9)
    funding_final_review.add_argument("--accept-min-trades", type=int, default=20)
    funding_final_review.add_argument("--accept-min-win-rate", type=float, default=0.6)
    funding_final_review.add_argument("--accept-min-expectancy-quote", type=float, default=0.0)
    funding_final_review.add_argument("--accept-min-net-pnl-quote", type=float, default=0.0)
    funding_final_review.add_argument("--accept-max-drawdown-quote", type=float, default=5.0)
    funding_final_review.add_argument("--accept-min-profit-factor", type=float, default=1.2)
    funding_final_review.add_argument("--accept-min-markets", type=int, default=1)
    funding_final_review.add_argument("--accept-max-market-trade-share", type=float, default=1.0)
    funding_final_review.add_argument("--accept-min-exchanges", type=int, default=1)
    funding_final_review.add_argument("--accept-max-exchange-trade-share", type=float, default=1.0)
    funding_final_review.add_argument("--accept-min-profitable-windows", type=int, default=0)
    funding_final_review.add_argument("--accept-max-window-pnl-share", type=float, default=1.0)
    funding_final_review.add_argument("--stress-enabled", action="store_true")
    funding_final_review.add_argument("--stress-adverse-basis-bps", type=float, default=0.0)
    funding_final_review.add_argument("--stress-spread-widen-bps", type=float, default=0.0)
    funding_final_review.add_argument("--stress-funding-flip-bps", type=float, default=0.0)
    funding_final_review.add_argument("--stress-min-net-pnl-quote", type=float, default=0.0)
    funding_final_review.add_argument("--stress-max-drawdown-quote", type=float, default=5.0)
    funding_final_review.add_argument("--sensitivity-spot-fee-bps", type=str, default="0,5,10")
    funding_final_review.add_argument("--sensitivity-perp-fee-bps", type=str, default="0,2.5,7.5")
    funding_final_review.add_argument("--sensitivity-slippage-bps", type=str, default="0,0.5,1")
    funding_final_review.add_argument("--sensitivity-target-hold-intervals", type=str, default="1,3,6")
    funding_final_review.add_argument("--sensitivity-max-break-even-hours", type=str, default="24,72,168")
    funding_final_review.add_argument("--sensitivity-oos", action="store_true")
    funding_final_review.add_argument("--sensitivity-walk-forward", action="store_true")
    funding_final_review.add_argument("--oos-train-fraction", type=float, default=0.7)
    funding_final_review.add_argument("--oos-min-train-rows", type=int, default=20)
    funding_final_review.add_argument("--oos-min-rows", type=int, default=20)
    funding_final_review.add_argument("--oos-min-train-span-hours", type=float, default=0.0)
    funding_final_review.add_argument("--oos-min-span-hours", type=float, default=0.0)
    funding_final_review.add_argument("--walk-train-rows", type=int, default=200)
    funding_final_review.add_argument("--walk-test-rows", type=int, default=50)
    funding_final_review.add_argument("--walk-step-rows", type=int, default=50)
    funding_final_review.add_argument("--walk-min-windows", type=int, default=3)
    funding_final_review.add_argument("--walk-min-accepted-windows", type=int, default=3)
    funding_final_review.add_argument("--walk-min-accepted-ratio", type=float, default=1.0)
    funding_final_review.add_argument("--walk-min-train-span-hours", type=float, default=0.0)
    funding_final_review.add_argument("--walk-min-test-span-hours", type=float, default=0.0)
    funding_final_review.add_argument("--quality-min-rows", type=int, default=1)
    funding_final_review.add_argument("--quality-min-markets", type=int, default=1)
    funding_final_review.add_argument("--quality-min-completed-cycles", type=int, default=1)
    funding_final_review.add_argument("--quality-min-unique-cycles", type=int, default=0)
    funding_final_review.add_argument("--quality-min-avg-rows-per-cycle", type=float, default=0.0)
    funding_final_review.add_argument("--quality-min-min-rows-per-cycle", type=int, default=0)
    funding_final_review.add_argument("--quality-max-error-rate", type=float, default=1.0)
    funding_final_review.add_argument("--quality-max-cycle-market-duplicate-rate", type=float, default=1.0)
    funding_final_review.add_argument("--quality-required-row-fields", type=str, default="")
    funding_final_review.add_argument("--quality-min-required-row-field-presence", type=float, default=1.0)
    funding_final_review.add_argument("--min-forward-hours", type=float, default=24.0)
    funding_final_review.add_argument("--min-forward-rows", type=int, default=20)
    funding_final_review.add_argument("--min-forward-markets", type=int, default=1)

    funding_paper_plan = sub.add_parser("funding-paper-plan", help="Freeze accepted funding research config for paper-forward")
    funding_paper_plan.add_argument("--postprocess", required=True)
    funding_paper_plan.add_argument("--decision-report", required=True)
    funding_paper_plan.add_argument("--output", type=str, default=None)
    funding_paper_plan.add_argument("--paper-output", type=str, default=None)
    funding_paper_plan.add_argument("--min-forward-hours", type=float, default=24.0)
    funding_paper_plan.add_argument("--min-forward-rows", type=int, default=20)
    funding_paper_plan.add_argument("--min-forward-markets", type=int, default=1)

    funding_paper_forward = sub.add_parser("funding-paper-forward", help="Run frozen funding plan on forward paper-only data")
    funding_paper_forward.add_argument("--plan", required=True)
    funding_paper_forward.add_argument("--input", required=True)
    funding_paper_forward.add_argument("--output", type=str, default=None)
    funding_paper_forward.add_argument("--summary-output", type=str, default=None)
    funding_paper_forward.add_argument("--allow-source-input", action="store_true")

    funding_paper_decision_report_parser = sub.add_parser("funding-paper-decision-report", help="Decide whether paper-forward funding results pass research-only gates")
    funding_paper_decision_report_parser.add_argument("--summary", required=True)
    funding_paper_decision_report_parser.add_argument("--plan", required=True)
    funding_paper_decision_report_parser.add_argument("--output", type=str, default=None)

    funding_goal_audit_parser = sub.add_parser("funding-goal-audit", help="Audit current funding research goal stage and next safe action")
    funding_goal_audit_parser.add_argument("--input", type=str, default=None)
    funding_goal_audit_parser.add_argument("--manifest", type=str, default=None)
    funding_goal_audit_parser.add_argument("--final-review", type=str, default=None)
    funding_goal_audit_parser.add_argument("--paper-plan", type=str, default=None)
    funding_goal_audit_parser.add_argument("--paper-summary", type=str, default=None)
    funding_goal_audit_parser.add_argument("--paper-decision", type=str, default=None)
    funding_goal_audit_parser.add_argument("--output", type=str, default=None)
    funding_goal_audit_parser.add_argument("--stale-after-sec", type=float, default=900.0)
    funding_goal_audit_parser.add_argument("--strict-research", action="store_true")
    funding_goal_audit_parser.add_argument("--quality-min-rows", type=int, default=None)
    funding_goal_audit_parser.add_argument("--quality-min-markets", type=int, default=None)
    funding_goal_audit_parser.add_argument("--quality-min-completed-cycles", type=int, default=None)
    funding_goal_audit_parser.add_argument("--quality-min-unique-cycles", type=int, default=None)
    funding_goal_audit_parser.add_argument("--quality-min-avg-rows-per-cycle", type=float, default=None)
    funding_goal_audit_parser.add_argument("--quality-min-min-rows-per-cycle", type=int, default=None)
    funding_goal_audit_parser.add_argument("--quality-max-error-rate", type=float, default=None)
    funding_goal_audit_parser.add_argument("--quality-max-cycle-market-duplicate-rate", type=float, default=None)
    funding_goal_audit_parser.add_argument("--quality-required-row-fields", type=str, default=None)
    funding_goal_audit_parser.add_argument("--quality-min-required-row-field-presence", type=float, default=None)

    fast_edge_v4_validate = sub.add_parser(
        "fast-edge-v4-validate",
        help="Validate hash-bound funding-pressure evaluator without reading OOS",
    )
    fast_edge_v4_validate.add_argument("--plan", required=True)
    fast_edge_v4_validate.add_argument("--expected-plan-hash", required=True)
    fast_edge_v4_validate.add_argument("--output", type=str, default=None)

    fast_edge_v4_evaluate = sub.add_parser(
        "fast-edge-v4-evaluate",
        help="Run one frozen no-grid funding-pressure evaluation",
    )
    fast_edge_v4_evaluate.add_argument("--plan", required=True)
    fast_edge_v4_evaluate.add_argument("--expected-plan-hash", required=True)
    fast_edge_v4_evaluate.add_argument("--output", required=True)

    fast_edge_v5_validate = sub.add_parser(
        "fast-edge-v5-validate",
        help="Validate hash-bound wick-rejection evaluator without reading OOS",
    )
    fast_edge_v5_validate.add_argument("--plan", required=True)
    fast_edge_v5_validate.add_argument("--expected-plan-hash", required=True)
    fast_edge_v5_validate.add_argument("--output", type=str, default=None)

    fast_edge_v5_evaluate = sub.add_parser(
        "fast-edge-v5-evaluate",
        help="Run one frozen no-grid wick-rejection evaluation",
    )
    fast_edge_v5_evaluate.add_argument("--plan", required=True)
    fast_edge_v5_evaluate.add_argument("--expected-plan-hash", required=True)
    fast_edge_v5_evaluate.add_argument("--output", required=True)

    setup_registry = sub.add_parser("setup-registry", help="Write the research-only setup registry")
    setup_registry.add_argument("--output", type=str, default=None)

    experiment_record = sub.add_parser("experiment-record", help="Append an experiment ledger record")
    experiment_record.add_argument("--output", type=str, default=None)
    experiment_record.add_argument("--source-video-id", required=True)
    experiment_record.add_argument("--source-url", required=True)
    experiment_record.add_argument("--source-channel", default="https://www.youtube.com/@AnufrievNikita/")
    experiment_record.add_argument("--participant", default="")
    experiment_record.add_argument("--claim-family", required=True)
    experiment_record.add_argument("--hypothesis", required=True)
    experiment_record.add_argument("--setup-id", required=True)
    experiment_record.add_argument("--dataset", required=True)
    experiment_record.add_argument("--config-json", default=None)
    experiment_record.add_argument("--result-path", default=None)
    experiment_record.add_argument("--metrics-json", default=None)
    experiment_record.add_argument("--verdict", choices=["untested", "failed", "inconclusive", "promising", "accepted_research", "rejected", "blocked"], required=True)
    experiment_record.add_argument("--verdict-reason", default="")
    experiment_record.add_argument("--tags", default=None)
    experiment_record.add_argument("--notes", default="")
    experiment_record.add_argument("--fee-schedule-revision", default="unspecified")
    experiment_record.add_argument("--evaluation-scope", default="unspecified")
    experiment_record.add_argument("--oos-status", default="not_evaluated")

    experiment_list = sub.add_parser("experiment-list", help="List experiment ledger records")
    experiment_list.add_argument("--input", type=str, default=None)
    experiment_list.add_argument("--output", type=str, default=None)
    experiment_list.add_argument("--verdict", type=str, default=None)
    experiment_list.add_argument("--setup-id", type=str, default=None)
    experiment_list.add_argument("--top-n", type=int, default=20)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    _apply_funding_strict_research_preset(args)
    cfg = load_config(args.config)

    if args.command == "collect":
        cmd_collect(cfg, seconds=args.seconds)
        return
    if args.command == "backtest":
        cmd_backtest(cfg, input_path=args.input, qty=args.qty)
        return
    if args.command == "run":
        cmd_run(cfg, mode=args.mode, cycles=args.cycles, qty=args.qty)
        return
    if args.command == "universe":
        cmd_universe(cfg, date_stamp=args.date_stamp, top_preview=args.top_preview)
        return
    if args.command == "multi-run":
        cmd_multi_run(
            cfg,
            exchanges=args.exchanges,
            universe_path=args.universe,
            quote=args.quote,
            max_symbols=args.max_symbols,
            max_pairs_per_exchange=args.max_pairs_per_exchange,
            cycles=args.cycles,
            duration_sec=args.duration_sec,
            paper_notional_quote=args.paper_notional_quote,
        )
        return
    if args.command == "ws-collect":
        cmd_ws_collect(
            cfg,
            exchanges=args.exchanges,
            universe_path=args.universe,
            quote=args.quote,
            max_symbols=args.max_symbols,
            max_pairs_per_exchange=args.max_pairs_per_exchange,
            duration_sec=args.duration_sec,
            update_interval=args.update_interval,
        )
        return
    if args.command == "ws-normalize":
        cmd_ws_normalize(cfg, input_path=args.input, output_path=args.output)
        return
    if args.command == "ws-data-quality":
        cmd_ws_data_quality(
            cfg,
            input_path=args.input,
            manifest_path=args.manifest,
            output_path=args.output,
            min_rows=args.min_rows,
            min_exchanges=args.min_exchanges,
            min_markets=args.min_markets,
            min_span_hours=args.min_span_hours,
            min_duration_ratio=args.min_duration_ratio,
            max_parse_error_rate=args.max_parse_error_rate,
            required_event_kinds=args.required_event_kinds,
            min_markets_with_required_kinds=args.min_markets_with_required_kinds,
            max_market_event_share=args.max_market_event_share,
            max_gap_sec=args.max_gap_sec,
            max_manifest_error_count=args.max_manifest_error_count,
        )
        return
    if args.command == "ws-postprocess":
        cmd_ws_postprocess(
            cfg,
            input_path=args.input,
            manifest_path=args.manifest,
            normalized_output_path=args.normalized_output,
            quality_output_path=args.quality_output,
            report_output_path=args.output,
            min_rows=args.min_rows,
            min_exchanges=args.min_exchanges,
            min_markets=args.min_markets,
            min_span_hours=args.min_span_hours,
            min_duration_ratio=args.min_duration_ratio,
            max_parse_error_rate=args.max_parse_error_rate,
            required_event_kinds=args.required_event_kinds,
            min_markets_with_required_kinds=args.min_markets_with_required_kinds,
            max_market_event_share=args.max_market_event_share,
            max_gap_sec=args.max_gap_sec,
            max_manifest_error_count=args.max_manifest_error_count,
        )
        return
    if args.command == "perp-collect":
        cmd_perp_collect(
            cfg,
            exchanges=args.exchanges,
            universe_path=args.universe,
            quote=args.quote,
            max_symbols=args.max_symbols,
            max_pairs_per_exchange=args.max_pairs_per_exchange,
            cycles=args.cycles,
            duration_sec=args.duration_sec,
            poll_interval_sec=args.poll_interval_sec,
            depth_limit=args.depth_limit,
            trades_limit=args.trades_limit,
            output_path=args.output,
        )
        return
    if args.command == "perp-report":
        cmd_perp_report(cfg, input_path=args.input, output_path=args.output)
        return
    if args.command == "event-quality-report":
        cmd_event_quality_report(
            cfg,
            input_path=args.input,
            output_path=args.output,
            lookback_sec=args.lookback_sec,
            horizon_sec=args.horizon_sec,
            min_sweep_notional_quote=args.min_sweep_notional_quote,
            reclaim_bps=args.reclaim_bps,
            target_bps=args.target_bps,
            stop_bps=args.stop_bps,
            max_pre_spread_bps=args.max_pre_spread_bps,
            event_cooldown_sec=args.event_cooldown_sec,
            max_events=args.max_events,
        )
        return
    if args.command == "event-slice-optimizer":
        cmd_event_slice_optimizer(
            cfg,
            input_path=args.input,
            output_path=args.output,
            min_events=args.min_events,
            min_reclaimed=args.min_reclaimed,
            min_target_before_stop_rate=args.min_target_before_stop_rate,
            min_target_rate_all=args.min_target_rate_all,
            max_false_sweep_rate=args.max_false_sweep_rate,
            max_avg_adverse_bps=args.max_avg_adverse_bps,
            min_favorable_to_adverse=args.min_favorable_to_adverse,
            min_sweep_intensity_bps=args.min_sweep_intensity_bps,
            max_time_to_reclaim_sec=args.max_time_to_reclaim_sec,
            max_pre_spread_bps=args.max_pre_spread_bps,
            max_abs_basis_bps=args.max_abs_basis_bps,
            min_trade_notional_quote=args.min_trade_notional_quote,
            top_n=args.top_n,
        )
        return
    if args.command == "event-validation-report":
        cmd_event_validation_report(
            cfg,
            input_path=args.input,
            output_path=args.output,
            train_fraction=args.train_fraction,
            walk_forward_windows=args.walk_forward_windows,
            walk_forward_min_pass_ratio=args.walk_forward_min_pass_ratio,
            min_events=args.min_events,
            min_reclaimed=args.min_reclaimed,
            min_target_before_stop_rate=args.min_target_before_stop_rate,
            min_target_rate_all=args.min_target_rate_all,
            max_false_sweep_rate=args.max_false_sweep_rate,
            max_avg_adverse_bps=args.max_avg_adverse_bps,
            min_favorable_to_adverse=args.min_favorable_to_adverse,
            min_sweep_intensity_bps=args.min_sweep_intensity_bps,
            max_time_to_reclaim_sec=args.max_time_to_reclaim_sec,
            max_pre_spread_bps=args.max_pre_spread_bps,
            max_abs_basis_bps=args.max_abs_basis_bps,
            min_trade_notional_quote=args.min_trade_notional_quote,
            stress_favorable_haircut_bps=args.stress_favorable_haircut_bps,
            stress_adverse_widen_bps=args.stress_adverse_widen_bps,
            stress_target_bps=args.stress_target_bps,
            stress_stop_bps=args.stress_stop_bps,
            top_n=args.top_n,
        )
        return
    if args.command == "cross-venue-dislocation":
        report_path = args.output or str(default_cross_venue_dislocation_path(cfg.paths.backtest_dir))
        report = run_cross_venue_dislocation_file(
            args.input,
            output_path=report_path,
            cfg=CrossVenueDislocationConfig(
                quote=args.quote,
                stale_quote_sec=args.stale_quote_sec,
                min_top_notional_quote=args.min_top_notional_quote,
                round_trip_fee_bps=args.round_trip_fee_bps,
                slippage_bps=args.slippage_bps,
                inventory_rebalance_buffer_bps=args.inventory_rebalance_buffer_bps,
                min_net_edge_bps=args.min_net_edge_bps,
                cooldown_sec=args.cooldown_sec,
                max_rows=args.max_rows,
                max_events=args.max_events,
                progress_every_rows=args.progress_every_rows,
                include_bases=_parse_optional_csv(args.include_bases),
            ),
        )
        print(json.dumps({"ok": True, "output": report_path, "summary": report["summary"], "decision": report["decision"]}, ensure_ascii=False))
        return
    if args.command == "perp-postprocess":
        cmd_perp_postprocess(
            cfg,
            input_path=args.input,
            manifest_path=args.manifest,
            report_output_path=args.report_output,
            grid_output_path=args.grid_output,
            require_final=not args.allow_partial,
        )
        return
    if args.command == "ws-replay":
        cmd_ws_replay(
            cfg,
            input_path=args.input,
            output_path=args.output,
            signal_type=args.signal_type,
            notional_quote=args.notional_quote,
            execution_mode=args.execution_mode,
            taker_fee_bps=args.taker_fee_bps,
            maker_fee_bps=args.maker_fee_bps,
            slippage_bps=args.slippage_bps,
            latency_ms=args.latency_ms,
            flow_window_sec=args.flow_window_sec,
            allow_short=args.allow_short,
            max_open_positions=args.max_open_positions,
            maker_queue_ahead_qty=args.maker_queue_ahead_qty,
            maker_queue_model=args.maker_queue_model,
            maker_queue_ahead_fraction=args.maker_queue_ahead_fraction,
            maker_order_ttl_sec=args.maker_order_ttl_sec,
            quality_filter_enabled=args.quality_filter,
            quality_window_sec=args.quality_window_sec,
            quality_min_trade_count=args.quality_min_trade_count,
            quality_min_trade_notional=args.quality_min_trade_notional,
            quality_max_avg_spread_bps=args.quality_max_avg_spread_bps,
            quality_min_quote_updates=args.quality_min_quote_updates,
            quality_min_top_qty=args.quality_min_top_qty,
            min_net_take_profit_bps=args.min_net_take_profit_bps,
            sweep_v2_allowed_markets=args.sweep_v2_allowed_markets,
            sweep_v2_side=args.sweep_v2_side,
            sweep_v2_min_trade_notional_quote=args.sweep_v2_min_trade_notional_quote,
            sweep_v2_min_intensity_bps=args.sweep_v2_min_intensity_bps,
            sweep_v2_max_pre_spread_bps=args.sweep_v2_max_pre_spread_bps,
            sweep_v2_max_reclaim_sec=args.sweep_v2_max_reclaim_sec,
            sweep_v2_event_cooldown_sec=args.sweep_v2_event_cooldown_sec,
            breakout_lookback_sec=args.breakout_lookback_sec,
            breakout_bps=args.breakout_bps,
            breakout_min_samples=args.breakout_min_samples,
            venue_costs_json=args.venue_costs_json,
            max_quote_age_sec=args.max_quote_age_sec,
        )
        return
    if args.command == "ws-grid-search":
        cmd_ws_grid_search(
            cfg,
            input_path=args.input,
            output_path=args.output,
            notional_quote=args.notional_quote,
            execution_mode=args.execution_mode,
            taker_fee_bps=args.taker_fee_bps,
            maker_fee_bps=args.maker_fee_bps,
            slippage_bps=args.slippage_bps,
            latency_ms=args.latency_ms,
            flow_window_sec=args.flow_window_sec,
            allow_short=args.allow_short,
            max_open_positions=args.max_open_positions,
            maker_queue_ahead_qty=args.maker_queue_ahead_qty,
            maker_queue_model=args.maker_queue_model,
            maker_queue_ahead_fraction=args.maker_queue_ahead_fraction,
            maker_order_ttl_sec=args.maker_order_ttl_sec,
            quality_filter_enabled=args.quality_filter,
            quality_window_sec=args.quality_window_sec,
            quality_min_trade_count=args.quality_min_trade_count,
            quality_min_trade_notional=args.quality_min_trade_notional,
            quality_max_avg_spread_bps=args.quality_max_avg_spread_bps,
            quality_min_quote_updates=args.quality_min_quote_updates,
            quality_min_top_qty=args.quality_min_top_qty,
            entry_imbalance_abs=args.entry_imbalance_abs,
            entry_signed_flow_notional=args.entry_signed_flow_notional,
            max_spread_bps=args.max_spread_bps,
            take_profit_bps=args.take_profit_bps,
            stop_loss_bps=args.stop_loss_bps,
            max_hold_sec=args.max_hold_sec,
            grid_signal_type=args.grid_signal_type,
            min_trades=args.min_trades,
            min_win_rate=args.min_win_rate,
            min_expectancy_quote=args.min_expectancy_quote,
            min_net_pnl_quote=args.min_net_pnl_quote,
            min_profit_factor=args.min_profit_factor,
            max_drawdown_quote=args.max_drawdown_quote,
            min_net_take_profit_bps=args.min_net_take_profit_bps,
            sweep_v2_allowed_markets=args.sweep_v2_allowed_markets,
            sweep_v2_side=args.sweep_v2_side,
            sweep_v2_min_trade_notional_quote=args.sweep_v2_min_trade_notional_quote,
            sweep_v2_min_intensity_bps=args.sweep_v2_min_intensity_bps,
            sweep_v2_max_pre_spread_bps=args.sweep_v2_max_pre_spread_bps,
            sweep_v2_max_reclaim_sec=args.sweep_v2_max_reclaim_sec,
            sweep_v2_event_cooldown_sec=args.sweep_v2_event_cooldown_sec,
            grid_breakout_bps=args.grid_breakout_bps,
            grid_breakout_lookback_sec=args.grid_breakout_lookback_sec,
            grid_breakout_min_samples=args.grid_breakout_min_samples,
            top_n=args.top_n,
            max_grid_combinations=args.max_grid_combinations,
            venue_costs_json=args.venue_costs_json,
            max_quote_age_sec=args.max_quote_age_sec,
        )
        return
    if args.command == "perp-replay":
        cmd_perp_replay(
            cfg,
            input_path=args.input,
            output_path=args.output,
            signal_type=args.signal_type,
            notional_quote=args.notional_quote,
            execution_mode=args.execution_mode,
            taker_fee_bps=args.taker_fee_bps,
            maker_fee_bps=args.maker_fee_bps,
            slippage_bps=args.slippage_bps,
            latency_ms=args.latency_ms,
            flow_window_sec=args.flow_window_sec,
            max_open_positions=args.max_open_positions,
            maker_queue_ahead_qty=args.maker_queue_ahead_qty,
            maker_queue_model=args.maker_queue_model,
            maker_queue_ahead_fraction=args.maker_queue_ahead_fraction,
            maker_order_ttl_sec=args.maker_order_ttl_sec,
            quality_filter_enabled=args.quality_filter,
            quality_window_sec=args.quality_window_sec,
            quality_min_trade_count=args.quality_min_trade_count,
            quality_min_trade_notional=args.quality_min_trade_notional,
            quality_max_avg_spread_bps=args.quality_max_avg_spread_bps,
            quality_min_quote_updates=args.quality_min_quote_updates,
            quality_min_top_qty=args.quality_min_top_qty,
            min_net_take_profit_bps=args.min_net_take_profit_bps,
            sweep_v2_allowed_markets=args.sweep_v2_allowed_markets,
            sweep_v2_side=args.sweep_v2_side,
            sweep_v2_min_trade_notional_quote=args.sweep_v2_min_trade_notional_quote,
            sweep_v2_min_intensity_bps=args.sweep_v2_min_intensity_bps,
            sweep_v2_max_pre_spread_bps=args.sweep_v2_max_pre_spread_bps,
            sweep_v2_max_reclaim_sec=args.sweep_v2_max_reclaim_sec,
            sweep_v2_event_cooldown_sec=args.sweep_v2_event_cooldown_sec,
            venue_costs_json=args.venue_costs_json,
            max_quote_age_sec=args.max_quote_age_sec,
        )
        return
    if args.command == "perp-grid-search":
        cmd_perp_grid_search(
            cfg,
            input_path=args.input,
            output_path=args.output,
            notional_quote=args.notional_quote,
            execution_mode=args.execution_mode,
            taker_fee_bps=args.taker_fee_bps,
            maker_fee_bps=args.maker_fee_bps,
            slippage_bps=args.slippage_bps,
            latency_ms=args.latency_ms,
            flow_window_sec=args.flow_window_sec,
            max_open_positions=args.max_open_positions,
            maker_queue_ahead_qty=args.maker_queue_ahead_qty,
            maker_queue_model=args.maker_queue_model,
            maker_queue_ahead_fraction=args.maker_queue_ahead_fraction,
            maker_order_ttl_sec=args.maker_order_ttl_sec,
            quality_filter_enabled=args.quality_filter,
            quality_window_sec=args.quality_window_sec,
            quality_min_trade_count=args.quality_min_trade_count,
            quality_min_trade_notional=args.quality_min_trade_notional,
            quality_max_avg_spread_bps=args.quality_max_avg_spread_bps,
            quality_min_quote_updates=args.quality_min_quote_updates,
            quality_min_top_qty=args.quality_min_top_qty,
            entry_imbalance_abs=args.entry_imbalance_abs,
            entry_signed_flow_notional=args.entry_signed_flow_notional,
            max_spread_bps=args.max_spread_bps,
            take_profit_bps=args.take_profit_bps,
            stop_loss_bps=args.stop_loss_bps,
            max_hold_sec=args.max_hold_sec,
            grid_signal_type=args.grid_signal_type,
            min_trades=args.min_trades,
            min_win_rate=args.min_win_rate,
            min_expectancy_quote=args.min_expectancy_quote,
            min_net_pnl_quote=args.min_net_pnl_quote,
            min_profit_factor=args.min_profit_factor,
            max_drawdown_quote=args.max_drawdown_quote,
            min_net_take_profit_bps=args.min_net_take_profit_bps,
            sweep_v2_allowed_markets=args.sweep_v2_allowed_markets,
            sweep_v2_side=args.sweep_v2_side,
            sweep_v2_min_trade_notional_quote=args.sweep_v2_min_trade_notional_quote,
            sweep_v2_min_intensity_bps=args.sweep_v2_min_intensity_bps,
            sweep_v2_max_pre_spread_bps=args.sweep_v2_max_pre_spread_bps,
            sweep_v2_max_reclaim_sec=args.sweep_v2_max_reclaim_sec,
            sweep_v2_event_cooldown_sec=args.sweep_v2_event_cooldown_sec,
            top_n=args.top_n,
            max_grid_combinations=args.max_grid_combinations,
            venue_costs_json=args.venue_costs_json,
            max_quote_age_sec=args.max_quote_age_sec,
        )
        return
    if args.command == "funding-scan":
        cmd_funding_scan(
            cfg,
            exchanges=args.exchanges,
            universe_path=args.universe,
            quote=args.quote,
            max_symbols=args.max_symbols,
            max_pairs_per_exchange=args.max_pairs_per_exchange,
            notional_quote=args.notional_quote,
            max_spot_spread_bps=args.max_spot_spread_bps,
            max_perp_spread_bps=args.max_perp_spread_bps,
            max_abs_basis_bps=args.max_abs_basis_bps,
            min_basis_bps=args.min_basis_bps,
            min_funding_rate=args.min_funding_rate,
            min_volume_24h_quote=args.min_volume_24h_quote,
            min_spot_top_notional_quote=args.min_spot_top_notional_quote,
            spot_fee_bps=args.spot_fee_bps,
            perp_fee_bps=args.perp_fee_bps,
            slippage_bps=args.slippage_bps,
            target_hold_intervals=args.target_hold_intervals,
            min_expected_net_carry_bps=args.min_expected_net_carry_bps,
            max_break_even_hours=args.max_break_even_hours,
            output_path=args.output,
        )
        return
    if args.command == "funding-coverage":
        cmd_funding_coverage(
            cfg,
            exchanges=args.exchanges,
            universe_path=args.universe,
            quote=args.quote,
            max_symbols=args.max_symbols,
            output_path=args.output,
            matched_universe_output_path=args.matched_universe_output,
        )
        return
    if args.command == "funding-collect":
        cmd_funding_collect(
            cfg,
            exchanges=args.exchanges,
            universe_path=args.universe,
            quote=args.quote,
            max_symbols=args.max_symbols,
            max_pairs_per_exchange=args.max_pairs_per_exchange,
            cycles=args.cycles,
            poll_interval_sec=args.poll_interval_sec,
            notional_quote=args.notional_quote,
            max_spot_spread_bps=args.max_spot_spread_bps,
            max_perp_spread_bps=args.max_perp_spread_bps,
            max_abs_basis_bps=args.max_abs_basis_bps,
            min_basis_bps=args.min_basis_bps,
            min_funding_rate=args.min_funding_rate,
            min_volume_24h_quote=args.min_volume_24h_quote,
            min_spot_top_notional_quote=args.min_spot_top_notional_quote,
            spot_fee_bps=args.spot_fee_bps,
            perp_fee_bps=args.perp_fee_bps,
            slippage_bps=args.slippage_bps,
            target_hold_intervals=args.target_hold_intervals,
            min_expected_net_carry_bps=args.min_expected_net_carry_bps,
            max_break_even_hours=args.max_break_even_hours,
            resume=args.resume,
            output_path=args.output,
        )
        return
    if args.command == "funding-status":
        cmd_funding_status(
            cfg,
            input_path=args.input,
            manifest_path=args.manifest,
            stale_after_sec=args.stale_after_sec,
            quality_min_rows=args.quality_min_rows,
            quality_min_markets=args.quality_min_markets,
            quality_min_completed_cycles=args.quality_min_completed_cycles,
            quality_min_unique_cycles=args.quality_min_unique_cycles,
            quality_min_avg_rows_per_cycle=args.quality_min_avg_rows_per_cycle,
            quality_min_min_rows_per_cycle=args.quality_min_min_rows_per_cycle,
            quality_max_error_rate=args.quality_max_error_rate,
            quality_max_cycle_market_duplicate_rate=args.quality_max_cycle_market_duplicate_rate,
            quality_required_row_fields=args.quality_required_row_fields,
            quality_min_required_row_field_presence=args.quality_min_required_row_field_presence,
        )
        return
    if args.command == "funding-collect-diagnostics":
        cmd_funding_collect_diagnostics(
            cfg,
            input_path=args.input,
            manifest_path=args.manifest,
            output_path=args.output,
            top_n=args.top_n,
            required_row_fields=args.required_row_fields,
        )
        return
    if args.command == "funding-wait-ready":
        cmd_funding_wait_ready(
            cfg,
            input_path=args.input,
            manifest_path=args.manifest,
            output_path=args.output,
            timeout_sec=args.timeout_sec,
            poll_interval_sec=args.poll_interval_sec,
            stale_after_sec=args.stale_after_sec,
            quality_min_rows=args.quality_min_rows,
            quality_min_markets=args.quality_min_markets,
            quality_min_completed_cycles=args.quality_min_completed_cycles,
            quality_min_unique_cycles=args.quality_min_unique_cycles,
            quality_min_avg_rows_per_cycle=args.quality_min_avg_rows_per_cycle,
            quality_min_min_rows_per_cycle=args.quality_min_min_rows_per_cycle,
            quality_max_error_rate=args.quality_max_error_rate,
            quality_max_cycle_market_duplicate_rate=args.quality_max_cycle_market_duplicate_rate,
            quality_required_row_fields=args.quality_required_row_fields,
            quality_min_required_row_field_presence=args.quality_min_required_row_field_presence,
        )
        return
    if args.command == "funding-rank":
        cmd_funding_rank(
            cfg,
            input_path=args.input,
            output_path=args.output,
            top_n=args.top_n,
            min_funding_observations=args.min_funding_observations,
            min_funding_positive_ratio=args.min_funding_positive_ratio,
            min_funding_persistence_score=args.min_funding_persistence_score,
            funding_persistence_weight=args.funding_persistence_weight,
            min_funding_rate=args.min_funding_rate,
            max_spot_spread_bps=args.max_spot_spread_bps,
            max_perp_spread_bps=args.max_perp_spread_bps,
            max_abs_basis_bps=args.max_abs_basis_bps,
            min_basis_bps=args.min_basis_bps,
            min_expected_net_carry_bps=args.min_expected_net_carry_bps,
            min_risk_adjusted_edge_bps=args.min_risk_adjusted_edge_bps,
            basis_risk_multiplier=args.basis_risk_multiplier,
            spread_risk_multiplier=args.spread_risk_multiplier,
            max_break_even_hours=args.max_break_even_hours,
            min_regime_observations=args.min_regime_observations,
            min_perp_volume_24h_quote=args.min_perp_volume_24h_quote,
            min_spot_top_notional_quote=args.min_spot_top_notional_quote,
            max_basis_std_bps=args.max_basis_std_bps,
            max_avg_spot_spread_bps=args.max_avg_spot_spread_bps,
            max_avg_perp_spread_bps=args.max_avg_perp_spread_bps,
        )
        return
    if args.command == "funding-gate-report":
        cmd_funding_gate_report(
            cfg,
            input_path=args.input,
            output_path=args.output,
            quality_universe_output_path=args.quality_universe_output,
            top_n=args.top_n,
            min_funding_observations=args.min_funding_observations,
            min_funding_positive_ratio=args.min_funding_positive_ratio,
            min_funding_persistence_score=args.min_funding_persistence_score,
            funding_persistence_weight=args.funding_persistence_weight,
            min_funding_rate=args.min_funding_rate,
            max_spot_spread_bps=args.max_spot_spread_bps,
            max_perp_spread_bps=args.max_perp_spread_bps,
            max_abs_basis_bps=args.max_abs_basis_bps,
            min_basis_bps=args.min_basis_bps,
            min_expected_net_carry_bps=args.min_expected_net_carry_bps,
            min_risk_adjusted_edge_bps=args.min_risk_adjusted_edge_bps,
            basis_risk_multiplier=args.basis_risk_multiplier,
            spread_risk_multiplier=args.spread_risk_multiplier,
            max_break_even_hours=args.max_break_even_hours,
            min_regime_observations=args.min_regime_observations,
            min_perp_volume_24h_quote=args.min_perp_volume_24h_quote,
            min_spot_top_notional_quote=args.min_spot_top_notional_quote,
            max_basis_std_bps=args.max_basis_std_bps,
            max_avg_spot_spread_bps=args.max_avg_spot_spread_bps,
            max_avg_perp_spread_bps=args.max_avg_perp_spread_bps,
        )
        return
    if args.command == "funding-regime-report":
        cmd_funding_regime_report(
            cfg,
            input_path=args.input,
            output_path=args.output,
            top_n=args.top_n,
            min_funding_observations=args.min_funding_observations,
            min_funding_positive_ratio=args.min_funding_positive_ratio,
            min_funding_persistence_score=args.min_funding_persistence_score,
            funding_persistence_weight=args.funding_persistence_weight,
            min_funding_rate=args.min_funding_rate,
            max_spot_spread_bps=args.max_spot_spread_bps,
            max_perp_spread_bps=args.max_perp_spread_bps,
            max_abs_basis_bps=args.max_abs_basis_bps,
            min_basis_bps=args.min_basis_bps,
            min_expected_net_carry_bps=args.min_expected_net_carry_bps,
            min_risk_adjusted_edge_bps=args.min_risk_adjusted_edge_bps,
            basis_risk_multiplier=args.basis_risk_multiplier,
            spread_risk_multiplier=args.spread_risk_multiplier,
            max_break_even_hours=args.max_break_even_hours,
            min_regime_observations=args.min_regime_observations,
            min_perp_volume_24h_quote=args.min_perp_volume_24h_quote,
            min_spot_top_notional_quote=args.min_spot_top_notional_quote,
            max_basis_std_bps=args.max_basis_std_bps,
            max_avg_spot_spread_bps=args.max_avg_spot_spread_bps,
            max_avg_perp_spread_bps=args.max_avg_perp_spread_bps,
        )
        return
    if args.command == "funding-frontier-report":
        cmd_funding_frontier_report(
            cfg,
            input_path=args.input,
            output_path=args.output,
            top_n=args.top_n,
            min_funding_observations=args.min_funding_observations,
            min_funding_positive_ratio=args.min_funding_positive_ratio,
            min_funding_persistence_score=args.min_funding_persistence_score,
            funding_persistence_weight=args.funding_persistence_weight,
            min_funding_rate=args.min_funding_rate,
            max_spot_spread_bps=args.max_spot_spread_bps,
            max_perp_spread_bps=args.max_perp_spread_bps,
            max_abs_basis_bps=args.max_abs_basis_bps,
            min_basis_bps=args.min_basis_bps,
            min_expected_net_carry_bps=args.min_expected_net_carry_bps,
            min_risk_adjusted_edge_bps=args.min_risk_adjusted_edge_bps,
            basis_risk_multiplier=args.basis_risk_multiplier,
            spread_risk_multiplier=args.spread_risk_multiplier,
            max_break_even_hours=args.max_break_even_hours,
            min_regime_observations=args.min_regime_observations,
            min_perp_volume_24h_quote=args.min_perp_volume_24h_quote,
            min_spot_top_notional_quote=args.min_spot_top_notional_quote,
            max_basis_std_bps=args.max_basis_std_bps,
            max_avg_spot_spread_bps=args.max_avg_spot_spread_bps,
            max_avg_perp_spread_bps=args.max_avg_perp_spread_bps,
        )
        return
    if args.command == "funding-decision-report":
        cmd_funding_decision_report(
            cfg,
            input_path=args.input,
            manifest_path=args.manifest,
            postprocess_report_path=args.postprocess_report,
            gate_report_path=args.gate_report,
            regime_report_path=args.regime_report,
            frontier_report_path=args.frontier_report,
            sensitivity_report_path=args.sensitivity_report,
            output_path=args.output,
            stale_after_sec=args.stale_after_sec,
            quality_min_rows=args.quality_min_rows,
            quality_min_markets=args.quality_min_markets,
            quality_min_completed_cycles=args.quality_min_completed_cycles,
            quality_min_unique_cycles=args.quality_min_unique_cycles,
            quality_min_avg_rows_per_cycle=args.quality_min_avg_rows_per_cycle,
            quality_min_min_rows_per_cycle=args.quality_min_min_rows_per_cycle,
            quality_max_error_rate=args.quality_max_error_rate,
            quality_max_cycle_market_duplicate_rate=args.quality_max_cycle_market_duplicate_rate,
            quality_required_row_fields=args.quality_required_row_fields,
            quality_min_required_row_field_presence=args.quality_min_required_row_field_presence,
        )
        return
    if args.command == "funding-progress-report":
        cmd_funding_progress_report(
            cfg,
            input_path=args.input,
            manifest_path=args.manifest,
            output_path=args.output,
            top_n=args.top_n,
            min_funding_observations=args.min_funding_observations,
            min_funding_positive_ratio=args.min_funding_positive_ratio,
            min_funding_persistence_score=args.min_funding_persistence_score,
            funding_persistence_weight=args.funding_persistence_weight,
            min_funding_rate=args.min_funding_rate,
            max_spot_spread_bps=args.max_spot_spread_bps,
            max_perp_spread_bps=args.max_perp_spread_bps,
            max_abs_basis_bps=args.max_abs_basis_bps,
            min_basis_bps=args.min_basis_bps,
            min_expected_net_carry_bps=args.min_expected_net_carry_bps,
            min_risk_adjusted_edge_bps=args.min_risk_adjusted_edge_bps,
            basis_risk_multiplier=args.basis_risk_multiplier,
            spread_risk_multiplier=args.spread_risk_multiplier,
            max_break_even_hours=args.max_break_even_hours,
            min_regime_observations=args.min_regime_observations,
            min_perp_volume_24h_quote=args.min_perp_volume_24h_quote,
            min_spot_top_notional_quote=args.min_spot_top_notional_quote,
            max_basis_std_bps=args.max_basis_std_bps,
            max_avg_spot_spread_bps=args.max_avg_spot_spread_bps,
            max_avg_perp_spread_bps=args.max_avg_perp_spread_bps,
        )
        return
    if args.command == "funding-backtest":
        cmd_funding_backtest(
            cfg,
            input_path=args.input,
            output_path=args.output,
            notional_quote=args.notional_quote,
            spot_fee_bps=args.spot_fee_bps,
            perp_fee_bps=args.perp_fee_bps,
            slippage_bps=args.slippage_bps,
            min_funding_rate=args.min_funding_rate,
            min_total_score=args.min_total_score,
            max_spot_spread_bps=args.max_spot_spread_bps,
            max_perp_spread_bps=args.max_perp_spread_bps,
            max_abs_basis_bps=args.max_abs_basis_bps,
            min_basis_bps=args.min_basis_bps,
            min_expected_net_carry_bps=args.min_expected_net_carry_bps,
            min_risk_adjusted_edge_bps=args.min_risk_adjusted_edge_bps,
            basis_risk_multiplier=args.basis_risk_multiplier,
            spread_risk_multiplier=args.spread_risk_multiplier,
            max_break_even_hours=args.max_break_even_hours,
            min_funding_observations=args.min_funding_observations,
            min_funding_positive_ratio=args.min_funding_positive_ratio,
            min_funding_persistence_score=args.min_funding_persistence_score,
            min_regime_observations=args.min_regime_observations,
            min_perp_volume_24h_quote=args.min_perp_volume_24h_quote,
            min_spot_top_notional_quote=args.min_spot_top_notional_quote,
            max_basis_std_bps=args.max_basis_std_bps,
            max_avg_spot_spread_bps=args.max_avg_spot_spread_bps,
            max_avg_perp_spread_bps=args.max_avg_perp_spread_bps,
            venue_costs_json=args.venue_costs_json,
        )
        return
    if args.command == "funding-sensitivity":
        cmd_funding_sensitivity(
            cfg,
            input_path=args.input,
            output_path=args.output,
            spot_fee_bps_list=args.spot_fee_bps_list,
            perp_fee_bps_list=args.perp_fee_bps_list,
            slippage_bps_list=args.slippage_bps_list,
            target_hold_intervals_list=args.target_hold_intervals_list,
            max_break_even_hours_list=args.max_break_even_hours_list,
            top_n=args.top_n,
            notional_quote=args.notional_quote,
            min_funding_rate=args.min_funding_rate,
            min_total_score=args.min_total_score,
            max_spot_spread_bps=args.max_spot_spread_bps,
            max_perp_spread_bps=args.max_perp_spread_bps,
            max_abs_basis_bps=args.max_abs_basis_bps,
            min_basis_bps=args.min_basis_bps,
            min_expected_net_carry_bps=args.min_expected_net_carry_bps,
            min_risk_adjusted_edge_bps=args.min_risk_adjusted_edge_bps,
            basis_risk_multiplier=args.basis_risk_multiplier,
            spread_risk_multiplier=args.spread_risk_multiplier,
            min_funding_observations=args.min_funding_observations,
            min_funding_positive_ratio=args.min_funding_positive_ratio,
            min_funding_persistence_score=args.min_funding_persistence_score,
            min_regime_observations=args.min_regime_observations,
            min_perp_volume_24h_quote=args.min_perp_volume_24h_quote,
            min_spot_top_notional_quote=args.min_spot_top_notional_quote,
            max_basis_std_bps=args.max_basis_std_bps,
            max_avg_spot_spread_bps=args.max_avg_spot_spread_bps,
            max_avg_perp_spread_bps=args.max_avg_perp_spread_bps,
            accept_min_trades=args.accept_min_trades,
            accept_min_win_rate=args.accept_min_win_rate,
            accept_min_expectancy_quote=args.accept_min_expectancy_quote,
            accept_min_net_pnl_quote=args.accept_min_net_pnl_quote,
            accept_max_drawdown_quote=args.accept_max_drawdown_quote,
            accept_min_profit_factor=args.accept_min_profit_factor,
            accept_min_markets=args.accept_min_markets,
            accept_max_market_trade_share=args.accept_max_market_trade_share,
            accept_min_exchanges=args.accept_min_exchanges,
            accept_max_exchange_trade_share=args.accept_max_exchange_trade_share,
            accept_min_profitable_windows=args.accept_min_profitable_windows,
            accept_max_window_pnl_share=args.accept_max_window_pnl_share,
            stress_enabled=args.stress_enabled,
            stress_adverse_basis_bps=args.stress_adverse_basis_bps,
            stress_spread_widen_bps=args.stress_spread_widen_bps,
            stress_funding_flip_bps=args.stress_funding_flip_bps,
            stress_min_net_pnl_quote=args.stress_min_net_pnl_quote,
            stress_max_drawdown_quote=args.stress_max_drawdown_quote,
            sensitivity_oos=args.sensitivity_oos,
            oos_train_fraction=args.oos_train_fraction,
            oos_min_train_rows=args.oos_min_train_rows,
            oos_min_rows=args.oos_min_rows,
            oos_min_train_span_hours=args.oos_min_train_span_hours,
            oos_min_span_hours=args.oos_min_span_hours,
            sensitivity_walk_forward=args.sensitivity_walk_forward,
            walk_train_rows=args.walk_train_rows,
            walk_test_rows=args.walk_test_rows,
            walk_step_rows=args.walk_step_rows,
            walk_min_windows=args.walk_min_windows,
            walk_min_accepted_windows=args.walk_min_accepted_windows,
            walk_min_accepted_ratio=args.walk_min_accepted_ratio,
            walk_min_train_span_hours=args.walk_min_train_span_hours,
            walk_min_test_span_hours=args.walk_min_test_span_hours,
        )
        return
    if args.command == "funding-oos-backtest":
        cmd_funding_oos_backtest(
            cfg,
            input_path=args.input,
            output_path=args.output,
            notional_quote=args.notional_quote,
            spot_fee_bps=args.spot_fee_bps,
            perp_fee_bps=args.perp_fee_bps,
            slippage_bps=args.slippage_bps,
            min_funding_rate=args.min_funding_rate,
            min_total_score=args.min_total_score,
            max_spot_spread_bps=args.max_spot_spread_bps,
            max_perp_spread_bps=args.max_perp_spread_bps,
            max_abs_basis_bps=args.max_abs_basis_bps,
            min_basis_bps=args.min_basis_bps,
            min_expected_net_carry_bps=args.min_expected_net_carry_bps,
            min_risk_adjusted_edge_bps=args.min_risk_adjusted_edge_bps,
            basis_risk_multiplier=args.basis_risk_multiplier,
            spread_risk_multiplier=args.spread_risk_multiplier,
            max_break_even_hours=args.max_break_even_hours,
            min_funding_observations=args.min_funding_observations,
            min_funding_positive_ratio=args.min_funding_positive_ratio,
            min_funding_persistence_score=args.min_funding_persistence_score,
            min_regime_observations=args.min_regime_observations,
            min_perp_volume_24h_quote=args.min_perp_volume_24h_quote,
            min_spot_top_notional_quote=args.min_spot_top_notional_quote,
            max_basis_std_bps=args.max_basis_std_bps,
            max_avg_spot_spread_bps=args.max_avg_spot_spread_bps,
            max_avg_perp_spread_bps=args.max_avg_perp_spread_bps,
            train_fraction=args.train_fraction,
            min_train_rows=args.min_train_rows,
            min_oos_rows=args.min_oos_rows,
            min_train_span_hours=args.min_train_span_hours,
            min_oos_span_hours=args.min_oos_span_hours,
            accept_min_trades=args.accept_min_trades,
            accept_min_win_rate=args.accept_min_win_rate,
            accept_min_expectancy_quote=args.accept_min_expectancy_quote,
            accept_min_net_pnl_quote=args.accept_min_net_pnl_quote,
            accept_max_drawdown_quote=args.accept_max_drawdown_quote,
            accept_min_profit_factor=args.accept_min_profit_factor,
            accept_min_markets=args.accept_min_markets,
            accept_max_market_trade_share=args.accept_max_market_trade_share,
            accept_min_exchanges=args.accept_min_exchanges,
            accept_max_exchange_trade_share=args.accept_max_exchange_trade_share,
            accept_min_profitable_windows=args.accept_min_profitable_windows,
            accept_max_window_pnl_share=args.accept_max_window_pnl_share,
            stress_enabled=args.stress_enabled,
            stress_adverse_basis_bps=args.stress_adverse_basis_bps,
            stress_spread_widen_bps=args.stress_spread_widen_bps,
            stress_funding_flip_bps=args.stress_funding_flip_bps,
            stress_min_net_pnl_quote=args.stress_min_net_pnl_quote,
            stress_max_drawdown_quote=args.stress_max_drawdown_quote,
        )
        return
    if args.command == "funding-walk-forward":
        cmd_funding_walk_forward(
            cfg,
            input_path=args.input,
            output_path=args.output,
            notional_quote=args.notional_quote,
            spot_fee_bps=args.spot_fee_bps,
            perp_fee_bps=args.perp_fee_bps,
            slippage_bps=args.slippage_bps,
            min_funding_rate=args.min_funding_rate,
            min_total_score=args.min_total_score,
            max_spot_spread_bps=args.max_spot_spread_bps,
            max_perp_spread_bps=args.max_perp_spread_bps,
            max_abs_basis_bps=args.max_abs_basis_bps,
            min_basis_bps=args.min_basis_bps,
            min_expected_net_carry_bps=args.min_expected_net_carry_bps,
            min_risk_adjusted_edge_bps=args.min_risk_adjusted_edge_bps,
            basis_risk_multiplier=args.basis_risk_multiplier,
            spread_risk_multiplier=args.spread_risk_multiplier,
            max_break_even_hours=args.max_break_even_hours,
            min_funding_observations=args.min_funding_observations,
            min_funding_positive_ratio=args.min_funding_positive_ratio,
            min_funding_persistence_score=args.min_funding_persistence_score,
            min_regime_observations=args.min_regime_observations,
            min_perp_volume_24h_quote=args.min_perp_volume_24h_quote,
            min_spot_top_notional_quote=args.min_spot_top_notional_quote,
            max_basis_std_bps=args.max_basis_std_bps,
            max_avg_spot_spread_bps=args.max_avg_spot_spread_bps,
            max_avg_perp_spread_bps=args.max_avg_perp_spread_bps,
            walk_train_rows=args.walk_train_rows,
            walk_test_rows=args.walk_test_rows,
            walk_step_rows=args.walk_step_rows,
            walk_min_windows=args.walk_min_windows,
            walk_min_accepted_windows=args.walk_min_accepted_windows,
            walk_min_accepted_ratio=args.walk_min_accepted_ratio,
            walk_min_train_span_hours=args.walk_min_train_span_hours,
            walk_min_test_span_hours=args.walk_min_test_span_hours,
            accept_min_trades=args.accept_min_trades,
            accept_min_win_rate=args.accept_min_win_rate,
            accept_min_expectancy_quote=args.accept_min_expectancy_quote,
            accept_min_net_pnl_quote=args.accept_min_net_pnl_quote,
            accept_max_drawdown_quote=args.accept_max_drawdown_quote,
            accept_min_profit_factor=args.accept_min_profit_factor,
            accept_min_markets=args.accept_min_markets,
            accept_max_market_trade_share=args.accept_max_market_trade_share,
            accept_min_exchanges=args.accept_min_exchanges,
            accept_max_exchange_trade_share=args.accept_max_exchange_trade_share,
            accept_min_profitable_windows=args.accept_min_profitable_windows,
            accept_max_window_pnl_share=args.accept_max_window_pnl_share,
            stress_enabled=args.stress_enabled,
            stress_adverse_basis_bps=args.stress_adverse_basis_bps,
            stress_spread_widen_bps=args.stress_spread_widen_bps,
            stress_funding_flip_bps=args.stress_funding_flip_bps,
            stress_min_net_pnl_quote=args.stress_min_net_pnl_quote,
            stress_max_drawdown_quote=args.stress_max_drawdown_quote,
        )
        return
    if args.command == "funding-postprocess":
        cmd_funding_postprocess(
            cfg,
            input_path=args.input,
            manifest_path=args.manifest,
            rank_output_path=args.rank_output,
            backtest_output_path=args.backtest_output,
            oos_output_path=args.oos_output,
            walk_forward_output_path=args.walk_forward_output,
            postprocess_output_path=args.postprocess_output,
            allow_partial=args.allow_partial,
            top_n=args.top_n,
            min_funding_observations=args.min_funding_observations,
            min_funding_positive_ratio=args.min_funding_positive_ratio,
            min_funding_persistence_score=args.min_funding_persistence_score,
            funding_persistence_weight=args.funding_persistence_weight,
            notional_quote=args.notional_quote,
            spot_fee_bps=args.spot_fee_bps,
            perp_fee_bps=args.perp_fee_bps,
            slippage_bps=args.slippage_bps,
            min_funding_rate=args.min_funding_rate,
            min_total_score=args.min_total_score,
            max_spot_spread_bps=args.max_spot_spread_bps,
            max_perp_spread_bps=args.max_perp_spread_bps,
            max_abs_basis_bps=args.max_abs_basis_bps,
            min_basis_bps=args.min_basis_bps,
            min_expected_net_carry_bps=args.min_expected_net_carry_bps,
            min_risk_adjusted_edge_bps=args.min_risk_adjusted_edge_bps,
            basis_risk_multiplier=args.basis_risk_multiplier,
            spread_risk_multiplier=args.spread_risk_multiplier,
            max_break_even_hours=args.max_break_even_hours,
            min_regime_observations=args.min_regime_observations,
            min_perp_volume_24h_quote=args.min_perp_volume_24h_quote,
            min_spot_top_notional_quote=args.min_spot_top_notional_quote,
            max_basis_std_bps=args.max_basis_std_bps,
            max_avg_spot_spread_bps=args.max_avg_spot_spread_bps,
            max_avg_perp_spread_bps=args.max_avg_perp_spread_bps,
            accept_min_trades=args.accept_min_trades,
            accept_min_win_rate=args.accept_min_win_rate,
            accept_min_expectancy_quote=args.accept_min_expectancy_quote,
            accept_min_net_pnl_quote=args.accept_min_net_pnl_quote,
            accept_max_drawdown_quote=args.accept_max_drawdown_quote,
            accept_min_profit_factor=args.accept_min_profit_factor,
            accept_min_markets=args.accept_min_markets,
            accept_max_market_trade_share=args.accept_max_market_trade_share,
            accept_min_exchanges=args.accept_min_exchanges,
            accept_max_exchange_trade_share=args.accept_max_exchange_trade_share,
            accept_min_profitable_windows=args.accept_min_profitable_windows,
            accept_max_window_pnl_share=args.accept_max_window_pnl_share,
            stress_enabled=args.stress_enabled,
            stress_adverse_basis_bps=args.stress_adverse_basis_bps,
            stress_spread_widen_bps=args.stress_spread_widen_bps,
            stress_funding_flip_bps=args.stress_funding_flip_bps,
            stress_min_net_pnl_quote=args.stress_min_net_pnl_quote,
            stress_max_drawdown_quote=args.stress_max_drawdown_quote,
            oos_train_fraction=args.oos_train_fraction,
            oos_min_train_rows=args.oos_min_train_rows,
            oos_min_rows=args.oos_min_rows,
            oos_min_train_span_hours=args.oos_min_train_span_hours,
            oos_min_span_hours=args.oos_min_span_hours,
            walk_train_rows=args.walk_train_rows,
            walk_test_rows=args.walk_test_rows,
            walk_step_rows=args.walk_step_rows,
            walk_min_windows=args.walk_min_windows,
            walk_min_accepted_windows=args.walk_min_accepted_windows,
            walk_min_accepted_ratio=args.walk_min_accepted_ratio,
            walk_min_train_span_hours=args.walk_min_train_span_hours,
            walk_min_test_span_hours=args.walk_min_test_span_hours,
            quality_min_rows=args.quality_min_rows,
            quality_min_markets=args.quality_min_markets,
            quality_min_completed_cycles=args.quality_min_completed_cycles,
            quality_min_unique_cycles=args.quality_min_unique_cycles,
            quality_min_avg_rows_per_cycle=args.quality_min_avg_rows_per_cycle,
            quality_min_min_rows_per_cycle=args.quality_min_min_rows_per_cycle,
            quality_max_error_rate=args.quality_max_error_rate,
            quality_max_cycle_market_duplicate_rate=args.quality_max_cycle_market_duplicate_rate,
            quality_required_row_fields=args.quality_required_row_fields,
            quality_min_required_row_field_presence=args.quality_min_required_row_field_presence,
        )
        return
    if args.command == "funding-finalize":
        cmd_funding_finalize(
            cfg,
            input_path=args.input,
            manifest_path=args.manifest,
            rank_output_path=args.rank_output,
            backtest_output_path=args.backtest_output,
            oos_output_path=args.oos_output,
            walk_forward_output_path=args.walk_forward_output,
            postprocess_output_path=args.postprocess_output,
            paper_plan_output_path=args.paper_plan_output,
            paper_output_path=args.paper_output,
            top_n=args.top_n,
            min_funding_observations=args.min_funding_observations,
            min_funding_positive_ratio=args.min_funding_positive_ratio,
            min_funding_persistence_score=args.min_funding_persistence_score,
            funding_persistence_weight=args.funding_persistence_weight,
            notional_quote=args.notional_quote,
            spot_fee_bps=args.spot_fee_bps,
            perp_fee_bps=args.perp_fee_bps,
            slippage_bps=args.slippage_bps,
            min_funding_rate=args.min_funding_rate,
            min_total_score=args.min_total_score,
            max_spot_spread_bps=args.max_spot_spread_bps,
            max_perp_spread_bps=args.max_perp_spread_bps,
            max_abs_basis_bps=args.max_abs_basis_bps,
            min_basis_bps=args.min_basis_bps,
            min_expected_net_carry_bps=args.min_expected_net_carry_bps,
            min_risk_adjusted_edge_bps=args.min_risk_adjusted_edge_bps,
            basis_risk_multiplier=args.basis_risk_multiplier,
            spread_risk_multiplier=args.spread_risk_multiplier,
            max_break_even_hours=args.max_break_even_hours,
            min_regime_observations=args.min_regime_observations,
            min_perp_volume_24h_quote=args.min_perp_volume_24h_quote,
            min_spot_top_notional_quote=args.min_spot_top_notional_quote,
            max_basis_std_bps=args.max_basis_std_bps,
            max_avg_spot_spread_bps=args.max_avg_spot_spread_bps,
            max_avg_perp_spread_bps=args.max_avg_perp_spread_bps,
            accept_min_trades=args.accept_min_trades,
            accept_min_win_rate=args.accept_min_win_rate,
            accept_min_expectancy_quote=args.accept_min_expectancy_quote,
            accept_min_net_pnl_quote=args.accept_min_net_pnl_quote,
            accept_max_drawdown_quote=args.accept_max_drawdown_quote,
            accept_min_profit_factor=args.accept_min_profit_factor,
            accept_min_markets=args.accept_min_markets,
            accept_max_market_trade_share=args.accept_max_market_trade_share,
            accept_min_exchanges=args.accept_min_exchanges,
            accept_max_exchange_trade_share=args.accept_max_exchange_trade_share,
            accept_min_profitable_windows=args.accept_min_profitable_windows,
            accept_max_window_pnl_share=args.accept_max_window_pnl_share,
            stress_enabled=args.stress_enabled,
            stress_adverse_basis_bps=args.stress_adverse_basis_bps,
            stress_spread_widen_bps=args.stress_spread_widen_bps,
            stress_funding_flip_bps=args.stress_funding_flip_bps,
            stress_min_net_pnl_quote=args.stress_min_net_pnl_quote,
            stress_max_drawdown_quote=args.stress_max_drawdown_quote,
            oos_train_fraction=args.oos_train_fraction,
            oos_min_train_rows=args.oos_min_train_rows,
            oos_min_rows=args.oos_min_rows,
            oos_min_train_span_hours=args.oos_min_train_span_hours,
            oos_min_span_hours=args.oos_min_span_hours,
            walk_train_rows=args.walk_train_rows,
            walk_test_rows=args.walk_test_rows,
            walk_step_rows=args.walk_step_rows,
            walk_min_windows=args.walk_min_windows,
            walk_min_accepted_windows=args.walk_min_accepted_windows,
            walk_min_accepted_ratio=args.walk_min_accepted_ratio,
            walk_min_train_span_hours=args.walk_min_train_span_hours,
            walk_min_test_span_hours=args.walk_min_test_span_hours,
            quality_min_rows=args.quality_min_rows,
            quality_min_markets=args.quality_min_markets,
            quality_min_completed_cycles=args.quality_min_completed_cycles,
            quality_min_unique_cycles=args.quality_min_unique_cycles,
            quality_min_avg_rows_per_cycle=args.quality_min_avg_rows_per_cycle,
            quality_min_min_rows_per_cycle=args.quality_min_min_rows_per_cycle,
            quality_max_error_rate=args.quality_max_error_rate,
            quality_max_cycle_market_duplicate_rate=args.quality_max_cycle_market_duplicate_rate,
            quality_required_row_fields=args.quality_required_row_fields,
            quality_min_required_row_field_presence=args.quality_min_required_row_field_presence,
            min_forward_hours=args.min_forward_hours,
            min_forward_rows=args.min_forward_rows,
            min_forward_markets=args.min_forward_markets,
        )
        return
    if args.command == "funding-final-review":
        cmd_funding_final_review(cfg, args)
        return
    if args.command == "funding-paper-plan":
        cmd_funding_paper_plan(
            cfg,
            postprocess_path=args.postprocess,
            decision_report_path=args.decision_report,
            output_path=args.output,
            paper_output_path=args.paper_output,
            min_forward_hours=args.min_forward_hours,
            min_forward_rows=args.min_forward_rows,
            min_forward_markets=args.min_forward_markets,
        )
        return
    if args.command == "funding-paper-forward":
        cmd_funding_paper_forward(
            cfg,
            plan_path=args.plan,
            input_path=args.input,
            output_path=args.output,
            summary_output_path=args.summary_output,
            allow_source_input=args.allow_source_input,
        )
        return
    if args.command == "funding-paper-decision-report":
        cmd_funding_paper_decision_report(
            cfg,
            summary_path=args.summary,
            plan_path=args.plan,
            output_path=args.output,
        )
        return
    if args.command == "funding-goal-audit":
        cmd_funding_goal_audit(
            cfg,
            input_path=args.input,
            manifest_path=args.manifest,
            final_review_path=args.final_review,
            paper_plan_path=args.paper_plan,
            paper_summary_path=args.paper_summary,
            paper_decision_path=args.paper_decision,
            output_path=args.output,
            stale_after_sec=args.stale_after_sec,
            quality_min_rows=args.quality_min_rows,
            quality_min_markets=args.quality_min_markets,
            quality_min_completed_cycles=args.quality_min_completed_cycles,
            quality_min_unique_cycles=args.quality_min_unique_cycles,
            quality_min_avg_rows_per_cycle=args.quality_min_avg_rows_per_cycle,
            quality_min_min_rows_per_cycle=args.quality_min_min_rows_per_cycle,
            quality_max_error_rate=args.quality_max_error_rate,
            quality_max_cycle_market_duplicate_rate=args.quality_max_cycle_market_duplicate_rate,
            quality_required_row_fields=args.quality_required_row_fields,
            quality_min_required_row_field_presence=args.quality_min_required_row_field_presence,
        )
        return
    if args.command == "fast-edge-v4-validate":
        result = validate_funding_pressure_readiness(
            args.plan,
            expected_plan_hash=args.expected_plan_hash,
        )
        if args.output:
            target = Path(args.output).expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".tmp")
            temporary.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(target)
        print(json.dumps(result, ensure_ascii=False))
        return
    if args.command == "fast-edge-v4-evaluate":
        readiness = validate_funding_pressure_readiness(
            args.plan,
            expected_plan_hash=args.expected_plan_hash,
        )
        if readiness["status"] != "FAST_FIRST_V4_EVALUATOR_READY_OOS_NOT_RUN":
            raise RuntimeError("Fast-First v4 evaluator readiness failed")
        result = evaluate_funding_pressure_plan(args.plan, output_path=args.output)
        print(
            json.dumps(
                {
                    "artifact_path": result["artifact_path"],
                    "plan_hash": result["plan_hash"],
                    "verdict": result["verdict"],
                    "deterministic_result_hash": result["deterministic_result_hash"],
                },
                ensure_ascii=False,
            )
        )
        return
    if args.command == "fast-edge-v5-validate":
        result = validate_wick_rejection_readiness(
            args.plan,
            expected_plan_hash=args.expected_plan_hash,
        )
        if args.output:
            target = Path(args.output).expanduser().resolve()
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".tmp")
            temporary.write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            temporary.replace(target)
        print(json.dumps(result, ensure_ascii=False))
        return
    if args.command == "fast-edge-v5-evaluate":
        readiness = validate_wick_rejection_readiness(
            args.plan,
            expected_plan_hash=args.expected_plan_hash,
        )
        if readiness["status"] != "FAST_FIRST_V5_EVALUATOR_READY_OOS_NOT_RUN":
            raise RuntimeError("Fast-First v5 evaluator readiness failed")
        result = evaluate_wick_rejection_plan(args.plan, output_path=args.output)
        print(
            json.dumps(
                {
                    "artifact_path": result["artifact_path"],
                    "plan_hash": result["plan_hash"],
                    "verdict": result["verdict"],
                    "deterministic_result_hash": result["deterministic_result_hash"],
                },
                ensure_ascii=False,
            )
        )
        return
    if args.command == "setup-registry":
        cmd_setup_registry(cfg, output_path=args.output)
        return
    if args.command == "experiment-record":
        cmd_experiment_record(
            cfg,
            source_video_id=args.source_video_id,
            source_url=args.source_url,
            source_channel=args.source_channel,
            participant=args.participant,
            claim_family=args.claim_family,
            hypothesis=args.hypothesis,
            setup_id=args.setup_id,
            dataset=args.dataset,
            config_json=args.config_json,
            result_path=args.result_path,
            metrics_json=args.metrics_json,
            verdict=args.verdict,
            verdict_reason=args.verdict_reason,
            tags=args.tags,
            notes=args.notes,
            fee_schedule_revision=args.fee_schedule_revision,
            evaluation_scope=args.evaluation_scope,
            oos_status=args.oos_status,
            output_path=args.output,
        )
        return
    if args.command == "experiment-list":
        cmd_experiment_list(
            cfg,
            input_path=args.input,
            verdict=args.verdict,
            setup_id=args.setup_id,
            top_n=args.top_n,
            output_path=args.output,
        )
        return
    raise RuntimeError(f"Неизвестная команда: {args.command}")


if __name__ == "__main__":
    main()
