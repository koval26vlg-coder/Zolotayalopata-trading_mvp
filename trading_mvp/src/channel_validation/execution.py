"""Visible-owner worker entrypoint. No subprocess may escape the owner's job."""
import argparse
import json
import os
from pathlib import Path
import time

from .contract import ROOT, OUTPUT_ROOT, build_plan, canonical_hash, runtime_binding
from .data import write_immutable
from .runner import main
from global_market_writer_claim import claim_global_market_writer, release_global_market_writer


def run():
    p = argparse.ArgumentParser()
    p.add_argument('--run-id', required=True)
    p.add_argument('--token', required=True)
    args = p.parse_args()
    if not args.run_id.startswith('history_') or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in args.run_id):
        raise ValueError('Invalid run id')
    output = OUTPUT_ROOT/'runs'/args.run_id
    intent = json.loads((output/'intent.json').read_text(encoding='utf-8-sig'))
    if intent['token'] != args.token or intent['runtime_hash'] != canonical_hash(runtime_binding()):
        raise ValueError('Exact intent/code binding mismatch')
    until = time.monotonic()+30
    while not (output/'owner.json').exists():
        if time.monotonic() >= until:
            raise TimeoutError('Visible owner handshake absent')
        time.sleep(.1)
    owner = json.loads((output/'owner.json').read_text(encoding='utf-8-sig'))
    if owner['worker_pid'] != os.getpid() or owner['token'] != args.token or not owner['job_assigned']:
        raise ValueError('Visible owner/worker mismatch')
    claim_path = ROOT/'docs/agent-log/active-market-data-writer-claim.json'
    plan = build_plan()
    claim = claim_global_market_writer(claim_path, run_id=args.run_id, owner_pid=os.getpid(),
                                      owner_kind='visible_historical_offline_validation', plan_hash=plan['plan_hash'],
                                      output_namespace=output.resolve(), writer_pid=os.getpid(),
                                      terminal_pid=owner['owner_pid'])
    status, code = 'STOPPED_INCOMPLETE', 2
    try:
        argv = [intent['stage'], '--output', str(output/'artifacts'), '--max-runtime-sec', str(intent['max_runtime_sec']),
                '--stop-file', str(output/'stop.json')]
        if intent.get('input_manifest'):
            argv += ['--input-manifest', intent['input_manifest']]
        if intent.get('evaluation_path'):
            argv += ['--evaluation', intent['evaluation_path']]
        code = main(argv)
        if code == 0:
            status = 'COMPLETE'
    except Exception as exc:
        print(str(exc), flush=True)
        write_immutable(output/'failure.json', dict(error=str(exc), retry_authorized=False))
    finally:
        release_global_market_writer(claim_path, run_id=args.run_id, owner_pid=os.getpid(),
                                     ownership_token=claim['ownership_token'], final_status=status,
                                     expected_plan_hash=plan['plan_hash'], archive_dir=output/'claim-archive')
        write_immutable(output/'completion.json', dict(status=status, exit_code=code, run_id=args.run_id,
                                                      runtime_hash=intent['runtime_hash'], plan_hash=plan['plan_hash']))
    return code


if __name__ == '__main__':
    raise SystemExit(run())
