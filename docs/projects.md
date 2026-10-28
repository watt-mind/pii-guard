# Projects, policies and endpoints

Hosted and self-hosted users can organize guard configuration into projects. A project owns
reusable policy families and inference endpoints. A newly established owner receives one
default project and a default policy; additional projects are isolated configuration spaces.
Project selection never changes the hosted account-wide quota or sponsored allowance.

## Policies

A policy family contains a sequence of immutable versions. Each version records a complete
text-entity action set (`mask`, `keep` or `block`), language, and detection mode. Creating a
revision appends the next version to the family; it does not edit an existing version. An
endpoint pins one exact version. New revisions do not move existing endpoints. To change an
endpoint's behavior, explicitly edit that endpoint and select the intended version.

Policy `keep` actions affect masking only after detection and resolution. They do not disable
detection or suppress account/global quotas. `block` fails the request closed when an entity
of that type is detected. Visual entity policies are not configurable here. Hosted endpoints
run the hosted fast detector; self-hosted endpoints may use the supported detector modes for
the configured deployment profile. Local-only detection continues to prohibit remote original-
text detectors and refuses audit mode.

## Endpoints and credentials

An endpoint binds one provider, upstream base URL, model, credential and policy version. A
provider credential is write-only: it is encrypted in the local metadata store, excluded from
metadata responses and never returned after creation. Editing an endpoint can preserve its
credential or replace it. Sponsored Meta endpoints use the deployment's sponsored credential
and do not store a per-endpoint provider secret. Endpoint gateway URLs use the form
`/e/{endpoint_id}/v1`; supported OpenAI-compatible routes are chat completions, Responses and
model catalogs. Endpoint selection is explicit. Invalid, disabled or revoked endpoint
credentials fail closed; they do not fall back to another endpoint or sponsored inference.

An owner may issue endpoint-scoped guard keys. The raw value is shown once at creation; the
store retains only its SHA-256 verifier. At most 32 keys are active per endpoint, with up to
128 total active and revoked records retained; a global limit of 65,536 records applies. The oldest
revoked records may be pruned to stay within these limits. A key authorizes only that
endpoint's gateway and model-catalog routes; it cannot access account, project, policy,
endpoint-management, traffic or vault-inspection routes. Keys are individually revocable.
Setting `enabled=false` on an endpoint revokes all currently active keys atomically while
preserving the endpoint configuration. Re-enabling it does not reactivate those keys; issue
new keys. Deleting an endpoint permanently removes its configuration and key records. Revocation
applies to new admissions; a request that already captured its endpoint configuration may
finish with that snapshot.

## Isolation and lifetime

The hosted owner remains the account identity. Hosted management operations require that
identity; an endpoint key is not an owner credential. Project and endpoint IDs are always
checked against the authenticated owner and selected project. Hosted account-wide request,
token, concurrency and sponsorship accounting remains shared across projects. Creating another
project or endpoint does not create another quota or sponsored budget.

Vault mappings, known values, detection caches, session coordination, masked traffic events and
vault inspector state are held in bounded process memory. Runtime namespaces include owner and
project; endpoint-scoped gateway requests also include the endpoint. Hosted vault/session
capacity is shared across that owner's project and endpoint namespaces. Identical session IDs
in different namespaces cannot restore one another's mappings. These request and token mappings
are ephemeral and disappear on runtime expiry or process loss. Project persistence must never be
described as persistence of original text, restored output, vault mappings, session contents,
traffic, quota counters or sponsored spend records.

## Metadata storage and operations

Project configuration is stored in a dedicated SQLite database. By default its path is
`~/.local/share/pii-guard/projects/state.sqlite3`; override it with
`PII_GUARD_PROJECT_STATE_PATH`. The directory and database are created with owner-only
permissions (`0700` and `0600`). Hosted images set the path to
`/var/lib/pii-guard/projects/state.sqlite3`; that directory is writable but ephemeral unless
the operator mounts storage there. The hosted topology runs one replica/worker, but a durable
mount still needs a verified local-filesystem SQLite locking contract. Do not assume generic
SMB/Azure Files semantics are suitable for SQLite. Include the database in protected backups
only if restoration is required. A backup contains configuration, not request mappings.
Restrict backup access as carefully as the running store.

Hosted deployments require the existing stable 32-byte `PII_GUARD_TENANT_KEY`. Credential
encryption uses authenticated Fernet encryption with a domain-separated HMAC-SHA256 key derived
from that tenant key. The database also contains an encrypted sentinel; a missing or changed key
prevents the application from opening the project store. Back up the database and retain the
matching tenant key through approved secret management. Rotating the tenant key without
re-encrypting the database makes stored provider credentials unavailable. Do not log database
rows, credential envelopes, key material or raw endpoint keys.

For local self-hosting, when no tenant key is configured, pii-guard creates a random
`project-storage.key` beside the database with owner-only permissions. Back up that key with
the database; losing either or restoring them from different points makes stored credentials
unavailable. Existing environment-based upstream configuration remains available for the local
single-owner setup.

