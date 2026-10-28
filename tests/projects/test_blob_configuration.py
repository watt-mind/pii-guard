"""Hosted configuration selects Blob explicitly without touching local SQLite state."""

from pathlib import Path

import pytest

from pii_guard.config import Settings
from pii_guard.projects import blob
from pii_guard.projects.runtime import ProjectService
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
