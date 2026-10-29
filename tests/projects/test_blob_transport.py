"""Synthetic SDK doubles: no Azure identity, storage or network access."""

from types import SimpleNamespace

import pytest

from pii_guard.projects import blob_transport
from pii_guard.projects.blob_transport import MAX_BLOB_BYTES, AzureProjectBlob
from pii_guard.projects.store import ProjectStorageError


class FakeBlob:
    def __init__(self, **kwargs):
        self.options = kwargs
        self.calls = []
        self.raw = b"synthetic-encrypted-snapshot"
        self.properties = SimpleNamespace(
            size=len(self.raw), etag='"synthetic-1"', blob_type="BlockBlob"
        )
        self.response = {"etag": '"synthetic-2"'}
        self.error = None
        self.chunks = None
        self.closed = False

    def get_blob_properties(self, **kwargs):
        self.calls.append(("head", kwargs))
        if self.error:
            raise self.error
        return self.properties

    def download_blob(self, **kwargs):
        raise AssertionError("Blob SDK downloader must never be used")

    def upload_blob(self, value, **kwargs):
        self.calls.append(("put", kwargs))
        if self.error:
            raise self.error
        return self.response

    def close(self):
        self.closed = True


@pytest.fixture
def sdk(monkeypatch):
    result = SimpleNamespace(blob=None, credential=None, imports=[])

    def credential(**kwargs):
        result.credential = SimpleNamespace(options=kwargs, close=lambda: None)
        return result.credential

    def blob(**kwargs):
        result.blob = FakeBlob(**kwargs)
        return result.blob

    class FakeTransport:
        def __init__(self, **kwargs):
            self.options = kwargs
            self.closed = False

        def close(self):
            self.closed = True

    class FakePipeline:
        def __init__(self, **kwargs):
            self.options = kwargs
            result.pipeline = self
            self.header_overrides = {}
            self.status_code = 206
            self.closed_responses = 0

        def run(self, request, **kwargs):
            result.blob.calls.append(("get", {**kwargs, "request": request}))
            properties = result.blob.properties

            def close():
                self.closed_responses += 1

            return SimpleNamespace(
                http_response=SimpleNamespace(
                    status_code=self.status_code,
                    headers={
                        "ETag": properties.etag,
                        "Content-Length": str(properties.size),
                        "Content-Range": f"bytes 0-{properties.size - 1}/{properties.size}",
                        **self.header_overrides,
                    },
                    iter_raw=lambda: iter(
                        result.blob.chunks if result.blob.chunks is not None else [result.blob.raw]
                    ),
                    close=close,
                )
            )

    def imported(name):
        result.imports.append(name)
        return {
            "azure.identity": SimpleNamespace(ManagedIdentityCredential=credential),
            "azure.storage.blob": SimpleNamespace(BlobClient=blob),
            "azure.core": SimpleNamespace(
                MatchConditions=SimpleNamespace(IfNotModified="if-match")
            ),
            "azure.core.pipeline": SimpleNamespace(Pipeline=FakePipeline),
            "azure.core.pipeline.policies": SimpleNamespace(
                RetryPolicy=lambda **kwargs: SimpleNamespace(options=kwargs),
                BearerTokenCredentialPolicy=lambda credential, scope: SimpleNamespace(
                    credential=credential, scope=scope
                ),
            ),
            "azure.core.pipeline.transport": SimpleNamespace(RequestsTransport=FakeTransport),
            "azure.core.rest": SimpleNamespace(
                HttpRequest=lambda method, url, headers: SimpleNamespace(
                    method=method, url=url, headers=headers
                )
            ),
        }[name]

    monkeypatch.setattr(blob_transport, "import_module", imported)
    return result


def transport():
    return AzureProjectBlob(
        "https://syntheticaccount.blob.core.windows.net", "project-state", "dev"
    )


