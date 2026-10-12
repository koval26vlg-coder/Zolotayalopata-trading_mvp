"""One bounded historical-file sample, never a live or recurring collector."""
import csv
import gzip
import hashlib
import io
from pathlib import Path
import ssl
import urllib.error
import urllib.request

from .data import write_immutable


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def sample_requests():
    # Coverage probes are fixed before reading any returns. No universe selection
    # or profitability test is performed on these samples.
    return [f'https://download.gatedata.org/spot/candlesticks_{interval}/{month}/{base}_USDT-{month}.csv.gz'
            for base in ('BTC', 'ETH') for month in ('202301', '202501', '202609') for interval in ('1h', '4h')]


def inspect_csv_gzip(raw, max_uncompressed=32*1024**2):
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:
        data = f.read(max_uncompressed+1)
    if len(data) > max_uncompressed:
        raise ValueError('Decompressed sample exceeds budget')
    lines = list(csv.reader(io.StringIO(data.decode('utf-8-sig'))))
    return dict(uncompressed_bytes=len(data), csv_rows=len(lines),
                first_rows=lines[:2], last_row=lines[-1] if lines else [],
                normalized_input_eligible=False,
                reason='Coverage/schema probe only; no historical universe, fee, or exposure certification')


def download_samples(output, check, timeout=20):
    output = Path(output)
    if output.exists():
        raise FileExistsError('One-shot source namespace already exists; no blind retry')
    output.mkdir(parents=True)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(),
                                        urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    records = []
    for number, url in enumerate(sample_requests(), 1):
        check()
        print(f'Source sample {number}/12: {url}', flush=True)
        record = dict(url=url, attempts=1, archive_verified=False)
        try:
            request = urllib.request.Request(url, headers={'User-Agent': 'HistoricalValidation/1.0', 'Accept-Encoding': 'identity'})
            with opener.open(request, timeout=timeout) as response:
                record['http_status'] = response.status
                declared = response.headers.get('Content-Length')
                if declared and int(declared) > 1000000:
                    raise ValueError('Declared sample exceeds 1000000 bytes')
                chunks, size = [], 0
                while size < 1000000:
                    check()
                    chunk = response.read(min(65536, 1000000-size))
                    if not chunk:
                        break
                    chunks.append(chunk)
                    size += len(chunk)
                if size >= 1000000:
                    raise ValueError('Sample byte cap reached; no retry')
                raw = b''.join(chunks)
                record.update(inspect_csv_gzip(raw))
                sha = hashlib.sha256(raw).hexdigest()
                path = output/f'{number:02d}-{sha}.csv.gz'
                with path.open('xb') as f:
                    f.write(raw)
                record.update(archive_verified=True, bytes=size, sha256=sha, path=path.name)
        except (urllib.error.URLError, OSError, ValueError, EOFError) as exc:
            record.update(error=str(exc), status='SOURCE_UNAVAILABLE_OR_INVALID')
        records.append(record)
        write_immutable(output/f'{number:02d}.receipt.json', record)
    result = dict(requests=12, retries=0, paid_data=False, records=records,
                  eligibility='NOT_A_BACKTEST_INPUT', official_documentation='https://www.gate.com/developer/historical_quotes')
    write_immutable(output/'source-audit.json', result)
    return result
