"""Transactional project metadata; credentials encrypted, endpoint bearer keys hashed.

Only configuration is durable. Request texts, vault mappings and activity are never written
here. Policy versions are append-only and each endpoint pins one exact version.

A policy version holds text and visual entity actions (``FACE``, ``ID_PHOTO``, ``SIGNATURE``,
``STAMP``: ``mask`` or ``keep`` only) and ``visual_detection`` (``local`` by default, or ``sam``;
``local-only`` deployments accept ``local`` only), LAB-1444. Versions saved before then hold
text types only and no ``visual_detection``; they read as ``local`` with the server's visual
actions (:mod:`pii_guard.projects.visual`).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import stat
import threading
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from pii_guard.policy import Policy, PolicySet
from pii_guard.types import TEXT_ENTITY_TYPES, VISUAL_ENTITY_TYPES, EntityType, PiiGuardError

#: The actions a project policy may give a visual type (``block`` is text-only here).
VISUAL_POLICY_ACTIONS = frozenset({Policy.MASK, Policy.KEEP})
#: ``visual_detection`` values; the first is the default.
VISUAL_DETECTIONS = ("local", "sam")

_SCHEMA = """
                CREATE TABLE IF NOT EXISTS store_metadata (
                    name TEXT PRIMARY KEY, value BLOB NOT NULL
                );
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY, owner_id TEXT NOT NULL, name TEXT NOT NULL,
                    is_default INTEGER NOT NULL DEFAULT 0, default_policy_id TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS owner_default ON projects(owner_id)
                    WHERE is_default = 1;
                CREATE TABLE IF NOT EXISTS policy_versions (
                    policy_version_id TEXT PRIMARY KEY, policy_id TEXT NOT NULL,
                    project_id TEXT NOT NULL REFERENCES projects(id), version INTEGER NOT NULL,
                    name TEXT NOT NULL, data TEXT NOT NULL, created_at TEXT NOT NULL,
                    UNIQUE(policy_id, version)
                );
                CREATE TABLE IF NOT EXISTS endpoints (
                    id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id),
                    name TEXT NOT NULL, policy_version_id TEXT NOT NULL
                        REFERENCES policy_versions(policy_version_id),
                    provider TEXT NOT NULL, base_url TEXT NOT NULL, model TEXT NOT NULL,
                    credential BLOB, enabled INTEGER NOT NULL, created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS endpoint_keys (
                    id TEXT PRIMARY KEY, endpoint_id TEXT NOT NULL REFERENCES endpoints(id),
                    name TEXT NOT NULL, digest BLOB NOT NULL UNIQUE,
                    created_at TEXT NOT NULL, revoked_at TEXT
                );
                """


class ProjectNotFoundError(PiiGuardError):
    code = "project_not_found"
    status_code = 404

    def __init__(self) -> None:
        super().__init__("Project resource is unknown")


class InvalidProjectConfigError(PiiGuardError):
    code = "invalid_project_config"
    status_code = 422

    def __init__(self) -> None:
        super().__init__("Invalid project configuration")


class ProjectStorageError(PiiGuardError):
    code = "project_storage_unavailable"
    status_code = 503

    def __init__(self) -> None:
        super().__init__("Project configuration storage is unavailable")


@dataclass(frozen=True, slots=True, repr=False)
class EndpointSnapshot:
    owner_id: str
    project_id: str
    id: str
    name: str
    provider: str
    base_url: str
    # ``None`` is pass-through: the client's own ``model`` is forwarded unchanged.
    model: str | None
    api_key: SecretStr | None = field(repr=False)
    enabled: bool
    policy_id: str
    policy_version_id: str
    policy_version: int
    policy: Mapping[str, Any]


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _name(value: object, *, maximum: int = 64) -> str:
    if not isinstance(value, str):
        raise InvalidProjectConfigError()
    value = value.strip()
    if not value or len(value) > maximum or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise InvalidProjectConfigError()
    return value


def _model(value: object, provider: str) -> str:
    """The stored model: one pinned id, or ``''`` for pass-through (BYOK only).

    Pass-through is stored as ``''`` in the existing ``model TEXT NOT NULL`` column, so the
    schema (and every existing snapshot, which the loader checks against it) is unchanged.
    Sponsored endpoints always pin a model; the allow-list is checked by the caller.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        if provider == "sponsored":
            raise InvalidProjectConfigError()
        return ""
    return _name(value, maximum=256)


