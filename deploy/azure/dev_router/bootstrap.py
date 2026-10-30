#!/usr/bin/python3
"""Root-only, content-free enrollment and HTTPS for the development tailnet proxy.

The enrollment key and IMDS token exist only in Python/child-process memory. Normal
tailscaled machine identity persists under /var/lib/tailscale on the encrypted OS disk.
"""

from __future__ import annotations

import fcntl
import ipaddress
import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

CONFIG = Path("/etc/piiguard-dev-router/config.json")
DNS_NAME = "guard-dev.watt-mind.com"
TAILNET = ipaddress.ip_network("100.64.0.0/10")
SECRET_URI = re.compile(
    r"https://[a-z0-9][a-z0-9-]{1,22}[a-z0-9]\.vault\.azure\.net/"
    r"secrets/[A-Za-z0-9-]{1,127}/[a-fA-F0-9]{32}\Z"
)
# Forwarded security and control headers that are only ever sent once. nginx joins
# repeated lines into one $http_* value with ", ", so a comma means a repeat (LAB-1467).
SINGLE_VALUE_HEADERS = (
    "Authorization",
    "Origin",
    "X-PII-Guard-Token",
    "X-PII-Guard-Session",
    "X-PII-Guard-Connection",
    "X-PII-Guard-Mode",
    "X-PII-Guard-Language",
    "X-PII-Guard-Echo",
)
# Repeated Cookie lines are joined with "; ", like one ordinary Cookie header. A __Host-
# cookie has exactly one possible scope, so a repeated guest cookie is cookie tossing.
GUEST_COOKIE = "__Host-pii-guard-guest"


class BootstrapError(Exception):
    """A deliberately content-free failure."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise BootstrapError("router_http_redirect_refused")


def validate_config(config: dict) -> dict:
    if set(config) != {
        "hostname",
        "aca_fqdn",
        "secret_uri",
        "tls_secret_uri",
        "managed_identity_client_id",
    }:
        raise BootstrapError("router_config_invalid")
    if not all(isinstance(value, str) for value in config.values()):
        raise BootstrapError("router_config_invalid")
    if not re.fullmatch(
        r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.){3,5}azurecontainerapps\.io", config["aca_fqdn"]
    ):
        raise BootstrapError("router_config_invalid")
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", config["hostname"]):
        raise BootstrapError("router_config_invalid")
    if not all(SECRET_URI.fullmatch(config[key]) for key in ("secret_uri", "tls_secret_uri")):
        raise BootstrapError("router_config_invalid")
    uuid.UUID(config["managed_identity_client_id"])
    return config


def request_json(url: str, headers: dict) -> dict:
    imds = "http://169.254.169.254/metadata/identity/oauth2/token?"
    vault_uri = url.removesuffix("?api-version=7.4")
    if not url.startswith(imds) and not SECRET_URI.fullmatch(vault_uri):
        raise BootstrapError("router_http_destination_refused")
    # Never inherit proxy settings or follow redirects carrying Authorization.
    opener = build_opener(ProxyHandler({}), NoRedirect())
    with opener.open(Request(url, headers=headers), timeout=10) as response:  # noqa: S310 - allowlist above
        data = response.read(65537)
        if len(data) > 65536:
            raise BootstrapError("router_http_response_invalid")
        result = json.loads(data)
        if not isinstance(result, dict):
            raise BootstrapError("router_http_response_invalid")
        return result


def secret_value(config: dict, uri: str, request=request_json, sleep=time.sleep) -> str:
    """Bounded IMDS/RBAC propagation retries; no response/exception is logged."""
    query = urlencode(
        {
            "api-version": "2018-02-01",
            "resource": "https://vault.azure.net",
            "client_id": config["managed_identity_client_id"],
        }
    )
    for attempt in range(12):
        try:
            token = request(
                f"http://169.254.169.254/metadata/identity/oauth2/token?{query}",
                {"Metadata": "true"},
            )["access_token"]
            if not isinstance(token, str) or not token or "\n" in token or "\r" in token:
                raise BootstrapError("router_identity_invalid")
            secret = request(
                uri + "?api-version=7.4",
                {"Authorization": "Bearer " + token},
            )["value"]
            if not isinstance(secret, str) or not secret or len(secret) > 60000:
                raise BootstrapError("router_secret_invalid")
            return secret
        except Exception:
            if attempt < 11:
                sleep(10)
    raise BootstrapError("router_secret_unavailable") from None


def command(argv: list[str], *, stdin: bytes | None = None, capture: bool = False) -> bytes:
    executables = {
        "nft": "/usr/sbin/nft",
        "sysctl": "/usr/sbin/sysctl",
        "tailscale": "/usr/bin/tailscale",
        "systemctl": "/usr/bin/systemctl",
        "nginx": "/usr/sbin/nginx",
    }
    result = subprocess.run(  # noqa: S603 - fixed executable map, validated configuration, no shell
        [executables[argv[0]], *argv[1:]],
        input=stdin,
        stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=100,
        env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "TS_NO_LOGS_NO_SUPPORT": "true"},
    )
    if result.returncode:
        raise BootstrapError("router_command_failed")
    return result.stdout if capture else b""


def firewall(tail_ip: str | None = None) -> str:
    tail_rules = ""
    if tail_ip:
        address = ipaddress.IPv4Address(tail_ip)
        if address not in TAILNET:
            raise BootstrapError("router_tailnet_ip_invalid")
        prefix = f'iifname "tailscale0" ip saddr 100.64.0.0/10 ip daddr {address}'
        tail_rules = f"{prefix} udp dport 53 accept\n    {prefix} tcp dport {{ 53, 443 }} accept"
    return f"""#!/usr/sbin/nft -f