def test_managed_identity_fixed_environment_and_bounded_single_attempt_reads(sdk):
    store = transport()
    assert sdk.blob.calls == []
    assert sdk.blob.options["blob_name"] == "dev.projects.v1.enc"
    assert sdk.blob.options["credential"] is sdk.credential
    for options in (sdk.blob.options, sdk.credential.options):
        assert options["retry_total"] == 0
        assert options["connection_timeout"] == 3
        assert options["read_timeout"] == 5
    assert sdk.blob.options["permit_redirects"] is False
    assert sdk.blob.options["redirect_max"] == 0
    assert sdk.blob.options["max_single_get_size"] == 256 * 1024
    assert sdk.blob.options["max_chunk_get_size"] == 256 * 1024
    assert sdk.blob.options["max_single_put_size"] == MAX_BLOB_BYTES
    assert store.read() == (sdk.blob.raw, '"synthetic-1"')
    assert [call[0] for call in sdk.blob.calls] == ["head", "get"]
    download = sdk.blob.calls[1][1]
    assert download["stream"] is True
    assert download["request"].headers["Range"] == f"bytes=0-{MAX_BLOB_BYTES}"
    assert download["request"].headers["If-Match"] == '"synthetic-1"'
    assert download["request"].headers["Accept-Encoding"] == "identity"
    assert sdk.pipeline.options["transport"].options["use_env_settings"] is False
    assert sdk.blob.options["transport"].options["use_env_settings"] is False
    assert sdk.pipeline.options["policies"][0].options["retry_total"] == 0
    assert sdk.pipeline.options["policies"][1].scope == "https://storage.azure.com/.default"
    assert sdk.pipeline.closed_responses == 1
    assert sdk.blob.calls[0][1]["retry_total"] == 0
    assert set(download) == {"request", "stream", "connection_timeout", "read_timeout"}


@pytest.mark.parametrize(
    "url",
    [
        "http://syntheticaccount.blob.core.windows.net",
        "https://syntheticaccount.blob.core.windows.net/",
        "https://syntheticaccount.blob.core.windows.net/path",
        "https://syntheticaccount.blob.core.windows.net?sig=synthetic",
        "https://syntheticaccount.blob.core.windows.net#fragment",
        "https://syntheticaccount.blob.core.windows.net:443",
        "https://user:synthetic@syntheticaccount.blob.core.windows.net",
        "https://syntheticaccount.blob.core.windows.net.example.org",
        "https://127.0.0.1",
        "https://syntheticaccount.privatelink.blob.core.windows.net",
    ],
)
def test_invalid_origins_never_construct_sdk(sdk, url):
    with pytest.raises(ProjectStorageError):
        AzureProjectBlob(url, "project-state", "dev")
    assert sdk.imports == []


@pytest.mark.parametrize(
    ("container", "environment"),
    [
        ("ab", "dev"),
        ("Project-State", "dev"),
        ("project--state", "dev"),
        ("project-state", "staging"),
    ],
)
def test_invalid_storage_selection_never_constructs_sdk(sdk, container, environment):
    with pytest.raises(ProjectStorageError):
        AzureProjectBlob("https://syntheticaccount.blob.core.windows.net", container, environment)
    assert sdk.imports == []


def test_compare_and_swap_and_operator_create_have_distinct_preconditions(sdk):
    store = transport()
    store.compare_and_swap(b"synthetic", '"synthetic-1"')
    store.initialize(b"synthetic")
    cas, create = [call[1] for call in sdk.blob.calls]
    assert cas["overwrite"] is True
    assert cas["etag"] == '"synthetic-1"'
    assert cas["match_condition"] == "if-match"
    assert create["overwrite"] is False
    assert "etag" not in create
    assert all(options["retry_total"] == 0 for options in (cas, create))


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("synthetic-private-detail"),
        TimeoutError("synthetic-private-detail"),
    ],
)
def test_missing_denied_or_ambiguous_reads_and_writes_are_sanitized_and_never_retried(sdk, error):
    store = transport()
    sdk.blob.error = error
    for operation in (
        store.read,
        lambda: store.compare_and_swap(b"synthetic", '"synthetic-1"'),
        lambda: store.initialize(b"synthetic"),
    ):
        before = len(sdk.blob.calls)
        with pytest.raises(ProjectStorageError) as caught:
            operation()
        assert "synthetic-private-detail" not in str(caught.value)
        assert len(sdk.blob.calls) == before + 1


