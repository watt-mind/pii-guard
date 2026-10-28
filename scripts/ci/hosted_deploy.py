"""Admission and immutable promotion for hosted CI; never funds an allowance."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path

REPOSITORY = "watt-mind/pii-guard"
WORKFLOW = ".github/workflows/ci.yml"
IMAGE = re.compile(r"[a-z0-9]+\.azurecr\.io/pii-guard@sha256:[a-f0-9]{64}")
HEX40 = re.compile(r"[a-f0-9]{40}")
HEX64 = re.compile(r"[a-f0-9]{64}")
CANDIDATE_FIELDS = {
    "version",
    "repository",
    "source_sha",
    "source_tree",
    "template_hash",
    "image",
    "run_id",
    "environment",
    "smoke_passed",
    "created_at",
}
STATE = Path(".hosted-deploy")


class Refused(RuntimeError):
    """A bounded policy failure; messages contain no runtime response or secret values."""


def target_for(event: str, ref: str, repository: str, ci_result: str) -> str:
    if repository != REPOSITORY or event != "push" or ci_result != "success":
        raise Refused("Only canonical branch pushes after successful ci-ok are admitted")
    targets = {"refs/heads/develop": "dev", "refs/heads/main": "prod"}
    if ref not in targets:
        raise Refused("Only develop and main have deployment targets")
    return targets[ref]


def validate_candidate(
    candidate: dict, run: dict, *, source_tree: str, template_hash: str, now: int
) -> dict:
    if not isinstance(candidate, dict) or set(candidate) != CANDIDATE_FIELDS:
        raise Refused("Candidate schema is incomplete or unknown")
    if (
        type(candidate["version"]) is not int
        or candidate["version"] != 1
        or candidate["repository"] != REPOSITORY
        or candidate["environment"] != "dev"
        or candidate["smoke_passed"] is not True
        or type(candidate["run_id"]) is not int
        or candidate["run_id"] <= 0
        or type(candidate["created_at"]) is not int
    ):
        raise Refused("Candidate identity, smoke or timestamps are invalid")
    for field in ("source_sha", "source_tree"):
        if not isinstance(candidate[field], str) or not HEX40.fullmatch(candidate[field]):
            raise Refused("Candidate source identity is malformed")
    if not isinstance(candidate["template_hash"], str) or not HEX64.fullmatch(
        candidate["template_hash"]
    ):
        raise Refused("Candidate template identity is malformed")
    if not isinstance(candidate["image"], str) or not IMAGE.fullmatch(candidate["image"]):
        raise Refused("Candidate must reference an immutable dedicated ACR image")
    if candidate["source_tree"] != source_tree or candidate["template_hash"] != template_hash:
        raise Refused("Production source or template differs from the tested candidate")
    if not 0 <= now - candidate["created_at"] <= 7 * 86400:
        raise Refused("Candidate is expired or from the future; test a fresh candidate in dev")
    repository = run.get("repository") if isinstance(run, dict) else None
    if (
        not isinstance(repository, dict)
        or repository.get("full_name") != REPOSITORY
        or run.get("id") != candidate["run_id"]
        or run.get("event") != "push"
        or run.get("head_branch") != "develop"
        or run.get("head_sha") != candidate["source_sha"]
        or run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or run.get("path") != WORKFLOW
    ):
        raise Refused("Evidence does not belong to a successful canonical develop CI run")
    return candidate


def digest_matches(source_image: str, destination_digest: str) -> None:
    if not IMAGE.fullmatch(source_image) or destination_digest != source_image.split("@", 1)[1]:
        raise Refused("Registry import did not preserve the exact tested manifest digest")


def assert_config(config: dict, target: str) -> None:
    if target not in ("dev", "prod"):
        raise Refused("Unknown deployment environment")
    for field in ("HOSTED_ENVIRONMENT_READY", "HOSTED_NETWORK_READY", "HOSTED_BUDGET_READY"):
        if config.get(field) != "true":
            raise Refused(
                "Environment, private network and durable budget prerequisites must be reviewed"
            )
    for field in ("AZURE_CLIENT_ID", "AZURE_TENANT_ID", "AZURE_SUBSCRIPTION_ID"):
        try:
            uuid.UUID(config.get(field, ""))
        except (ValueError, TypeError, AttributeError):
            raise Refused("Azure identity configuration is missing or invalid") from None
    if config.get("AZURE_RESOURCE_GROUP") != f"rg-pii-guard-{target}":
        raise Refused("Deployment must target its dedicated environment resource group")
    if not re.fullmatch(r"[a-z0-9]+\.azurecr\.io", config.get("HOSTED_REGISTRY", "")):
        raise Refused("Configure the dedicated ACR hostname")
    if not re.fullmatch(r"https://[a-z0-9.-]+", config.get("HOSTED_PUBLIC_ORIGIN", "")):
        raise Refused("Configure an exact canonical HTTPS origin")
    if target == "dev" and (
        config.get("AZURE_DEV_NETWORK_APPROVED") != "true"
        or config.get("HOSTED_PUBLIC_ORIGIN") != "https://guard-dev.watt-mind.com"
    ):
        raise Refused("Dev requires the approved private network and exact split-DNS origin")
    for field in ("META_KEY_SECRET_URI", "TENANT_KEY_SECRET_URI", "GOOGLE_SECRET_URI"):
        if not re.fullmatch(
            r"https://[a-z0-9-]+\.vault\.azure\.net/secrets/[a-zA-Z0-9-]+/[a-f0-9]{32}",
            config.get(field, ""),
        ):
            raise Refused("Configure versioned environment-specific Key Vault references")
    if not config.get("GOOGLE_CLIENT_ID") or not config.get("HOSTED_RELEASE_EVIDENCE_JSON"):
        raise Refused("Configure OAuth and manually reviewed image-bound release evidence")


def command(*args: str, binary: bool = False):
    try:
        # Fixed executable names and validated argument lists; no shell interpolation.
        result = subprocess.run(  # noqa: S603
            args, capture_output=True, check=True, timeout=120, text=not binary
        )
        return result.stdout if binary else result.stdout.strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        # CLI stderr can contain upstream URLs/configuration; never relay it.
        raise Refused(
            "Required GitHub, Git or Azure operation failed; inspect its bounded platform status"
        ) from None


def api(path: str) -> dict:
    try:
        return json.loads(command("gh", "api", path))
    except (ValueError, TypeError):
        raise Refused("GitHub returned invalid metadata") from None


def assert_environment_policy(policy: dict, branches: dict, target: str) -> None:
    branch = "main" if target == "prod" else "develop"
    rule = policy.get("deployment_branch_policy") or {}
    allowed = branches.get("branch_policies", [])
    if not rule.get("custom_branch_policies") or len(allowed) != 1:
        raise Refused("GitHub Environment must allow only its exact deployment branch")
    if allowed[0].get("name") != branch or allowed[0].get("type", "branch") != "branch":
        raise Refused("Environment branch policy does not match the deployment target")
    if target == "prod" and not any(
        item.get("type") == "required_reviewers"
        and item.get("reviewers")
        and item.get("prevent_self_review") is True
        for item in policy.get("protection_rules", [])
    ):
        raise Refused("Production requires an independent Environment reviewer")


def check_environment(target: str) -> None:
    environment = "hosted-build" if target == "build" else target
    prefix = f"repos/{REPOSITORY}/environments/{environment}"
    assert_environment_policy(api(prefix), api(prefix + "/deployment-branch-policies"), target)


def assert_runtime_contract(payload: dict, target: str) -> None:
    required = ["app_only", "no_storage_keys", "no_role_assignments", "durable_budget"]
    if target == "dev":
        required.append("private_dev")
    if (
        not isinstance(payload, dict)
        or type(payload.get("version")) is not int
        or payload.get("version") != 1
        or not all(payload.get(key) is True for key in required)
    ):
        raise Refused("Reviewed app-only runtime contract is not available")


def runtime_preflight(target: str) -> None:
    # Current foundation rejects this unknown mode before Azure commands. The Azure lane
    # must supply this side-effect-free capability response before CI may obtain OIDC.
    try:
        payload = json.loads(command("/bin/bash", "deploy/azure/deploy.sh", "ci-preflight", target))
    except (ValueError, TypeError):
        raise Refused("Runtime preflight did not provide reviewed capabilities") from None
    assert_runtime_contract(payload, target)


def source_identity() -> tuple[str, str]:
    tree = command("git", "rev-parse", "HEAD^{tree}")
    if not HEX40.fullmatch(tree):
        raise Refused("Invalid source tree")
    digest = hashlib.sha256()
    for name in ("deploy/azure/main.bicep", "deploy/azure/release.bicep", "deploy/azure/deploy.sh"):
        if Path(name).exists():
            digest.update(name.encode())
            digest.update(Path(name).read_bytes())
    return tree, digest.hexdigest()


def write_state(name: str, value: dict) -> None:
    STATE.mkdir(exist_ok=True)
    (STATE / name).write_text(json.dumps(value, sort_keys=True) + "\n")


def state(name: str) -> dict:
    try:
        return json.loads((STATE / name).read_text())
    except (OSError, ValueError):
        raise Refused("Candidate state is unavailable") from None


def outputs(**values: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as stream:
            for key, value in values.items():
                if "\n" in value or "\r" in value:
                    raise Refused("Invalid workflow output")
                stream.write(f"{key}={value}\n")


def current_target() -> str:
    run_id = os.environ["GITHUB_RUN_ID"]
    run = api(f"repos/{REPOSITORY}/actions/runs/{run_id}")
    if run.get("path") != WORKFLOW or run.get("head_sha") != os.environ["GITHUB_SHA"]:
        raise Refused("Deployment caller is not the checked CI source")
    jobs = []
    for page in range(1, 11):
        batch = api(
            f"repos/{REPOSITORY}/actions/runs/{run_id}/jobs?filter=all&per_page=100&page={page}"
        ).get("jobs", [])
        jobs.extend(batch)
        if len(batch) < 100:
            break
    else:
        raise Refused("Too many job attempts to prove the CI gate")
    gates = [job for job in jobs if job.get("name") == "ci-ok"]
    latest = max(
        gates,
        key=lambda job: (job.get("run_attempt", 0), job.get("started_at") or ""),
        default={},
    )
    ci_ok = latest.get("conclusion")
    target = target_for(
        os.environ["GITHUB_EVENT_NAME"],
        os.environ["GITHUB_REF"],
        os.environ["GITHUB_REPOSITORY"],
        ci_ok,
    )
    branch = "develop" if target == "dev" else "main"
    if run.get("event") != "push" or run.get("head_branch") != branch:
        raise Refused("GitHub run provenance differs from the branch target")
    # Stale queued runs may never replace a newer branch candidate.
    if (
        api(f"repos/{REPOSITORY}/git/ref/heads/{branch}").get("object", {}).get("sha")
        != os.environ["GITHUB_SHA"]
    ):
        raise Refused("Branch advanced; deploy the newest successful CI run")
    return target


def find_candidate(tree: str, template: str) -> dict:
    runs = api(
        f"repos/{REPOSITORY}/actions/workflows/ci.yml/runs?branch=develop&event=push&status=success&per_page=100"
    ).get("workflow_runs", [])
    name = f"hosted-tested-{tree}"
    for run in runs:
        artifacts = api(
            f"repos/{REPOSITORY}/actions/runs/{run['id']}/artifacts?name={name}&per_page=100"
        ).get("artifacts", [])
        for artifact in artifacts:
            if (
                artifact.get("name") != name
                or artifact.get("expired")
                or artifact.get("size_in_bytes", 0) > 32768
            ):
                continue
            data = command(
                "gh",
                "api",
                f"repos/{REPOSITORY}/actions/artifacts/{artifact['id']}/zip",
                binary=True,
            )
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    if (
                        archive.namelist() != ["evidence.json"]
                        or archive.getinfo("evidence.json").file_size > 16384
                    ):
                        raise Refused("Unexpected candidate artifact contents")
                    candidate = json.loads(archive.read("evidence.json"))
            except (ValueError, KeyError, zipfile.BadZipFile):
                raise Refused("Malformed candidate artifact") from None
            return validate_candidate(
                candidate, run, source_tree=tree, template_hash=template, now=int(time.time())
            )
    raise Refused("No successful matching dev candidate exists; production never rebuilds")


def release_evidence(image: str, target: str) -> dict:
    try:
        evidence = json.loads(os.environ["HOSTED_RELEASE_EVIDENCE_JSON"])
    except (KeyError, ValueError):
        raise Refused(
            "Supply reviewed image-bound release evidence; CI cannot fabricate approval"
        ) from None
    required = ["lab_1372_done"]
    if target == "dev":
        required += ["private_dev_reviewed", "tailnet_acl", "proxy_tls", "proxy_headers"]
    if target == "prod":
        required += [
            "isolation",
            "csrf",
            "identity_header_spoofing",
            "quotas_restart",
            "ssrf",
            "synthetic_roundtrip",
            "streaming",
            "privacy_review",
        ]
    if int(os.environ.get("HOSTED_SPONSORED_MICRODOLLARS") or "0") > 0:
        required += ["meta_proxy_authorized"]
    if (
        not isinstance(evidence, dict)
        or evidence.get("image") != image
        or not all(evidence.get(key) is True for key in required)
    ):
        raise Refused("Reviewed release evidence does not authorize this exact image")
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "config", "candidate", "deploy", "tested"))
    parser.add_argument("--image", default="")
    parser.add_argument("--publisher", action="store_true")
    args = parser.parse_args()
    if args.action == "prepare":
        target = current_target()
        if target == "dev" and os.environ.get("HOSTED_PRIVATE_RUNNER_READY") != "true":
            raise Refused(
                "Private runner workflow restrictions and ephemeral isolation are not approved"
            )
        tree, template = source_identity()
        candidate = (
            find_candidate(tree, template)
            if target == "prod"
            else {
                "version": 1,
                "repository": REPOSITORY,
                "source_sha": os.environ["GITHUB_SHA"],
                "source_tree": tree,
                "template_hash": template,
                "run_id": int(os.environ["GITHUB_RUN_ID"]),
                "environment": "dev",
                "created_at": int(time.time()),
                "smoke_passed": False,
            }
        )
        write_state("candidate.json", candidate)
        outputs(target=target, source_tree=tree)
    elif args.action == "config":
        target = current_target()
        if args.publisher:
            if target != "dev":
                raise Refused("Production cannot build a replacement image")
            for field in ("AZURE_CLIENT_ID", "AZURE_TENANT_ID", "AZURE_SUBSCRIPTION_ID"):
                try:
                    uuid.UUID(os.environ.get(field, ""))
                except (ValueError, TypeError):
                    raise Refused("Publisher identity is not configured") from None
            if not re.fullmatch(r"[a-z0-9]+\.azurecr\.io", os.environ.get("HOSTED_REGISTRY", "")):
                raise Refused("Publisher registry is not configured")
            check_environment("build")
        else:
            assert_config(dict(os.environ), target)
            check_environment(target)
            if target == "dev" and os.environ.get("RUNNER_ENVIRONMENT") != "self-hosted":
                raise Refused("Dev requires the dedicated private runner; no public fallback")
            runtime_preflight(target)
            candidate = state("candidate.json")
            image = candidate["image"]
            if target == "prod":
                image = os.environ["HOSTED_REGISTRY"] + "/pii-guard@" + image.split("@", 1)[1]
            release_evidence(image, target)
    elif args.action == "candidate":
        if current_target() != "dev" or not IMAGE.fullmatch(args.image):
            raise Refused("Only a dev push may publish candidate image metadata")
        candidate = state("candidate.json")
        candidate["image"] = args.image
        write_state("candidate.json", candidate)
    elif args.action == "deploy":
        target = current_target()
        assert_config(dict(os.environ), target)
        candidate = state("candidate.json")
        image = candidate["image"]
        if target == "prod":
            tree, template = source_identity()
            run = api(f"repos/{REPOSITORY}/actions/runs/{candidate['run_id']}")
            validate_candidate(
                candidate, run, source_tree=tree, template_hash=template, now=int(time.time())
            )
            registry = os.environ["HOSTED_REGISTRY"].split(".", 1)[0]
            command(
                "az",
                "acr",
                "import",
                "--name",
                registry,
                "--source",
                image,
                "--repository",
                "pii-guard",
                "--output",
                "none",
            )
            digest = command(
                "az",
                "acr",
                "repository",
                "show",
                "--name",
                registry,
                "--image",
                image.split("/", 1)[1],
                "--query",
                "digest",
                "--output",
                "tsv",
            )
            digest_matches(image, digest)
            image = f"{os.environ['HOSTED_REGISTRY']}/pii-guard@{digest}"
        evidence = release_evidence(image, target)
        write_state("release-evidence.json", evidence)
        env = dict(os.environ)
        env.update(
            AZURE_ENVIRONMENT=target,
            HOSTED_IMAGE=image,
            HOSTED_RELEASE_EVIDENCE=str((STATE / "release-evidence.json").resolve()),
        )
        # Never bootstrap, fund, mint IDs or invoke public enablement for dev.
        result = subprocess.run(  # noqa: S603 - fixed reviewed deployment script, no shell input
            ["/bin/bash", "deploy/azure/deploy.sh", "stage" if target == "dev" else "enable"],
            env=env,
            check=False,
        )
        if result.returncode:
            raise Refused(
                "Deployment failed; existing ingress rollback applies, "
                "not an automatic image rollback"
            )
        # Smoke sends synthetic fixtures only. Dev must run from the reviewed private runner path.
        if target == "dev":
            command("python3", "deploy/azure/smoke.py", os.environ["HOSTED_PUBLIC_ORIGIN"])
    elif args.action == "tested":
        if current_target() != "dev":
            raise Refused("Only successful dev deployments can record test evidence")
        candidate = state("candidate.json")
        candidate["smoke_passed"] = True
        candidate["created_at"] = int(time.time())
        write_state("evidence.json", candidate)


if __name__ == "__main__":
    try:
        main()
    except (Refused, KeyError, ValueError, OSError):
        # Exceptions from subprocesses, malformed config and secrets must never be printed.
        print(
            "Hosted deployment refused: verify trusted source, prerequisites "
            "and exact image-bound evidence.",
            file=sys.stderr,
        )
        sys.exit(1)