class ProjectStore:
    """Single SQLite connection protected by a lock; SQL transactions protect other processes."""

    def __init__(self, path: str, key: bytes, defaults: PolicySet, detection_profile: str) -> None:
        if len(key) < 32 or detection_profile not in {"standard", "local-only"}:
            raise ValueError("Invalid project storage configuration")
        self._lock = threading.RLock()
        self._defaults = {t.value: defaults.of(t).value for t in TEXT_ENTITY_TYPES}
        # A visual default the server blocks is stored as mask; the server still wins when
        # stricter (pii_guard.projects.visual), so the image is refused either way.
        self._defaults.update(
            {
                t.value: (Policy.KEEP if defaults.of(t) is Policy.KEEP else Policy.MASK).value
                for t in VISUAL_ENTITY_TYPES
            }
        )
        self._profile = detection_profile
        derived = hmac.digest(key, b"pii-guard-project-credentials-v1", "sha256")
        self._cipher = Fernet(base64.urlsafe_b64encode(derived))
        try:
            location = Path(path).expanduser()
            location.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if location.parent.is_symlink() or location.is_symlink():
                raise ProjectStorageError()
            parent_stat = location.parent.stat()
            if parent_stat.st_uid != os.getuid() or stat.S_IMODE(parent_stat.st_mode) & 0o077:
                raise ProjectStorageError()
            # Exclusive creation preserves the permissions before SQLite ever opens it.
            try:
                descriptor = os.open(location, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                existing = location.stat()
                if (
                    not stat.S_ISREG(existing.st_mode)
                    or existing.st_uid != os.getuid()
                    or existing.st_nlink != 1
                    or stat.S_IMODE(existing.st_mode) & 0o077
                ):
                    raise ProjectStorageError() from None
            else:
                os.close(descriptor)
            self._db = sqlite3.connect(str(location), check_same_thread=False, timeout=10)
            self._db.row_factory = sqlite3.Row
            self._db.execute("PRAGMA foreign_keys = ON")
            # DELETE journals inherit the database's mode; WAL has no durability benefit here.
            self._db.execute("PRAGMA journal_mode = DELETE")
            self._db.execute("PRAGMA secure_delete = ON")
            self._db.executescript(_SCHEMA)
            # Refuse opening an existing store with another key before serving any requests.
            with self._db:
                self._db.execute(
                    "INSERT OR IGNORE INTO store_metadata VALUES ('key_check', ?)",
                    (self._cipher.encrypt(b"pii-guard-project-store-v1"),),
                )
                sentinel = self._db.execute(
                    "SELECT value FROM store_metadata WHERE name = 'key_check'"
                ).fetchone()[0]
                if self._cipher.decrypt(sentinel) != b"pii-guard-project-store-v1":
                    raise ProjectStorageError()
        except (OSError, sqlite3.Error, InvalidToken):
            raise ProjectStorageError() from None

    @classmethod
    def memory(
        cls,
        key: bytes,
        defaults: PolicySet,
        detection_profile: str,
        snapshot: bytes | None = None,
    ) -> ProjectStore:
        """Build a bounded private in-memory engine; existing snapshots are never migrated."""
        if len(key) < 32 or detection_profile not in {"standard", "local-only"}:
            raise ProjectStorageError()
        instance = cls.__new__(cls)
        instance._lock = threading.RLock()
        instance._defaults = {t.value: defaults.of(t).value for t in TEXT_ENTITY_TYPES}
        instance._profile = detection_profile
        derived = hmac.digest(key, b"pii-guard-project-credentials-v1", "sha256")
        instance._cipher = Fernet(base64.urlsafe_b64encode(derived))
        instance._db = sqlite3.connect(":memory:", check_same_thread=False)
        db = instance._db
        try:
            db.row_factory = sqlite3.Row
            if snapshot is None:
                db.executescript(_SCHEMA)
                db.execute(
                    "INSERT INTO store_metadata VALUES ('key_check', ?)",
                    (instance._cipher.encrypt(b"pii-guard-project-store-v1"),),
                )
                db.commit()
            else:
                if not isinstance(snapshot, bytes) or not 0 < len(snapshot) <= 8 * 1024 * 1024:
                    raise ProjectStorageError()
                db.deserialize(snapshot)
                # No extension loading, triggers, views or implicit migrations are accepted.
                reference = sqlite3.connect(":memory:")
                try:
                    reference.executescript(_SCHEMA)
                    expected = reference.execute(
                        "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY name"
                    ).fetchall()
                finally:
                    reference.close()
                actual = db.execute(
                    "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY name"
                ).fetchall()
                if [tuple(row) for row in actual] != expected:
                    raise ProjectStorageError()
                if [tuple(row) for row in db.execute("PRAGMA integrity_check")] != [("ok",)]:
                    raise ProjectStorageError()
                if db.execute("PRAGMA foreign_key_check").fetchone() is not None:
                    raise ProjectStorageError()
                sentinels = db.execute("SELECT name, value FROM store_metadata").fetchall()
                if (
                    len(sentinels) != 1
                    or sentinels[0]["name"] != "key_check"
                    or instance._cipher.decrypt(sentinels[0]["value"])
                    != b"pii-guard-project-store-v1"
                ):
                    raise ProjectStorageError()
            if db.execute("PRAGMA page_size").fetchone()[0] != 4096:
                raise ProjectStorageError()
            db.execute("PRAGMA max_page_count = 2048")
            db.execute("PRAGMA foreign_keys = ON")
            db.execute("PRAGMA temp_store = MEMORY")
            db.execute("PRAGMA secure_delete = ON")
            db.execute("PRAGMA trusted_schema = OFF")
            return instance
        except Exception:
            db.close()
            raise ProjectStorageError() from None

    def serialized(self) -> bytes:
        """Serialize only configuration; the caller encrypts it before persistence."""
        try:
            raw = self._db.serialize()
            if len(raw) > 8 * 1024 * 1024:
                raise ProjectStorageError()
            return raw
        except sqlite3.Error:
            raise ProjectStorageError() from None

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            try:
                self._db.execute("BEGIN IMMEDIATE")
                yield self._db
                self._db.commit()
            except sqlite3.Error:
                self._db.rollback()
                raise ProjectStorageError() from None
            except BaseException:
                self._db.rollback()
                raise

    @staticmethod
    def _project(db: sqlite3.Connection, owner: str, project: str) -> sqlite3.Row:
        row = db.execute(
            "SELECT * FROM projects WHERE id = ? AND owner_id = ?", (project, owner)
        ).fetchone()
        if row is None:
            raise ProjectNotFoundError()
        return row

    def _project_metadata(self, row: sqlite3.Row) -> dict[str, Any]:
        version = self._db.execute(
            "SELECT policy_version_id FROM policy_versions "
            "WHERE project_id = ? AND policy_id = ? AND version = 1",
            (row["id"], row["default_policy_id"]),
        ).fetchone()
        if version is None:
            raise ProjectStorageError()
        return {
            "id": row["id"],
            "name": row["name"],
            "default_policy_id": row["default_policy_id"],
            "default_policy_version_id": version["policy_version_id"],
            "is_default": bool(row["is_default"]),
            "created_at": row["created_at"],
        }

    def _new_project(
        self, db: sqlite3.Connection, owner: str, name: str, *, default: bool
    ) -> dict[str, Any]:
        count = db.execute("SELECT COUNT(*) FROM projects WHERE owner_id = ?", (owner,)).fetchone()[
            0
        ]
        if count >= 32 or db.execute("SELECT COUNT(*) FROM projects").fetchone()[0] >= 4096:
            raise InvalidProjectConfigError()
        project, family = secrets.token_urlsafe(18), secrets.token_urlsafe(18)
        db.execute(
            "INSERT INTO projects VALUES (?, ?, ?, ?, ?, ?)",
            (project, owner, _name(name), int(default), family, _now()),
        )
        self._new_policy(db, project, {"name": "Default policy"}, family)
        return self._project_metadata(self._project(db, owner, project))

    def default_project(self, owner: str) -> dict[str, Any]:
        if not owner:
            raise InvalidProjectConfigError()
        with self._transaction() as db:
            row = db.execute(
                "SELECT * FROM projects WHERE owner_id = ? AND is_default = 1", (owner,)
            ).fetchone()
            return (
                self._project_metadata(row)
                if row
                else self._new_project(db, owner, "Default project", default=True)
            )

    def list_projects(self, owner: str) -> list[dict[str, Any]]:
        self.default_project(owner)
        with self._transaction() as db:
            return [
                self._project_metadata(row)
                for row in db.execute(
                    "SELECT * FROM projects WHERE owner_id = ? "
                    "ORDER BY is_default DESC, created_at, id",
                    (owner,),
                )
            ]

    def create_project(self, owner: str, name: str) -> dict[str, Any]:
        self.default_project(owner)
        with self._transaction() as db:
            return self._new_project(db, owner, name, default=False)

    def get_project(self, owner: str, project: str) -> dict[str, Any]:
        with self._transaction() as db:
            return self._project_metadata(self._project(db, owner, project))

    def _policy_data(self, data: Mapping[str, Any]) -> dict[str, Any]:
        policies = dict(self._defaults)
        overrides = data.get("entity_policies", {})
        if not isinstance(overrides, Mapping):
            raise InvalidProjectConfigError()
        try:
            for entity, policy in overrides.items():
                typed = EntityType(entity)
                action = Policy(policy)
                if typed in VISUAL_ENTITY_TYPES and action not in VISUAL_POLICY_ACTIONS:
                    raise InvalidProjectConfigError()
                policies[typed.value] = action.value
        except (TypeError, ValueError):
            raise InvalidProjectConfigError() from None
        language = data.get("language", "hu")
        mode = data.get("mode", "fast")
        detection = data.get("visual_detection", VISUAL_DETECTIONS[0])
        if (
            detection not in VISUAL_DETECTIONS
            or (self._profile == "local-only" and detection != "local")
            or not isinstance(language, str)
            or not 2 <= len(language) <= 16
            or not all(char.isascii() and (char.isalpha() or char == "-") for char in language)
            or mode not in {"fast", "audit"}
            or data.get("detection_profile", self._profile) != self._profile
            or (self._profile == "local-only" and mode != "fast")
        ):
            raise InvalidProjectConfigError()
        return {
            "entity_policies": policies,
            "language": language,
            "mode": mode,
            "detection_profile": self._profile,
            "visual_detection": detection,
        }

    @staticmethod
    def _policy_metadata(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["policy_id"],
            "policy_id": row["policy_id"],
            "policy_version_id": row["policy_version_id"],
            "version": row["version"],
            "name": row["name"],
            "created_at": row["created_at"],
            **json.loads(row["data"]),
        }

    def _new_policy(
        self, db: sqlite3.Connection, project: str, data: Mapping[str, Any], family: str
    ) -> dict[str, Any]:
        count = db.execute(
            "SELECT COUNT(*) FROM policy_versions WHERE project_id = ?", (project,)
        ).fetchone()[0]
        if (
            count >= 256
            or db.execute("SELECT COUNT(*) FROM policy_versions").fetchone()[0] >= 65536
        ):
            raise InvalidProjectConfigError()
        previous = db.execute(
            "SELECT MAX(version) FROM policy_versions WHERE project_id = ? AND policy_id = ?",
            (project, family),
        ).fetchone()[0]
        version_id = secrets.token_urlsafe(18)
        db.execute(
            "INSERT INTO policy_versions VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                version_id,
                family,
                project,
                (previous or 0) + 1,
                _name(data.get("name")),
                json.dumps(self._policy_data(data), sort_keys=True),
                _now(),
            ),
        )
        return self._policy_metadata(
            db.execute(
                "SELECT * FROM policy_versions WHERE policy_version_id = ?", (version_id,)
            ).fetchone()
        )

    def list_policies(self, owner: str, project: str) -> list[dict[str, Any]]:
        with self._transaction() as db:
            self._project(db, owner, project)
            return [
                self._policy_metadata(row)
                for row in db.execute(
                    "SELECT * FROM policy_versions WHERE project_id = ? "
                    "ORDER BY created_at, version",
                    (project,),
                )
            ]

    def create_policy(
        self, owner: str, project: str, data: Mapping[str, Any], policy_id: str | None = None
    ) -> dict[str, Any]:
        with self._transaction() as db:
            self._project(db, owner, project)
            if (
                policy_id is not None
                and db.execute(
                    "SELECT 1 FROM policy_versions WHERE project_id = ? AND policy_id = ?",
                    (project, policy_id),
                ).fetchone()
                is None
            ):
                raise ProjectNotFoundError()
            return self._new_policy(db, project, data, policy_id or secrets.token_urlsafe(18))

    def get_policy(self, owner: str, project: str, policy_version_id: str) -> dict[str, Any]:
        with self._transaction() as db:
            self._project(db, owner, project)
            row = db.execute(
                "SELECT * FROM policy_versions WHERE project_id = ? AND policy_version_id = ?",
                (project, policy_version_id),
            ).fetchone()
            if row is None:
                raise ProjectNotFoundError()
            return self._policy_metadata(row)

    @staticmethod
    def _endpoint(db: sqlite3.Connection, project: str, endpoint: str) -> sqlite3.Row:
        row = db.execute(
            "SELECT e.*, p.policy_id, p.version AS policy_version, p.data AS policy_data, "
            "p.name AS policy_name, p.created_at AS policy_created_at FROM endpoints e "
            "JOIN policy_versions p USING(policy_version_id) WHERE e.id = ? AND e.project_id = ?",
            (endpoint, project),
        ).fetchone()
        if row is None:
            raise ProjectNotFoundError()
        return row

    @staticmethod
    def _endpoint_metadata(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "project_id": row["project_id"],
            "name": row["name"],
            "policy_id": row["policy_id"],
            "policy_version_id": row["policy_version_id"],
            "policy_version": row["policy_version"],
            "provider": row["provider"],
            "base_url": row["base_url"],
            "model": row["model"] or None,
            "credential_configured": row["credential"] is not None,
            "enabled": bool(row["enabled"]),
            "base_path": f"/e/{row['id']}/v1",
            "created_at": row["created_at"],
        }

    def list_endpoints(self, owner: str, project: str) -> list[dict[str, Any]]:
        with self._transaction() as db:
            self._project(db, owner, project)
            ids = db.execute(
                "SELECT id FROM endpoints WHERE project_id = ? ORDER BY created_at", (project,)
            ).fetchall()
            return [self._endpoint_metadata(self._endpoint(db, project, row["id"])) for row in ids]

    def save_endpoint(
        self, owner: str, project: str, data: Mapping[str, Any], endpoint_id: str | None = None
    ) -> dict[str, Any]:
        with self._transaction() as db:
            self._project(db, owner, project)
            previous = self._endpoint(db, project, endpoint_id) if endpoint_id else None
            count = db.execute(
                "SELECT COUNT(*) FROM endpoints WHERE project_id = ?", (project,)
            ).fetchone()[0]
            if previous is None and (
                count >= 128 or db.execute("SELECT COUNT(*) FROM endpoints").fetchone()[0] >= 16384
            ):
                raise InvalidProjectConfigError()
            version_id = data.get("policy_version_id")
            if (
                not isinstance(version_id, str)
                or db.execute(
                    "SELECT 1 FROM policy_versions WHERE project_id = ? AND policy_version_id = ?",
                    (project, version_id),
                ).fetchone()
                is None
            ):
                raise InvalidProjectConfigError()
            provider, base_url = data.get("provider"), data.get("base_url")
            if provider not in {"meta", "openai", "fireworks", "openrouter", "custom", "sponsored"}:
                raise InvalidProjectConfigError()
            if not isinstance(base_url, str) or not 1 <= len(base_url) <= 2048:
                raise InvalidProjectConfigError()
            model = _model(data.get("model"), provider)
            enabled = data.get("enabled", True)
            if type(enabled) is not bool:
                raise InvalidProjectConfigError()
            endpoint = endpoint_id or secrets.token_urlsafe(18)
            raw_key = data.get("api_key")
            if isinstance(raw_key, SecretStr):
                raw_key = raw_key.get_secret_value()
            credential = None
            if provider == "sponsored":
                if raw_key is not None:
                    raise InvalidProjectConfigError()
            elif raw_key is None:
                if previous is None or (provider, base_url) != (
                    previous["provider"],
                    previous["base_url"],
                ):
                    raise InvalidProjectConfigError()
                credential = previous["credential"]
                if credential is None:
                    raise InvalidProjectConfigError()
            else:
                if (
                    not isinstance(raw_key, str)
                    or not 1 <= len(raw_key) <= 4096
                    or any(ord(c) <= 32 or ord(c) >= 127 for c in raw_key)
                    or raw_key.startswith("pg_")
                ):
                    raise InvalidProjectConfigError()
                envelope = json.dumps(
                    {
                        "owner": owner,
                        "project": project,
                        "endpoint": endpoint,
                        "provider": provider,
                        "base_url": base_url,
                        "key": raw_key,
                    }
                ).encode()
                credential = self._cipher.encrypt(envelope)
            values = (
                _name(data.get("name")),
                version_id,
                provider,
                base_url,
                model,
                credential,
                int(enabled),
            )
            if previous is None:
                db.execute(
                    "INSERT INTO endpoints VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (endpoint, project, *values, _now()),
                )
            else:
                db.execute(
                    "UPDATE endpoints SET name=?, policy_version_id=?, provider=?, base_url=?, "
                    "model=?, credential=?, enabled=? WHERE id=? AND project_id=?",
                    (*values, endpoint, project),
                )
            if not enabled:
                # Disable and revocation commit together. Re-enabling never restores an old key.
                db.execute(
                    "UPDATE endpoint_keys SET revoked_at = COALESCE(revoked_at, ?) "
                    "WHERE endpoint_id = ? AND revoked_at IS NULL",
                    (_now(), endpoint),
                )
            return self._endpoint_metadata(self._endpoint(db, project, endpoint))

    def delete_endpoint(self, owner: str, project: str, endpoint: str) -> None:
        with self._transaction() as db:
            self._project(db, owner, project)
            self._endpoint(db, project, endpoint)
            db.execute("DELETE FROM endpoint_keys WHERE endpoint_id = ?", (endpoint,))
            db.execute("DELETE FROM endpoints WHERE id = ?", (endpoint,))

    def _snapshot(self, owner: str, row: sqlite3.Row) -> EndpointSnapshot:
        credential = row["credential"]
        try:
            key = None
            if credential is not None:
                envelope = json.loads(self._cipher.decrypt(credential))
                expected = {
                    "owner": owner,
                    "project": row["project_id"],
                    "endpoint": row["id"],
                    "provider": row["provider"],
                    "base_url": row["base_url"],
                }
                if any(envelope.get(name) != value for name, value in expected.items()):
                    raise ProjectStorageError()
                if not isinstance(envelope.get("key"), str):
                    raise ProjectStorageError()
                key = SecretStr(envelope["key"])
            policy_data = json.loads(row["policy_data"])
            policy_data["entity_policies"] = MappingProxyType(policy_data["entity_policies"])
            policy_data.update(
                {
                    "id": row["policy_id"],
                    "policy_id": row["policy_id"],
                    "policy_version_id": row["policy_version_id"],
                    "version": row["policy_version"],
                    "name": row["policy_name"],
                }
            )
        except (InvalidToken, UnicodeError, ValueError, TypeError):
            raise ProjectStorageError() from None
        return EndpointSnapshot(
            owner,
            row["project_id"],
            row["id"],
            row["name"],
            row["provider"],
            row["base_url"],
            row["model"] or None,
            key,
            bool(row["enabled"]),
            row["policy_id"],
            row["policy_version_id"],
            row["policy_version"],
            MappingProxyType(policy_data),
        )

    def endpoint_snapshot(self, owner: str, project: str, endpoint: str) -> EndpointSnapshot:
        with self._transaction() as db:
            self._project(db, owner, project)
            row = self._endpoint(db, project, endpoint)
            if not row["enabled"]:
                raise ProjectNotFoundError()
            return self._snapshot(owner, row)

    @staticmethod
    def _key_metadata(row: sqlite3.Row) -> dict[str, Any]:
        return {key: row[key] for key in ("id", "name", "created_at", "revoked_at")}

    def issue_key(self, owner: str, project: str, endpoint: str, name: str) -> dict[str, Any]:
        with self._transaction() as db:
            self._project(db, owner, project)
            row = self._endpoint(db, project, endpoint)
            if not row["enabled"]:
                raise InvalidProjectConfigError()
            active = db.execute(
                "SELECT COUNT(*) FROM endpoint_keys WHERE endpoint_id = ? AND revoked_at IS NULL",
                (endpoint,),
            ).fetchone()[0]
            if active >= 32:
                raise InvalidProjectConfigError()
            # Rotation must not become permanently unavailable after old keys are revoked.
            # Retain bounded recent history, and never evict a live verifier.
            db.execute(
                "DELETE FROM endpoint_keys WHERE id IN (SELECT id FROM endpoint_keys "
                "WHERE endpoint_id = ? AND revoked_at IS NOT NULL "
                "ORDER BY revoked_at DESC, created_at DESC, id DESC LIMIT -1 OFFSET 96)",
                (endpoint,),
            )
            total = db.execute("SELECT COUNT(*) FROM endpoint_keys").fetchone()[0]
            if total >= 65536:
                db.execute(
                    "DELETE FROM endpoint_keys WHERE id IN (SELECT id FROM endpoint_keys "
                    "WHERE revoked_at IS NOT NULL ORDER BY revoked_at, created_at, id LIMIT ?)",
                    (total - 65535,),
                )
                if db.execute("SELECT COUNT(*) FROM endpoint_keys").fetchone()[0] >= 65536:
                    raise InvalidProjectConfigError()
            secret, key_id = "pg_ep_" + secrets.token_urlsafe(32), secrets.token_urlsafe(18)
            db.execute(
                "INSERT INTO endpoint_keys VALUES (?, ?, ?, ?, ?, NULL)",
                (key_id, endpoint, _name(name), hashlib.sha256(secret.encode()).digest(), _now()),
            )
            row = db.execute("SELECT * FROM endpoint_keys WHERE id = ?", (key_id,)).fetchone()
            return {**self._key_metadata(row), "key": secret}

    def list_keys(self, owner: str, project: str, endpoint: str) -> list[dict[str, Any]]:
        with self._transaction() as db:
            self._project(db, owner, project)
            self._endpoint(db, project, endpoint)
            return [
                self._key_metadata(row)
                for row in db.execute(
                    "SELECT * FROM endpoint_keys WHERE endpoint_id = ? ORDER BY created_at",
                    (endpoint,),
                )
            ]

    def revoke_key(self, owner: str, project: str, endpoint: str, key_id: str) -> None:
        with self._transaction() as db:
            self._project(db, owner, project)
            self._endpoint(db, project, endpoint)
            cursor = db.execute(
                "UPDATE endpoint_keys SET revoked_at = COALESCE(revoked_at, ?) "
                "WHERE id = ? AND endpoint_id = ?",
                (_now(), key_id, endpoint),
            )
            if cursor.rowcount != 1:
                raise ProjectNotFoundError()

    def resolve_key(self, secret: str, endpoint: str) -> EndpointSnapshot | None:
        if not isinstance(secret, str) or not secret.startswith("pg_ep_") or len(secret) > 128:
            return None
        with self._transaction() as db:
            row = db.execute(
                "SELECT e.project_id, p.owner_id FROM endpoint_keys k "
                "JOIN endpoints e ON e.id = k.endpoint_id JOIN projects p ON p.id = e.project_id "
                "WHERE k.digest = ? AND k.endpoint_id = ? AND k.revoked_at IS NULL AND e.enabled=1",
                (hashlib.sha256(secret.encode()).digest(), endpoint),
            ).fetchone()
            if row is None:
                return None
            return self._snapshot(row["owner_id"], self._endpoint(db, row["project_id"], endpoint))

    def close(self) -> None:
        with self._lock:
            self._db.close()
