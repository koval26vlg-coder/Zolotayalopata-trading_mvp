from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from threading import Lock
from time import monotonic
from typing import Any, Callable, Mapping, Sequence


RUN_ID = "slow_liquidity_official_currentness_topology_discovery_20260813_v1"
RUNTIME_MANIFEST_SCHEMA = (
    "trading_mvp_slow_liquidity_official_currentness_topology_runtime_manifest_v1"
)
RUNTIME_MANIFEST_STATUS = (
    "FROZEN_OFFLINE_IMPLEMENTATION_AWAIT_EXACT_TOPOLOGY_EXECUTION_APPROVAL"
)
EXECUTION_MANIFEST_SCHEMA = (
    "trading_mvp_slow_liquidity_official_currentness_topology_execution_manifest_v1"
)
EXECUTION_APPROVED_STATUS = "FROZEN_WITH_EXACT_TOPOLOGY_EXECUTION_APPROVAL"
EXECUTION_RECEIPT_SCHEMA = (
    "trading_mvp_slow_liquidity_official_currentness_topology_"
    "execution_approval_receipt_v1"
)
SANITIZED_OUTPUT_SCHEMA = (
    "trading_mvp_slow_liquidity_official_currentness_topology_sanitized_v1"
)
SANITIZED_OUTPUT_MANIFEST_SCHEMA = (
    "trading_mvp_slow_liquidity_official_currentness_topology_output_manifest_v1"
)

PROPOSAL_FILE_SHA256 = (
    "a694c51c8d1f3f8d2abe81797a90f5908f45252b938c7420cb58277972d45555"
)
PROPOSAL_HASH = "fff9f0453d5cc378344b94ad38113a267bd068a3215d29953fa2db62ef8f9686"
PARENT_PLAN_FILE_SHA256 = (
    "501f42f7f418fcc07522f8df8a59db38db106cd3d2ae86cc598ffb19af34afe4"
)
PARENT_PLAN_HASH = "6246471964815d139e6900298a2a78e80e830df40f0c06b39078487c254183cc"
PARENT_RUNTIME_FILE_SHA256 = (
    "0e2dfa6be70c289a877f9660d2ef58adca4c05276d38bfc8d99c4b8e703b250d"
)
PARENT_RUNTIME_HASH = "f2cedc562660b25da6d0eac1845deb2e4ef17ba38782867ed49792f13fb392e1"

SEED_URLS = (
    "https://www.mexc.com/robots.txt",
    "https://www.mexc.com/sitemap.xml",
    "https://www.mexc.com/support/articles/",
    "https://www.gate.com/robots.txt",
    "https://www.gate.com/sitemap.xml",
    "https://www.gate.com/announcements",
)
OFFICIAL_HOSTS = ("www.mexc.com", "www.gate.com")
MAX_TOTAL_HTTP_REQUESTS = 6
MAX_ATTEMPTS_PER_URL = 1
MAX_RESPONSE_BYTES = 1_000_000
MAX_RUNTIME_SEC = 300
HARD_OUTPUT_CAP_BYTES = 10_000_000
MAX_DISCOVERED_URLS = 256
MAX_URL_BYTES = 2048
BLOCKED_EXIT_CODE = 3
JSON_READ_CAP_BYTES = 5_000_000
READ_CHUNK_BYTES = 64 * 1024

ALLOWED_RECORD_FIELD_ORDER = (
    "source_url",
    "response_sha256",
    "response_bytes",
    "content_type",
    "same_host_candidate_index_urls",
    "same_host_candidate_pagination_templates",
    "candidate_termination_markers",
    "disposition",
)
ALLOWED_RECORD_FIELDS = frozenset(ALLOWED_RECORD_FIELD_ORDER)
ALLOWED_TERMINATION_MARKERS = frozenset(
    {
        "ROBOTS_SITEMAP_DIRECTIVES_PRESENT",
        "SITEMAP_INDEX_FINITE_LOC_SET",
        "SITEMAP_URLSET_FINITE_LOC_SET",
        "HTML_REL_NEXT_PRESENT",
        "HTML_REL_NEXT_ABSENT_ON_SEED",
        "HTML_NUMERIC_PAGINATION_LINKS_PRESENT",
        "NO_ALLOWLISTED_INDEX_CANDIDATE",
    }
)
ALLOWED_DISPOSITIONS = frozenset(
    {
        "CANDIDATE_TOPOLOGY_FOUND_NOT_EXHAUSTIVENESS_PROOF",
        "NO_ALLOWLISTED_TOPOLOGY_FOUND",
    }
)

REPO_ROOT = Path(__file__).resolve().parents[2]
PROPOSAL_PATH = (
    REPO_ROOT / "docs/plans/drafts/slow-liquidity-identity-currentness-refreeze-"
    "proposal-20260813-v7.json"
)
PARENT_PLAN_PATH = (
    REPO_ROOT / "docs/plans/slow-liquidity-identity-request-plan-discovery-"
    "20260813-v2/plan.json"
)
PARENT_RUNTIME_PATH = (
    REPO_ROOT / "docs/plans/slow-liquidity-identity-request-plan-discovery-"
    "20260813-v2/runtime-manifest.json"
)
RUNTIME_MODULE_PATH = Path(__file__).resolve()
SYNTHETIC_TESTS_PATH = (
    REPO_ROOT / "trading_mvp/tests/test_slow_liquidity_official_currentness_topology.py"
)
RUNTIME_MANIFEST_PATH = (
    REPO_ROOT / "docs/plans/slow-liquidity-official-currentness-topology-runtime-"
    "manifest-20260813-v1.json"
)
FUTURE_VISIBLE_LAUNCHER_PATH = (
    REPO_ROOT / "tools/start_exact_approved_slow_liquidity_official_currentness_"
    "topology_visible.ps1"
)

_CAPABILITY_SENTINEL = object()
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f]")
_SITEMAP_DIRECTIVE = re.compile(r"^\s*sitemap\s*:\s*(\S+)\s*$", re.I)
_PAGINATION_KEYS = frozenset(
    {"page", "p", "current", "pagenum", "page_num", "pageindex"}
)


class TopologyDiscoveryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class FetchedResponse:
    requested_url: str
    final_url: str
    status: int
    headers: Mapping[str, str]
    body: bytes


class _ExecutionBudget:
    __slots__ = ("deadline_monotonic", "_attempts_by_url", "_lock", "_total_attempts")

    def __init__(self, *, started_monotonic: float) -> None:
        self.deadline_monotonic = started_monotonic + MAX_RUNTIME_SEC
        self._attempts_by_url = {url: 0 for url in SEED_URLS}
        self._lock = Lock()
        self._total_attempts = 0

    def reserve(
        self,
        url: str,
        *,
        requested_deadline_monotonic: float,
        clock: Callable[[], float],
    ) -> float:
        with self._lock:
            now = clock()
            effective_deadline = min(
                requested_deadline_monotonic,
                self.deadline_monotonic,
            )
            _require(now < effective_deadline, "topology runtime deadline exceeded")
            _require(
                self._total_attempts < MAX_TOTAL_HTTP_REQUESTS,
                "total request attempt cap exceeded",
            )
            _require(
                self._attempts_by_url[url] < MAX_ATTEMPTS_PER_URL,
                "per-URL request attempt cap exceeded",
            )
            # Reserve before opening transport. Failed requests still consume the one shot.
            self._total_attempts += 1
            self._attempts_by_url[url] += 1
        return effective_deadline


@dataclass(frozen=True, slots=True, init=False)
class TopologyExecutionCapability:
    run_id: str
    runtime_manifest_hash: str
    execution_manifest_hash: str
    output_path: str
    _budget: _ExecutionBudget
    _sentinel: object

    def __init__(
        self,
        *,
        run_id: str,
        runtime_manifest_hash: str,
        execution_manifest_hash: str,
        output_path: str,
        _budget: _ExecutionBudget,
        _sentinel: object,
    ) -> None:
        if _sentinel is not _CAPABILITY_SENTINEL:
            raise TopologyDiscoveryError("invalid execution capability")
        object.__setattr__(self, "run_id", run_id)
        object.__setattr__(self, "runtime_manifest_hash", runtime_manifest_hash)
        object.__setattr__(self, "execution_manifest_hash", execution_manifest_hash)
        object.__setattr__(self, "output_path", output_path)
        object.__setattr__(self, "_budget", _budget)
        object.__setattr__(self, "_sentinel", _sentinel)


