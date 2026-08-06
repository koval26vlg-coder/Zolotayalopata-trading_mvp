from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from paper_secret_provider import (  # noqa: E402
    InMemoryTestCredentialProvider,
    SecretHandle,
    interface_capabilities,
)


def _handle() -> SecretHandle:
    return SecretHandle(
        provider_id="in_memory_test",
        reference_id="ref_0123456789abcdef",
        venue="mexc",
        purpose="paper_private_readiness_fixture",
    )


class PaperSecretProviderTests(unittest.TestCase):
    def test_handle_and_provider_repr_are_redacted(self) -> None:
        handle = _handle()
        provider = InMemoryTestCredentialProvider()
        fake_secret = b"fixture-secret-never-log"
        provider.register_fixture(handle, fake_secret)

        rendered = repr(handle) + repr(provider) + json.dumps(handle.to_public_dict())
        self.assertNotIn(fake_secret.decode(), rendered)
        self.assertNotIn(handle.reference_id, rendered)
        self.assertIn("REDACTED", rendered)

    def test_lease_exposes_readonly_view_and_zeroizes_on_close(self) -> None:
        handle = _handle()
        provider = InMemoryTestCredentialProvider()
        provider.register_fixture(handle, b"fixture-material")
        lease = provider.resolve(handle)
        captured = lease.consume(lambda view: bytes(view))
        self.assertEqual(captured, b"fixture-material")
        material = lease._material
        lease.close()
        self.assertTrue(lease.closed)
        self.assertEqual(bytes(material), b"\x00" * len(material))
        with self.assertRaisesRegex(RuntimeError, "closed"):
            lease.consume(bytes)

    def test_provider_context_zeroizes_and_forgets_fixtures(self) -> None:
        handle = _handle()
        provider = InMemoryTestCredentialProvider()
        provider.register_fixture(handle, b"fixture-material")
        original = provider._fixtures[handle]
        provider.close()
        self.assertEqual(bytes(original), b"\x00" * len(original))
        self.assertEqual(provider._fixtures, {})
        with self.assertRaisesRegex(RuntimeError, "closed"):
            provider.resolve(handle)

    def test_duplicate_or_unknown_handle_fails_closed(self) -> None:
        handle = _handle()
        provider = InMemoryTestCredentialProvider()
        provider.register_fixture(handle, b"one")
        with self.assertRaisesRegex(ValueError, "already registered"):
            provider.register_fixture(handle, b"two")
        unknown = SecretHandle(
            provider_id="in_memory_test",
            reference_id="ref_aaaaaaaaaaaaaaaa",
            venue="gateio",
            purpose="paper_private_readiness_fixture",
        )
        with self.assertRaisesRegex(KeyError, "not registered"):
            provider.resolve(unknown)

    def test_only_fixture_provider_and_purpose_are_accepted(self) -> None:
        with self.assertRaisesRegex(ValueError, "only the in-memory"):
            SecretHandle(
                provider_id="environment",
                reference_id="ref_0123456789abcdef",
                venue="mexc",
                purpose="paper_private_readiness_fixture",
            )
        with self.assertRaisesRegex(ValueError, "purpose"):
            SecretHandle(
                provider_id="in_memory_test",
                reference_id="ref_0123456789abcdef",
                venue="mexc",
                purpose="live_trading",
            )

    def test_capabilities_have_no_private_or_live_surface(self) -> None:
        capabilities = interface_capabilities()
        self.assertEqual(capabilities["implemented_providers"], ["in_memory_test"])
        self.assertFalse(capabilities["environment_provider"])
        self.assertFalse(capabilities["file_provider"])
        self.assertFalse(capabilities["private_exchange_client"])
        self.assertFalse(capabilities["live_orders"])
        self.assertFalse(capabilities["private_api_keys_read"])


if __name__ == "__main__":
    unittest.main()
