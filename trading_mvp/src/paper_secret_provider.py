from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Protocol, TypeVar


INTERFACE_SCHEMA = "trading_mvp_paper_secret_provider_interface_v1"
_REFERENCE_PATTERN = re.compile(r"^ref_[0-9a-f]{16,64}$")
_ALLOWED_VENUES = {"mexc", "gateio"}
_ALLOWED_PURPOSES = {"paper_private_readiness_fixture"}
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class SecretHandle:
    provider_id: str
    reference_id: str
    venue: str
    purpose: str

    def __post_init__(self) -> None:
        if self.provider_id != "in_memory_test":
            raise ValueError("only the in-memory test provider is implemented")
        if not _REFERENCE_PATTERN.fullmatch(self.reference_id):
            raise ValueError("reference_id must be an opaque ref_ hexadecimal identifier")
        if self.venue not in _ALLOWED_VENUES:
            raise ValueError("unsupported test credential venue")
        if self.purpose not in _ALLOWED_PURPOSES:
            raise ValueError("unsupported test credential purpose")

    def __repr__(self) -> str:
        return (
            "SecretHandle(provider_id='in_memory_test', "
            f"reference_id='{self.reference_id[:8]}...REDACTED', "
            f"venue='{self.venue}', purpose='{self.purpose}')"
        )

    __str__ = __repr__

    def to_public_dict(self) -> dict[str, str]:
        return {
            "schema": INTERFACE_SCHEMA,
            "provider_id": self.provider_id,
            "reference_fingerprint": self.reference_id[:12],
            "venue": self.venue,
            "purpose": self.purpose,
            "secret_value": "REDACTED",
        }


class SecretLease:
    __slots__ = ("_material", "_closed")

    def __init__(self, material: bytes) -> None:
        if not material:
            raise ValueError("test secret material must not be empty")
        self._material = bytearray(material)
        self._closed = False

    def __repr__(self) -> str:
        return "SecretLease(REDACTED)"

    __str__ = __repr__

    @property
    def closed(self) -> bool:
        return self._closed

    def consume(self, consumer: Callable[[memoryview], T]) -> T:
        if self._closed:
            raise RuntimeError("secret lease is closed")
        return consumer(memoryview(self._material).toreadonly())

    def close(self) -> None:
        if self._closed:
            return
        for index in range(len(self._material)):
            self._material[index] = 0
        self._closed = True

    def __enter__(self) -> SecretLease:
        if self._closed:
            raise RuntimeError("secret lease is closed")
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


class CredentialProvider(Protocol):
    provider_id: str

    def resolve(self, handle: SecretHandle) -> SecretLease:
        ...


class InMemoryTestCredentialProvider:
    provider_id = "in_memory_test"

    def __init__(self) -> None:
        self._fixtures: dict[SecretHandle, bytearray] = {}
        self._closed = False

    def __repr__(self) -> str:
        return (
            "InMemoryTestCredentialProvider("
            f"fixture_count={len(self._fixtures)}, material=REDACTED)"
        )

    def register_fixture(self, handle: SecretHandle, material: bytes) -> None:
        if self._closed:
            raise RuntimeError("test credential provider is closed")
        if handle.provider_id != self.provider_id:
            raise ValueError("secret handle belongs to another provider")
        if handle in self._fixtures:
            raise ValueError("test credential fixture is already registered")
        if not isinstance(material, bytes) or not material:
            raise ValueError("test credential fixture must be non-empty bytes")
        self._fixtures[handle] = bytearray(material)

    def resolve(self, handle: SecretHandle) -> SecretLease:
        if self._closed:
            raise RuntimeError("test credential provider is closed")
        try:
            material = self._fixtures[handle]
        except KeyError as exc:
            raise KeyError("test credential handle is not registered") from exc
        return SecretLease(bytes(material))

    def close(self) -> None:
        if self._closed:
            return
        for material in self._fixtures.values():
            for index in range(len(material)):
                material[index] = 0
        self._fixtures.clear()
        self._closed = True

    def __enter__(self) -> InMemoryTestCredentialProvider:
        if self._closed:
            raise RuntimeError("test credential provider is closed")
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()


def interface_capabilities() -> dict[str, object]:
    return {
        "schema": INTERFACE_SCHEMA,
        "status": "FIXTURE_INTERFACE_ONLY",
        "implemented_providers": ["in_memory_test"],
        "environment_provider": False,
        "file_provider": False,
        "windows_credential_manager_provider": False,
        "private_exchange_client": False,
        "secret_serialization": False,
        "secret_logging": False,
        "live_orders": False,
        "private_api_keys_read": False,
        "maximum_authority": "IN_MEMORY_TEST_SECRET_USE_ONLY",
    }