class _TopologyLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []
        self.rel_next = False

    def _handle_attrs(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {name.lower(): value for name, value in attrs if value is not None}
        href = values.get("href")
        if tag.lower() in {"a", "link"} and href:
            self.urls.append(href)
            if len(self.urls) > MAX_DISCOVERED_URLS:
                raise TopologyDiscoveryError("discovered URL cap exceeded")
        rel_tokens = {
            token.lower() for token in str(values.get("rel") or "").split() if token
        }
        if href and "next" in rel_tokens:
            self.rel_next = True

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._handle_attrs(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._handle_attrs(tag, attrs)


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise TopologyDiscoveryError(message)


def _require_hash(value: Any, label: str) -> str:
    _require(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value),
        f"{label} is not a lowercase SHA256",
    )
    return value


def _validate_timestamp(value: Any, label: str) -> str:
    _require(isinstance(value, str) and value.endswith("Z"), f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise TopologyDiscoveryError(f"{label} is invalid") from exc
    _require(parsed.utcoffset() is not None, f"{label} is not timezone-aware")
    return value


def _reject_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise TopologyDiscoveryError("JSON contains duplicate keys")
        result[key] = value
    return result


def _strict_json_loads(raw: bytes, label: str) -> dict[str, Any]:
    try:
        decoded = raw.decode("utf-8")
        value = json.loads(decoded, object_pairs_hook=_reject_duplicate_json_keys)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TopologyDiscoveryError(f"{label} is not valid strict JSON") from exc
    _require(isinstance(value, dict), f"{label} must contain a JSON object")
    return value


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def canonical_hash_without(payload: Mapping[str, Any], field: str) -> str:
    clone = dict(payload)
    clone.pop(field, None)
    return hashlib.sha256(canonical_json_bytes(clone)).hexdigest()


def _json_file_bytes(value: Mapping[str, Any]) -> bytes:
    return canonical_json_bytes(value) + b"\n"


def _sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    expected_path = Path(path)
    with expected_path.open("rb") as handle:
        _assert_open_handle_path(handle, expected_path)
        while chunk := handle.read(READ_CHUNK_BYTES):
            digest.update(chunk)
        _assert_open_handle_path(handle, expected_path)
    return digest.hexdigest()


def _is_reparse_point(path: Path) -> bool:
    try:
        stat_result = path.lstat()
    except FileNotFoundError:
        return False
    attributes = int(getattr(stat_result, "st_file_attributes", 0))
    return path.is_symlink() or bool(attributes & 0x400)


def _assert_no_reparse_components(path: Path) -> None:
    absolute = Path(os.path.abspath(os.fspath(path)))
    parts = absolute.parts
    if not parts:
        raise TopologyDiscoveryError("local path is empty")
    current = Path(parts[0])
    for part in parts[1:]:
        current /= part
        if current.exists() and _is_reparse_point(current):
            raise TopologyDiscoveryError(
                "local path contains a symlink or reparse point"
            )


def _assert_open_handle_path(handle: Any, expected_path: Path) -> None:
    expected = os.path.normcase(os.path.abspath(os.fspath(expected_path)))
    if os.name != "nt":
        observed = os.path.normcase(os.path.realpath(os.fspath(handle.name)))
        _require(observed == expected, "open file handle escaped the expected path")
        return

    import ctypes
    import msvcrt

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_final_path = kernel32.GetFinalPathNameByHandleW
    get_final_path.argtypes = [
        ctypes.c_void_p,
        ctypes.c_wchar_p,
        ctypes.c_uint32,
        ctypes.c_uint32,
    ]
    get_final_path.restype = ctypes.c_uint32
    native_handle = msvcrt.get_osfhandle(handle.fileno())
    size = 32768
    buffer = ctypes.create_unicode_buffer(size)
    length = get_final_path(native_handle, buffer, size, 0)
    _require(0 < length < size, "cannot resolve open file handle")
    observed = buffer.value
    _require(
        not observed.startswith("\\\\?\\UNC\\"),
        "open file handle resolved to a remote path",
    )
    if observed.startswith("\\\\?\\"):
        observed = observed[4:]
    _require(
        os.path.normcase(os.path.abspath(observed)) == expected,
        "open file handle escaped the expected path",
    )


def _validated_local_output_path(value: str | Path, *, label: str) -> Path:
    raw = os.fspath(value)
    _require(type(raw) is str and raw != "", f"{label} is missing")
    _require("\x00" not in raw, f"{label} contains a null byte")
    windows_form = raw.replace("/", "\\")
    _require(
        not windows_form.startswith(("\\\\", "\\?\\", "\\.\\")),
        f"{label} remote or device path is forbidden",
    )
    candidate = Path(os.path.abspath(os.path.expanduser(raw)))
    _require(candidate.is_absolute(), f"{label} is not absolute")
    if os.name == "nt":
        import ctypes

        drive, _ = os.path.splitdrive(str(candidate))
        _require(drive != "", f"{label} has no local drive")
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(f"{drive}\\")
        _require(drive_type != 4, f"{label} remote drive is forbidden")
        _require(drive_type not in (0, 1), f"{label} drive type is invalid")
    _assert_no_reparse_components(candidate)
    return candidate


def _local_repo_path(
    value: str | Path,
    *,
    repo_root: str | Path,
    label: str,
    must_exist: bool = True,
) -> Path:
    root = Path(repo_root).expanduser()
    root = Path(os.path.abspath(os.fspath(root)))
    candidate = Path(value).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    candidate = Path(os.path.abspath(os.fspath(candidate)))
    _assert_no_reparse_components(root)
    _assert_no_reparse_components(candidate)
    try:
        common = Path(os.path.commonpath((os.fspath(root), os.fspath(candidate))))
    except ValueError as exc:
        raise TopologyDiscoveryError(f"{label} is outside the repository") from exc
    _require(common == root, f"{label} is outside the repository")
    if must_exist:
        _require(candidate.is_file(), f"{label} is missing")
    return candidate


def _validated_repo_root(value: str | Path) -> Path:
    root = Path(value).expanduser()
    root = Path(os.path.abspath(os.fspath(root)))
    _assert_no_reparse_components(root)
    _require(root.is_dir(), "repo root is missing")
    _require(root == REPO_ROOT, "repo root mismatch")
    return root


def _read_bounded_file(path: Path, label: str) -> bytes:
    _require(path.is_file(), f"{label} is missing")
    _require(path.stat().st_size <= JSON_READ_CAP_BYTES, f"{label} exceeds read cap")
    with path.open("rb") as handle:
        _assert_open_handle_path(handle, path)
        before = os.fstat(handle.fileno())
        raw = handle.read(JSON_READ_CAP_BYTES + 1)
        after = os.fstat(handle.fileno())
        _assert_open_handle_path(handle, path)
    _require(len(raw) <= JSON_READ_CAP_BYTES, f"{label} exceeds read cap")
    _require(
        before.st_size == after.st_size
        and before.st_mtime_ns == after.st_mtime_ns
        and before.st_ino == after.st_ino,
        f"{label} changed while being read",
    )
    return raw


def _read_exact_json(
    path: Path,
    *,
    label: str,
    expected_file_sha256: str,
) -> tuple[str, dict[str, Any]]:
    raw = _read_bounded_file(path, label)
    observed = hashlib.sha256(raw).hexdigest()
    _require(observed == expected_file_sha256, f"{label} file hash mismatch")
    return observed, _strict_json_loads(raw, label)


def _file_binding(path: Path) -> dict[str, str]:
    return {"path": str(path), "file_sha256": _sha256_file(path)}


def _expected_transport_requirements() -> dict[str, bool]:
    return {
        "https_only": True,
        "get_only": True,
        "request_body_allowed": False,
        "private_or_auth_headers_allowed": False,
        "redirects_allowed": False,
        "environment_proxies_allowed": False,
        "retries_allowed": False,
        "streaming_body_limit_required": True,
        "content_length_precheck_required": True,
        "deadline_checks_before_request_and_each_chunk_required": True,
        "global_deadline_check_after_response_required": True,
        "response_url_must_equal_requested_url": True,
        "dns_or_redirect_host_expansion_allowed": False,
        "raw_payload_persistence_allowed": False,
        "search_payload_persistence_allowed": False,
        "free_form_error_text_persistence_allowed": False,
    }


def _expected_output_contract() -> dict[str, Any]:
    return {
        "sanitized_topology_only": True,
        "allowlisted_fields": list(ALLOWED_RECORD_FIELD_ORDER),
        "raw_payload_persistence_allowed": False,
        "free_form_text_persistence_allowed": False,
        "article_body_persistence_allowed": False,
        "identity_identifier_persistence_allowed": False,
        "prices_or_funding_rates_persistence_allowed": False,
        "maximum_discovered_urls": MAX_DISCOVERED_URLS,
        "maximum_url_bytes": MAX_URL_BYTES,
        "topology_success_does_not_prove_exhaustiveness": True,
        "topology_success_does_not_authorize_identity_runtime": True,
    }


def _validate_exact_proposal(
    proposal_path: str | Path,
    *,
    repo_root: str | Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    root = _validated_repo_root(repo_root)
    path = _local_repo_path(
        proposal_path,
        repo_root=root,
        label="topology proposal",
    )
    expected_path = _local_repo_path(
        PROPOSAL_PATH,
        repo_root=root,
        label="canonical topology proposal",
    )
    _require(path == expected_path, "topology proposal path mismatch")
    _, proposal = _read_exact_json(
        path,
        label="topology proposal",
        expected_file_sha256=PROPOSAL_FILE_SHA256,
    )
    _require(
        proposal.get("schema")
        == "trading_mvp_slow_liquidity_identity_currentness_refreeze_proposal_v7",
        "topology proposal schema mismatch",
    )
    _require(proposal.get("proposal_hash") == PROPOSAL_HASH, "proposal hash mismatch")
    _require(
        canonical_hash_without(proposal, "proposal_hash") == PROPOSAL_HASH,
        "proposal canonical hash mismatch",
    )
    parent = proposal.get("parent_discovery")
    _require(isinstance(parent, dict), "proposal parent binding is missing")
    expected_parent = {
        "plan_file_sha256": PARENT_PLAN_FILE_SHA256,
        "plan_hash": PARENT_PLAN_HASH,
        "runtime_file_sha256": PARENT_RUNTIME_FILE_SHA256,
        "runtime_hash": PARENT_RUNTIME_HASH,
    }
    for key, expected in expected_parent.items():
        _require(parent.get(key) == expected, f"proposal parent {key} mismatch")

    candidate = proposal.get("topology_discovery_candidate")
    _require(isinstance(candidate, dict), "topology candidate is missing")
    _require(candidate.get("run_id") == RUN_ID, "topology run_id mismatch")
    _require(
        candidate.get("exact_seed_urls") == list(SEED_URLS),
        "topology seed URLs mismatch",
    )
    _require(
        candidate.get("official_hosts") == list(OFFICIAL_HOSTS),
        "topology official hosts mismatch",
    )
    _require(
        candidate.get("maximum_total_http_requests") == MAX_TOTAL_HTTP_REQUESTS,
        "topology request cap mismatch",
    )
    _require(
        candidate.get("maximum_attempts_per_url") == MAX_ATTEMPTS_PER_URL,
        "topology attempt cap mismatch",
    )
    _require(
        candidate.get("maximum_response_bytes_per_request") == MAX_RESPONSE_BYTES,
        "topology response cap mismatch",
    )
    _require(
        candidate.get("max_runtime_sec") == MAX_RUNTIME_SEC,
        "topology runtime cap mismatch",
    )
    _require(
        candidate.get("hard_output_cap_bytes") == HARD_OUTPUT_CAP_BYTES,
        "topology output cap mismatch",
    )
    _require(
        candidate.get("transport_requirements") == _expected_transport_requirements(),
        "topology transport contract mismatch",
    )
    _require(
        candidate.get("canonical_runtime_module_path") == str(RUNTIME_MODULE_PATH),
        "topology runtime module path mismatch",
    )
    _require(
        candidate.get("canonical_tests_path") == str(SYNTHETIC_TESTS_PATH),
        "topology tests path mismatch",
    )
    _require(
        candidate.get("future_visible_launcher_path")
        == str(FUTURE_VISIBLE_LAUNCHER_PATH),
        "future topology launcher path mismatch",
    )
    _require(
        proposal.get("topology_output_contract") == _expected_output_contract(),
        "topology output contract mismatch",
    )
    authorization = proposal.get("authorization_now")
    _require(isinstance(authorization, dict), "proposal authorization is missing")
    for key in (
        "offline_runtime_implementation_allowed",
        "synthetic_tests_allowed",
        "runtime_refreeze_allowed",
        "network_run_allowed",
        "official_source_content_read_allowed",
        "approval_receipt_creation_allowed",
        "visible_launcher_creation_allowed",
        "global_writer_claim_allowed",
        "request_plan_output_allowed",
        "identity_output_allowed",
    ):
        _require(authorization.get(key) is False, f"proposal permission changed: {key}")

    parent_plan_path = _local_repo_path(
        PARENT_PLAN_PATH,
        repo_root=root,
        label="parent discovery plan",
    )
    parent_runtime_path = _local_repo_path(
        PARENT_RUNTIME_PATH,
        repo_root=root,
        label="parent discovery runtime",
    )
    _, parent_plan = _read_exact_json(
        parent_plan_path,
        label="parent discovery plan",
        expected_file_sha256=PARENT_PLAN_FILE_SHA256,
    )
    _, parent_runtime = _read_exact_json(
        parent_runtime_path,
        label="parent discovery runtime",
        expected_file_sha256=PARENT_RUNTIME_FILE_SHA256,
    )
    _require(
        parent_plan.get("plan_hash") == PARENT_PLAN_HASH, "parent plan hash mismatch"
    )
    _require(
        canonical_hash_without(parent_plan, "plan_hash") == PARENT_PLAN_HASH,
        "parent plan canonical hash mismatch",
    )
    _require(
        parent_runtime.get("manifest_hash") == PARENT_RUNTIME_HASH,
        "parent runtime hash mismatch",
    )
    _require(
        canonical_hash_without(parent_runtime, "manifest_hash") == PARENT_RUNTIME_HASH,
        "parent runtime canonical hash mismatch",
    )
    return proposal, parent_plan, parent_runtime


def _offline_authorization_contract() -> dict[str, Any]:
    return {
        "mode": "DIRECT_EXACT_USER_APPROVAL_NOT_MATERIALIZED_AS_RECEIPT",
        "proposal_binding_verified": True,
        "approval_receipt_created": False,
        "authorized_scope": {
            "topology_runtime_implementation": True,
            "synthetic_tests": True,
            "immutable_code_bound_runtime_refreeze": True,
            "preflight_only": True,
        },
        "not_authorized": {
            "network": True,
            "official_source_content_read": True,
            "approval_receipt": True,
            "visible_launcher": True,
            "writer_claim": True,
            "topology_output": True,
            "request_plan_output": True,
            "identity_output": True,
            "collector_or_evaluator": True,
            "oos_or_returns_or_pnl": True,
            "grid_or_retune": True,
            "execution_probe": True,
            "paper_or_live": True,
            "private_api_or_real_capital": True,
            "leverage_or_margin": True,
        },
    }


def _execution_authorization_closed() -> dict[str, Any]:
    return {
        "approved": False,
        "execution_manifest": None,
        "network_run_allowed": False,
        "official_source_content_read_allowed": False,
        "topology_output_allowed": False,
        "global_writer_claim_allowed": False,
        "separate_exact_code_bound_execution_approval_required": True,
        "runtime_can_mint_execution_approval": False,
        "visible_launcher_exists": False,
        "direct_cli_execution_allowed": False,
    }


def _preflight_contract() -> dict[str, Any]:
    return {
        "status": "BLOCKED_AWAIT_EXACT_TOPOLOGY_EXECUTION_APPROVAL",
        "proposal_must_be_read_and_validated": True,
        "runtime_manifest_must_be_read_and_validated": True,
        "execution_manifest_must_not_be_read": True,
        "network_must_not_be_accessed": True,
        "official_source_content_must_not_be_read": True,
        "output_must_not_be_created": True,
        "global_writer_must_not_be_claimed": True,
        "visible_launcher_must_not_be_created": True,
        "blocked_cli_exit_code": BLOCKED_EXIT_CODE,
    }


def _safety_contract() -> dict[str, bool]:
    return {
        "network_accessed_while_freezing": False,
        "official_source_content_read_while_freezing": False,
        "execution_manifest_read_while_freezing": False,
        "approval_receipt_created": False,
        "visible_launcher_created": False,
        "global_writer_claim_created": False,
        "topology_output_created": False,
        "request_plan_output_created": False,
        "identity_output_created": False,
        "collector_or_evaluator_run": False,
        "oos_or_returns_or_pnl_read": False,
        "grid_or_retune": False,
        "execution_probe": False,
        "paper_or_live": False,
        "private_api_or_real_capital": False,
        "leverage_or_margin": False,
    }


def build_runtime_manifest(
    *,
    repo_root: str | Path,
    proposal_path: str | Path,
    runtime_module_path: str | Path,
    synthetic_tests_path: str | Path,
    generated_at_utc: str,
) -> dict[str, Any]:
    _validate_timestamp(generated_at_utc, "runtime manifest timestamp")
    root = _validated_repo_root(repo_root)
    proposal, _, _ = _validate_exact_proposal(proposal_path, repo_root=root)
    module_path = _local_repo_path(
        runtime_module_path,
        repo_root=root,
        label="topology runtime module",
    )
    tests_path = _local_repo_path(
        synthetic_tests_path,
        repo_root=root,
        label="topology synthetic tests",
    )
    _require(module_path == RUNTIME_MODULE_PATH, "runtime module path mismatch")
    _require(tests_path == SYNTHETIC_TESTS_PATH, "synthetic tests path mismatch")
    manifest: dict[str, Any] = {
        "schema": RUNTIME_MANIFEST_SCHEMA,
        "status": RUNTIME_MANIFEST_STATUS,
        "generated_at_utc": generated_at_utc,
        "research_only": True,
        "run_id": RUN_ID,
        "proposal": {
            "path": str(PROPOSAL_PATH),
            "file_sha256": PROPOSAL_FILE_SHA256,
            "proposal_hash": PROPOSAL_HASH,
        },
        "parent_discovery": {
            "plan_path": str(PARENT_PLAN_PATH),
            "plan_file_sha256": PARENT_PLAN_FILE_SHA256,
            "plan_hash": PARENT_PLAN_HASH,
            "runtime_path": str(PARENT_RUNTIME_PATH),
            "runtime_file_sha256": PARENT_RUNTIME_FILE_SHA256,
            "runtime_hash": PARENT_RUNTIME_HASH,
        },
        "offline_authorization": _offline_authorization_contract(),
        "runtime": {
            "module_path": str(module_path),
            "module_sha256": _sha256_file(module_path),
            "synthetic_tests_path": str(tests_path),
            "synthetic_tests_sha256": _sha256_file(tests_path),
            "parser_implemented": True,
            "network_adapter_implemented": True,
            "execution_manifest_validator_implemented": True,
            "sanitized_output_writer_implemented": True,
            "visible_launcher_implemented": False,
            "direct_cli_execution_enabled": False,
            "preflight_only_enabled": True,
            "runtime_can_mint_execution_approval": False,
        },
        "source_contract": {
            "exact_seed_urls": list(SEED_URLS),
            "official_hosts": list(OFFICIAL_HOSTS),
            "maximum_total_http_requests": MAX_TOTAL_HTTP_REQUESTS,
            "maximum_attempts_per_url": MAX_ATTEMPTS_PER_URL,
            "maximum_response_bytes_per_request": MAX_RESPONSE_BYTES,
            "max_runtime_sec": MAX_RUNTIME_SEC,
            "hard_output_cap_bytes": HARD_OUTPUT_CAP_BYTES,
            "transport_requirements": _expected_transport_requirements(),
        },
        "sanitized_output_contract": _expected_output_contract(),
        "execution_authorization": _execution_authorization_closed(),
        "preflight_contract": _preflight_contract(),
        "safety": _safety_contract(),
        "manifest_hash_method": "sha256_canonical_json_excluding_manifest_hash",
    }
    _require(
        proposal["topology_discovery_candidate"]["run_id"] == RUN_ID,
        "validated proposal run_id changed",
    )
    manifest["manifest_hash"] = canonical_hash_without(manifest, "manifest_hash")
    return manifest


def validate_runtime_manifest(
    manifest: Mapping[str, Any],
    *,
    repo_root: str | Path,
) -> None:
    expected_fields = {
        "schema",
        "status",
        "generated_at_utc",
        "research_only",
        "run_id",
        "proposal",
        "parent_discovery",
        "offline_authorization",
        "runtime",
        "source_contract",
        "sanitized_output_contract",
        "execution_authorization",
        "preflight_contract",
        "safety",
        "manifest_hash_method",
        "manifest_hash",
    }
    _require(set(manifest) == expected_fields, "runtime manifest field set changed")
    _require(
        manifest.get("schema") == RUNTIME_MANIFEST_SCHEMA, "runtime schema mismatch"
    )
    _require(
        manifest.get("status") == RUNTIME_MANIFEST_STATUS, "runtime status mismatch"
    )
    _require(manifest.get("research_only") is True, "runtime is not research-only")
    _require(manifest.get("run_id") == RUN_ID, "runtime run_id mismatch")
    _validate_timestamp(manifest.get("generated_at_utc"), "runtime manifest timestamp")
    _require(
        manifest.get("manifest_hash_method")
        == "sha256_canonical_json_excluding_manifest_hash",
        "runtime hash method mismatch",
    )
    observed_hash = _require_hash(manifest.get("manifest_hash"), "runtime hash")
    _require(
        observed_hash == canonical_hash_without(manifest, "manifest_hash"),
        "runtime canonical hash mismatch",
    )
    expected = build_runtime_manifest(
        repo_root=repo_root,
        proposal_path=PROPOSAL_PATH,
        runtime_module_path=RUNTIME_MODULE_PATH,
        synthetic_tests_path=SYNTHETIC_TESTS_PATH,
        generated_at_utc=str(manifest["generated_at_utc"]),
    )
    _require(
        dict(manifest) == expected, "runtime manifest code-bound contract mismatch"
    )


def write_runtime_manifest(
    path: str | Path,
    manifest: Mapping[str, Any],
) -> Path:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = _json_file_bytes(manifest)
    try:
        descriptor = os.open(
            output,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
    except FileExistsError:
        existing = _read_bounded_file(output, "existing runtime manifest")
        _require(existing == payload, "immutable runtime manifest already differs")
        return output.resolve()
    try:
        with os.fdopen(descriptor, "wb") as handle:
            _assert_open_handle_path(handle, output)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
            _assert_open_handle_path(handle, output)
    except BaseException:
        try:
            output.unlink(missing_ok=True)
        finally:
            raise
    return output.resolve()


def _header_value(headers: Mapping[str, str], name: str) -> str | None:
    lower_name = name.lower()
    for key, value in headers.items():
        if str(key).lower() == lower_name:
            return str(value)
    return None


def _content_type(response: FetchedResponse) -> str:
    value = _header_value(response.headers, "content-type")
    _require(value is not None, "response content type is missing")
    media_type = value.split(";", 1)[0].strip().lower()
    _require(
        len(media_type.encode("ascii", "ignore")) <= 128, "content type is too long"
    )
    expected: set[str]
    if response.requested_url.endswith("robots.txt"):
        expected = {"text/plain"}
    elif response.requested_url.endswith("sitemap.xml"):
        expected = {"application/xml", "text/xml"}
    else:
        expected = {"text/html", "application/xhtml+xml"}
    _require(media_type in expected, "response content type is not allowlisted")
    return media_type


def _declared_content_length(response: FetchedResponse) -> int | None:
    value = _header_value(response.headers, "content-length")
    if value is None or value == "":
        return None
    _require(value.isascii() and value.isdigit(), "content length is invalid")
    length = int(value)
    _require(length <= MAX_RESPONSE_BYTES, "content length exceeds response cap")
    return length


def _validate_response(response: FetchedResponse, expected_url: str) -> str:
    _require(isinstance(response, FetchedResponse), "fetcher response type is invalid")
    _require(response.requested_url == expected_url, "response request URL mismatch")
    _require(response.final_url == expected_url, "HTTP redirect is forbidden")
    _require(response.status == 200, "official source must return HTTP 200")
    _require(type(response.body) is bytes, "response body must be bytes")
    _require(len(response.body) <= MAX_RESPONSE_BYTES, "response cap exceeded")
    declared = _declared_content_length(response)
    if declared is not None:
        _require(
            declared == len(response.body), "content length does not match response"
        )
    return _content_type(response)


def _decode_body(body: bytes) -> str:
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TopologyDiscoveryError("official topology response is not UTF-8") from exc


def _local_xml_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _extract_candidates(
    response: FetchedResponse,
) -> tuple[list[str], set[str], bool]:
    body = response.body
    url = response.requested_url
    markers: set[str] = set()
    rel_next = False
    if url.endswith("robots.txt"):
        text = _decode_body(body)
        candidates: list[str] = []
        for line in text.splitlines():
            match = _SITEMAP_DIRECTIVE.match(line)
            if match:
                candidates.append(match.group(1))
                if len(candidates) > MAX_DISCOVERED_URLS:
                    raise TopologyDiscoveryError("discovered URL cap exceeded")
        if candidates:
            markers.add("ROBOTS_SITEMAP_DIRECTIVES_PRESENT")
        return candidates, markers, rel_next

    if url.endswith("sitemap.xml"):
        lowered = body.lower()
        _require(b"<!doctype" not in lowered, "XML DOCTYPE is forbidden")
        _require(b"<!entity" not in lowered, "XML ENTITY is forbidden")
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise TopologyDiscoveryError("sitemap XML is invalid") from exc
        root_name = _local_xml_name(root.tag)
        _require(root_name in {"sitemapindex", "urlset"}, "sitemap root is invalid")
        candidates = []
        for element in root.iter():
            if _local_xml_name(element.tag) != "loc":
                continue
            if element.text and element.text.strip():
                candidates.append(element.text.strip())
                if len(candidates) > MAX_DISCOVERED_URLS:
                    raise TopologyDiscoveryError("discovered URL cap exceeded")
        markers.add(
            "SITEMAP_INDEX_FINITE_LOC_SET"
            if root_name == "sitemapindex"
            else "SITEMAP_URLSET_FINITE_LOC_SET"
        )
        return candidates, markers, rel_next

    parser = _TopologyLinkParser()
    try:
        parser.feed(_decode_body(body))
        parser.close()
    except TopologyDiscoveryError:
        raise
    except Exception as exc:
        raise TopologyDiscoveryError("official topology HTML is invalid") from exc
    rel_next = parser.rel_next
    markers.add("HTML_REL_NEXT_PRESENT" if rel_next else "HTML_REL_NEXT_ABSENT_ON_SEED")
    return parser.urls, markers, rel_next


def _canonical_candidate_url(source_url: str, value: str) -> str | None:
    _require(isinstance(value, str), "discovered URL is not a string")
    _require(
        not _CONTROL_CHARACTERS.search(value), "discovered URL has control characters"
    )
    _require(
        len(value.encode("utf-8")) <= MAX_URL_BYTES, "discovered URL byte cap exceeded"
    )
    absolute = urllib.parse.urljoin(source_url, value)
    parsed = urllib.parse.urlsplit(absolute)
    source = urllib.parse.urlsplit(source_url)
    _require(parsed.scheme == "https", "discovered URL is not HTTPS")
    _require(
        parsed.username is None and parsed.password is None,
        "discovered URL has userinfo",
    )
    try:
        port = parsed.port
    except ValueError as exc:
        raise TopologyDiscoveryError("discovered URL port is invalid") from exc
    _require(port in (None, 443), "discovered URL port is not allowlisted")
    if parsed.hostname != source.hostname:
        return None
    _require(parsed.fragment == "", "discovered URL fragment is forbidden")
    decoded_path = urllib.parse.unquote(parsed.path)
    _require("\\" not in decoded_path, "discovered URL backslash is forbidden")
    path_parts = [part for part in decoded_path.split("/") if part]
    _require(
        not any(part in {".", ".."} for part in path_parts),
        "URL dot segment is forbidden",
    )
    try:
        query_items = urllib.parse.parse_qsl(
            parsed.query,
            keep_blank_values=True,
            max_num_fields=32,
        )
    except ValueError as exc:
        raise TopologyDiscoveryError("discovered URL query is invalid") from exc
    for key, item in query_items:
        _require(not _CONTROL_CHARACTERS.search(key + item), "URL query is invalid")
        _require(len(key.encode("utf-8")) <= 128, "URL query key is too long")
        _require(len(item.encode("utf-8")) <= 512, "URL query value is too long")
    query = urllib.parse.urlencode(sorted(query_items), doseq=True)
    canonical = urllib.parse.urlunsplit(
        ("https", parsed.hostname or "", parsed.path or "/", query, "")
    )
    _require(
        len(canonical.encode("utf-8")) <= MAX_URL_BYTES,
        "discovered URL byte cap exceeded",
    )
    return canonical


def _is_index_candidate(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    path = parsed.path.lower()
    name = path.rsplit("/", 1)[-1]
    if path.endswith("/robots.txt") or "sitemap" in name:
        return True
    normalized = path.rstrip("/")
    if parsed.hostname == "www.mexc.com":
        return normalized == "/support/articles"
    if parsed.hostname == "www.gate.com":
        return normalized == "/announcements"
    return False


def _pagination_templates(url: str) -> list[str]:
    parsed = urllib.parse.urlsplit(url)
    query_items = urllib.parse.parse_qsl(
        parsed.query,
        keep_blank_values=True,
        max_num_fields=32,
    )
    templates: list[str] = []
    for index, (key, value) in enumerate(query_items):
        if (
            key.lower() not in _PAGINATION_KEYS
            or not value.isascii()
            or not value.isdigit()
        ):
            continue
        templated = list(query_items)
        templated[index] = (key, "{page}")
        query = urllib.parse.urlencode(sorted(templated), doseq=True)
        query = query.replace("%7Bpage%7D", "{page}").replace("%7bpage%7d", "{page}")
        templates.append(
            urllib.parse.urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, query, "")
            )
        )
    return templates


def _record_for_response(response: FetchedResponse) -> dict[str, Any]:
    content_type = _validate_response(response, response.requested_url)
    raw_candidates, markers, _ = _extract_candidates(response)
    candidate_urls: set[str] = set()
    templates: set[str] = set()
    for raw_candidate in raw_candidates:
        canonical = _canonical_candidate_url(response.requested_url, raw_candidate)
        if canonical is None or not _is_index_candidate(canonical):
            continue
        candidate_urls.add(canonical)
        templates.update(_pagination_templates(canonical))
    _require(len(candidate_urls) <= MAX_DISCOVERED_URLS, "discovered URL cap exceeded")
    if templates:
        markers.add("HTML_NUMERIC_PAGINATION_LINKS_PRESENT")
    if not candidate_urls:
        markers.add("NO_ALLOWLISTED_INDEX_CANDIDATE")
    disposition = (
        "CANDIDATE_TOPOLOGY_FOUND_NOT_EXHAUSTIVENESS_PROOF"
        if candidate_urls or templates
        else "NO_ALLOWLISTED_TOPOLOGY_FOUND"
    )
    _require(
        markers <= ALLOWED_TERMINATION_MARKERS, "termination marker is not allowlisted"
    )
    _require(disposition in ALLOWED_DISPOSITIONS, "topology disposition is invalid")
    record = {
        "source_url": response.requested_url,
        "response_sha256": hashlib.sha256(response.body).hexdigest(),
        "response_bytes": len(response.body),
        "content_type": content_type,
        "same_host_candidate_index_urls": sorted(candidate_urls),
        "same_host_candidate_pagination_templates": sorted(templates),
        "candidate_termination_markers": sorted(markers),
        "disposition": disposition,
    }
    _require(set(record) == ALLOWED_RECORD_FIELDS, "topology record field set changed")
    return record


def _validate_sanitized_result(result: Mapping[str, Any]) -> None:
    expected_fields = {
        "schema",
        "run_id",
        "request_count",
        "records",
        "identity_evidence_created",
        "raw_payload_persisted",
        "topology_success_does_not_prove_exhaustiveness",
        "topology_success_does_not_authorize_identity_runtime",
        "result_hash_method",
        "result_hash",
    }
    _require(set(result) == expected_fields, "sanitized topology field set changed")
    _require(result.get("schema") == SANITIZED_OUTPUT_SCHEMA, "output schema mismatch")
    _require(result.get("run_id") == RUN_ID, "output run_id mismatch")
    _require(
        result.get("request_count") == len(SEED_URLS), "output request count mismatch"
    )
    _require(
        result.get("identity_evidence_created") is False,
        "identity evidence was created",
    )
    _require(result.get("raw_payload_persisted") is False, "raw payload was persisted")
    _require(
        result.get("topology_success_does_not_prove_exhaustiveness") is True,
        "topology result claims exhaustiveness",
    )
    _require(
        result.get("topology_success_does_not_authorize_identity_runtime") is True,
        "topology result authorizes identity runtime",
    )
    records = result.get("records")
    _require(
        isinstance(records, list) and len(records) == len(SEED_URLS),
        "output records are incomplete",
    )
    discovered_count = 0
    for index, record in enumerate(records):
        _require(isinstance(record, dict), "output record is invalid")
        _require(
            set(record) == ALLOWED_RECORD_FIELDS, "output record field set changed"
        )
        _require(
            record.get("source_url") == SEED_URLS[index], "output source order changed"
        )
        _require_hash(record.get("response_sha256"), "response hash")
        _require(
            isinstance(record.get("response_bytes"), int)
            and 0 <= record["response_bytes"] <= MAX_RESPONSE_BYTES,
            "response byte count is invalid",
        )
        candidates = record.get("same_host_candidate_index_urls")
        templates = record.get("same_host_candidate_pagination_templates")
        markers = record.get("candidate_termination_markers")
        _require(isinstance(candidates, list), "candidate URLs are invalid")
        _require(isinstance(templates, list), "pagination templates are invalid")
        _require(isinstance(markers, list), "termination markers are invalid")
        discovered_count += len(candidates)
        _require(discovered_count <= MAX_DISCOVERED_URLS, "discovered URL cap exceeded")
        for candidate in candidates:
            _require(
                _canonical_candidate_url(record["source_url"], candidate) == candidate,
                "candidate URL is not canonical",
            )
            _require(_is_index_candidate(candidate), "non-index URL persisted")
        for template in templates:
            _require(
                isinstance(template, str)
                and "{page}" in template
                and len(template.encode("utf-8")) <= MAX_URL_BYTES,
                "pagination template is invalid",
            )
        _require(
            set(markers) <= ALLOWED_TERMINATION_MARKERS, "termination marker is invalid"
        )
        _require(
            record.get("disposition") in ALLOWED_DISPOSITIONS, "disposition is invalid"
        )
    _require(
        result.get("result_hash_method")
        == "sha256_canonical_json_excluding_result_hash",
        "output result hash method mismatch",
    )
    result_hash = _require_hash(result.get("result_hash"), "output result hash")
    _require(
        result_hash == canonical_hash_without(result, "result_hash"),
        "output result canonical hash mismatch",
    )


def analyze_topology_responses(
    responses: Sequence[FetchedResponse],
) -> dict[str, Any]:
    observed_order = tuple(response.requested_url for response in responses)
    _require(observed_order == SEED_URLS, "responses do not match exact seed order")
    records = [_record_for_response(response) for response in responses]
    discovered_count = sum(
        len(record["same_host_candidate_index_urls"]) for record in records
    )
    _require(discovered_count <= MAX_DISCOVERED_URLS, "discovered URL cap exceeded")
    result: dict[str, Any] = {
        "schema": SANITIZED_OUTPUT_SCHEMA,
        "run_id": RUN_ID,
        "request_count": len(responses),
        "records": records,
        "identity_evidence_created": False,
        "raw_payload_persisted": False,
        "topology_success_does_not_prove_exhaustiveness": True,
        "topology_success_does_not_authorize_identity_runtime": True,
        "result_hash_method": "sha256_canonical_json_excluding_result_hash",
    }
    result["result_hash"] = canonical_hash_without(result, "result_hash")
    _validate_sanitized_result(result)
    return result


def _exact_authorized_scope() -> dict[str, bool]:
    return {
        "one_visible_public_read_only_topology_run": True,
        "official_source_content_read": True,
        "sanitized_topology_output": True,
        "global_writer_claim": True,
        "collector_or_evaluator": False,
        "oos_or_returns_or_pnl": False,
        "grid_or_retune": False,
        "execution_probe": False,
        "paper_or_live": False,
        "private_api_or_real_capital": False,
        "leverage_or_margin": False,
    }


def _exact_execution_limits() -> dict[str, int]:
    return {
        "maximum_total_http_requests": MAX_TOTAL_HTTP_REQUESTS,
        "maximum_attempts_per_url": MAX_ATTEMPTS_PER_URL,
        "maximum_response_bytes_per_request": MAX_RESPONSE_BYTES,
        "max_runtime_sec": MAX_RUNTIME_SEC,
        "hard_output_cap_bytes": HARD_OUTPUT_CAP_BYTES,
    }


def _validate_execution_receipt(
    receipt: Mapping[str, Any],
    *,
    runtime_binding: Mapping[str, Any],
    expected_user_approval_text: str,
) -> None:
    expected_fields = {
        "schema",
        "status",
        "approved_at_utc",
        "user_approval_text",
        "approval_provenance",
        "runtime_manifest",
        "run_id",
        "exact_seed_urls",
        "authorized_scope",
        "limits",
        "output_path",
        "single_use",
        "stopped_incomplete_retry_authorized",
        "receipt_hash_method",
        "receipt_hash",
    }
    _require(set(receipt) == expected_fields, "execution receipt field set changed")
    _require(
        receipt.get("schema") == EXECUTION_RECEIPT_SCHEMA,
        "execution receipt schema mismatch",
    )
    _require(
        receipt.get("status") == "APPROVED_SINGLE_USE",
        "execution receipt is not approved",
    )
    _validate_timestamp(receipt.get("approved_at_utc"), "execution approval timestamp")
    _require(
        receipt.get("user_approval_text") == expected_user_approval_text,
        "execution approval text mismatch",
    )
    provenance = receipt.get("approval_provenance")
    _require(
        provenance
        == {
            "mode": "MANUAL_CODEX_CHECKPOINT_AFTER_DIRECT_USER_APPROVAL",
            "runtime_minting_allowed": False,
            "launcher_minting_allowed": False,
        },
        "execution approval provenance is invalid",
    )
    _require(
        receipt.get("runtime_manifest") == dict(runtime_binding),
        "execution receipt runtime binding mismatch",
    )
    _require(receipt.get("run_id") == RUN_ID, "execution receipt run_id mismatch")
    _require(
        receipt.get("exact_seed_urls") == list(SEED_URLS),
        "execution receipt seed URLs mismatch",
    )
    _require(
        receipt.get("authorized_scope") == _exact_authorized_scope(),
        "execution receipt scope mismatch",
    )
    _require(
        receipt.get("limits") == _exact_execution_limits(),
        "execution receipt limits mismatch",
    )
    _require(
        isinstance(receipt.get("output_path"), str)
        and Path(receipt["output_path"]).is_absolute(),
        "execution receipt output path is invalid",
    )
    _require(receipt.get("single_use") is True, "execution receipt is not single-use")
    _require(
        receipt.get("stopped_incomplete_retry_authorized") is False,
        "STOPPED_INCOMPLETE retry is enabled",
    )
    _require(
        receipt.get("receipt_hash_method")
        == "sha256_canonical_json_excluding_receipt_hash",
        "execution receipt hash method mismatch",
    )
    receipt_hash = _require_hash(receipt.get("receipt_hash"), "execution receipt hash")
    _require(
        receipt_hash == canonical_hash_without(receipt, "receipt_hash"),
        "execution receipt canonical hash mismatch",
    )
    required_tokens = [
        RUN_ID,
        str(runtime_binding["file_sha256"]),
        str(runtime_binding["manifest_hash"]),
        *SEED_URLS,
        str(MAX_TOTAL_HTTP_REQUESTS),
        str(MAX_RUNTIME_SEC),
        str(HARD_OUTPUT_CAP_BYTES),
        str(receipt["output_path"]),
    ]
    approval_text = str(receipt["user_approval_text"])
    for token in required_tokens:
        _require(token in approval_text, "execution approval text is incomplete")


def validate_execution_manifest(
    execution_manifest: Mapping[str, Any],
    *,
    runtime_manifest: Mapping[str, Any],
    repo_root: str | Path,
    approval_receipt_snapshot: Mapping[str, Any] | None = None,
    approval_receipt_file_sha256: str | None = None,
) -> TopologyExecutionCapability:
    validate_runtime_manifest(runtime_manifest, repo_root=repo_root)
    expected_fields = {
        "schema",
        "status",
        "execution_authorized",
        "execution_approval",
        "runtime_manifest",
        "run_id",
        "exact_seed_urls",
        "authorized_scope",
        "limits",
        "output_path",
        "single_use",
        "stopped_incomplete_retry_authorized",
        "manifest_hash_method",
        "manifest_hash",
    }
    _require(
        set(execution_manifest) == expected_fields,
        "execution manifest field set changed",
    )
    _require(
        execution_manifest.get("schema") == EXECUTION_MANIFEST_SCHEMA,
        "execution schema mismatch",
    )
    _require(
        execution_manifest.get("status") == EXECUTION_APPROVED_STATUS,
        "exact execution approval is missing",
    )
    _require(
        execution_manifest.get("execution_authorized") is True,
        "exact execution approval is missing",
    )
    _require(execution_manifest.get("run_id") == RUN_ID, "execution run_id mismatch")
    _require(
        execution_manifest.get("exact_seed_urls") == list(SEED_URLS),
        "execution seed URLs mismatch",
    )
    _require(
        execution_manifest.get("authorized_scope") == _exact_authorized_scope(),
        "execution scope mismatch",
    )
    _require(
        execution_manifest.get("limits") == _exact_execution_limits(),
        "execution limits mismatch",
    )
    _require(
        isinstance(execution_manifest.get("output_path"), str),
        "execution output path is invalid",
    )
    validated_output_path = _validated_local_output_path(
        str(execution_manifest["output_path"]),
        label="execution output path",
    )
    _require(
        execution_manifest.get("single_use") is True, "execution is not single-use"
    )
    _require(
        execution_manifest.get("stopped_incomplete_retry_authorized") is False,
        "STOPPED_INCOMPLETE retry is enabled",
    )
    _require(
        execution_manifest.get("manifest_hash_method")
        == "sha256_canonical_json_excluding_manifest_hash",
        "execution hash method mismatch",
    )
    execution_hash = _require_hash(
        execution_manifest.get("manifest_hash"), "execution manifest hash"
    )
    _require(
        execution_hash == canonical_hash_without(execution_manifest, "manifest_hash"),
        "execution manifest canonical hash mismatch",
    )

    runtime_binding = execution_manifest.get("runtime_manifest")
    _require(isinstance(runtime_binding, dict), "execution runtime binding is missing")
    _require(
        set(runtime_binding) == {"path", "file_sha256", "manifest_hash"},
        "execution runtime binding field set changed",
    )
    runtime_path = _local_repo_path(
        str(runtime_binding.get("path", "")),
        repo_root=repo_root,
        label="code-bound topology runtime manifest",
    )
    _require(runtime_path == RUNTIME_MANIFEST_PATH, "execution runtime path mismatch")
    runtime_file_sha256 = _require_hash(
        runtime_binding.get("file_sha256"),
        "execution runtime file hash",
    )
    _require(
        _sha256_file(runtime_path) == runtime_file_sha256,
        "execution runtime file hash mismatch",
    )
    _require(
        runtime_binding.get("manifest_hash") == runtime_manifest.get("manifest_hash"),
        "execution runtime canonical hash mismatch",
    )
    loaded_runtime = _strict_json_loads(
        _read_bounded_file(runtime_path, "code-bound topology runtime manifest"),
        "code-bound topology runtime manifest",
    )
    _require(
        loaded_runtime == dict(runtime_manifest), "execution runtime snapshot mismatch"
    )

    approval = execution_manifest.get("execution_approval")
    _require(isinstance(approval, dict), "execution approval binding is missing")
    _require(
        set(approval)
        == {
            "status",
            "path",
            "file_sha256",
            "receipt_hash",
            "user_approval_text",
            "approved_at_utc",
        },
        "execution approval binding field set changed",
    )
    _require(approval.get("status") == "APPROVED", "execution approval is missing")
    _validate_timestamp(approval.get("approved_at_utc"), "execution approval timestamp")
    _require(
        isinstance(approval.get("user_approval_text"), str)
        and bool(approval["user_approval_text"].strip()),
        "execution approval text is missing",
    )
    expected_receipt_file_sha256 = _require_hash(
        approval.get("file_sha256"),
        "execution approval receipt file hash",
    )
    if approval_receipt_snapshot is None:
        receipt_path = _local_repo_path(
            str(approval.get("path", "")),
            repo_root=repo_root,
            label="execution approval receipt",
        )
        receipt_raw = _read_bounded_file(receipt_path, "execution approval receipt")
        observed_receipt_file_sha256 = hashlib.sha256(receipt_raw).hexdigest()
        receipt = _strict_json_loads(receipt_raw, "execution approval receipt")
    else:
        receipt = dict(approval_receipt_snapshot)
        observed_receipt_file_sha256 = approval_receipt_file_sha256
    _require(
        observed_receipt_file_sha256 == expected_receipt_file_sha256,
        "execution approval receipt file hash mismatch",
    )
    _validate_execution_receipt(
        receipt,
        runtime_binding=runtime_binding,
        expected_user_approval_text=str(approval["user_approval_text"]),
    )
    _require(
        receipt.get("receipt_hash") == approval.get("receipt_hash"),
        "execution receipt hash binding mismatch",
    )
    _require(
        receipt.get("approved_at_utc") == approval.get("approved_at_utc"),
        "execution approval timestamp binding mismatch",
    )
    _require(
        receipt.get("output_path") == str(validated_output_path),
        "execution output path binding mismatch",
    )
    return TopologyExecutionCapability(
        run_id=RUN_ID,
        runtime_manifest_hash=str(runtime_manifest["manifest_hash"]),
        execution_manifest_hash=execution_hash,
        output_path=str(validated_output_path),
        _budget=_ExecutionBudget(started_monotonic=monotonic()),
        _sentinel=_CAPABILITY_SENTINEL,
    )


def _require_execution_capability(
    capability: TopologyExecutionCapability | None,
) -> TopologyExecutionCapability:
    _require(
        isinstance(capability, TopologyExecutionCapability)
        and capability._sentinel is _CAPABILITY_SENTINEL
        and capability.run_id == RUN_ID
        and isinstance(capability._budget, _ExecutionBudget),
        "valid external execution capability is required",
    )
    return capability


def fetch_official_topology_response(
    url: str,
    *,
    capability: TopologyExecutionCapability | None,
    deadline_monotonic: float,
    opener: Any | None = None,
    clock: Callable[[], float] = monotonic,
) -> FetchedResponse:
    validated_capability = _require_execution_capability(capability)
    _require(url in SEED_URLS, "request URL is not an exact seed URL")
    effective_deadline = validated_capability._budget.reserve(
        url,
        requested_deadline_monotonic=deadline_monotonic,
        clock=clock,
    )
    remaining = effective_deadline - clock()
    _require(remaining > 0, "topology runtime deadline exceeded")
    timeout = min(20.0, remaining)
    request = urllib.request.Request(
        url,
        method="GET",
        headers={
            "User-Agent": "trading-mvp-currentness-topology/1.0",
            "Accept": "text/plain,application/xml,text/xml,text/html,application/xhtml+xml",
        },
    )
    _require(
        request.data is None and request.get_method() == "GET",
        "request is not read-only GET",
    )
    transport = opener or urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoRedirectHandler(),
    )
    try:
        with transport.open(request, timeout=timeout) as response:
            final_url = str(response.geturl())
            status = int(response.status)
            _require(final_url == url, "HTTP redirect is forbidden")
            _require(status == 200, "official source must return HTTP 200")
            content_length = response.headers.get("content-length")
            if content_length not in (None, ""):
                _require(
                    str(content_length).isascii() and str(content_length).isdigit(),
                    "content length is invalid",
                )
                _require(
                    int(str(content_length)) <= MAX_RESPONSE_BYTES,
                    "content length exceeds response cap",
                )
            content_encoding = response.headers.get("content-encoding")
            _require(
                content_encoding in (None, "", "identity"),
                "compressed response encoding is forbidden",
            )
            body_parts: list[bytes] = []
            body_bytes = 0
            while True:
                _require(
                    clock() < effective_deadline, "topology runtime deadline exceeded"
                )
                chunk = response.read(READ_CHUNK_BYTES)
                if not chunk:
                    break
                _require(type(chunk) is bytes, "response chunk is invalid")
                body_bytes += len(chunk)
                _require(body_bytes <= MAX_RESPONSE_BYTES, "response cap exceeded")
                body_parts.append(chunk)
            _require(
                clock() <= effective_deadline, "topology runtime deadline exceeded"
            )
            headers = {
                "content-type": str(response.headers.get("content-type") or ""),
                "content-length": str(content_length or body_bytes),
            }
    except TopologyDiscoveryError:
        raise
    except urllib.error.HTTPError as exc:
        if 300 <= exc.code < 400:
            raise TopologyDiscoveryError("HTTP redirect is forbidden") from exc
        raise TopologyDiscoveryError("official topology HTTP request failed") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise TopologyDiscoveryError("official topology HTTP request failed") from exc
    fetched = FetchedResponse(
        requested_url=url,
        final_url=final_url,
        status=status,
        headers=headers,
        body=b"".join(body_parts),
    )
    _validate_response(fetched, url)
    return fetched


def collect_topology_responses(
    *,
    capability: TopologyExecutionCapability | None,
    fetcher: Callable[..., FetchedResponse] = fetch_official_topology_response,
    clock: Callable[[], float] = monotonic,
) -> dict[str, Any]:
    validated_capability = _require_execution_capability(capability)
    deadline = validated_capability._budget.deadline_monotonic
    responses: list[FetchedResponse] = []
    for url in SEED_URLS:
        _require(clock() < deadline, "topology runtime deadline exceeded")
        responses.append(
            fetcher(
                url,
                capability=validated_capability,
                deadline_monotonic=deadline,
            )
        )
    _require(len(responses) <= MAX_TOTAL_HTTP_REQUESTS, "request cap exceeded")
    _require(clock() <= deadline, "topology runtime deadline exceeded")
    return analyze_topology_responses(responses)


def _write_exclusive(path: Path, payload: bytes) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
        0o600,
    )
    with os.fdopen(descriptor, "wb") as handle:
        _assert_open_handle_path(handle, path)
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        _assert_open_handle_path(handle, path)


def write_sanitized_topology_bundle(
    output_path: str | Path,
    result: Mapping[str, Any],
    *,
    capability: TopologyExecutionCapability | None,
) -> dict[str, Any]:
    validated_capability = _require_execution_capability(capability)
    _validate_sanitized_result(result)
    root = _validated_local_output_path(output_path, label="topology output path")
    _require(
        root == Path(validated_capability.output_path),
        "topology output path does not match execution approval",
    )
    _require(not root.exists(), "topology output path already exists")
    topology_payload = _json_file_bytes(result)
    _require(
        len(topology_payload) <= HARD_OUTPUT_CAP_BYTES, "topology output cap exceeded"
    )
    manifest: dict[str, Any] = {
        "schema": SANITIZED_OUTPUT_MANIFEST_SCHEMA,
        "status": "COMPLETE_SANITIZED_TOPOLOGY_NOT_IDENTITY_EVIDENCE",
        "run_id": RUN_ID,
        "execution_manifest_hash": validated_capability.execution_manifest_hash,
        "runtime_manifest_hash": validated_capability.runtime_manifest_hash,
        "topology_file": {
            "name": "topology.json",
            "file_sha256": hashlib.sha256(topology_payload).hexdigest(),
            "bytes": len(topology_payload),
            "result_hash": result["result_hash"],
        },
        "raw_payload_persisted": False,
        "identity_evidence_created": False,
        "request_plan_created": False,
        "currentness_verdict_created": False,
        "manifest_hash_method": "sha256_canonical_json_excluding_manifest_hash",
    }
    manifest["manifest_hash"] = canonical_hash_without(manifest, "manifest_hash")
    manifest_payload = _json_file_bytes(manifest)
    _require(
        len(topology_payload) + len(manifest_payload) <= HARD_OUTPUT_CAP_BYTES,
        "topology output cap exceeded",
    )
    root.mkdir(parents=False, exist_ok=False)
    try:
        _write_exclusive(root / "topology.json", topology_payload)
        _write_exclusive(root / "manifest.json", manifest_payload)
    except BaseException:
        for child in (root / "manifest.json", root / "topology.json"):
            child.unlink(missing_ok=True)
        root.rmdir()
        raise
    return manifest


def preflight_only(
    *,
    repo_root: str | Path,
    proposal_path: str | Path,
    runtime_manifest_path: str | Path,
    execution_manifest_path: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    root = Path(repo_root).resolve()
    _validate_exact_proposal(proposal_path, repo_root=root)
    runtime_path = _local_repo_path(
        runtime_manifest_path,
        repo_root=root,
        label="code-bound topology runtime manifest",
    )
    _require(runtime_path == RUNTIME_MANIFEST_PATH, "runtime manifest path mismatch")
    runtime_raw = _read_bounded_file(
        runtime_path, "code-bound topology runtime manifest"
    )
    runtime = _strict_json_loads(runtime_raw, "code-bound topology runtime manifest")
    validate_runtime_manifest(runtime, repo_root=root)
    execution_path = Path(execution_manifest_path).expanduser()
    if not execution_path.is_absolute():
        execution_path = root / execution_path
    output = Path(output_path).expanduser()
    if not output.is_absolute():
        output = root / output
    return {
        "status": "BLOCKED_AWAIT_EXACT_TOPOLOGY_EXECUTION_APPROVAL",
        "reason": "offline runtime is frozen; separate exact network execution approval is required",
        "run_id": RUN_ID,
        "proposal_path": str(PROPOSAL_PATH),
        "proposal_file_sha256": PROPOSAL_FILE_SHA256,
        "proposal_hash": PROPOSAL_HASH,
        "runtime_manifest_path": str(runtime_path),
        "runtime_manifest_file_sha256": hashlib.sha256(runtime_raw).hexdigest(),
        "runtime_manifest_hash": runtime["manifest_hash"],
        "execution_manifest_path": str(execution_path),
        "output_path": str(output),
        "network_accessed": False,
        "official_source_content_read": False,
        "execution_manifest_read": False,
        "output_created": False,
        "global_writer_claim_created": False,
        "visible_launcher_created": False,
        "separate_exact_execution_approval_required": True,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    freeze = subparsers.add_parser("freeze-runtime")
    freeze.add_argument("--repo-root", required=True)
    freeze.add_argument("--proposal", required=True)
    freeze.add_argument("--runtime-module", required=True)
    freeze.add_argument("--synthetic-tests", required=True)
    freeze.add_argument("--generated-at-utc", required=True)
    freeze.add_argument("--output", required=True)

    validate = subparsers.add_parser("validate-runtime")
    validate.add_argument("--repo-root", required=True)
    validate.add_argument("--runtime-manifest", required=True)

    preflight = subparsers.add_parser("preflight")
    preflight.add_argument("--repo-root", required=True)
    preflight.add_argument("--proposal", required=True)
    preflight.add_argument("--runtime-manifest", required=True)
    preflight.add_argument("--execution-manifest", required=True)
    preflight.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.command == "freeze-runtime":
        manifest = build_runtime_manifest(
            repo_root=args.repo_root,
            proposal_path=args.proposal,
            runtime_module_path=args.runtime_module,
            synthetic_tests_path=args.synthetic_tests,
            generated_at_utc=args.generated_at_utc,
        )
        output_path = _local_repo_path(
            args.output,
            repo_root=args.repo_root,
            label="canonical topology runtime manifest output",
            must_exist=False,
        )
        _require(
            output_path == RUNTIME_MANIFEST_PATH,
            "runtime manifest output path mismatch",
        )
        output = write_runtime_manifest(output_path, manifest)
        payload = {
            "status": RUNTIME_MANIFEST_STATUS,
            "runtime_manifest_path": str(output),
            "runtime_manifest_file_sha256": _sha256_file(output),
            "runtime_manifest_hash": manifest["manifest_hash"],
            "network_accessed": False,
            "official_source_content_read": False,
            "approval_receipt_created": False,
            "visible_launcher_created": False,
            "topology_output_created": False,
        }
        exit_code = 0
    elif args.command == "validate-runtime":
        runtime_path = _local_repo_path(
            args.runtime_manifest,
            repo_root=args.repo_root,
            label="code-bound topology runtime manifest",
        )
        raw = _read_bounded_file(runtime_path, "code-bound topology runtime manifest")
        manifest = _strict_json_loads(raw, "code-bound topology runtime manifest")
        validate_runtime_manifest(manifest, repo_root=args.repo_root)
        payload = {
            "status": "VALID_CODE_BOUND_RUNTIME_EXECUTION_CLOSED",
            "runtime_manifest_path": str(runtime_path),
            "runtime_manifest_file_sha256": hashlib.sha256(raw).hexdigest(),
            "runtime_manifest_hash": manifest["manifest_hash"],
        }
        exit_code = 0
    else:
        payload = preflight_only(
            repo_root=args.repo_root,
            proposal_path=args.proposal,
            runtime_manifest_path=args.runtime_manifest,
            execution_manifest_path=args.execution_manifest,
            output_path=args.output,
        )
        exit_code = BLOCKED_EXIT_CODE
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ALLOWED_RECORD_FIELDS",
    "BLOCKED_EXIT_CODE",
    "EXECUTION_APPROVED_STATUS",
    "EXECUTION_MANIFEST_SCHEMA",
    "EXECUTION_RECEIPT_SCHEMA",
    "FetchedResponse",
    "HARD_OUTPUT_CAP_BYTES",
    "MAX_DISCOVERED_URLS",
    "MAX_RESPONSE_BYTES",
    "MAX_RUNTIME_SEC",
    "MAX_TOTAL_HTTP_REQUESTS",
    "PARENT_PLAN_FILE_SHA256",
    "PARENT_PLAN_HASH",
    "PARENT_RUNTIME_FILE_SHA256",
    "PARENT_RUNTIME_HASH",
    "PROPOSAL_FILE_SHA256",
    "PROPOSAL_HASH",
    "RUN_ID",
    "RUNTIME_MANIFEST_SCHEMA",
    "RUNTIME_MANIFEST_STATUS",
    "SEED_URLS",
    "TopologyDiscoveryError",
    "TopologyExecutionCapability",
    "analyze_topology_responses",
    "build_runtime_manifest",
    "canonical_hash_without",
    "collect_topology_responses",
    "fetch_official_topology_response",
    "preflight_only",
    "validate_execution_manifest",
    "validate_runtime_manifest",
    "write_runtime_manifest",
    "write_sanitized_topology_bundle",
]
