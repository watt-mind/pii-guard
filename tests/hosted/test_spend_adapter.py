"""Offline Azure SDK boundary: managed identity, conditional writes and no hidden retries."""

from types import SimpleNamespace

import pytest

from pii_guard.config import Settings
from pii_guard.hosted.quotas import SponsoredUnavailableError
from pii_guard.hosted.spend import MAX_BLOB_BYTES, AzureBlobStore, Conflict, azure_spend


def configured(**overrides):
    return Settings(
        _env_file=None,
        **{
            "hosted_spend_store": "azure_blob",
            "hosted_spend_account_url": "https://synthetic123.blob.core.windows.net",
            "hosted_spend_container": "sponsored-allowance",
            "hosted_spend_environment": "prod",
            "hosted_spend_managed_identity_client_id": "synthetic-client-id",
            "hosted_sponsored_microdollars": 1_000_000,
            "hosted_sponsored_allocation_id": "synthetic-approved",
            "hosted_allocation_expires_at": 1_900_000_000,
            **overrides,
        },
    )


@pytest.fixture
def sdk(monkeypatch):
    calls = []
    credential = SimpleNamespace(close=lambda: calls.append(("credential_close",)))
    state = SimpleNamespace(raw=b"{}", etag='"synthetic-etag"', error=None)

    def managed_identity(**kwargs):
        calls.append(("identity", kwargs))
        return credential

    class Client:
        def __init__(self, **kwargs):
            calls.append(("client", kwargs))

        def download_blob(self, **kwargs):
            calls.append(("read", kwargs))
            return SimpleNamespace(
                readall=lambda: state.raw, properties=SimpleNamespace(etag=state.etag)
            )

        def upload_blob(self, value, **kwargs):
            calls.append(("write", value, kwargs))
            if state.error:
                raise state.error

        def close(self):
            calls.append(("client_close",))

    modules = {
        "azure.identity": SimpleNamespace(ManagedIdentityCredential=managed_identity),
        "azure.storage.blob": SimpleNamespace(BlobClient=Client),
        "azure.core": SimpleNamespace(MatchConditions=SimpleNamespace(IfNotModified="if-match")),
    }
    monkeypatch.setattr("pii_guard.hosted.spend.import_module", modules.__getitem__)
    return calls, state


def test_sdk_uses_only_managed_identity_and_disables_retries_and_logging(sdk):
    calls, _ = sdk
    store = AzureBlobStore(configured())
    assert calls[0] == (
        "identity",
        {
            "client_id": "synthetic-client-id",
            "retry_total": 0,
            "connection_timeout": 3,
            "read_timeout": 5,
        },
    )
    options = calls[1][1]
    assert options["blob_name"] == "prod.json"
    assert options["container_name"] == "sponsored-allowance"
    assert options["account_url"] == "https://synthetic123.blob.core.windows.net"
    assert all(
        options[name] == 0
        for name in ("retry_total", "retry_read", "retry_status", "retry_connect")
    )
    assert options["connection_timeout"] == 3
    assert options["read_timeout"] == 5
    assert options["logging_enable"] is False
    assert options["max_single_put_size"] == MAX_BLOB_BYTES
    store.close()
    assert calls[-2:] == [("client_close",), ("credential_close",)]


def test_bounded_read_and_if_match_write_use_same_get_etag(sdk):
    calls, state = sdk
    store = AzureBlobStore(configured())
    raw, etag = store.read()
    assert raw == state.raw and etag == state.etag
    assert calls[-1][1] == {
        "offset": 0,
        "length": MAX_BLOB_BYTES + 1,
        "max_concurrency": 1,
        "timeout": 5,
        "logging_enable": False,
    }
    store.compare_and_swap(b'{"charged_total":1}', etag)
    assert calls[-1] == (
        "write",
        b'{"charged_total":1}',
        {
            "overwrite": True,
            "etag": etag,
            "match_condition": "if-match",
            "max_concurrency": 1,
            "timeout": 5,
            "logging_enable": False,
        },
    )


