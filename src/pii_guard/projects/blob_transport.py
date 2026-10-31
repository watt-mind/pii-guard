"""Bounded, single-attempt Azure Blob transport for encrypted project snapshots.

Only managed identity authenticates. The application never creates missing storage during
normal reads/writes; initialization is a separate operator-only create-if-absent operation.
"""

from __future__ import annotations

import re
import time
from contextlib import suppress
from email.utils import formatdate
from importlib import import_module
from typing import Any
from urllib.parse import urlsplit

from pii_guard.projects.store import ProjectStorageError

MAX_BLOB_BYTES = 12 * 1024 * 1024
_CHUNK_BYTES = 256 * 1024
_OPERATION_TIMEOUT_SECONDS = 10
_ETAG = re.compile(r'"[^"\x00-\x20\x7f]{1,254}"')


def _etag(value: object) -> str:
    if not isinstance(value, str) or not value.isascii() or not _ETAG.fullmatch(value):
        raise ProjectStorageError()
    return value


class AzureProjectBlob:
    """Fixed environment blob, encrypted bytes only; no automatic retries or recovery."""

    def __init__(
        self,
        account_url: str,
        container: str,
        environment: str,
        client_id: str | None = None,
    ) -> None:
        self._credential: Any = None
        self._client: Any = None
        self._read_transport: Any = None
        try:
            url = urlsplit(account_url)
            if (
                url.scheme != "https"
                or not re.fullmatch(r"[a-z0-9]{3,24}\.blob\.core\.windows\.net", url.netloc)
                or url.path
                or url.query
                or url.fragment
                or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,61})[a-z0-9]", container)
                or "--" in container
                or environment not in {"dev", "prod"}
            ):
                raise ProjectStorageError()
            identity = import_module("azure.identity")
            blob = import_module("azure.storage.blob")
            self._match = import_module("azure.core").MatchConditions.IfNotModified
            policies = import_module("azure.core.pipeline.policies")
            transport = import_module("azure.core.pipeline.transport")
            self._request = import_module("azure.core.rest").HttpRequest
            self._url = f"{account_url}/{container}/{environment}.projects.v1.enc"
            self._credential = identity.ManagedIdentityCredential(
                client_id=client_id,
                retry_total=0,
                connection_timeout=3,
                read_timeout=5,
            )

            def http_transport() -> Any:
                return transport.RequestsTransport(
                    use_env_settings=False,
                    connection_timeout=3,
                    read_timeout=5,
                    connection_data_block_size=_CHUNK_BYTES,
                )

            self._read_transport = http_transport()
            self._pipeline = import_module("azure.core.pipeline").Pipeline(
                transport=self._read_transport,
                policies=[
                    policies.RetryPolicy(
                        retry_total=0, retry_connect=0, retry_read=0, retry_status=0
                    ),
                    policies.BearerTokenCredentialPolicy(
                        self._credential, "https://storage.azure.com/.default"
                    ),
                ],
            )
            self._client = blob.BlobClient(
                account_url=account_url,
                container_name=container,
                blob_name=f"{environment}.projects.v1.enc",
                credential=self._credential,
                transport=http_transport(),
                retry_total=0,
                retry_connect=0,
                retry_read=0,
                retry_status=0,
                permit_redirects=False,
                redirect_max=0,
                connection_timeout=3,
                read_timeout=5,
                logging_enable=False,
                max_single_get_size=_CHUNK_BYTES,
                max_chunk_get_size=_CHUNK_BYTES,
                max_single_put_size=MAX_BLOB_BYTES,
            )
        except Exception:
            self.close()
            raise ProjectStorageError() from None

    @staticmethod
    def _options() -> dict[str, Any]:
        return {
            "timeout": 5,
            "connection_timeout": 3,
            "read_timeout": 5,
            "retry_total": 0,
            "retry_connect": 0,
            "retry_read": 0,
            "retry_status": 0,
            "permit_redirects": False,
            "redirect_max": 0,
            "logging_enable": False,
        }

    def read(self) -> tuple[bytes, str]:
        response = None
        try:
            deadline = time.monotonic() + _OPERATION_TIMEOUT_SECONDS

            def require_time() -> None:
                if time.monotonic() >= deadline:
                    raise ProjectStorageError()

            properties = self._client.get_blob_properties(**self._options())
            require_time()
            size = properties.size
            expected = _etag(properties.etag)
            if (
                type(size) is not int
                or not 0 < size <= MAX_BLOB_BYTES
                or properties.blob_type != "BlockBlob"
            ):
                raise ProjectStorageError()
            # The Blob SDK downloader has an independent hard-coded incomplete-body retry
            # loop. A public Azure Core streaming request avoids replaying even failed reads.
            request = self._request(
                "GET",
                self._url,
                headers={
                    "Accept-Encoding": "identity",
                    "If-Match": expected,
                    "Range": f"bytes=0-{MAX_BLOB_BYTES}",
                    "x-ms-version": "2023-11-03",
                    "x-ms-date": formatdate(usegmt=True),
                },
            )
            # Azure Core accepts transport timeouts directly. Storage SDK server-timeout
            # and logging options must never reach the bare requests transport.
            response = self._pipeline.run(
                request, stream=True, connection_timeout=3, read_timeout=5
            ).http_response
            require_time()
            if (
                response.status_code != 206
                or _etag(response.headers.get("ETag")) != expected
                or response.headers.get("Content-Encoding", "identity") != "identity"
                or response.headers.get("Content-Length") != str(size)
                or response.headers.get("Content-Range") != f"bytes 0-{size - 1}/{size}"
            ):
                raise ProjectStorageError()
            raw = bytearray()
            chunks = iter(response.iter_raw())
            while True:
                require_time()
                try:
                    chunk = next(chunks)
                except StopIteration:
                    break
                require_time()
                if not isinstance(chunk, bytes) or len(raw) + len(chunk) > MAX_BLOB_BYTES:
                    raise ProjectStorageError()
                raw.extend(chunk)
            require_time()
            if len(raw) != size:
                raise ProjectStorageError()
            return bytes(raw), expected
        except Exception:
            raise ProjectStorageError() from None
        finally:
            if response is not None:
                with suppress(Exception):
                    response.close()

    @staticmethod
    def _value(value: bytes) -> bytes:
        if not isinstance(value, bytes) or not 0 < len(value) <= MAX_BLOB_BYTES:
            raise ProjectStorageError()
        return value

    def compare_and_swap(self, value: bytes, etag: str) -> None:
        try:
            response = self._client.upload_blob(
                self._value(value),
                overwrite=True,
                etag=_etag(etag),
                match_condition=self._match,
                max_concurrency=1,
                **self._options(),
            )
            # Do not return an issued credential unless Azure confirms a completed write.
            _etag(response["etag"])
        except Exception:
            # Includes 412 and ambiguous commits. Never replay a configuration mutation.
            raise ProjectStorageError() from None

    def initialize(self, value: bytes) -> None:
        """Operator-only bootstrap; overwrite=False gives a create-if-absent block PUT."""
        try:
            response = self._client.upload_blob(
                self._value(value),
                overwrite=False,
                max_concurrency=1,
                **self._options(),
            )
            _etag(response["etag"])
        except Exception:
            raise ProjectStorageError() from None

    def close(self) -> None:
        with suppress(Exception):
            if self._read_transport is not None:
                self._read_transport.close()
        with suppress(Exception):
            if self._client is not None:
                self._client.close()
        with suppress(Exception):
            if self._credential is not None:
                self._credential.close()