def test_conflicts_are_not_retried(sdk):
    store = transport()
    sdk.blob.error = type("Conflict", (Exception,), {"status_code": 412})()
    with pytest.raises(ProjectStorageError):
        store.compare_and_swap(b"synthetic", '"synthetic-1"')
    assert len(sdk.blob.calls) == 1


@pytest.mark.parametrize("size", [0, MAX_BLOB_BYTES + 1, True, 1.5])
def test_oversize_or_invalid_size_stops_before_download(sdk, size):
    store = transport()
    sdk.blob.properties.size = size
    with pytest.raises(ProjectStorageError):
        store.read()
    assert [call[0] for call in sdk.blob.calls] == ["head"]


def test_bounded_stream_stops_before_adding_oversize_chunk(sdk):
    store = transport()
    sdk.blob.chunks = [b"synthetic", b"x" * MAX_BLOB_BYTES]
    with pytest.raises(ProjectStorageError):
        store.read()
    assert len(sdk.blob.calls) == 2


@pytest.mark.parametrize("etag", ["*", '""', '"secret\nvalue"', '"é"', None])
def test_invalid_etags_cannot_broaden_write_precondition(sdk, etag):
    store = transport()
    with pytest.raises(ProjectStorageError):
        store.compare_and_swap(b"synthetic", etag)
    assert sdk.blob.calls == []


@pytest.mark.parametrize("response", [None, {}, {"etag": "*"}])
def test_write_needs_confirmed_valid_etag(sdk, response):
    store = transport()
    sdk.blob.response = response
    with pytest.raises(ProjectStorageError):
        store.compare_and_swap(b"synthetic", '"synthetic-1"')
    assert len(sdk.blob.calls) == 1


def test_mismatched_size_and_wrong_blob_type_are_rejected(sdk):
    store = transport()
    sdk.blob.properties.size += 1
    with pytest.raises(ProjectStorageError):
        store.read()
    sdk.blob.calls.clear()
    sdk.blob.properties.blob_type = "AppendBlob"
    with pytest.raises(ProjectStorageError):
        store.read()
    assert [call[0] for call in sdk.blob.calls] == ["head"]


def test_oversize_writes_and_bad_initializers_do_not_call_sdk(sdk):
    store = transport()
    for value in (b"", "synthetic", b"x" * (MAX_BLOB_BYTES + 1)):
        with pytest.raises(ProjectStorageError):
            store.compare_and_swap(value, '"synthetic-1"')
        with pytest.raises(ProjectStorageError):
            store.initialize(value)
    assert sdk.blob.calls == []


def test_total_read_deadline_stops_between_chunks_without_retry(sdk, monkeypatch):
    store = transport()
    clock = SimpleNamespace(now=0.0)
    monkeypatch.setattr(blob_transport.time, "monotonic", lambda: clock.now)
    delivered = []

    def delayed_chunks():
        delivered.append(1)
        clock.now = 9.0
        yield b"synthetic"
        delivered.append(2)
        clock.now = 10.0
        yield b"late"
        delivered.append(3)
        yield b"never-read"

    sdk.blob.chunks = delayed_chunks()
    with pytest.raises(ProjectStorageError):
        store.read()
    assert delivered == [1, 2]
    assert [call[0] for call in sdk.blob.calls] == ["head", "get"]
    assert sdk.pipeline.closed_responses == 1


def test_total_read_deadline_rejects_slow_head_before_download(sdk, monkeypatch):
    store = transport()
    ticks = iter((0.0, 10.0))
    monkeypatch.setattr(blob_transport.time, "monotonic", lambda: next(ticks))
    with pytest.raises(ProjectStorageError):
        store.read()
    assert [call[0] for call in sdk.blob.calls] == ["head"]


@pytest.mark.parametrize(
    "headers",
    [
        {"Content-Encoding": "gzip"},
        {"Content-Length": str(MAX_BLOB_BYTES + 1)},
        {"Content-Range": "bytes 0-42/43"},
        {"ETag": '"synthetic-changed"'},
    ],
)
def test_get_headers_must_confirm_exact_uncompressed_bounded_head(sdk, headers):
    store = transport()
    sdk.pipeline.header_overrides = headers
    with pytest.raises(ProjectStorageError):
        store.read()
    assert sdk.pipeline.closed_responses == 1


