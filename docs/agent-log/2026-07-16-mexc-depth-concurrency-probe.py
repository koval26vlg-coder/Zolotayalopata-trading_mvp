from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC = PROJECT_ROOT / "trading_mvp" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from pit_universe_public_probe import run_public_probe, write_report  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Isolated MEXC depth concurrency verifier")
    parser.add_argument("--output", required=True)
    parser.add_argument("--timeout-sec", type=int, default=10)
    args = parser.parse_args()

    output_path = Path(args.output)
    report = run_public_probe(
        output_path=output_path,
        min_contracts_per_exchange=50,
        timeout_sec=args.timeout_sec,
        include_mexc_depth=True,
    )
    write_report(report, output_path)
    depth = report["summary"]["mexc_depth"]
    summary = {
        "decision": report["decision"],
        "targets": depth["targets"],
        "complete": depth["complete"],
        "missing": depth["missing"],
        "coverage": depth["coverage"],
        "minimum_required_coverage": depth["minimum_required_coverage"],
        "depth_error_count": len(report["depth_errors"]),
        "include_mexc_depth": report["params"]["include_mexc_depth"],
        "mexc_depth_request_interval_sec": report["params"]["mexc_depth_request_interval_sec"],
        "mexc_depth_max_workers": report["params"]["mexc_depth_max_workers"],
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if depth["coverage"] >= depth["minimum_required_coverage"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
