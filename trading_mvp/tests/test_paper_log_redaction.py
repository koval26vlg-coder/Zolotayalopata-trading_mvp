from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from paper_log_redaction import REDACTED, safe_json_dumps, sanitize_for_log  # noqa: E402
from paper_secret_provider import (  # noqa: E402
    InMemoryTestCredentialProvider,
    SecretHandle,
)


SECRET = "fixture-secret-do-not-log"


def _handle() -> SecretHandle:
    return SecretHandle(
        provider_id="in_memory_test",
        reference_id="ref_0123456789abcdef",
        venue="gateio",
        purpose="paper_private_readiness_fixture",
    )


class PaperLogRedactionTests(unittest.TestCase):
    def test_headers_are_redacted_case_and_punctuation_insensitively(self) -> None:
        payload = {
            "headers": {
                "X-MEXC-APIKEY": SECRET,
                "Authorization": f"Bearer {SECRET}",
                "Content-Type": "application/json",
            }
        }
        sanitized = sanitize_for_log(payload)
        self.assertEqual(sanitized["headers"]["X-MEXC-APIKEY"], REDACTED)
        self.assertEqual(sanitized["headers"]["Authorization"], REDACTED)
        self.assertEqual(sanitized["headers"]["Content-Type"], "application/json")
        self.assertNotIn(SECRET, json.dumps(sanitized))

    def test_url_credentials_and_sensitive_query_values_are_redacted(self) -> None:
        url = (
            f"https://user:{SECRET}@example.test/private?"
            f"symbol=A00_USDT&api_key={SECRET}&signature={SECRET}"
        )
        rendered = sanitize_for_log({"url": url})["url"]
        self.assertIn("symbol=A00_USDT", rendered)
        self.assertNotIn("user", rendered)
        self.assertNotIn(SECRET, rendered)
        self.assertEqual(rendered.count("%5BREDACTED%5D"), 2)

    def test_nested_payload_and_inline_authorization_are_redacted(self) -> None:
        payload = {
            "request": {
                "credentials": {"secret": SECRET, "passphrase": SECRET},
                "message": f"Authorization: Bearer {SECRET}",
            }
        }
        rendered = safe_json_dumps(payload)
        self.assertNotIn(SECRET, rendered)
        self.assertIn("REDACTED", rendered)

    def test_secret_handle_has_safe_projection(self) -> None:
        rendered = safe_json_dumps({"handle": _handle()})
        self.assertIn("reference_fingerprint", rendered)
        self.assertNotIn(_handle().reference_id, rendered)
        self.assertIn("REDACTED", rendered)

    def test_secret_lease_and_raw_bytes_fail_closed(self) -> None:
        provider = InMemoryTestCredentialProvider()
        handle = _handle()
        provider.register_fixture(handle, SECRET.encode())
        with provider.resolve(handle) as lease:
            with self.assertRaisesRegex(ValueError, "cannot be serialized"):
                safe_json_dumps({"lease": lease})
        with self.assertRaisesRegex(ValueError, "raw byte"):
            safe_json_dumps({"payload": SECRET.encode()})

    def test_redaction_is_deterministic(self) -> None:
        payload = {
            "signature": SECRET,
            "symbol": "A00_USDT",
            "items": [{"token": SECRET}, "Bearer abcdefghijklmnop"],
        }
        self.assertEqual(safe_json_dumps(payload), safe_json_dumps(payload))


if __name__ == "__main__":
    unittest.main()
