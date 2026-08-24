import argparse
import json
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List

def _epoch_seconds(ts_ms: Any) -> float:
    return float(ts_ms) / 1000.0

def fetch_mexc_historical_trades(symbol: str, start_ts: float, end_ts: float) -> List[dict]:
    symbol_formatted = symbol.replace("_", "").upper()
    start_ms = int(start_ts * 1000)
    end_ms = int(end_ts * 1000)
    url = f"https://api.mexc.com/api/v3/aggTrades?symbol={symbol_formatted}&startTime={start_ms}&endTime={end_ms}&limit=1000"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            trades = []
            for item in data:
                trades.append({
                    "event_kind": "trade",
                    "exchange": "mexc",
                    "symbol": symbol,
                    "trade_id": str(item.get("a", "")),
                    "price": float(item.get("p", 0.0)),
                    "qty": float(item.get("q", 0.0)),
                    "side": "sell" if item.get("m") else "buy",
                    "exchange_ts": float(item.get("T", 0)) / 1000.0,
                    "recv_ts": time.time(),
                    "channel": "rest_backfill"
                })
            return trades
    except Exception as e:
        print(f"Error fetching MEXC trades for {symbol}: {e}")
        return []

def fetch_gate_historical_trades(symbol: str, start_ts: float, end_ts: float) -> List[dict]:
    symbol_formatted = symbol.replace("-", "_").upper()
    start_s = int(start_ts)
    end_s = int(end_ts)
    url = f"https://api.gateio.ws/api/v4/spot/trades?currency_pair={symbol_formatted}&from={start_s}&to={end_s}&limit=1000"
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            trades = []
            for item in data:
                trades.append({
                    "event_kind": "trade",
                    "exchange": "gateio",
                    "symbol": symbol,
                    "trade_id": str(item.get("id", "")),
                    "price": float(item.get("price", 0.0)),
                    "qty": float(item.get("amount", 0.0)),
                    "side": str(item.get("side", "buy")).lower(),
                    "exchange_ts": float(item.get("create_time_ms", 0)) / 1000.0,
                    "recv_ts": time.time(),
                    "channel": "rest_backfill"
                })
            return trades
    except Exception as e:
        print(f"Error fetching Gate trades for {symbol}: {e}")
        return []

def backfill_gaps(gap_report_path: Path, output_file: Path) -> dict:
    report = json.loads(gap_report_path.read_text(encoding="utf-8"))
    top_gaps = report.get("top_market_kind_gaps", [])
    
    total_fetched = 0
    with output_file.open("a", encoding="utf-8") as out:
        for gap in top_gaps:
            key = gap.get("key", "")
            if not key.endswith(":trade"):
                continue
            
            parts = key.split(":")
            if len(parts) < 3:
                continue
            exchange = parts[0]
            symbol = parts[1]
            
            start_ts = gap.get("max_gap_start_ts")
            end_ts = gap.get("max_gap_end_ts")
            
            if not start_ts or not end_ts:
                continue
            
            print(f"Backfilling {exchange} {symbol} from {start_ts} to {end_ts}...")
            trades = []
            if exchange == "mexc":
                trades = fetch_mexc_historical_trades(symbol, start_ts, end_ts)
            elif exchange == "gateio":
                trades = fetch_gate_historical_trades(symbol, start_ts, end_ts)
            
            for trade in trades:
                out.write(json.dumps(trade, ensure_ascii=False) + "\n")
                total_fetched += 1
                
            time.sleep(0.5)
            
    return {"status": "success", "total_fetched_trades": total_fetched}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-report", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    
    result = backfill_gaps(Path(args.audit_report), Path(args.output))
    print(json.dumps(result))

if __name__ == "__main__":
    main()