flush ruleset
table inet piiguard_dev {{
  chain input {{
    type filter hook input priority 0; policy drop;
    iifname "lo" accept
    ct state established,related accept
    udp sport 67 udp dport 68 accept
    udp dport 41641 accept
    {tail_rules}
  }}
  chain forward {{ type filter hook forward priority 0; policy drop; }}
}}
"""


def dns_config(tail_ip: str) -> str:
    return f"""# Exact host only. No query logging, upstream recursion or wildcard records.
interface=tailscale0
except-interface=lo
listen-address={tail_ip}
bind-interfaces
no-resolv
no-hosts
host-record={DNS_NAME},{tail_ip}
cache-size=0
log-facility=/dev/null
"""


def nginx_config(aca_fqdn: str, tail_ip: str, pem_path: str) -> str:
    # All incoming identity and proxy headers (including unknown X-MS-* fields)
    # are dropped by forwarding only the explicitly supported client header set.
    headers = {
        "Authorization": "$http_authorization",
        "Cookie": "$http_cookie",
        "Content-Type": "$http_content_type",
        "Accept": "$http_accept",
        # The app compresses static assets itself; nginx gzip stays off (LAB-1472).
        "Accept-Encoding": "$http_accept_encoding",
        "Origin": "$http_origin",
        "Sec-Fetch-Site": "$http_sec_fetch_site",
        "Referer": "$http_referer",
        "Last-Event-ID": "$http_last_event_id",
        "Cache-Control": "$http_cache_control",
        "X-PII-Guard-Token": "$http_x_pii_guard_token",
        "X-PII-Guard-Session": "$http_x_pii_guard_session",
        "X-PII-Guard-Connection": "$http_x_pii_guard_connection",
        "X-PII-Guard-Mode": "$http_x_pii_guard_mode",
        "X-PII-Guard-Language": "$http_x_pii_guard_language",
        "X-PII-Guard-Echo": "$http_x_pii_guard_echo",
    }
    forwarded = "\n".join(
        f"      proxy_set_header {key} {value};" for key, value in headers.items()
    )
    single = "|".join("$http_" + name.lower().replace("-", "_") for name in SINGLE_VALUE_HEADERS)
    return f"""user www-data;
