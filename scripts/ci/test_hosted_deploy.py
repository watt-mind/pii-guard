"""Admission and promotion regressions, entirely offline and with synthetic fixtures."""

from __future__ import annotations

import copy
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from hosted_deploy import (
    Refused,
    assert_config,
    assert_environment_policy,
    assert_runtime_contract,
    current_target,
    digest_matches,
    main,
    release_evidence,
    target_for,
    validate_candidate,
)

REPOSITORY = "watt-mind/pii-guard"
SOURCE = "a" * 40
TREE = "b" * 40
TEMPLATE = "c" * 64
DIGEST = "sha256:" + "d" * 64
IMAGE = "devregistry.azurecr.io/pii-guard@" + DIGEST
NOW = 1_800_000_000


def candidate() -> dict:
    return {
        "version": 1,
        "repository": REPOSITORY,
        "source_sha": SOURCE,
        "source_tree": TREE,
        "template_hash": TEMPLATE,
        "image": IMAGE,
        "run_id": 12345,
        "environment": "dev",
        "smoke_passed": True,
        "created_at": NOW - 60,
    }


def trusted_run() -> dict:
    return {
        "id": 12345,
        "event": "push",
        "head_branch": "develop",
        "head_sha": SOURCE,
        "status": "completed",
        "conclusion": "success",
        "path": ".github/workflows/ci.yml",
        "repository": {"full_name": REPOSITORY},
    }


def config(target: str = "dev") -> dict:
    return {
        "HOSTED_ENVIRONMENT_READY": "true",
        "HOSTED_NETWORK_READY": "true",
        "HOSTED_BUDGET_READY": "true",
        "AZURE_CLIENT_ID": "11111111-1111-4111-8111-111111111111",
        "AZURE_TENANT_ID": "22222222-2222-4222-8222-222222222222",
        "AZURE_SUBSCRIPTION_ID": "33333333-3333-4333-8333-333333333333",
        "AZURE_RESOURCE_GROUP": "rg-pii-guard-" + target,
        "HOSTED_REGISTRY": "syntheticregistry.azurecr.io",
        "HOSTED_PUBLIC_ORIGIN": "https://guard-dev.watt-mind.com"
        if target == "dev"
        else "https://synthetic.example.com",
        **({"AZURE_DEV_NETWORK_APPROVED": "true"} if target == "dev" else {}),
        "HOSTED_RELEASE_EVIDENCE_JSON": '{"synthetic":true}',
        "META_KEY_SECRET_URI": "https://syntheticvault.vault.azure.net/secrets/meta/" + "a" * 32,
        "TENANT_KEY_SECRET_URI": "https://syntheticvault.vault.azure.net/secrets/tenant/"
        + "b" * 32,
        "GOOGLE_SECRET_URI": "https://syntheticvault.vault.azure.net/secrets/google/" + "c" * 32,
        "GOOGLE_CLIENT_ID": "synthetic-client-id",
    }


class TrustedBranchTests(unittest.TestCase):
    def test_only_exact_develop_and_main_pushes_map_to_environments(self) -> None:
        self.assertEqual(target_for("push", "refs/heads/develop", REPOSITORY, "success"), "dev")
        self.assertEqual(target_for("push", "refs/heads/main", REPOSITORY, "success"), "prod")

    def test_untrusted_events_cannot_acquire_deployment_target(self) -> None:
        for event in (
            "pull_request",
            "pull_request_target",
            "merge_group",
            "schedule",
            "workflow_dispatch",
            "workflow_run",
            "",
        ):
            with self.subTest(event=event), self.assertRaises(Refused):
                target_for(event, "refs/heads/develop", REPOSITORY, "success")

    def test_similar_or_arbitrary_refs_are_rejected(self) -> None:
        for ref in (
            "develop",
            "main",
            "refs/heads/master",
            "refs/heads/develop-extra",
            "refs/heads/Main",
            "refs/tags/main",
            "refs/pull/1/merge",
            "refs/heads/codex/test",
            "",
        ):
            with self.subTest(ref=ref), self.assertRaises(Refused):
                target_for("push", ref, REPOSITORY, "success")

    def test_forks_and_failed_or_skipped_ci_are_rejected(self) -> None:
        with self.assertRaises(Refused):
            target_for("push", "refs/heads/main", "synthetic-fork/pii-guard", "success")
        for result in ("failure", "cancelled", "skipped", "", "SUCCESS"):
            with self.subTest(result=result), self.assertRaises(Refused):
                target_for("push", "refs/heads/main", REPOSITORY, result)


