#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo $0" >&2
  exit 1
fi
if [[ $PWD != /home/ubuntu/process-aquarium ]]; then
  echo "Update the paths in tools/process-aquarium-agent.service before installing from $PWD" >&2
  exit 1
fi
if pgrep -f '[m]ain.py agent' >/dev/null; then
  if ! systemctl is-active --quiet process-aquarium-agent.service; then
    echo "Stop the manually started aquarium agent before installing this service." >&2
    exit 1
  fi
fi
install -m 0644 tools/process-aquarium-agent.service /etc/systemd/system/process-aquarium-agent.service
if [[ ! -e /etc/default/process-aquarium-agent ]]; then
  install -m 0600 /dev/null /etc/default/process-aquarium-agent
  cat > /etc/default/process-aquarium-agent <<'EOF'
AQUARIUM_SERVER=http://127.0.0.1:8765
AQUARIUM_NETWORK_INTERFACE=ens18
EOF
fi
systemctl daemon-reload
systemctl enable process-aquarium-agent.service
systemctl restart process-aquarium-agent.service
systemctl status process-aquarium-agent.service --no-pager
