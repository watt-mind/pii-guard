"""Hosted configuration selects Blob explicitly without touching local SQLite state."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from pii_guard.config import Settings
from pii_guard.detect.pipeline import DetectionPipeline
from pii_guard.policy import PolicySet
from pii_guard.projects import blob
from pii_guard.projects.blob import MAX_BLOB_BYTES, MAX_DATABASE_BYTES, BlobProjectStore
from pii_guard.projects.runtime import PolicyAnalyzer, ProjectService
from pii_guard.projects.store import ProjectStorageError


def settings(**updates):
    values = {
        "hosted": True,
        "hosted_project_store": "azure_blob",
        "hosted_project_account_url": "https://synthetic.blob.core.windows.net",
        "tenant_key": "42" * 32,
    }
    values.update(updates)
    return Settings(_env_file=None, **values)


def test_blob_service_constructs_without_storage_io_or_local_fallback(monkeypatch, tmp_path: Path):
    from pii_guard.projects import blob_transport

    class NoIO:
        def __init__(self, account_url, container, environment, client_id):
            assert account_url == "https://synthetic.blob.core.windows.net"
            assert environment == "prod"

        def read(self):
            raise OSError("synthetic-private-detail")

        def close(self):
            pass

    monkeypatch.setattr(blob_transport, "AzureProjectBlob", NoIO)
    path = tmp_path / "must-not-exist" / "state.sqlite3"
    service = ProjectService(
        settings(project_state_path=str(path), hosted_project_environment="prod")
    )
    assert isinstance(service.store, blob.BlobProjectStore)
    with pytest.raises(ProjectStorageError, match="Project configuration storage is unavailable"):
        service.store.default_project("synthetic-owner")
    assert not path.parent.exists()
    service.close()


@pytest.mark.parametrize(
    "updates", [{"hosted": False}, {"tenant_key": None}, {"tenant_key": "42" * 31}]
)
def test_blob_requires_hosted_stable_exact_key(updates):
    with pytest.raises(ProjectStorageError):
        blob.configured_blob_store(settings(**updates))


def test_defaults_keep_local_storage():
    config = Settings(_env_file=None)
    assert config.hosted_project_store == "sqlite"
    assert config.hosted_project_container == "project-configuration"
    assert config.hosted_project_environment == "dev"


def test_blob_store_error_conditions():
    mock_blob = MagicMock()
    # Invalid environment
    with pytest.raises(ProjectStorageError):
        BlobProjectStore(mock_blob, b"0" * 32, PolicySet(), "standard", "invalid-env")
    # Invalid key length
    with pytest.raises(ProjectStorageError):
        BlobProjectStore(mock_blob, b"0" * 16, PolicySet(), "standard", "dev")

    store = BlobProjectStore(mock_blob, b"0" * 32, PolicySet(), "standard", "dev")
    # _decode errors
    with pytest.raises(ProjectStorageError):
        store._decode(b"")
    with pytest.raises(ProjectStorageError):
        store._decode(b"x" * (MAX_BLOB_BYTES + 1))
    bad_prefix = store._cipher.encrypt(b"wrong-binding\0" + b"db")
    with pytest.raises(ProjectStorageError):
        store._decode(bad_prefix)

    empty_db = store._cipher.encrypt(store._binding)
    with pytest.raises(ProjectStorageError):
        store._decode(empty_db)

    # _encode error
    with pytest.raises(ProjectStorageError):
        store._encode(b"x" * (MAX_DATABASE_BYTES + 1))

    # initialize_empty error
    mock_blob.initialize.side_effect = RuntimeError("failed")
    with pytest.raises(ProjectStorageError):
        store.initialize_empty()

    # resolve_key delegation
    mock_blob.read.return_value = (store._encode(b""), '"valid-etag"')
    # empty db raises when loading in memory, confirming delegation reached _run
    with pytest.raises(ProjectStorageError):
        store.resolve_key("secret", "endpoint")


def test_blob_requires_valid_hex_key():
    with pytest.raises(ProjectStorageError):
        blob.configured_blob_store(settings(tenant_key="not-a-hex-string!"))


def test_blob_main_cli(monkeypatch):
    import sys

    monkeypatch.setenv("PII_GUARD_HOSTED_PROJECT_STORE", "azure_blob")
    monkeypatch.setattr(sys, "argv", ["pii-guard-blob", "--initialize-empty"])
    monkeypatch.setattr("pii_guard.projects.blob.configured_blob_store", lambda s: MagicMock())
    assert blob.main() == 0

    # Failure path
    monkeypatch.setattr(
        "pii_guard.projects.blob.configured_blob_store",
        lambda s: (_ for _ in ()).throw(RuntimeError("fail")),
    )
    assert blob.main() == 1


def test_runtime_storage_key_generation_and_loading(tmp_path: Path):
    db_path = tmp_path / "sub" / "state.sqlite3"
    cfg = Settings(_env_file=None, hosted=False, tenant_key=None, project_state_path=str(db_path))
    svc = ProjectService(cfg)
    st = svc.store
    assert st is not None
    key_file = tmp_path / "sub" / "project-storage.key"
    assert key_file.exists()
    assert len(key_file.read_bytes()) == 32
    svc.close()

    # Reopening uses existing key
    svc2 = ProjectService(cfg)
    assert svc2.store is not None
    assert svc2._key == key_file.read_bytes()
    svc2.close()

    # Symlink key raises ValueError
    symlink_dir = tmp_path / "sym"
    symlink_dir.mkdir()
    sym_key = symlink_dir / "project-storage.key"
    sym_key.symlink_to(key_file)
    cfg_sym = Settings(
        _env_file=None,
        hosted=False,
        tenant_key=None,
        project_state_path=str(symlink_dir / "db.sqlite3"),
    )
    svc_sym = ProjectService(cfg_sym)
    with pytest.raises(ValueError, match="must be a regular private file"):
        _ = svc_sym.store


def test_policy_analyzer_require_available():
    inner = MagicMock()
    inner.pipeline = DetectionPipeline(["rules"])
    inner.require_available = MagicMock()
    analyzer = PolicyAnalyzer(inner, PolicySet())
    analyzer.analyze("hello", "en")
    inner.require_available.assert_called_once()
