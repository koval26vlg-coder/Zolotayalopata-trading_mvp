from __future__ import annotations

import ast
import copy
import hashlib
import importlib
import json
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest import mock

from trading_mvp.src.slow_liquidity_identity_currentness_refreeze_proposal import (
    BASES,
    PARENT_PLAN_FILE_SHA256,
    PARENT_PLAN_HASH,
    PARENT_PLAN_PATH,
    PARENT_RUNTIME_FILE_SHA256,
    PARENT_RUNTIME_HASH,
    ProposalError,
    build_proposal,
    canonical_proposal_hash,
    preflight_future_execution,
    validate_proposal,
    write_proposal,
)


ROOT = Path(__file__).resolve().parents[2]
CHECKED_IN = (
    ROOT
    / "docs/plans/drafts/slow-liquidity-identity-currentness-refreeze-"
    "proposal-20260813-v7.json"
)
GENERATED_AT = "2026-08-13T20:15:00Z"

OFFLINE_CHILD_SCRIPT = textwrap.dedent(
    r"""
    import contextlib
    import http.client
    import importlib
    import os
    import socket
    import subprocess
    import sys
    import urllib.request
    from pathlib import Path
    from unittest import mock

    repo_root = Path(sys.argv[1]).resolve()
    proposal_path = Path(sys.argv[2]).resolve()
    execution_path = Path(sys.argv[3]).resolve()
    output_path = Path(sys.argv[4]).resolve()
    generated_at = sys.argv[5]
    blocked = AssertionError("offline proposal attempted network or child process")

    patchers = [
        mock.patch.object(socket, "socket", side_effect=blocked),
        mock.patch.object(socket, "create_connection", side_effect=blocked),
        mock.patch.object(socket, "getaddrinfo", side_effect=blocked),
        mock.patch.object(socket, "gethostbyname", side_effect=blocked),
        mock.patch.object(socket, "gethostbyname_ex", side_effect=blocked),
        mock.patch.object(socket, "gethostbyaddr", side_effect=blocked),
        mock.patch.object(socket, "getnameinfo", side_effect=blocked),
        mock.patch.object(urllib.request, "urlopen", side_effect=blocked),
        mock.patch.object(urllib.request.OpenerDirector, "open", side_effect=blocked),
        mock.patch.object(http.client.HTTPConnection, "connect", side_effect=blocked),
        mock.patch.object(http.client.HTTPSConnection, "connect", side_effect=blocked),
        mock.patch.object(subprocess, "Popen", side_effect=blocked),
        mock.patch.object(os, "system", side_effect=blocked),
        mock.patch.object(os, "popen", side_effect=blocked),
    ]
    for name in (
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
    ):
        if hasattr(os, name):
            patchers.append(mock.patch.object(os, name, side_effect=blocked))

    with contextlib.ExitStack() as stack:
        for patcher in patchers:
            stack.enter_context(patcher)
        module = importlib.import_module(
            "trading_mvp.src."
            "slow_liquidity_identity_currentness_refreeze_proposal"
        )
        proposal = module.build_proposal(repo_root, generated_at)
        module.validate_proposal(proposal, repo_root)
        result = module.preflight_future_execution(
            proposal_path=proposal_path,
            execution_manifest_path=execution_path,
            output_path=output_path,
            repo_root=repo_root,
        )
        if result["network_accessed"]:
            raise AssertionError("preflight reported network access")
        if result["execution_manifest_read"] or result["output_created"]:
            raise AssertionError("preflight crossed a forbidden file boundary")
        sys.argv = [
            module.__name__,
            "preflight",
            "--repo-root",
            str(repo_root),
            "--proposal",
            str(proposal_path),
            "--execution-manifest",
            str(execution_path),
            "--output",
            str(output_path),
        ]
        raise SystemExit(module.main())
    """
)


