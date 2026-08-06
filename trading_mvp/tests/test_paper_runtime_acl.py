from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import paper_runtime_acl as acl  # noqa: E402


OWNER_SID = "S-1-5-21-111111111-222222222-333333333-1001"


def _policy() -> dict:
    return acl.build_acl_policy(
        public_research_root=r"E:\ZolotyayLopata-data\exports\trading-mvp",
        private_runtime_root=r"C:\Users\koval\AppData\Local\trading_mvp\private-runtime",
        generated_at_utc="2026-07-28T18:30:00+00:00",
    )


def _snapshot() -> dict:
    rights = sorted(acl.PRIVATE_REQUIRED_RIGHTS)
    return {
        "schema": acl.SNAPSHOT_SCHEMA,
        "inheritance_enabled": False,
        "owner_sid": OWNER_SID,
        "entries": [
            {
                "sid": OWNER_SID,
                "access_type": "ALLOW",
                "inherited": False,
                "rights": rights,
            },
            {
                "sid": acl.SYSTEM_SID,
                "access_type": "ALLOW",
                "inherited": False,
                "rights": rights,
            },
        ],
    }


class PaperRuntimeAclTests(unittest.TestCase):
    def test_policy_is_render_only_and_separates_roots(self) -> None:
        policy = acl.validate_acl_policy(_policy())
        self.assertEqual(policy["status"], "DESIGN_VALIDATED_NOT_APPLIED")
        self.assertFalse(policy["application"]["apply_live_acl"])
        self.assertTrue(policy["application"]["render_only"])
        self.assertFalse(policy["safety"]["filesystem_acl_mutation"])

    def test_private_fixture_accepts_owner_and_system_only(self) -> None:
        result = acl.validate_private_acl_fixture(_policy(), _snapshot())
        self.assertEqual(result["verdict"], "PRIVATE_ACL_FIXTURE_ACCEPTED")
        self.assertEqual(result["principal_count"], 2)
        self.assertFalse(result["filesystem_acl_mutation"])

    def test_private_fixture_rejects_broad_principal(self) -> None:
        snapshot = _snapshot()
        snapshot["entries"].append(
            {
                "sid": "S-1-1-0",
                "access_type": "ALLOW",
                "inherited": False,
                "rights": ["read"],
            }
        )
        with self.assertRaisesRegex(ValueError, "broad principal"):
            acl.validate_private_acl_fixture(_policy(), snapshot)

    def test_private_fixture_rejects_inheritance_and_missing_rights(self) -> None:
        inherited = _snapshot()
        inherited["inheritance_enabled"] = True
        with self.assertRaisesRegex(ValueError, "inheritance enabled"):
            acl.validate_private_acl_fixture(_policy(), inherited)
        missing = _snapshot()
        missing["entries"][0]["rights"] = ["read"]
        with self.assertRaisesRegex(ValueError, "lacks required rights"):
            acl.validate_private_acl_fixture(_policy(), missing)

    def test_policy_hash_detects_tampering(self) -> None:
        policy = _policy()
        policy["application"]["apply_live_acl"] = True
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            acl.validate_acl_policy(policy)

    def test_overlapping_roots_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not overlap"):
            acl.build_acl_policy(
                public_research_root=r"C:\data",
                private_runtime_root=r"C:\data\private",
            )

    def test_cli_writes_policy_without_touching_acl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "policy.json"
            exit_code = acl.main(
                [
                    "--public-root",
                    r"E:\public",
                    "--private-root",
                    r"C:\private",
                    "--output",
                    str(output),
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(output.is_file())
            self.assertEqual(
                acl.validate_acl_policy(json.loads(output.read_text(encoding="utf-8")))[
                    "status"
                ],
                "DESIGN_VALIDATED_NOT_APPLIED",
            )


if __name__ == "__main__":
    unittest.main()
