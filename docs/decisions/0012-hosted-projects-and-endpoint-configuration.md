# 0012. Persist project configuration separately from request state

- **Status:** accepted
- **Date:** 2026-10-28
- **Supersedes:** the configuration-retention portions of [ADR 0011](0011-hosted-saas.md)

## Context

The hosted service needs reusable projects, policy versions and explicitly configured
inference endpoints. Keeping every configuration only in process memory would lose encrypted
provider credentials and endpoint assignments on routine process restart. Persisting request
content or vault mappings would expand the privacy boundary and create a different retention
problem.

## Decision

Persist project metadata in a dedicated SQLite database. Each owner has a default project;
projects contain reusable policy families whose versions are immutable. Every endpoint pins one
exact policy version and one provider, upstream, model and credential. Publishing a new policy
version never changes existing endpoint assignments. Owners must explicitly select the version
when editing an endpoint.

Encrypt provider credentials with authenticated encryption using a domain-separated key derived
from the stable tenant key. Persist endpoint-key verifiers, not the raw keys; show raw keys once
at issue time. Owner identity manages projects, policies, endpoints and keys. Endpoint keys
authorize only the corresponding endpoint gateway and catalog routes.

Keep request content, reversible mappings, session coordination, traffic, and quota state
ephemeral and isolated by owner and project. Endpoint-scoped gateway calls add the endpoint to
the runtime namespace. Hosted quotas and sponsored allowance remain account/global resources,
not project resources.

Hosted SQLite uses `/var/lib/pii-guard/projects/state.sqlite3` with private file permissions.
The current deployment does not mount this path durably, so container replacement may lose the
configuration file. Enabling persistence across replacements requires a verified filesystem
locking contract for SQLite; generic network file shares are not assumed safe. Self-hosted
installations use `~/.local/share/pii-guard/projects/state.sqlite3` by default, overridable via
`PII_GUARD_PROJECT_STATE_PATH`. When no tenant key is configured locally, a random private
`project-storage.key` next to the database encrypts credentials. Backups must preserve the
matching database and key. Hosted backups must retain the matching tenant key through approved
secret management.

## Consequences

Project names, ownership, policy versions, endpoint configuration, encrypted provider
credentials and endpoint-key verifier/revocation metadata can persist for the lifetime of the
SQLite file. They do not make original input, restored output, vault mappings or activity
durable. Operators must provision and protect the tenant key, preserve it when restoring a
database, and disclose the current hosted container-storage limitation. Key rotation without
re-encryption makes existing provider credentials unavailable. SQLite remains a single-file,
single-host configuration store; this decision does not authorize multi-replica shared state.

See [projects and endpoints](../projects.md), [contracts](../contracts.md#projects-and-endpoints)
and [hosted operations](../hosted.md#retention-deletion-and-keys).
