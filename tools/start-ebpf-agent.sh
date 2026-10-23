#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo $0" >&2
  exit 1
fi
if ! mountpoint -q /sys/kernel/tracing; then
  mount -t tracefs tracefs /sys/kernel/tracing
fi
exec .venv/bin/python main.py agent \
  --server "${AQUARIUM_SERVER:-http://127.0.0.1:8765}" \
  --source ebpf --network-peers ebpf \
  --network-interface "${AQUARIUM_NETWORK_INTERFACE:-ens18}" "$@"