The default Docker image creates `/var/lib/pii-guard/projects` and uses the same database path.
The `api` service in `compose.yaml` mounts a named `pii-guard-projects` volume there, so
`docker compose down` preserves project configuration and the locally generated encryption
key. `docker compose down -v` removes that volume. If `.env` supplies
`PII_GUARD_TENANT_KEY`, keep that key stable with the volume; back up both together if the
configuration must be restored. Restrict access to the Docker volume and its backups.

The optional `demo` Compose profile deliberately uses `/tmp/pii-guard-projects` and generates
a new tenant key for each container. Its project configuration and credentials are ephemeral
and are expected to be lost when the demo container is replaced.

### Hosted encrypted Blob snapshots

Set `PII_GUARD_HOSTED_PROJECT_STORE=azure_blob` and install the `hosted-azure` extra to
persist hosted configuration without relying on a mounted filesystem's SQLite locks.
`PII_GUARD_HOSTED_PROJECT_ACCOUNT_URL` must be the account's public HTTPS Blob origin,
with no path, SAS, credentials, query or fragment. Set `PII_GUARD_HOSTED_PROJECT_CONTAINER`
(default `project-configuration`) and `PII_GUARD_HOSTED_PROJECT_ENVIRONMENT=dev|prod`.
Only managed identity authenticates; an optional
`PII_GUARD_HOSTED_PROJECT_MANAGED_IDENTITY_CLIENT_ID` chooses a user-assigned identity.
Use separate private dev/prod containers or accounts, identities and stable tenant keys.
Give the app data access only to its environment's configuration container.

The fixed blob is `<environment>.projects.v1.enc`. The outer authenticated encryption key
uses a distinct tenant-key derivation domain and environment binding. Provider credentials
remain encrypted independently inside the database, and the existing encrypted key sentinel
is verified on every load. Losing or changing the stable 32-byte tenant key makes the store
unreadable. Backups and authorized writers are trusted: ETags prevent concurrent lost updates,
but do not prevent an authorized operator from restoring an older snapshot and its old key
revocations. Never roll back configuration storage to roll back application code.

Serving code never creates missing blobs, containers or encryption keys. Before first use,
an authorized operator runs the following once with the target environment's settings and
managed identity (for example as a one-off job in that environment):

```bash
uv run python -m pii_guard.projects.blob --initialize-empty
```

This initializes an empty encrypted database only if the blob does not exist. Repeating it,
including after an unknown write outcome, cannot overwrite existing configuration. It is an
explicit bootstrap command, never a startup/deploy hook. It does not import local SQLite state;
a migration requires a separately reviewed operator procedure. Set the private container up
before initialization; anonymous/public blob access must be disabled at the storage account.

Every operation fetches fresh encrypted state, validates its environment, exact schema,
integrity, foreign keys and credential sentinel, and uses a private in-memory SQLite engine.
The database is capped at 8 MiB and ciphertext at 12 MiB; downloads and SDK timeouts are
bounded and SDK retries are disabled. No plaintext snapshot, SQLite journal or fallback file
is written to disk. Read-only operations issue no PUT. Establishing a missing owner default
is a mutation even when triggered by a GET. Each mutation commits through the read ETag's
`If-Match` and returns success, including a newly issued raw endpoint key, only after a
confirmed write. Conflicts, missing state, corruption, wrong keys, unavailable storage and
ambiguous commits return sanitized `503 project_storage_unavailable`; mutations are never
automatically retried or replayed. After a failed mutation, inspect current configuration
before making an explicit new request. Revocation is observed on each subsequent instance's
admission; already admitted requests can finish with their captured snapshot.

Project routes execute in worker threads, and middleware offloads project operations before
ASGI routing. This durable store does not enable multiple application workers/replicas:
request/session state and quota counters still require the existing single-process topology.
There is no connection, vault, session, traffic or sponsored allowance persistence in this blob.

### Owner access in Docker Compose

The Compose API joins a bridge network. A request reaching the container through that network
is not a trusted loopback request, even though Compose publishes the service only on host
loopback. Set `PII_GUARD_API_TOKEN` in the local `.env` file to authorize management requests;
the token protects API routes other than `/healthz`. Keep `.env` private and do not commit it.

In the local Projects page, expand **Local guard access**, enter the same value in **Owner API
token**, and choose **Use owner token**. The browser keeps it in tab memory only; it clears on
reload and is never written to browser storage or a URL. The local client attaches it only to
recognized same-origin guard API routes. It does not send the owner token to provider origins,
endpoint-key routes, public/account/demo routes or static assets. Use **Clear owner token** to
remove it from the current tab. Hosted mode keeps Google/cookie authentication and does not
show this local token control.

Metadata that is durable includes project ownership and names, default-project selection,
complete immutable policy versions, endpoint provider/URL/model/policy assignment/enabled
state, encrypted provider credentials, and endpoint-key verifier/revocation metadata. The
provider secret itself is encrypted; the one-time endpoint key is not recoverable from its
verifier. SQLite durability is independent of the ephemeral runtime mappings and the separate
hosted sponsored-spend store.