@pytest.mark.parametrize("code", [400, 401, 403, 404, 408, 409, 429, 500, 503, None])
def test_only_known_412_is_a_retryable_conflict(sdk, code):
    calls, state = sdk
    store = AzureBlobStore(configured())
    error = RuntimeError("synthetic secret SDK payload")
    error.status_code = code
    state.error = error
    with pytest.raises(SponsoredUnavailableError) as raised:
        store.compare_and_swap(b"{}", state.etag)
    assert "secret" not in str(raised.value)
    assert sum(call[0] == "write" for call in calls) == 1
    error.status_code = 412
    with pytest.raises(Conflict):
        store.compare_and_swap(b"{}", state.etag)


def test_oversized_read_or_write_is_refused(sdk):
    calls, state = sdk
    store = AzureBlobStore(configured())
    state.raw = b"x" * (MAX_BLOB_BYTES + 1)
    with pytest.raises(SponsoredUnavailableError):
        store.read()
    with pytest.raises(SponsoredUnavailableError):
        store.compare_and_swap(state.raw, state.etag)
    assert not any(call[0] == "write" for call in calls)


@pytest.mark.parametrize(
    "url",
    [
        "http://synthetic123.blob.core.windows.net",
        "https://example.com",
        "https://synthetic123.blob.core.windows.net/?sig=synthetic",
        "https://synthetic123.blob.core.windows.net:443",
        "https://synthetic123.blob.core.windows.net/path",
        "https://user@synthetic123.blob.core.windows.net",
        "https://synthetic123.blob.core.windows.net/#fragment",
    ],
)
def test_storage_endpoint_refuses_sas_credentials_custom_hosts_and_paths(sdk, url):
    calls, _ = sdk
    with pytest.raises(ValueError):
        AzureBlobStore(configured(hosted_spend_account_url=url))
    assert not calls


def test_missing_approval_or_sdk_disables_sponsorship_without_startup_failure(sdk):
    calls, _ = sdk
    ledger = azure_spend(configured(hosted_sponsored_microdollars=0), daily_ceiling=1000)
    assert not ledger.available
    assert not calls


def test_config_is_opt_in_and_exposes_documented_environment(monkeypatch):
    assert Settings(_env_file=None).hosted_spend_store == "marker"
    monkeypatch.setenv("PII_GUARD_HOSTED_SPEND_STORE", "azure_blob")
    monkeypatch.setenv("PII_GUARD_HOSTED_SPEND_ENVIRONMENT", "prod")
    assert Settings(_env_file=None).hosted_spend_store == "azure_blob"
    assert Settings(_env_file=None).hosted_spend_environment == "prod"
    monkeypatch.setenv("PII_GUARD_HOSTED_SPEND_STORE", "create-a-budget")
    with pytest.raises(ValueError):
        Settings(_env_file=None)


def test_real_sdk_emits_if_match_and_does_not_retry_412_offline(monkeypatch):
    blob = pytest.importorskip("azure.storage.blob")
    from azure.core.credentials import AccessToken
    from azure.core.pipeline.transport import HttpResponse, HttpTransport

    real_client = blob.BlobClient
    requests = []

    class Response(HttpResponse):
        def __init__(self, request):
            super().__init__(request, None)
            self.status_code = 412
            self.reason = "Precondition Failed"
            self.headers = {"content-type": "application/xml", "x-ms-error-code": "ConditionNotMet"}

        def body(self):
            return b"<Error><Code>ConditionNotMet</Code><Message>synthetic</Message></Error>"

    class Transport(HttpTransport):
        def open(self):
            pass

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def send(self, request, **kwargs):
            requests.append(request)
            return Response(request)

    class Credential:
        def get_token(self, *args, **kwargs):
            return AccessToken("synthetic-sdk-test-token", 4_102_444_800)

        def close(self):
            pass

    modules = {
        "azure.identity": SimpleNamespace(ManagedIdentityCredential=lambda **kwargs: Credential()),
        "azure.storage.blob": SimpleNamespace(
            BlobClient=lambda **kwargs: real_client(transport=Transport(), **kwargs)
        ),
        "azure.core": __import__("azure.core", fromlist=["MatchConditions"]),
    }
    monkeypatch.setattr("pii_guard.hosted.spend.import_module", modules.__getitem__)
    store = AzureBlobStore(configured())
    with pytest.raises(Conflict):
        store.compare_and_swap(b"{}", '"synthetic-etag"')
    assert len(requests) == 1
    assert requests[0].method == "PUT"
    assert requests[0].headers["If-Match"] == '"synthetic-etag"'
    assert "If-None-Match" not in requests[0].headers
    assert requests[0].body == b"{}"
    store.close()
