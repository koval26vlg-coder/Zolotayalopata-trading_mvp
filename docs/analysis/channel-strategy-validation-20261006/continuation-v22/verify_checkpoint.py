"""Publication integrity check for the bounded existing-evidence review."""
import json
from pathlib import Path
from audit_evidence import verify, read, require, file_hash, HERE


def verify_publication():
    result = verify()
    index = read(HERE/'evidence-index.json')
    items = index['files']
    names = {p.relative_to(HERE).as_posix() for p in HERE.rglob('*')
             if p.is_file() and p.name != 'evidence-index.json'}
    require(len(items) == len(names) and {r['file'] for r in items} == names, 'Publication inventory mismatch')
    for item in items:
        path = (HERE/item['file']).resolve()
        require(path.is_relative_to(HERE) and path.stat().st_size == item['bytes']
                and file_hash(path) == item['sha256'], 'Publication byte mismatch')
    require(read(HERE/'verification.json') == result, 'Verification receipt mismatch')
    dispatch = read(HERE/'dispatch.json')
    require(dispatch['script_sha256'] == file_hash(HERE/'run_audit_visible.ps1')
            and dispatch['window_style'] == 'Normal' and dispatch['no_exit'] is True, 'Launcher visibility binding')
    claims = list((HERE/'claim-archive').glob('*.json'))
    require(len(claims) == 1, 'Missing or ambiguous released writer claim')
    claim = read(claims[0])
    require(claim['status'] == 'RELEASED' and claim['final_status'] == 'COMPLETE'
            and claim['run_id'] == read(HERE/'completion.json')['run_id']
            and claim['terminal_pid'] == dispatch['terminal_pid']
            and Path(claim['output_namespace']).resolve() == HERE, 'Writer release mismatch')
    return result


if __name__ == '__main__':
    print(json.dumps(verify_publication(), indent=2))