worker_processes 1;
error_log /dev/null crit;
pid /run/piiguard-dev-router/nginx.pid;
events {{ worker_connections 256; }}
http {{
  access_log off;
  server_tokens off;
  client_body_temp_path /run/piiguard-dev-router/body;
  proxy_temp_path /run/piiguard-dev-router/proxy;
  resolver 168.63.129.16 valid=30s ipv6=off;
  # The app refuses duplicate security headers, but only nginx sees the separate lines.
  map "{single}" $piiguard_repeated_header {{
    default 0;
    "~," 1;
  }}
  map $http_cookie $piiguard_repeated_cookie {{
    default 0;
    "~{GUEST_COOKIE}=.*{GUEST_COOKIE}=" 1;
  }}
  server {{
    listen {tail_ip}:443 ssl;
    server_name {DNS_NAME};
    ssl_certificate {pem_path};
    ssl_certificate_key {pem_path};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_tickets off;
    client_max_body_size 16m;
    client_body_buffer_size 16m;
    client_body_in_file_only off;
    if ($piiguard_repeated_header) {{ return 400; }}
    if ($piiguard_repeated_cookie) {{ return 400; }}
    location / {{
      set $aca_origin {aca_fqdn};
      proxy_pass https://$aca_origin;
      proxy_ssl_verify on;
      # Default depth 1 rejects ACA's leaf -> intermediate -> root chain (LAB-1422).
      proxy_ssl_verify_depth 3;
      proxy_ssl_trusted_certificate /etc/ssl/certs/ca-certificates.crt;
      proxy_ssl_server_name on;
      proxy_ssl_name {aca_fqdn};
      proxy_http_version 1.1;
      proxy_buffering off;
      proxy_request_buffering off;
      proxy_max_temp_file_size 0;
      proxy_read_timeout 3600s;
      proxy_send_timeout 3600s;
      proxy_pass_request_headers off;
      proxy_set_header Host {aca_fqdn};
      proxy_set_header Connection "";
      proxy_set_header X-Forwarded-Host {DNS_NAME};
      proxy_set_header X-Forwarded-Proto https;
      proxy_set_header X-Forwarded-For $remote_addr;
      proxy_set_header X-Pii-Guard-External-Host {DNS_NAME};
      proxy_set_header X-Pii-Guard-External-Proto https;
{forwarded}
      proxy_redirect https://{aca_fqdn}/ https://{DNS_NAME}/;
    }}
  }}
}}
"""


def sealed_pem(pem: str) -> int:
    # Linux memfd has no filesystem backing; only this root supervisor holds it.
    fd = os.memfd_create("piiguard-dev-tls", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, pem.encode())
        os.lseek(fd, 0, os.SEEK_SET)
        fcntl.fcntl(
            fd,
            fcntl.F_ADD_SEALS,
            fcntl.F_SEAL_WRITE | fcntl.F_SEAL_GROW | fcntl.F_SEAL_SHRINK | fcntl.F_SEAL_SEAL,
        )
    except Exception:
        os.close(fd)
        raise BootstrapError("router_tls_memory_failed") from None
    return fd


def write_private(path: Path, content: str) -> None:
    # Paths and contents are configuration only, never credentials.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        os.chmod(path, 0o600)
        handle.write(content)


def configure(config: dict, *, run=command, fetch=secret_value, write=write_private) -> str:
    validate_config(config)
    rules = firewall()
    run(["nft", "-f", "-"], stdin=rules.encode())
    write(Path("/etc/nftables.conf"), rules)
    run(["sysctl", "-w", "net.ipv4.ip_forward=0"])
    write(Path("/etc/sysctl.d/90-piiguard-dev-router.conf"), "net.ipv4.ip_forward=0\n")
    status = json.loads(run(["tailscale", "status", "--json", "--peers=false"], capture=True))
    state = status.get("BackendState")
    if state not in {"Running", "Stopped", "NeedsLogin"}:
        raise BootstrapError("router_identity_not_ready")
    args = [
        "tailscale",
        "up",
        "--reset",
        "--timeout=90s",
        "--hostname=" + config["hostname"],
        "--advertise-routes=",
        "--advertise-tags=tag:piiguard-dev",
        "--accept-routes=false",
        "--accept-dns=false",
        "--advertise-exit-node=false",
        "--exit-node=",
        "--ssh=false",
        "--netfilter-mode=off",
        "--snat-subnet-routes=false",
    ]
    if state == "NeedsLogin":
        key = fetch(config, config["secret_uri"])
        if not re.fullmatch(r"tskey-auth-[A-Za-z0-9-]{10,200}", key):
            raise BootstrapError("router_enrollment_invalid")
        # Official file: support uses os.ReadFile; /proc/self/fd/0 is the child pipe.
        # The key is never an argv, environment, temporary file or logged output.
        run([*args, "--auth-key=file:/proc/self/fd/0"], stdin=key.encode())
    else:
        run(args)
    run(["tailscale", "serve", "reset"])
    tail_ip = run(["tailscale", "ip", "-4"], capture=True).decode().strip()
    rules = firewall(tail_ip)
    run(["nft", "-f", "-"], stdin=rules.encode())
    write(Path("/etc/nftables.conf"), rules)
    write(Path("/etc/dnsmasq.d/piiguard-dev-router.conf"), dns_config(tail_ip))
    run(["systemctl", "restart", "dnsmasq.service"])
    return tail_ip


def supervise_proxy(
    config: dict, tail_ip: str, *, fetch=secret_value, seal=sealed_pem, run=command
) -> None:
    fd = seal(fetch(config, config["tls_secret_uri"]))
    try:
        pem_path = f"/proc/{os.getpid()}/fd/{fd}"
        write_private(
            Path("/run/piiguard-dev-router/nginx.conf"),
            nginx_config(config["aca_fqdn"], tail_ip, pem_path),
        )
        # Syntax/key/chain validation completes before the public-facing listener.
        run(["nginx", "-t", "-c", "/run/piiguard-dev-router/nginx.conf"])
        process = subprocess.Popen(
            ["/usr/sbin/nginx", "-c", "/run/piiguard-dev-router/nginx.conf", "-g", "daemon off;"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env={"PATH": "/usr/sbin:/usr/bin:/sbin:/bin"},
        )
        # systemd stops the whole cgroup; keep memfd alive until nginx exits.
        signal.signal(signal.SIGTERM, lambda *_: process.terminate())
        result = process.wait()
        if result:
            raise BootstrapError("router_proxy_failed")
    finally:
        os.close(fd)


def main() -> int:
    os.umask(0o077)
    try:
        if CONFIG.stat().st_mode & 0o077 or CONFIG.stat().st_uid != 0:
            raise BootstrapError("router_config_permissions_invalid")
        config = json.loads(CONFIG.read_text())
        tail_ip = configure(config)
        supervise_proxy(config, tail_ip)
    except Exception:
        # Do not emit exception text, HTTP bodies or child output, even in failure paths.
        print("router_bootstrap_failed", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
