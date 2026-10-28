"""Encrypted configuration snapshots with a fresh read and conditional commit per operation.

No local database/cache/fallback is used. A failed or ambiguous PUT never returns the
operation's result (including newly generated endpoint keys), and is never replayed.
"""

from __future__ import annotations

import argparse
import base64
import hmac
import re
import threading
from collections.abc import Callable, Mapping
from typing import Any, Protocol, TypeVar

from cryptography.fernet import Fernet

from pii_guard.policy import PolicySet
from pii_guard.projects.store import EndpointSnapshot, ProjectStorageError, ProjectStore

MAX_DATABASE_BYTES = 8 * 1024 * 1024
MAX_BLOB_BYTES = 12 * 1024 * 1024
T = TypeVar("T")


class ProjectBlob(Protocol):
    def read(self) -> tuple[bytes, str]: ...
    def compare_and_swap(self, value: bytes, etag: str) -> None: ...
    def initialize(self, value: bytes) -> None: ...
    def close(self) -> None: ...


class BlobProjectStore:
    """Synchronous store; callers must run operations outside the ASGI event loop."""

    def __init__(
        self,
        blob: ProjectBlob,
        key: bytes,
        defaults: PolicySet,
        detection_profile: str,
        environment: str,
    ) -> None:
        if len(key) != 32 or environment not in {"dev", "prod"}:
            raise ProjectStorageError()
        self._blob, self._key = blob, key
        self._defaults, self._profile = defaults, detection_profile
        self._lock = threading.Lock()
        self._closed = False
        # The inner credential key and outer snapshot key have separate HMAC domains.
        derived = hmac.digest(
            key, b"pii-guard-project-snapshot-v1\0" + environment.encode(), "sha256"
        )
        self._cipher = Fernet(base64.urlsafe_b64encode(derived))
        self._binding = b"pii-guard-project-snapshot-v1\0" + environment.encode() + b"\0"

    def _encode(self, database: bytes) -> bytes:
        if len(database) > MAX_DATABASE_BYTES:
            raise ProjectStorageError()
        raw = self._cipher.encrypt(self._binding + database)
        if len(raw) > MAX_BLOB_BYTES:
            raise ProjectStorageError()
        return raw

    def _decode(self, raw: bytes) -> bytes:
        if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_BLOB_BYTES:
            raise ProjectStorageError()
        plain = self._cipher.decrypt(raw)
        if not plain.startswith(self._binding):
            raise ProjectStorageError()
        database = plain[len(self._binding) :]
        if not 0 < len(database) <= MAX_DATABASE_BYTES:
            raise ProjectStorageError()
        return database

    def _run(self, operation: Callable[[ProjectStore], T]) -> T:
        with self._lock:
            engine = None
            try:
                if self._closed:
                    raise ProjectStorageError()
                raw, etag = self._blob.read()
                if (
                    not isinstance(etag, str)
                    or not etag.isascii()
                    or not re.fullmatch(r'"[^"\x00-\x20\x7f]{1,254}"', etag)
                ):
                    raise ProjectStorageError()
                engine = ProjectStore.memory(
                    self._key, self._defaults, self._profile, self._decode(raw)
                )
                before = engine._db.total_changes
                result = operation(engine)
                # Read-only calls perform no PUT. Default creation in a GET remains an
                # atomic mutation, exactly as in the local store.
                if engine._db.total_changes != before:
                    self._blob.compare_and_swap(self._encode(engine.serialized()), etag)
                return result
            except Exception as exc:
                from pii_guard.projects.store import InvalidProjectConfigError, ProjectNotFoundError

                if isinstance(exc, (InvalidProjectConfigError, ProjectNotFoundError)):
                    raise
                raise ProjectStorageError() from None
            finally:
                if engine is not None:
                    engine.close()

    def initialize_empty(self) -> None:
        """Explicit operator-only create-if-absent; never called by serving code."""
        with self._lock:
            engine = None
            try:
                if self._closed:
                    raise ProjectStorageError()
                engine = ProjectStore.memory(self._key, self._defaults, self._profile)
                self._blob.initialize(self._encode(engine.serialized()))
            except Exception:
                raise ProjectStorageError() from None
            finally:
                if engine is not None:
                    engine.close()

    def default_project(self, owner: str) -> dict[str, Any]:
        return self._run(lambda store: store.default_project(owner))

    def list_projects(self, owner: str) -> list[dict[str, Any]]:
        return self._run(lambda store: store.list_projects(owner))

    def create_project(self, owner: str, name: str) -> dict[str, Any]:
        return self._run(lambda store: store.create_project(owner, name))

    def get_project(self, owner: str, project: str) -> dict[str, Any]:
        return self._run(lambda store: store.get_project(owner, project))

    def list_policies(self, owner: str, project: str) -> list[dict[str, Any]]:
        return self._run(lambda store: store.list_policies(owner, project))

    def create_policy(
        self, owner: str, project: str, data: Mapping[str, Any], policy_id: str | None = None
    ) -> dict[str, Any]:
        return self._run(lambda store: store.create_policy(owner, project, data, policy_id))

    def get_policy(self, owner: str, project: str, policy_version_id: str) -> dict[str, Any]:
        return self._run(lambda store: store.get_policy(owner, project, policy_version_id))

    def list_endpoints(self, owner: str, project: str) -> list[dict[str, Any]]:
        return self._run(lambda store: store.list_endpoints(owner, project))

    def save_endpoint(
        self, owner: str, project: str, data: Mapping[str, Any], endpoint_id: str | None = None
    ) -> dict[str, Any]:
        return self._run(lambda store: store.save_endpoint(owner, project, data, endpoint_id))

    def delete_endpoint(self, owner: str, project: str, endpoint: str) -> None:
        return self._run(lambda store: store.delete_endpoint(owner, project, endpoint))

    def endpoint_snapshot(self, owner: str, project: str, endpoint: str) -> EndpointSnapshot:
        return self._run(lambda store: store.endpoint_snapshot(owner, project, endpoint))

    def issue_key(self, owner: str, project: str, endpoint: str, name: str) -> dict[str, Any]:
        return self._run(lambda store: store.issue_key(owner, project, endpoint, name))

    def list_keys(self, owner: str, project: str, endpoint: str) -> list[dict[str, Any]]:
        return self._run(lambda store: store.list_keys(owner, project, endpoint))

    def revoke_key(self, owner: str, project: str, endpoint: str, key_id: str) -> None:
        return self._run(lambda store: store.revoke_key(owner, project, endpoint, key_id))

    def resolve_key(self, secret: str, endpoint: str) -> EndpointSnapshot | None:
        return self._run(lambda store: store.resolve_key(secret, endpoint))

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._blob.close()


