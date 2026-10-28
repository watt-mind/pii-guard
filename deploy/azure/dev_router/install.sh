#!/bin/bash
# Cloud-init writes these non-secret sources under /opt/piiguard-dev-router first.
# No shell tracing: enrollment occurs only inside bootstrap.py, after installation.
set -euo pipefail
umask 077
exec >/dev/null 2>&1
export DEBIAN_FRONTEND=noninteractive
test "$(id -u)" = 0
# shellcheck source=/dev/null
. /etc/os-release
test "$ID" = ubuntu
test "$VERSION_ID" = 24.04
test "$(dpkg --print-architecture)" = amd64

# Packages must not start a default wildcard resolver or unmanaged daemon.
systemctl mask dnsmasq.service tailscaled.service nginx.service
apt-get update -qq
apt-get install -y --no-install-recommends ca-certificates curl nftables dnsmasq nginx-light python3
# Validate the exact public repository trust key before apt uses its signed metadata.
curl --proto '=https' --tlsv1.2 --fail --silent --show-error \
  https://pkgs.tailscale.com/stable/ubuntu/noble.noarmor.gpg \
  -o /usr/share/keyrings/tailscale-archive-keyring.gpg
echo '3e03dacf222698c60b8e2f990b809ca1b3e104de127767864284e6c228f1fb39  /usr/share/keyrings/tailscale-archive-keyring.gpg' | sha256sum --check --status
chmod 0644 /usr/share/keyrings/tailscale-archive-keyring.gpg
echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/tailscale-archive-keyring.gpg] https://pkgs.tailscale.com/stable/ubuntu noble main' > /etc/apt/sources.list.d/tailscale.list
apt-get update -qq
apt-get install -y --no-install-recommends tailscale=1.104.4
apt-mark hold tailscale

# Block IP forwarding before first enrollment. The runtime atomically replaces this
# with tailnet-interface-only TCP443 and DNS input. nftables loads it early on subsequent boots.
cat > /etc/nftables.conf <<'EOF'
flush ruleset
table inet piiguard_dev {
  chain input {
    type filter hook input priority 0; policy drop;
    iifname "lo" accept
    ct state established,related accept
    udp sport 67 udp dport 68 accept
    udp dport 41641 accept
  }
  chain forward { type filter hook forward priority 0; policy drop; }
}
EOF
systemctl enable --now nftables.service
systemctl disable --now ssh.service ssh.socket || true
systemctl stop dnsmasq.service
systemctl disable nginx.service
# Suppress default wildcard DNS service; bootstrap writes its tailnet-only listener.
echo 'port=0' > /etc/dnsmasq.d/piiguard-dev-router.conf
install -d -m 0700 /var/lib/tailscale
chmod 0700 /var/lib/tailscale
install -d -m 0755 /etc/systemd/system/tailscaled.service.d
cat > /etc/systemd/system/tailscaled.service.d/privacy.conf <<'EOF'
[Service]
Environment=TS_NO_LOGS_NO_SUPPORT=true
UMask=0077
LimitCORE=0
StandardOutput=null
StandardError=null
EOF
install -m 0644 /opt/piiguard-dev-router/piiguard-dev-router.service /etc/systemd/system/piiguard-dev-router.service
chmod 0600 /etc/piiguard-dev-router/config.json
systemctl daemon-reload
systemctl unmask dnsmasq.service tailscaled.service
systemctl disable dnsmasq.service
# Nginx stays masked: the Python supervisor starts its binary with in-memory TLS.
install -d -m 0750 -g www-data /run/piiguard-dev-router
systemctl enable tailscaled.service piiguard-dev-router.service
systemctl restart tailscaled.service
systemctl start --no-block piiguard-dev-router.service