class HistoricalIdentityCurrentnessProposalTests(unittest.TestCase):
    def test_checked_in_proposal_is_canonical_and_explicitly_stale(self) -> None:
        checked_in = json.loads(CHECKED_IN.read_text(encoding="utf-8"))
        bound_identity_path = Path(
            checked_in["code_bindings"]["parent_identity_validator_path"]
        )
        current_identity_sha256 = hashlib.sha256(
            bound_identity_path.read_bytes()
        ).hexdigest()

        self.assertEqual(
            checked_in["proposal_hash"], canonical_proposal_hash(checked_in)
        )
        self.assertNotEqual(
            current_identity_sha256,
            checked_in["code_bindings"]["parent_identity_validator_sha256"],
        )
        with self.assertRaisesRegex(
            ProposalError, "parent_identity_validator file hash changed"
        ):
            build_proposal(ROOT, GENERATED_AT)


class SlowLiquidityIdentityCurrentnessRefreezeProposalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            cls.proposal = build_proposal(ROOT, GENERATED_AT)
        except ProposalError as exc:
            if str(exc) == "parent_identity_validator file hash changed":
                raise unittest.SkipTest(
                    "historical topology proposal is superseded by identity runtime v7"
                ) from exc
            raise

    def test_proposal_is_hash_bound_planonly(self) -> None:
        proposal = self.proposal
        self.assertEqual(proposal["mode"], "PlanOnlyReviewProposal")
        self.assertEqual(
            proposal["status"],
            "BLOCKED_CURRENTNESS_FEASIBILITY_UNPROVEN",
        )
        self.assertEqual(proposal["proposal_hash"], canonical_proposal_hash(proposal))
        self.assertEqual(
            proposal["parent_discovery"]["plan_file_sha256"],
            PARENT_PLAN_FILE_SHA256,
        )
        self.assertEqual(
            proposal["parent_discovery"]["plan_hash"], PARENT_PLAN_HASH
        )
        self.assertEqual(
            proposal["parent_discovery"]["runtime_file_sha256"],
            PARENT_RUNTIME_FILE_SHA256,
        )
        self.assertEqual(
            proposal["parent_discovery"]["runtime_hash"], PARENT_RUNTIME_HASH
        )
        validate_proposal(proposal, ROOT)

    def test_complete_first_party_validator_closure_is_hash_bound(self) -> None:
        bindings = self.proposal["code_bindings"]
        prefixes = {
            "proposal_generator",
            "synthetic_tests",
            "guard_checker",
            "parent_discovery_validator",
            "parent_identity_validator",
            "parent_identity_proposal_validator",
        }
        self.assertEqual(
            set(bindings),
            {
                field
                for prefix in prefixes
                for field in (f"{prefix}_path", f"{prefix}_sha256")
            },
        )
        for prefix in prefixes:
            path = Path(bindings[f"{prefix}_path"])
            self.assertTrue(path.is_file(), prefix)
            self.assertEqual(len(bindings[f"{prefix}_sha256"]), 64)

    def test_parent_validation_executes_no_transitive_module(self) -> None:
        source_path = Path(self.proposal["code_bindings"]["proposal_generator_path"])
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        forbidden_modules = {
            "slow_liquidity_identity_request_plan_discovery",
            "slow_liquidity_official_identity_verification",
            "slow_liquidity_official_identity_proposal",
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                self.assertTrue(
                    forbidden_modules.isdisjoint(node.module.split(".")),
                    node.module,
                )

        with (
            mock.patch.object(
                importlib,
                "import_module",
                side_effect=AssertionError("transitive validator import attempted"),
            ),
            mock.patch.object(
                importlib,
                "reload",
                side_effect=AssertionError("transitive validator reload attempted"),
            ),
        ):
            proposal = build_proposal(ROOT, GENERATED_AT)
            validate_proposal(proposal, ROOT)
        self.assertFalse(proposal["parent_discovery"]["parent_validator_code_executed"])

    def test_exact_parent_hash_is_checked_before_json_parse(self) -> None:
        module = sys.modules[build_proposal.__module__]
        with tempfile.TemporaryDirectory() as temp_dir:
            payload = Path(temp_dir) / "tampered-parent.json"
            payload.write_bytes(b"{")
            with mock.patch.object(
                module.json,
                "loads",
                side_effect=AssertionError("JSON parsed before exact hash check"),
            ):
                with self.assertRaisesRegex(ProposalError, "file hash changed"):
                    module._read_exact_json(payload, "tampered parent", "0" * 64)

    def test_parent_reparse_path_is_rejected_before_open(self) -> None:
        module = sys.modules[build_proposal.__module__]
        real_isjunction = getattr(module.os.path, "isjunction", lambda _path: False)
        target = module.os.path.normcase(module.os.path.abspath(PARENT_PLAN_PATH))

        def fake_isjunction(path: str | Path) -> bool:
            observed = module.os.path.normcase(module.os.path.abspath(path))
            return observed == target or real_isjunction(path)

        with (
            mock.patch.object(
                module.os.path,
                "isjunction",
                side_effect=fake_isjunction,
                create=True,
            ),
            mock.patch.object(
                Path,
                "open",
                side_effect=AssertionError("parent opened before reparse rejection"),
            ),
        ):
            with self.assertRaisesRegex(ProposalError, "reparse path is forbidden"):
                build_proposal(ROOT, GENERATED_AT)

    def test_scope_preserved_and_parent_budget_is_proven_exhausted(self) -> None:
        scope = self.proposal["scope"]
        feasibility = self.proposal["feasibility_assessment"]
        self.assertEqual(scope["bases"], list(BASES))
        self.assertEqual(scope["venues"], ["mexc", "gateio"])
        self.assertEqual(scope["required_pair_count"], 18)
        self.assertEqual(feasibility["parent_request_cap"], 38)
        self.assertEqual(feasibility["baseline_metadata_requests"], 2)
        self.assertEqual(feasibility["baseline_navigation_requests"], 18)
        self.assertEqual(feasibility["baseline_official_page_requests"], 18)
        self.assertEqual(feasibility["baseline_required_requests"], 38)
        self.assertEqual(feasibility["remaining_requests_for_lineage_or_topology"], 0)
        self.assertFalse(feasibility["complete_currentness_feasible_under_parent_cap"])
        self.assertFalse(feasibility["implementation_approval_safe_now"])
        self.assertFalse(feasibility["execution_approval_safe_now"])

    def test_target_identity_requirements_close_reviewed_gaps(self) -> None:
        contract = self.proposal["target_identity_requirements"]
        self.assertFalse(contract["bing_result_is_currentness_evidence"])
        self.assertFalse(contract["search_snippet_is_identity_evidence"])
        self.assertTrue(contract["active_metadata_snapshot_same_run_required"])
        self.assertEqual(contract["metadata_http_age_header_max_sec"], 60)
        self.assertEqual(contract["metadata_http_date_max_clock_skew_sec"], 300)
        self.assertFalse(contract["local_or_intermediate_cache_reuse_allowed"])
        self.assertIn(
            "metadata_record_locator_value",
            contract["direct_linkage_evidence_fields_required"],
        )
        self.assertTrue(contract["official_effective_timestamp_required"])
        self.assertTrue(contract["exact_instrument_and_identifier_same_fragment_required"])
        self.assertTrue(contract["complete_official_identity_event_lineage_required"])
        self.assertEqual(contract["canonical_chain_namespace_required"], "CAIP_2")
        self.assertFalse(contract["wrapped_or_bridged_equivalence_allowed"])
        self.assertFalse(contract["independent_later_replay_possible_under_parent_contract"])
        self.assertTrue(contract["reproducible_provenance_contract_change_required"])
        self.assertEqual(
            contract["missing_direct_metadata_page_link_disposition"],
            "UNRESOLVED_FAIL_CLOSED",
        )
        self.assertEqual(
            contract["non_exhaustive_official_index_disposition"],
            "UNRESOLVED_FAIL_CLOSED",
        )
        self.assertEqual(
            contract["later_migration_or_relisting_ambiguity_disposition"],
            "UNRESOLVED_FAIL_CLOSED",
        )
        self.assertFalse(contract["real_complete_status_enabled_now"])

    def test_topology_candidate_is_bounded_and_not_implemented(self) -> None:
        candidate = self.proposal["topology_discovery_candidate"]
        transport = candidate["transport_requirements"]
        self.assertEqual(candidate["maximum_total_http_requests"], 6)
        self.assertEqual(len(candidate["exact_seed_urls"]), 6)
        self.assertEqual(candidate["max_runtime_sec"], 300)
        self.assertEqual(candidate["hard_output_cap_bytes"], 10_000_000)
        self.assertTrue(transport["streaming_body_limit_required"])
        self.assertTrue(transport["deadline_checks_before_request_and_each_chunk_required"])
        self.assertFalse(transport["redirects_allowed"])
        self.assertFalse(transport["environment_proxies_allowed"])
        self.assertFalse(transport["retries_allowed"])
        self.assertFalse(candidate["network_adapter_implemented"])
        self.assertFalse(candidate["execution_manifest_validator_implemented"])
        self.assertFalse(candidate["visible_launcher_implemented"])
        self.assertFalse(candidate["output_writer_implemented"])

        authorization = self.proposal["authorization_now"]
        for key, value in authorization.items():
            if key == "proposal_freeze_allowed":
                self.assertTrue(value)
            else:
                self.assertFalse(value, key)

    def test_proposal_generator_has_no_network_imports(self) -> None:
        source_path = Path(self.proposal["code_bindings"]["proposal_generator_path"])
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".", 1)[0])
        self.assertTrue(
            imported.isdisjoint(
                {"aiohttp", "httpx", "requests", "socket", "urllib"}
            )
        )

    def test_build_validate_and_preflight_cannot_delegate_network(self) -> None:
        blocked = AssertionError("network call attempted in offline proposal phase")
        with (
            mock.patch("socket.socket", side_effect=blocked),
            mock.patch("socket.create_connection", side_effect=blocked),
            mock.patch("socket.getaddrinfo", side_effect=blocked),
            mock.patch("socket.gethostbyname", side_effect=blocked),
            mock.patch("socket.gethostbyname_ex", side_effect=blocked),
            mock.patch("socket.gethostbyaddr", side_effect=blocked),
            mock.patch("socket.getnameinfo", side_effect=blocked),
            mock.patch("urllib.request.urlopen", side_effect=blocked),
            mock.patch("urllib.request.OpenerDirector.open", side_effect=blocked),
            mock.patch("http.client.HTTPConnection.connect", side_effect=blocked),
            mock.patch("http.client.HTTPSConnection.connect", side_effect=blocked),
            mock.patch("subprocess.Popen", side_effect=blocked),
            tempfile.TemporaryDirectory() as temp_dir,
        ):
            proposal = build_proposal(ROOT, GENERATED_AT)
            validate_proposal(proposal, ROOT)
            result = preflight_future_execution(
                proposal_path=CHECKED_IN,
                execution_manifest_path=Path(temp_dir) / "execution.json",
                output_path=Path(temp_dir) / "output",
                repo_root=ROOT,
            )
        self.assertFalse(result["network_accessed"])

    def test_permission_or_currentness_tampering_fails_closed(self) -> None:
        mutations = (
            ("authorization_now", "network_run_allowed", True),
            ("authorization_now", "identity_output_allowed", True),
            ("target_identity_requirements", "bing_result_is_currentness_evidence", True),
            (
                "target_identity_requirements",
                "missing_direct_metadata_page_link_disposition",
                "ACCEPT",
            ),
            ("topology_discovery_candidate", "network_adapter_implemented", True),
            ("feasibility_assessment", "implementation_approval_safe_now", True),
        )
        for section, key, value in mutations:
            with self.subTest(section=section, key=key):
                proposal = copy.deepcopy(self.proposal)
                proposal[section][key] = value
                proposal["proposal_hash"] = canonical_proposal_hash(proposal)
                with self.assertRaises(ProposalError):
                    validate_proposal(proposal, ROOT)

    def test_next_checkpoint_tampering_fails_closed(self) -> None:
        proposal = copy.deepcopy(self.proposal)
        checkpoint = proposal["next_checkpoint"]
        checkpoint["approval_must_bind"] = []
        checkpoint["offline_approval_scope_only"].extend(
            ["approval_receipt", "writer_claim", "topology_output"]
        )
        checkpoint["offline_approval_does_not_authorize"] = ["network"]
        proposal["proposal_hash"] = canonical_proposal_hash(proposal)
        with self.assertRaisesRegex(ProposalError, "next checkpoint changed"):
            validate_proposal(proposal, ROOT)

    def test_parent_binding_or_hash_tampering_fails_closed(self) -> None:
        for key in (
            "plan_file_sha256",
            "plan_hash",
            "runtime_file_sha256",
            "runtime_hash",
        ):
            with self.subTest(key=key):
                proposal = copy.deepcopy(self.proposal)
                proposal["parent_discovery"][key] = "0" * 64
                proposal["proposal_hash"] = canonical_proposal_hash(proposal)
                with self.assertRaises(ProposalError):
                    validate_proposal(proposal, ROOT)

    def test_proposal_hash_tampering_fails_closed(self) -> None:
        proposal = copy.deepcopy(self.proposal)
        proposal["proposal_hash"] = "0" * 64
        with self.assertRaisesRegex(ProposalError, "proposal hash mismatch"):
            validate_proposal(proposal, ROOT)

    def test_write_is_immutable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "proposal.json"
            write_proposal(path, self.proposal)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")), self.proposal
            )
            write_proposal(path, self.proposal)
            path.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ProposalError, "immutable artifact mismatch"):
                write_proposal(path, self.proposal)

    def test_preflight_stays_blocked_and_creates_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            proposal_path = root / "proposal.json"
            output_path = root / "identity-output"
            execution_path = root / "execution-manifest.json"
            write_proposal(proposal_path, self.proposal)
            before = sorted(path.name for path in root.iterdir())
            result = preflight_future_execution(
                proposal_path=proposal_path,
                execution_manifest_path=execution_path,
                output_path=output_path,
                repo_root=ROOT,
            )
            after = sorted(path.name for path in root.iterdir())
            self.assertEqual(
                result["status"],
                "BLOCKED_NO_CODE_BOUND_TOPOLOGY_RUNTIME",
            )
            self.assertFalse(result["network_accessed"])
            self.assertFalse(result["execution_manifest_read"])
            self.assertFalse(result["output_created"])
            self.assertFalse(output_path.exists())
            self.assertEqual(before, after)

    def test_blocked_cli_preflight_returns_nonzero(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            execution_path = Path(temp_dir) / "execution.json"
            output_path = Path(temp_dir) / "output"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    OFFLINE_CHILD_SCRIPT,
                    str(ROOT),
                    str(CHECKED_IN),
                    str(execution_path),
                    str(output_path),
                    GENERATED_AT,
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
        self.assertEqual(completed.returncode, 3, completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["status"], "BLOCKED_NO_CODE_BOUND_TOPOLOGY_RUNTIME")
        self.assertFalse(payload["execution_manifest_read"])
        self.assertFalse(payload["output_created"])
        self.assertFalse(execution_path.exists())
        self.assertFalse(output_path.exists())

    def test_checked_in_proposal_matches_generator(self) -> None:
        checked_in = json.loads(CHECKED_IN.read_text(encoding="utf-8"))
        generated = build_proposal(ROOT, checked_in["generated_at_utc"])
        self.assertEqual(checked_in, generated)


if __name__ == "__main__":
    unittest.main()