def configured_blob_store(settings: Any) -> BlobProjectStore:
    """Construct clients without I/O; no local fallback when configuration is invalid."""
    from pii_guard.projects.blob_transport import AzureProjectBlob

    try:
        key = settings.tenant_key_bytes()
    except ValueError:
        raise ProjectStorageError() from None
    if not settings.hosted or key is None or len(key) != 32:
        raise ProjectStorageError()
    return BlobProjectStore(
        AzureProjectBlob(
            settings.hosted_project_account_url or "",
            settings.hosted_project_container,
            settings.hosted_project_environment,
            settings.hosted_project_managed_identity_client_id,
        ),
        key,
        PolicySet.from_settings(settings),
        settings.detection_profile,
        settings.hosted_project_environment,
    )


def main() -> int:
    from pii_guard.config import Settings

    parser = argparse.ArgumentParser(description="Initialize an empty hosted project blob once")
    parser.add_argument("--initialize-empty", action="store_true", required=True)
    parser.parse_args()
    store = None
    try:
        settings = Settings()
        if settings.hosted_project_store != "azure_blob":
            raise ProjectStorageError()
        store = configured_blob_store(settings)
        store.initialize_empty()
    except Exception:
        print("Project configuration initialization failed")
        return 1
    finally:
        if store is not None:
            store.close()
    print("Empty project configuration initialized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
