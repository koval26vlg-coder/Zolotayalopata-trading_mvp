"""CRC census and fixed prefix diagnostics of a quarantined, immutable ZIP; no network."""
from pathlib import Path
import zipfile

from .contract import OUTPUT_ROOT, build_plan, canonical_hash, file_hash, runtime_binding
from .data import write_immutable
from .gate_catalog import checked_json
from .histdata import ARCHIVE_RUN_ID, MEMBER, DECODE_CAP, quote

RUN_ID = 'history_histdata_local_v8_20261007'
RECOVERY_RUN_ID = 'history_histdata_local_recovery_v8_20261007'
RAW_SHA = '4786f42be652e22eb9ae9f567301b744ff0c0bc03b9fd6ff60173cc86c33a4a2'
SAMPLE_ROWS = 10000
REPORT_MEMBER = MEMBER.replace('.csv', '.txt')


def preflight(recovery=False):
    parent = OUTPUT_ROOT/'runs'/ARCHIVE_RUN_ID
    complete, complete_sha = checked_json(parent/'completion.json')
    proof, proof_sha = checked_json(parent/'supervisor-reconciliation.json')
    path = parent/'artifacts/histdata-sample/XAUUSD-202301.zip'
    if (complete['status'] != 'STOPPED_INCOMPLETE' or not complete.get('supervisor_reconciled') or
            complete['reconciliation_sha256'] != proof_sha or complete['plan_hash'] != build_plan()['plan_hash'] or
            proof['raw_file_sha256'] != RAW_SHA or file_hash(path) != RAW_SHA or
            proof['raw_file_bytes'] != path.stat().st_size or not proof['writer_confirmed_dead']):
        raise ValueError('Exact quarantined local source proof required')
    binding = dict(parent_run_id=ARCHIVE_RUN_ID, parent_status='STOPPED_INCOMPLETE',
                      completion_sha256=complete_sha, reconciliation_sha256=proof_sha,
                      raw_file_sha256=RAW_SHA, raw_bytes=path.stat().st_size,
                      network_requests=0, sample_rows=SAMPLE_ROWS, max_decoded_bytes=DECODE_CAP,
                      full_semantic_validation=False, parent_marked_complete=False)
    if recovery:
        stopped = OUTPUT_ROOT/'runs'/RUN_ID
        prior, prior_sha = checked_json(stopped/'completion.json')
        stop, stop_sha = checked_json(stopped/'supervisor-reconciliation.json')
        context, context_sha = checked_json(stopped/'user-stop-context.json')
        if (prior['status'] != 'STOPPED_INCOMPLETE' or prior['reconciliation_sha256'] != stop_sha or
                prior['plan_hash'] != build_plan()['plan_hash'] or
                not stop['writer_confirmed_dead'] or not stop['terminal_confirmed_dead'] or
                not context['confirmed_terminal_closure'] or context['network_retry_authorized'] or
                (stopped/'artifacts/histdata-local/audit.json').exists()):
            raise ValueError('Confirmed terminal-close interruption required for one local recovery')
        binding['local_recovery'] = dict(previous_run_id=RUN_ID,completion_sha256=prior_sha,
                                        stop_sha256=stop_sha,user_context_sha256=context_sha,
                                        previous_output_preserved=True, network_requests=0)
    return path, binding


def census(path, check=lambda: None):
    decoded, physical_rows, prefix, last = 0, 0, bytearray(), b''
    provider_report = None
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        names = [m.filename for m in members]
        # No extraction, and only the selected CSV and its named provider report.
        if (set(names) not in ({MEMBER}, {MEMBER, REPORT_MEMBER}) or len(set(names)) != len(names) or
                any(m.flag_bits & 1 or m.compress_type not in (zipfile.ZIP_STORED,zipfile.ZIP_DEFLATED) for m in members)):
            raise ValueError('Unexpected local archive members')
        member = archive.getinfo(MEMBER)
        if sum(m.file_size for m in members) > DECODE_CAP:
            raise ValueError('Local decompression budget or codec')
        with archive.open(member) as stream:
            while True:
                check()
                block = stream.read(65536)
                if not block:
                    break
                decoded += len(block)
                if decoded > DECODE_CAP:
                    raise ValueError('Local decoded budget')
                physical_rows += block.count(b'\n')
                if prefix.count(b'\n') < SAMPLE_ROWS:
                    prefix.extend(block)
                    if len(prefix) > SAMPLE_ROWS*256+65536:
                        raise ValueError('Sample line budget')
                last = block[-1:]
        if decoded != member.file_size:
            raise ValueError('ZIP length mismatch')
        if REPORT_MEMBER in names:
            check()
            if archive.getinfo(REPORT_MEMBER).file_size > 1000000:
                raise ValueError('Provider report budget')
            provider_report = archive.read(REPORT_MEMBER).decode('utf-8-sig')
    if last and last != b'\n':
        physical_rows += 1
    lines = bytes(prefix).splitlines()[:SAMPLE_ROWS]
    if not lines:
        raise ValueError('Empty sample')
    previous, first, max_gap, gaps, duplicates = None, None, 0, 0, 0
    bid_low, bid_high, ask_low, ask_high = None, None, None, None
    for line in lines:
        check()
        if len(line) > 256:
            raise ValueError('Long sample row')
        at, bid, ask = quote(line)
        if previous is not None:
            if at < previous:
                raise ValueError('Unordered sample')
            delta = at-previous
            duplicates += delta == 0
            gaps += delta > 60000
            max_gap = max(max_gap, delta)
        first = at if first is None else first
        previous = at
        bid_low, bid_high = (bid if bid_low is None else min(bid_low,bid)), (bid if bid_high is None else max(bid_high,bid))
        ask_low, ask_high = (ask if ask_low is None else min(ask_low,ask)), (ask if ask_high is None else max(ask_high,ask))
    return dict(zip_crc_verified=True, decoded_bytes=decoded, physical_csv_rows=physical_rows,
                provider_report_text=provider_report, provider_claims_independently_verified=False,
                validated_sample_rows=len(lines), unvalidated_rows=physical_rows-len(lines),
                sample_first_ms=first, sample_last_ms=previous, sample_max_gap_ms=max_gap,
                sample_gaps_over_minute=gaps, sample_equal_time_ticks=duplicates,
                sample_bid_range=list(map(str,(bid_low,bid_high))), sample_ask_range=list(map(str,(ask_low,ask_high))),
                full_month_semantics_verified=False, calendar_certified=False, costs_verified=False,
                metrics=None, evaluation_eligible=False)


def audit(output, check):
    output = Path(output)
    recovery = output.resolve() == (OUTPUT_ROOT/'runs'/RECOVERY_RUN_ID/'artifacts/histdata-local').resolve()
    if (not recovery and output.resolve() != (OUTPUT_ROOT/'runs'/RUN_ID/'artifacts/histdata-local').resolve()) or output.exists():
        raise ValueError('Fixed fresh local census namespace required')
    path, binding = preflight(recovery=recovery)
    write_immutable(output/'input-binding.json', binding)
    print('Local HistData CRC census, then first 10000 rows; network disabled',flush=True)
    result = census(path, check)
    if file_hash(path) != RAW_SHA:
        raise ValueError('Raw archive changed during local census')
    result.update(schema='histdata_local_prefix_census_v1',input_binding=binding,
                  plan_hash=build_plan()['plan_hash'],runtime_binding=runtime_binding(),input_status='BLOCKED_DATA')
    result['audit_hash'] = canonical_hash(result)
    write_immutable(output/'audit.json', result)
    return result