def test_redirect_and_partial_read_errors_are_not_retried(sdk):
    store = transport()
    sdk.pipeline.status_code = 302
    with pytest.raises(ProjectStorageError):
        store.read()
    assert [call[0] for call in sdk.blob.calls] == ["head", "get"]
    assert sdk.pipeline.closed_responses == 1
    sdk.blob.calls.clear()
    sdk.pipeline.status_code = 206

    def incomplete():
        yield b"synthetic"
        raise RuntimeError("synthetic-private-stream-error")

    sdk.blob.chunks = incomplete()
    with pytest.raises(ProjectStorageError) as caught:
        store.read()
    assert "synthetic-private-stream-error" not in str(caught.value)
    assert [call[0] for call in sdk.blob.calls] == ["head", "get"]
    assert sdk.pipeline.closed_responses == 2


@pytest.mark.parametrize("put_status", [201, 307, 503, 412])
def test_real_azure_core_stream_contract_without_network(monkeypatch, put_status):
    """Exercise actual SDK request/stream APIs, with synthetic in-process HTTP bytes."""
    import io
    import time

    identity = pytest.importorskip("azure.identity")
    credentials = pytest.importorskip("azure.core.credentials")
    requests = pytest.importorskip("requests")
    urllib3 = pytest.importorskip("urllib3")
    pytest.importorskip("azure.storage.blob")
    raw = b"synthetic-encrypted-snapshot"
    calls = []

    class Credential:
        def get_token(self, *scopes, **kwargs):
            assert scopes == ("https://storage.azure.com/.default",)
            return credentials.AccessToken("synthetic-access-token", int(time.time()) + 3600)

        def close(self):
            pass

    def response(session, method, url, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        result = requests.Response()
        result.status_code = 206 if method == "GET" else put_status
        result.headers.update(
            {
                "ETag": '"synthetic-1"',
                "Content-Length": str(len(raw)),
                "Content-Range": f"bytes 0-{len(raw) - 1}/{len(raw)}",
            }
        )
        result.raw = urllib3.response.HTTPResponse(body=io.BytesIO(raw), preload_content=False)
        if method == "PUT":
            if put_status == 307:
                result.headers["Location"] = (
                    "https://syntheticaccount.blob.core.windows.net/project-state/synthetic-redirect"
                )
            result.headers["Content-Length"] = "0"
            result._content = b""
            result.raw = urllib3.response.HTTPResponse(body=io.BytesIO(b""), preload_content=False)
        return result

    monkeypatch.setattr(identity, "ManagedIdentityCredential", lambda **kwargs: Credential())
    monkeypatch.setattr(requests.Session, "request", response)
    store = transport()
    monkeypatch.setattr(
        store._client,
        "get_blob_properties",
        lambda **kwargs: SimpleNamespace(
            size=len(raw), etag='"synthetic-1"', blob_type="BlockBlob"
        ),
    )
    try:
        assert store.read() == (raw, '"synthetic-1"')
        assert len(calls) == 1
        assert calls[0]["method"] == "GET"
        assert calls[0]["allow_redirects"] is False
        assert calls[0]["stream"] is True
        assert calls[0]["timeout"] == (3, 5)
        assert store._read_transport.session.trust_env is False
        if put_status != 201:
            with pytest.raises(ProjectStorageError):
                store.compare_and_swap(raw, '"synthetic-1"')
            assert [call["method"] for call in calls] == ["GET", "PUT"]
            return
        store.compare_and_swap(raw, '"synthetic-1"')
        store.initialize(raw)
        assert len(calls) == 3
        assert [call["method"] for call in calls] == ["GET", "PUT", "PUT"]
        assert calls[1]["headers"]["If-Match"] == '"synthetic-1"'
        assert calls[2]["headers"]["If-None-Match"] == "*"
        assert all(call["allow_redirects"] is False for call in calls)
    finally:
        store.close()