class CandidateProvenanceTests(unittest.TestCase):
    def validate(self, value: dict | None = None, run: dict | None = None, **overrides) -> dict:
        kwargs = {"source_tree": TREE, "template_hash": TEMPLATE, "now": NOW} | overrides
        return validate_candidate(
            candidate() if value is None else value, trusted_run() if run is None else run, **kwargs
        )

    def test_successful_dev_evidence_is_accepted_without_changing_its_digest(self) -> None:
        self.assertEqual(self.validate()["image"], IMAGE)

    def test_current_source_tree_or_template_difference_blocks_promotion(self) -> None:
        for change in ({"source_tree": "e" * 40}, {"template_hash": "f" * 64}):
            with self.subTest(change=change), self.assertRaises(Refused):
                self.validate(**change)

    def test_candidate_schema_rejects_missing_unknown_or_malformed_values(self) -> None:
        changes = (
            {"version": 2},
            {"version": True},
            {"repository": "synthetic-fork/pii-guard"},
            {"source_sha": "main"},
            {"source_tree": "invalid"},
            {"template_hash": "abc"},
            {"image": "devregistry.azurecr.io/pii-guard:latest"},
            {"image": "https://devregistry.azurecr.io/pii-guard@" + DIGEST},
            {"image": "devregistry.azurecr.io/pii-guard@sha256:" + "g" * 64},
            {"run_id": 0},
            {"run_id": True},
            {"environment": "prod"},
            {"smoke_passed": False},
            {"smoke_passed": "true"},
            {"created_at": "1800000000"},
            {"unexpected": "value"},
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(Refused):
                self.validate(candidate() | change)
        for field in candidate():
            broken = candidate()
            del broken[field]
            with self.subTest(missing=field), self.assertRaises(Refused):
                self.validate(broken)

    def test_expired_or_future_evidence_cannot_be_promoted(self) -> None:
        for timestamp in (NOW - 7 * 86400 - 1, NOW + 1, -1, True):
            with self.subTest(timestamp=timestamp), self.assertRaises(Refused):
                self.validate(candidate() | {"created_at": timestamp})

    def test_artifact_must_belong_to_successful_canonical_develop_ci_run(self) -> None:
        changes = (
            {"id": 54321},
            {"event": "pull_request"},
            {"event": "workflow_dispatch"},
            {"head_branch": "main"},
            {"head_sha": "e" * 40},
            {"status": "in_progress"},
            {"conclusion": "failure"},
            {"conclusion": "cancelled"},
            {"conclusion": "skipped"},
            {"path": ".github/workflows/untrusted.yml"},
            {"repository": {"full_name": "synthetic-fork/pii-guard"}},
            {"repository": None},
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(Refused):
                self.validate(run=trusted_run() | change)
        broken = copy.deepcopy(trusted_run())
        del broken["head_sha"]
        with self.assertRaises(Refused):
            self.validate(run=broken)

    def test_import_must_preserve_the_exact_manifest_digest(self) -> None:
        self.assertIsNone(digest_matches(IMAGE, DIGEST))
        for digest in ("sha256:" + "e" * 64, "d" * 64, "sha256:abc", "latest", ""):
            with self.subTest(digest=digest), self.assertRaises(Refused):
                digest_matches(IMAGE, digest)


class PrerequisiteTests(unittest.TestCase):
    def test_complete_environment_configuration_is_accepted(self) -> None:
        self.assertIsNone(assert_config(config(), "dev"))
        self.assertIsNone(assert_config(config("prod"), "prod"))

    def test_readiness_is_explicit_and_missing_configuration_fails_closed(self) -> None:
        for field in config():
            broken = config()
            del broken[field]
            with self.subTest(missing=field), self.assertRaises(Refused):
                assert_config(broken, "dev")
        for field in ("HOSTED_ENVIRONMENT_READY", "HOSTED_NETWORK_READY", "HOSTED_BUDGET_READY"):
            for value in ("false", "", "TRUE"):
                with self.subTest(field=field, value=value), self.assertRaises(Refused):
                    assert_config(config() | {field: value}, "dev")

    def test_cross_environment_group_or_unknown_target_is_rejected(self) -> None:
        with self.assertRaises(Refused):
            assert_config(config("prod"), "dev")
        with self.assertRaises(Refused):
            assert_config(config(), "staging")

    def test_dev_requires_explicit_network_approval_and_exact_reviewed_origin(self) -> None:
        for value in ("false", "", "TRUE", True):
            with self.subTest(approval=value), self.assertRaises(Refused):
                assert_config(config() | {"AZURE_DEV_NETWORK_APPROVED": value}, "dev")
        for origin in (
            "https://synthetic.example.com",
            "http://guard-dev.watt-mind.com",
            "https://guard-dev.watt-mind.com/",
            "https://guard-dev.watt-mind.com.evil.example",
        ):
            with self.subTest(origin=origin), self.assertRaises(Refused):
                assert_config(config() | {"HOSTED_PUBLIC_ORIGIN": origin}, "dev")

    def test_invalid_identity_registry_and_unversioned_secret_references_are_rejected(self) -> None:
        changes = (
            {"AZURE_CLIENT_ID": "not-a-uuid"},
            {"AZURE_TENANT_ID": ""},
            {"AZURE_SUBSCRIPTION_ID": "not-a-uuid"},
            {"HOSTED_REGISTRY": "syntheticregistry.example.com"},
            {"HOSTED_PUBLIC_ORIGIN": "http://synthetic.example.com"},
            {"META_KEY_SECRET_URI": "https://syntheticvault.vault.azure.net/secrets/meta"},
            {"TENANT_KEY_SECRET_URI": "https://syntheticvault.vault.azure.net/secrets/tenant"},
            {"GOOGLE_SECRET_URI": "not-a-secret-reference"},
            {"GOOGLE_CLIENT_ID": ""},
            {"HOSTED_RELEASE_EVIDENCE_JSON": ""},
        )
        for change in changes:
            with self.subTest(change=change), self.assertRaises(Refused):
                assert_config(config() | change, "dev")


class EnvironmentPolicyTests(unittest.TestCase):
    @staticmethod
    def policy(reviewers: bool = False) -> dict:
        return {
            "deployment_branch_policy": {"custom_branch_policies": True},
            "protection_rules": [
                {
                    "type": "required_reviewers",
                    "reviewers": [{"id": 12345}],
                    "prevent_self_review": True,
                }
            ]
            if reviewers
            else [],
        }

    def test_only_the_exact_branch_is_allowed_for_each_environment(self) -> None:
        for target, branch in (("dev", "develop"), ("build", "develop"), ("prod", "main")):
            with self.subTest(target=target):
                self.assertIsNone(
                    assert_environment_policy(
                        self.policy(reviewers=target == "prod"),
                        {"branch_policies": [{"name": branch, "type": "branch"}]},
                        target,
                    )
                )
        # The GitHub API historically omitted type for branch policies.
        self.assertIsNone(
            assert_environment_policy(
                self.policy(),
                {"branch_policies": [{"name": "develop"}]},
                "dev",
            )
        )

    def test_missing_custom_policy_or_multiple_allowed_refs_are_rejected(self) -> None:
        branches = {"branch_policies": [{"name": "develop", "type": "branch"}]}
        for policy in ({}, {"deployment_branch_policy": {"custom_branch_policies": False}}):
            with self.subTest(policy=policy), self.assertRaises(Refused):
                assert_environment_policy(policy, branches, "dev")
        for allowed in (
            [],
            [{"name": "develop"}, {"name": "main"}],
            [{"name": "develop*"}],
            [{"name": "develop", "type": "tag"}],
            [{"name": "main"}],
        ):
            with self.subTest(allowed=allowed), self.assertRaises(Refused):
                assert_environment_policy(self.policy(), {"branch_policies": allowed}, "dev")

    def test_prod_requires_reviewers_in_addition_to_exact_main_branch(self) -> None:
        branches = {"branch_policies": [{"name": "main", "type": "branch"}]}
        for rules in (
            [],
            [{"type": "required_reviewers", "reviewers": []}],
            [{"type": "wait_timer", "reviewers": [{"id": 12345}]}],
        ):
            policy = self.policy() | {"protection_rules": rules}
            with self.subTest(rules=rules), self.assertRaises(Refused):
                assert_environment_policy(policy, branches, "prod")
        with self.assertRaises(Refused):
            assert_environment_policy(
                self.policy(reviewers=True), {"branch_policies": [{"name": "develop"}]}, "prod"
            )

    def test_prod_reviewers_must_not_approve_their_own_deployment(self) -> None:
        branches = {"branch_policies": [{"name": "main", "type": "branch"}]}
        for value in (False, None, "true", 1):
            rule = {"type": "required_reviewers", "reviewers": [{"id": 12345}]}
            if value is not None:
                rule["prevent_self_review"] = value
            policy = self.policy() | {"protection_rules": [rule]}
            with self.subTest(value=value), self.assertRaises(Refused):
                assert_environment_policy(policy, branches, "prod")


class RuntimeContractTests(unittest.TestCase):
    @staticmethod
    def contract() -> dict:
        return {
            "version": 1,
            "app_only": True,
            "no_storage_keys": True,
            "no_role_assignments": True,
            "durable_budget": True,
            "private_dev": True,
        }

    def test_reviewed_app_only_runtime_contract_is_required_for_dev(self) -> None:
        self.assertIsNone(assert_runtime_contract(self.contract(), "dev"))
        for field in self.contract():
            missing = self.contract()
            del missing[field]
            with self.subTest(missing=field), self.assertRaises(Refused):
                assert_runtime_contract(missing, "dev")

    def test_prod_contract_does_not_require_private_dev_network(self) -> None:
        contract = self.contract()
        del contract["private_dev"]
        self.assertIsNone(assert_runtime_contract(contract, "prod"))

    def test_contract_version_and_readiness_flags_have_strict_types(self) -> None:
        for version in (True, "1", 0, 2, None):
            with self.subTest(version=version), self.assertRaises(Refused):
                assert_runtime_contract(self.contract() | {"version": version}, "dev")
        for field in set(self.contract()) - {"version"}:
            for value in (False, "true", 1, None):
                with self.subTest(field=field, value=value), self.assertRaises(Refused):
                    assert_runtime_contract(self.contract() | {field: value}, "dev")


class ReleaseEvidenceTests(unittest.TestCase):
    @staticmethod
    def evidence(target: str = "dev") -> dict:
        evidence = {"image": IMAGE, "lab_1372_done": True}
        if target == "prod":
            evidence |= dict.fromkeys(
                (
                    "isolation",
                    "csrf",
                    "identity_header_spoofing",
                    "quotas_restart",
                    "ssrf",
                    "synthetic_roundtrip",
                    "streaming",
                    "privacy_review",
                ),
                True,
            )
        else:
            evidence |= dict.fromkeys(
                ("private_dev_reviewed", "tailnet_acl", "proxy_tls", "proxy_headers"),
                True,
            )
        return evidence

    def validate(self, evidence: dict, target: str = "dev", sponsored: str = "0") -> dict:
        with patch.dict(
            os.environ,
            {
                "HOSTED_RELEASE_EVIDENCE_JSON": json.dumps(evidence),
                "HOSTED_SPONSORED_MICRODOLLARS": sponsored,
            },
            clear=True,
        ):
            return release_evidence(IMAGE, target)

    def test_development_and_production_require_image_bound_manual_evidence(self) -> None:
        for target in ("dev", "prod"):
            evidence = self.evidence(target)
            with self.subTest(target=target):
                self.assertEqual(self.validate(evidence, target), evidence)
            with self.subTest(target=target, image="different"), self.assertRaises(Refused):
                self.validate(evidence | {"image": IMAGE.replace("d" * 64, "e" * 64)}, target)

    def test_missing_malformed_or_non_object_evidence_is_rejected(self) -> None:
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(Refused):
            release_evidence(IMAGE, "dev")
        for value in ("invalid-json", "null", "[]", '"synthetic"'):
            with (
                self.subTest(value=value),
                patch.dict(os.environ, {"HOSTED_RELEASE_EVIDENCE_JSON": value}, clear=True),
                self.assertRaises(Refused),
            ):
                release_evidence(IMAGE, "dev")

    def test_every_dev_network_gate_must_be_explicitly_true(self) -> None:
        evidence = self.evidence("dev")
        for field in set(evidence) - {"image"}:
            for value in (False, "true", 1, None):
                with self.subTest(field=field, value=value), self.assertRaises(Refused):
                    self.validate(evidence | {field: value}, "dev")
            missing = evidence.copy()
            del missing[field]
            with self.subTest(missing=field), self.assertRaises(Refused):
                self.validate(missing, "dev")

    def test_every_production_gate_must_be_explicitly_true(self) -> None:
        evidence = self.evidence("prod")
        for field in set(evidence) - {"image"}:
            for value in (False, "true", 1, None):
                with self.subTest(field=field, value=value), self.assertRaises(Refused):
                    self.validate(evidence | {field: value}, "prod")
            missing = evidence.copy()
            del missing[field]
            with self.subTest(missing=field), self.assertRaises(Refused):
                self.validate(missing, "prod")

    def test_positive_sponsorship_requires_separate_provider_authorization(self) -> None:
        for target in ("dev", "prod"):
            evidence = self.evidence(target)
            with self.subTest(target=target), self.assertRaises(Refused):
                self.validate(evidence, target, sponsored="1000000")
            approved = evidence | {"meta_proxy_authorized": True}
            self.assertEqual(self.validate(approved, target, sponsored="1000000"), approved)
            with self.subTest(target=target, authorization="string"), self.assertRaises(Refused):
                self.validate(evidence | {"meta_proxy_authorized": "true"}, target, sponsored="1")

    def test_owner_risk_acceptance_substitutes_only_for_provider_authorization(self) -> None:
        waiver = {"by": "owner", "ref": "LAB-1389", "date": "2026-10-28", "scope": "hackathon-demo"}
        for target in ("dev", "prod"):
            evidence = self.evidence(target)
            waived = evidence | {"meta_proxy_owner_risk_accepted": waiver}
            with self.subTest(target=target):
                self.assertEqual(self.validate(waived, target, sponsored="1"), waived)
            with self.subTest(target=target, gate="lab_1372"), self.assertRaises(Refused):
                self.validate(waived | {"lab_1372_done": False}, target, sponsored="1")
            for bad in (
                True,
                {},
                waiver | {"by": "agent"},
                waiver | {"ref": "LAB-1372"},
                waiver | {"scope": "general-availability"},
                waiver | {"date": "2026-02-30"},
                waiver | {"date": "2999-01-01"},
                waiver | {"extra": True},
            ):
                with self.subTest(target=target, waiver=bad), self.assertRaises(Refused):
                    self.validate(
                        evidence
                        | {"meta_proxy_authorized": True, "meta_proxy_owner_risk_accepted": bad},
                        target,
                        sponsored="1",
                    )


class CurrentRunTests(unittest.TestCase):
    @staticmethod
    def environment(branch: str = "develop") -> dict:
        return {
            "GITHUB_RUN_ID": "12345",
            "GITHUB_SHA": SOURCE,
            "GITHUB_EVENT_NAME": "push",
            "GITHUB_REF": "refs/heads/" + branch,
            "GITHUB_REPOSITORY": REPOSITORY,
        }

    def invoke(
        self,
        *,
        branch: str = "develop",
        jobs: list | None = None,
        head: str = SOURCE,
        run_changes: dict | None = None,
        job_pages: list[list] | None = None,
    ) -> str:
        run = trusted_run() | {"head_branch": branch} | (run_changes or {})
        if jobs is None:
            jobs = [
                {
                    "name": "ci-ok",
                    "conclusion": "success",
                    "run_attempt": 1,
                    "started_at": "2026-10-28T12:00:00Z",
                }
            ]
        responses = {
            f"repos/{REPOSITORY}/actions/runs/12345": run,
            **{
                (
                    f"repos/{REPOSITORY}/actions/runs/12345/jobs"
                    f"?filter=all&per_page=100&page={index}"
                ): {"jobs": page}
                for index, page in enumerate(
                    job_pages if job_pages is not None else [jobs], start=1
                )
            },
            f"repos/{REPOSITORY}/git/ref/heads/{branch}": {"object": {"sha": head}},
        }
        with (
            patch.dict(
                os.environ,
                self.environment(branch) | {"GITHUB_RUN_ATTEMPT": str(run.get("run_attempt", 1))},
                clear=True,
            ),
            patch("hosted_deploy.api", side_effect=responses.__getitem__),
        ):
            return current_target()

    def test_current_successful_canonical_ci_run_is_admitted(self) -> None:
        self.assertEqual(self.invoke(), "dev")
        self.assertEqual(self.invoke(branch="main"), "prod")

    def test_missing_failed_or_skipped_ci_ok_is_rejected(self) -> None:
        for jobs in (
            [],
            [{"name": "ui", "conclusion": "success"}],
            [{"name": "ci-ok", "conclusion": "failure"}],
            [{"name": "ci-ok", "conclusion": "skipped"}],
            [{"name": "ci-ok", "conclusion": None}],
        ):
            with self.subTest(jobs=jobs), self.assertRaises(Refused):
                self.invoke(jobs=jobs)

    def test_failed_deployment_only_rerun_can_use_previous_successful_ci_ok(self) -> None:
        jobs = [
            {
                "name": "ci-ok",
                "conclusion": "success",
                "run_attempt": 1,
                "started_at": "2026-10-28T12:00:00Z",
            },
            {
                "name": "hosted-deploy / deploy",
                "conclusion": None,
                "run_attempt": 2,
                "started_at": "2026-10-28T13:00:00Z",
            },
        ]
        self.assertEqual(self.invoke(jobs=jobs, run_changes={"run_attempt": 2}), "dev")

    def test_newer_failed_or_incomplete_ci_ok_overrides_earlier_success(self) -> None:
        for conclusion in ("failure", "cancelled", "skipped", None):
            jobs = [
                {
                    "name": "ci-ok",
                    "conclusion": "success",
                    "run_attempt": 1,
                    "started_at": "2026-10-28T12:00:00Z",
                },
                {
                    "name": "ci-ok",
                    "conclusion": conclusion,
                    "run_attempt": 2,
                    "started_at": "2026-10-28T13:00:00Z",
                },
            ]
            for ordered in (jobs, list(reversed(jobs))):
                with self.subTest(conclusion=conclusion, order=ordered), self.assertRaises(Refused):
                    self.invoke(jobs=ordered, run_changes={"run_attempt": 2})

    def test_newest_ci_ok_within_same_attempt_wins_by_start_time(self) -> None:
        jobs = [
            {
                "name": "ci-ok",
                "conclusion": "failure",
                "run_attempt": 2,
                "started_at": "2026-10-28T13:01:00Z",
            },
            {
                "name": "ci-ok",
                "conclusion": "success",
                "run_attempt": 2,
                "started_at": "2026-10-28T13:00:00Z",
            },
        ]
        with self.assertRaises(Refused):
            self.invoke(jobs=jobs, run_changes={"run_attempt": 2})

    def test_paginated_job_history_cannot_hide_a_newer_failed_ci_ok(self) -> None:
        first = [{"name": f"synthetic-job-{index}", "conclusion": "success"} for index in range(99)]
        first.append(
            {
                "name": "ci-ok",
                "conclusion": "success",
                "run_attempt": 1,
                "started_at": "2026-10-28T12:00:00Z",
            }
        )
        second = [
            {
                "name": "ci-ok",
                "conclusion": "failure",
                "run_attempt": 2,
                "started_at": "2026-10-28T13:00:00Z",
            }
        ]
        with self.assertRaises(Refused):
            self.invoke(job_pages=[first, second], run_changes={"run_attempt": 2})

    def test_branch_advancement_rejects_an_older_queued_run(self) -> None:
        for branch in ("develop", "main"):
            with self.subTest(branch=branch), self.assertRaises(Refused):
                self.invoke(branch=branch, head="e" * 40)

    def test_wrong_workflow_source_event_or_branch_metadata_is_rejected(self) -> None:
        for change in (
            {"path": ".github/workflows/untrusted.yml"},
            {"head_sha": "e" * 40},
            {"event": "pull_request"},
            {"head_branch": "main"},
        ):
            with self.subTest(change=change), self.assertRaises(Refused):
                self.invoke(run_changes=change)


class DeploymentExecutionTests(unittest.TestCase):
    def test_failed_dev_deploy_does_not_smoke_or_record_successful_evidence(self) -> None:
        reviewed = {"image": IMAGE, "lab_1372_done": True}
        with (
            patch.dict(os.environ, config(), clear=True),
            patch("sys.argv", ["hosted_deploy.py", "deploy"]),
            patch("hosted_deploy.current_target", return_value="dev"),
            patch("hosted_deploy.assert_config"),
            patch("hosted_deploy.state", return_value=candidate()),
            patch("hosted_deploy.release_evidence", return_value=reviewed),
            patch("hosted_deploy.write_state") as writes,
            patch("hosted_deploy.command") as commands,
            patch(
                "hosted_deploy.subprocess.run", return_value=SimpleNamespace(returncode=1)
            ) as deploy,
            self.assertRaises(Refused),
        ):
            main()
        self.assertEqual(deploy.call_args.args[0], ["/bin/bash", "deploy/azure/deploy.sh", "stage"])
        commands.assert_not_called()
        self.assertEqual(
            [write.args[0] for write in writes.call_args_list], ["release-evidence.json"]
        )

    def test_changed_digest_after_prod_import_never_invokes_deployment_script(self) -> None:
        with (
            patch.dict(os.environ, config("prod"), clear=True),
            patch("sys.argv", ["hosted_deploy.py", "deploy"]),
            patch("hosted_deploy.current_target", return_value="prod"),
            patch("hosted_deploy.assert_config"),
            patch("hosted_deploy.state", return_value=candidate()),
            patch("hosted_deploy.source_identity", return_value=(TREE, TEMPLATE)),
            patch("hosted_deploy.api", return_value=trusted_run()),
            patch("hosted_deploy.time.time", return_value=NOW),
            patch("hosted_deploy.command", side_effect=["", "sha256:" + "e" * 64]) as commands,
            patch("hosted_deploy.subprocess.run") as deploy,
            patch("hosted_deploy.release_evidence") as review,
            patch("hosted_deploy.write_state") as writes,
            self.assertRaises(Refused),
        ):
            main()
        self.assertEqual(commands.call_count, 2)
        self.assertEqual(commands.call_args_list[0].args[:3], ("az", "acr", "import"))
        deploy.assert_not_called()
        review.assert_not_called()
        writes.assert_not_called()


if __name__ == "__main__":
    unittest.main()
