"""Router bootstrap contracts; no Azure or tailnet requests and no enrollment."""

# ruff: noqa: S603, S607 - local test binaries with synthetic files; no shell or network service

import http.client
import importlib.util
import io
import json
import os
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SOURCE = Path(__file__).with_name("dev_router")
SPEC = importlib.util.spec_from_file_location("dev_router_bootstrap", SOURCE / "bootstrap.py")
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("router test module unavailable")
router = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(router)
CONFIG = {
    "hostname": "piiguard-dev-router",
    "aca_fqdn": "piiguard-dev.synthetic.swedencentral.azurecontainerapps.io",
    "tls_secret_uri": "https://piiguardexample.vault.azure.net/secrets/dev-tls/" + "b" * 32,
    "secret_uri": "https://piiguardexample.vault.azure.net/secrets/router-enrollment/" + "a" * 32,
    "managed_identity_client_id": "11111111-1111-4111-8111-111111111111",
}
# Deliberately synthetic and never sent to any endpoint.
KEY = "tskey-auth-synthetic-only-not-a-working-key"
TOKEN = "synthetic-imds-token"  # noqa: S105 - fake token used only in mocked HTTP


class RouterTests(unittest.TestCase):
    def test_http_transport_refuses_redirects_and_unapproved_destinations(self):
        with self.assertRaisesRegex(router.BootstrapError, "router_http_redirect_refused"):
            router.NoRedirect().redirect_request(
                None, None, 302, None, None, "https://evil.example"
            )
        for uri in ("file:///etc/passwd", "https://evil.example", "http://127.0.0.1/"):
            with (
                self.subTest(uri=uri),
                self.assertRaisesRegex(router.BootstrapError, "router_http_destination_refused"),
            ):
                router.request_json(uri, {"Authorization": "Bearer " + TOKEN})

    def test_supervisor_keeps_tls_only_in_memfd_and_closes_it_on_validation_failure(self):
        pem = "synthetic certificate and private key bytes"
        for failure in (False, True):
            with self.subTest(failure=failure):
                writes, commands, seals, fetches = [], [], [], []

                def fetch(config, uri, fetches=fetches):
                    fetches.append(uri)
                    return pem

                def seal(value, seals=seals):
                    seals.append(value)
                    return 123

                def run(args, commands=commands, failure=failure):
                    commands.append(args)
                    if failure:
                        raise router.BootstrapError("router_command_failed")

                process = SimpleNamespace(wait=lambda: 0)
                with (
                    patch.object(
                        router,
                        "write_private",
                        side_effect=lambda p, v, writes=writes: writes.append((p, v)),
                    ),
                    patch.object(router.subprocess, "Popen", return_value=process) as popen,
                    patch.object(router.signal, "signal"),
                    patch.object(router.os, "close") as close,
                ):
                    if failure:
                        with self.assertRaises(router.BootstrapError):
                            router.supervise_proxy(
                                CONFIG, "100.101.102.103", fetch=fetch, seal=seal, run=run
                            )
                        popen.assert_not_called()
                    else:
                        router.supervise_proxy(
                            CONFIG, "100.101.102.103", fetch=fetch, seal=seal, run=run
                        )
                        self.assertNotIn(pem, repr(popen.call_args))
                    close.assert_called_once_with(123)
                self.assertEqual(fetches, [CONFIG["tls_secret_uri"]])
                self.assertEqual(seals, [pem])
                self.assertNotIn(pem, repr(writes))
                self.assertNotIn(pem, repr(commands))
                self.assertIn(f"/proc/{os.getpid()}/fd/123", writes[0][1])

    def test_proxy_only_forwards_allowlisted_headers_and_fixed_origin(self):
        config = router.nginx_config(CONFIG["aca_fqdn"], "100.101.102.103", "/proc/123/fd/4")
        for line in (
            "listen 100.101.102.103:443 ssl;",
            "proxy_pass_request_headers off;",
            "proxy_set_header Host " + CONFIG["aca_fqdn"] + ";",
            "proxy_set_header X-Forwarded-Host guard-dev.watt-mind.com;",
            "proxy_set_header X-Forwarded-Proto https;",
            "proxy_set_header X-Pii-Guard-External-Host guard-dev.watt-mind.com;",
            "proxy_set_header X-Pii-Guard-External-Proto https;",
            "proxy_set_header X-Forwarded-For $remote_addr;",
            "proxy_ssl_verify on;",
            "proxy_ssl_verify_depth 3;",
            "proxy_ssl_server_name on;",
            "proxy_buffering off;",
            "proxy_request_buffering off;",
            "proxy_max_temp_file_size 0;",
            "ssl_certificate /proc/123/fd/4;",
            "ssl_certificate_key /proc/123/fd/4;",
            "access_log off;",
            "error_log /dev/null crit;",
            "proxy_redirect https://" + CONFIG["aca_fqdn"] + "/ https://guard-dev.watt-mind.com/;",
        ):
            self.assertIn(line, config)
        self.assertNotIn("$proxy_add_x_forwarded_for", config)
        self.assertNotIn("$http_x_ms", config)
        self.assertNotIn("$http_forwarded", config)
        self.assertNotIn("$http_host", config)

    def test_proxy_forwards_accept_encoding_without_nginx_compression(self):
        # LAB-1472: without the client's Accept-Encoding the app serves static assets raw.
        config = router.nginx_config(CONFIG["aca_fqdn"], "100.101.102.103", "/proc/123/fd/4")
        self.assertIn("proxy_set_header Accept-Encoding $http_accept_encoding;", config)
        self.assertNotRegex(config, r"(?m)^\s*gzip\b")
        self.assertIn("access_log off;", config)

    def test_proxy_refuses_repeated_security_headers(self):
        # LAB-1467: nginx joins repeated lines into one $http_* value, so the app's
        # "Duplicate security header" refusal never fires behind the router.
        config = router.nginx_config(CONFIG["aca_fqdn"], "100.101.102.103", "/proc/123/fd/4")
        source = config.split("map ", 1)[1].split("{", 1)[0]
        for name in router.SINGLE_VALUE_HEADERS:
            self.assertIn("$http_" + name.lower().replace("-", "_"), source)
        for name in ("Authorization", "Origin", "X-PII-Guard-Token", "X-PII-Guard-Connection"):
            self.assertIn(name, router.SINGLE_VALUE_HEADERS)
        self.assertIn('"~," 1;', config)
        self.assertIn("if ($piiguard_repeated_header) { return 400; }", config)
        self.assertIn("if ($piiguard_repeated_cookie) { return 400; }", config)
        # The guest cookie name mirrors the app's; a repeat is cookie tossing, not a client.
        identity = Path(__file__).parents[2] / "src" / "pii_guard" / "hosted" / "identity.py"
        self.assertIn(f'GUEST_COOKIE_NAME = "{router.GUEST_COOKIE}"', identity.read_text())
        self.assertIn(f'"~{router.GUEST_COOKIE}=.*{router.GUEST_COOKIE}=" 1;', config)

    @unittest.skipUnless(hasattr(os, "memfd_create"), "Linux memfd is required")
    def test_tls_memfd_is_root_private_sealed_and_not_a_file(self):
        fd = router.sealed_pem("synthetic test bytes")
        try:
            self.assertEqual(os.read(fd, 100), b"synthetic test bytes")
            self.assertEqual(os.fstat(fd).st_mode & 0o777, 0o600)
            self.assertIn("memfd:", os.readlink(f"/proc/self/fd/{fd}"))
            with self.assertRaises(OSError):
                os.write(fd, b"cannot mutate sealed memory")
        finally:
            os.close(fd)

    def test_invalid_configuration_is_rejected_before_any_side_effect(self):
        for field, value in (
            ("aca_fqdn", "evil.example.com"),
            ("aca_fqdn", "app.env.region.azurecontainerapps.io.evil.example"),
            ("aca_fqdn", "app.env.region.azurecontainerapps.io; include /tmp/key;"),
            ("aca_fqdn", "10.0.0.1"),
            ("tls_secret_uri", "https://evil.example/secrets/tls/" + "b" * 32),
            ("hostname", "bad\nname"),
            ("secret_uri", "https://piiguardexample.vault.azure.net/secrets/key"),
            ("secret_uri", "https://evil.example/secrets/key/" + "a" * 32),
            ("secret_uri", CONFIG["secret_uri"] + "?redirect=example.com"),
            ("managed_identity_client_id", "not-an-identity"),
        ):
            with self.subTest(field=field, value=value):
                calls = []
                with self.assertRaises((ValueError, router.BootstrapError)):
                    router.configure(
                        CONFIG | {field: value}, run=lambda *a, calls=calls, **kw: calls.append(a)
                    )
                self.assertEqual(calls, [])

    def test_only_selected_identity_and_versioned_secret_are_requested(self):
        calls = []

        def request(url, headers):
            calls.append((url, headers))
            return {"access_token": TOKEN} if len(calls) == 1 else {"value": KEY}

        self.assertEqual(router.secret_value(CONFIG, CONFIG["secret_uri"], request=request), KEY)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0][0].startswith("http://169.254.169.254/metadata/identity/"))
        self.assertIn("client_id=" + CONFIG["managed_identity_client_id"], calls[0][0])
        self.assertIn("resource=https%3A%2F%2Fvault.azure.net", calls[0][0])
        self.assertEqual(calls[0][1], {"Metadata": "true"})
        self.assertEqual(calls[1][0], CONFIG["secret_uri"] + "?api-version=7.4")
        self.assertEqual(calls[1][1], {"Authorization": "Bearer " + TOKEN})

    def test_retry_is_bounded_and_error_is_content_free(self):
        calls, sleeps = [], []

        def request(*args):
            calls.append(args)
            raise RuntimeError(TOKEN + KEY + "response body")

        with self.assertRaisesRegex(router.BootstrapError, "^router_secret_unavailable$"):
            router.secret_value(CONFIG, CONFIG["secret_uri"], request=request, sleep=sleeps.append)
        self.assertEqual(len(calls), 12)
        self.assertEqual(sleeps, [10] * 11)

    def test_retry_then_rbac_success(self):
        calls, sleeps = [], []

        def request(url, headers):
            calls.append(url)
            if len(calls) < 3:
                raise RuntimeError("synthetic RBAC propagation")
            return {"value": KEY} if "secrets/" in url else {"access_token": TOKEN}

        self.assertEqual(
            router.secret_value(CONFIG, CONFIG["secret_uri"], request=request, sleep=sleeps.append),
            KEY,
        )
        self.assertEqual(sleeps, [10, 10])

    def scenario(self, state="NeedsLogin", fail_up=False):
        commands, writes, fetched = [], {}, []

        def run(args, *, stdin=None, capture=False):
            commands.append((args, stdin, capture))
            if args[:2] == ["tailscale", "status"]:
                return json.dumps({"BackendState": state}).encode()
            if args[:2] == ["tailscale", "up"] and fail_up:
                raise router.BootstrapError("router_command_failed")
            if args[:2] == ["tailscale", "ip"]:
                return b"100.101.102.103\n"
            return b""

        def fetch(config, uri):
            fetched.append(config)
            return KEY

        router.configure(
            CONFIG, run=run, fetch=fetch, write=lambda path, data: writes.update({str(path): data})
        )
        return commands, writes, fetched

    def test_secret_is_only_on_stdin_never_in_argv_configuration_or_output(self):
        with (
            patch("sys.stdout", new_callable=io.StringIO) as stdout,
            patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            commands, writes, fetched = self.scenario()
        self.assertEqual(len(fetched), 1)
        up = [item for item in commands if item[0][:2] == ["tailscale", "up"]]
        self.assertEqual(len(up), 1)
        self.assertEqual(up[0][1], KEY.encode())
        self.assertIn("--auth-key=file:/proc/self/fd/0", up[0][0])
        for args, _, _ in commands:
            self.assertNotIn(KEY, " ".join(args))
            self.assertNotIn(TOKEN, " ".join(args))
        self.assertNotIn(KEY, repr(writes))
        self.assertNotIn(TOKEN, repr(writes))
        self.assertEqual(stdout.getvalue() + stderr.getvalue(), "")
        self.assertEqual(commands[0][0], ["nft", "-f", "-"])
        self.assertTrue(all("auth" not in path for path in writes))

    def test_reboot_reuses_machine_identity_without_fetching_a_one_use_key(self):
        for state in ("Running", "Stopped"):
            commands, _, fetched = self.scenario(state)
            self.assertEqual(fetched, [])
            up = next(item for item in commands if item[0][:2] == ["tailscale", "up"])
            self.assertIsNone(up[1])
            self.assertFalse(any("auth-key" in arg for arg in up[0]))

    def test_route_dns_and_firewall_scope(self):
        commands, writes, _ = self.scenario()
        up = next(item[0] for item in commands if item[0][:2] == ["tailscale", "up"])
        for flag in (
            "--advertise-routes=",
            "--advertise-tags=tag:piiguard-dev",
            "--accept-routes=false",
            "--advertise-exit-node=false",
            "--exit-node=",
            "--accept-dns=false",
            "--ssh=false",
            "--netfilter-mode=off",
        ):
            self.assertIn(flag, up)
        firewall = writes["/etc/nftables.conf"]
        self.assertEqual(firewall.count("policy drop;"), 2)
        self.assertIn(
            'iifname "tailscale0" ip saddr 100.64.0.0/10 '
            "ip daddr 100.101.102.103 tcp dport { 53, 443 } accept",
            firewall,
        )
        self.assertIn(
            "chain forward { type filter hook forward priority 0; policy drop; }", firewall
        )
        self.assertNotIn("masquerade", firewall)
        self.assertNotIn("hook postrouting", firewall)
        self.assertEqual(
            writes["/etc/sysctl.d/90-piiguard-dev-router.conf"], "net.ipv4.ip_forward=0\n"
        )
        self.assertNotIn("dport 22", firewall)
        self.assertNotIn("dport 80", firewall)
        self.assertNotIn(" log ", firewall)
        self.assertIn("ip daddr 100.101.102.103 udp dport 53 accept", firewall)
        dns = writes["/etc/dnsmasq.d/piiguard-dev-router.conf"]
        for line in (
            "interface=tailscale0",
            "listen-address=100.101.102.103",
            "bind-interfaces",
            "no-resolv",
            "host-record=guard-dev.watt-mind.com,100.101.102.103",
        ):
            self.assertIn(line, dns.splitlines())
        self.assertNotIn("log-queries", dns)
        self.assertNotIn("server=", dns)

    def test_enrollment_failure_does_not_start_dns(self):
        with self.assertRaises(router.BootstrapError):
            self.scenario(fail_up=True)

    def test_cli_drops_output_and_never_places_stdin_in_environment(self):
        with patch.object(
            router.subprocess, "run", return_value=SimpleNamespace(returncode=0)
        ) as run:
            router.command(
                ["tailscale", "up", "--auth-key=file:/proc/self/fd/0"], stdin=KEY.encode()
            )
        _, kwargs = run.call_args
        self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)
        self.assertNotIn(KEY, repr(kwargs["env"]))
        self.assertFalse(kwargs["check"])

    def test_main_never_prints_exception_content(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / "config.json"
            config.write_text(json.dumps(CONFIG))
            config.chmod(0o600)
            # macOS test owner differs from Linux root; mock only the metadata.
            metadata = SimpleNamespace(st_mode=0o100600, st_uid=0)
            with (
                patch.object(router, "CONFIG", config),
                patch.object(Path, "stat", return_value=metadata),
                patch.object(router, "configure", side_effect=RuntimeError(KEY + TOKEN)),
                patch("sys.stderr", new_callable=io.StringIO) as stderr,
            ):
                self.assertEqual(router.main(), 1)
            self.assertEqual(stderr.getvalue(), "router_bootstrap_failed\n")

    def test_installation_is_pinned_and_does_not_pipe_shell_or_embed_credentials(self):
        installer = (SOURCE / "install.sh").read_text()
        self.assertIn("tailscale=1.104.4", installer)
        self.assertIn("sha256sum --check --status", installer)
        self.assertIn("signed-by=/usr/share/keyrings/tailscale-archive-keyring.gpg", installer)
        self.assertIn("systemctl mask dnsmasq.service tailscaled.service nginx.service", installer)
        self.assertIn("systemctl disable --now ssh.service ssh.socket", installer)
        self.assertNotIn("curl |", installer)
        self.assertNotIn("tskey-", installer)
        service = (SOURCE / "piiguard-dev-router.service").read_text()
        self.assertIn("LimitCORE=0", service)
        self.assertIn("StandardOutput=null", service)
        self.assertNotIn("Before=dnsmasq.service", service)


@unittest.skipUnless(
    hasattr(os, "memfd_create") and shutil.which("nginx") and shutil.which("openssl"),
    "Linux, nginx and openssl are required for the local TLS proxy integration test",
)
class LiveProxyTests(unittest.TestCase):
    def test_oauth_redirect_and_upstream_error_leave_no_content_in_logs_or_files(self):
        canaries = {
            "code": "synthetic_oauth_code_privacy_canary",
            "state": "synthetic_oauth_state_privacy_canary",
            "authorization": "synthetic_authorization_privacy_canary",
            "cookie": "synthetic_cookie_privacy_canary",
            "body": "synthetic_request_body_privacy_canary",
        }
        query = f"code={canaries['code']}&state={canaries['state']}"
        received = []

        class Upstream(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                received.append((self.path, dict(self.headers), body))
                self.send_response(302)
                self.send_header("Location", "https://localhost/after-login?" + query)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *_):
                pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o755)
            key, cert = root / "synthetic.key", root / "synthetic.crt"
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-days",
                    "1",
                    "-subj",
                    "/CN=localhost",
                    "-addext",
                    "subjectAltName=DNS:localhost,IP:127.0.0.1",
                    "-keyout",
                    str(key),
                    "-out",
                    str(cert),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(str(cert), str(key))
            server = HTTPServer(("127.0.0.1", 0), Upstream)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            with socket.socket() as reserve:
                reserve.bind(("127.0.0.1", 0))
                port = reserve.getsockname()[1]
            fd = router.sealed_pem(cert.read_text() + key.read_text())
            key.unlink()
            config = router.nginx_config("localhost", "127.0.0.1", f"/proc/{os.getpid()}/fd/{fd}")
            config = config.replace("listen 127.0.0.1:443", f"listen 127.0.0.1:{port}")
            config = config.replace(
                "set $aca_origin localhost;", f"set $aca_origin 127.0.0.1:{server.server_port};"
            )
            config = config.replace("/run/piiguard-dev-router", str(root))
            config = config.replace("/etc/ssl/certs/ca-certificates.crt", str(cert))
            path = root / "nginx.conf"
            path.write_text(config)
            validation = subprocess.run(
                ["nginx", "-t", "-c", str(path)], check=True, capture_output=True
            )
            process = subprocess.Popen(
                ["nginx", "-c", str(path), "-g", "daemon off;"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            output = b""
            try:
                for attempt in range(50):
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                            break
                    except OSError:
                        if attempt == 49:
                            self.fail("local proxy did not start")
                        time.sleep(0.05)
                for expected_status in (302, 502):
                    with self.subTest(status=expected_status):
                        connection = http.client.HTTPSConnection(
                            "127.0.0.1",
                            port,
                            context=ssl.create_default_context(cafile=str(cert)),
                            timeout=5,
                        )
                        connection.request(
                            "POST",
                            "/.auth/login/google/callback?" + query,
                            body=canaries["body"].encode(),
                            headers={
                                "Authorization": "Bearer " + canaries["authorization"],
                                "Cookie": "synthetic=" + canaries["cookie"],
                                "Content-Type": "application/octet-stream",
                            },
                        )
                        response = connection.getresponse()
                        self.assertEqual(response.status, expected_status)
                        if expected_status == 302:
                            self.assertEqual(
                                response.getheader("Location"),
                                "https://guard-dev.watt-mind.com/after-login?" + query,
                            )
                            self.assertEqual(
                                received[0][0], "/.auth/login/google/callback?" + query
                            )
                            self.assertEqual(received[0][2], canaries["body"].encode())
                        response.read()
                        connection.close()
                    # The next request must exercise Nginx's real connection-refused
                    # upstream failure path, with the same sensitive URL/header/body.
                    server.shutdown()
                    server.server_close()
            finally:
                process.terminate()
                stdout, stderr = process.communicate(timeout=5)
                output = validation.stdout + validation.stderr + stdout + stderr
                os.close(fd)
                server.shutdown()
                server.server_close()
            for value in canaries.values():
                self.assertNotIn(value.encode(), output)
                for created in root.rglob("*"):
                    if created.is_file():
                        self.assertNotIn(value.encode(), created.read_bytes(), str(created))
            self.assertFalse(any(root.glob("body/*")))
            self.assertFalse(any(root.glob("proxy/*")))

    def test_nginx_loads_memory_only_tls_strips_spoofed_headers_and_rewrites_redirect(self):
        # Everything is local and synthetic. No Azure, Tailscale or model request.
        received = []
        release_stream = threading.Event()

        class Upstream(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append(dict(self.headers))
                if self.path == "/stream":
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    self.wfile.write(b"data: first\n\n")
                    self.wfile.flush()
                    release_stream.wait(timeout=3)
                    self.wfile.write(b"data: second\n\n")
                    self.wfile.flush()
                    return
                self.send_response(302)
                self.send_header("Location", "https://localhost/after-login")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *_):
                pass

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o755)
            key, cert = root / "synthetic.key", root / "synthetic.crt"
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-days",
                    "1",
                    "-subj",
                    "/CN=localhost",
                    "-addext",
                    "subjectAltName=DNS:localhost,IP:127.0.0.1",
                    "-keyout",
                    str(key),
                    "-out",
                    str(cert),
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(str(cert), str(key))
            server = HTTPServer(("127.0.0.1", 0), Upstream)
            server.socket = context.wrap_socket(server.socket, server_side=True)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            with socket.socket() as reserve:
                reserve.bind(("127.0.0.1", 0))
                port = reserve.getsockname()[1]
            fd = router.sealed_pem(cert.read_text() + key.read_text())
            # Remove the synthetic files: frontend must load its cert/key from memfd.
            key.unlink()
            pem_path = f"/proc/{os.getpid()}/fd/{fd}"
            config = router.nginx_config("localhost", "127.0.0.1", pem_path)
            config = config.replace("listen 127.0.0.1:443", f"listen 127.0.0.1:{port}")
            config = config.replace(
                "set $aca_origin localhost;", f"set $aca_origin 127.0.0.1:{server.server_port};"
            )
            config = config.replace("/run/piiguard-dev-router", str(root))
            config = config.replace("/etc/ssl/certs/ca-certificates.crt", str(cert))
            path = root / "nginx.conf"
            path.write_text(config)
            process = None
            try:
                subprocess.run(
                    ["nginx", "-t", "-c", str(path)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                process = subprocess.Popen(
                    ["nginx", "-c", str(path), "-g", "daemon off;"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                for attempt in range(50):
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                            break
                    except OSError:
                        if attempt == 49:
                            self.fail("local proxy did not start")
                        time.sleep(0.05)
                connection = http.client.HTTPSConnection(
                    "127.0.0.1",
                    port,
                    context=ssl.create_default_context(cafile=str(cert)),
                    timeout=5,
                )
                connection.request(
                    "GET",
                    "/login",
                    headers={
                        "Host": "evil.example",
                        "Forwarded": "host=evil.example;proto=http",
                        "X-Forwarded-Host": "evil.example",
                        "X-Forwarded-Proto": "http",
                        "X-Forwarded-For": "192.0.2.123",
                        "X-MS-CLIENT-PRINCIPAL": "forged",
                        "X-MS-CUSTOM-IDENTITY": "forged",
                        "X-Real-IP": "192.0.2.123",
                        "X-Pii-Guard-External-Host": "evil.example",
                        "X-Pii-Guard-External-Proto": "http",
                        "Origin": "https://actual-origin.example",
                        "Sec-Fetch-Site": "cross-site",
                        "X-PII-Guard-Connection": "synthetic-connection",
                        "Cookie": "synthetic=1",
                        "Authorization": "Bearer synthetic",
                    },
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 302)
                self.assertEqual(
                    response.getheader("Location"), "https://guard-dev.watt-mind.com/after-login"
                )
                response.read()
                connection.close()
                headers = {name.lower(): value for name, value in received[0].items()}
                self.assertEqual(headers["host"], "localhost")
                self.assertEqual(headers["x-forwarded-host"], "guard-dev.watt-mind.com")
                self.assertEqual(headers["x-forwarded-proto"], "https")
                self.assertEqual(headers["x-forwarded-for"], "127.0.0.1")
                self.assertEqual(headers["x-pii-guard-external-host"], "guard-dev.watt-mind.com")
                self.assertEqual(headers["x-pii-guard-external-proto"], "https")
                self.assertEqual(headers["origin"], "https://actual-origin.example")
                self.assertEqual(headers["sec-fetch-site"], "cross-site")
                self.assertEqual(headers["x-pii-guard-connection"], "synthetic-connection")
                self.assertNotIn("x-real-ip", headers)
                self.assertEqual(headers["cookie"], "synthetic=1")
                self.assertEqual(headers["authorization"], "Bearer synthetic")
                self.assertNotIn("forwarded", headers)
                self.assertFalse(any(name.startswith("x-ms-") for name in headers))
                self.assertFalse(any(root.glob("body/*")))
                self.assertFalse(any(root.glob("proxy/*")))
                connection = http.client.HTTPSConnection(
                    "127.0.0.1",
                    port,
                    context=ssl.create_default_context(cafile=str(cert)),
                    timeout=5,
                )
                seen = len(received)
                for repeated in (
                    [("Origin", "https://a.example"), ("Origin", "https://b.example")],
                    [("X-PII-Guard-Token", "0" * 32), ("X-PII-Guard-Token", "1" * 32)],
                    [("X-PII-Guard-Connection", "one"), ("X-PII-Guard-Connection", "two")],
                    [("Authorization", "Bearer one"), ("Authorization", "Bearer two")],
                    [
                        ("Cookie", "__Host-pii-guard-guest=a"),
                        ("Cookie", "__Host-pii-guard-guest=b"),
                    ],
                    [("Cookie", "__Host-pii-guard-guest=a; other=1; __Host-pii-guard-guest=b")],
                ):
                    connection = http.client.HTTPSConnection(
                        "127.0.0.1",
                        port,
                        context=ssl.create_default_context(cafile=str(cert)),
                        timeout=5,
                    )
                    connection.putrequest("GET", "/login")
                    for name, value in repeated:
                        connection.putheader(name, value)
                    connection.endheaders()
                    response = connection.getresponse()
                    self.assertEqual(response.status, 400, repeated)
                    response.read()
                    connection.close()
                self.assertEqual(len(received), seen)
                connection = http.client.HTTPSConnection(
                    "127.0.0.1",
                    port,
                    context=ssl.create_default_context(cafile=str(cert)),
                    timeout=5,
                )
                connection.request(
                    "GET", "/login", headers={"Cookie": "__Host-pii-guard-guest=a; other=1"}
                )
                response = connection.getresponse()
                self.assertEqual(response.status, 302)
                response.read()
                connection.close()
                self.assertEqual(len(received), seen + 1)
                connection = http.client.HTTPSConnection(
                    "127.0.0.1",
                    port,
                    context=ssl.create_default_context(cafile=str(cert)),
                    timeout=5,
                )
                connection.request("GET", "/stream", headers={"Accept": "text/event-stream"})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                self.assertEqual(response.read(len(b"data: first\n\n")), b"data: first\n\n")
                self.assertFalse(release_stream.is_set())
                release_stream.set()
                self.assertEqual(response.read(), b"data: second\n\n")
                connection.close()
            finally:
                release_stream.set()
                if process is not None:
                    process.terminate()
                    process.wait(timeout=5)
                os.close(fd)
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    unittest.main()
