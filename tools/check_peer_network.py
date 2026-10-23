#!/usr/bin/env python3
"""Opt-in Linux/BCC integration check using two disposable network namespaces.

Run as root: python3 tools/check_peer_network.py
Only uniquely named test namespaces/veth devices are changed. Nothing is
published to an existing server. Cleanup runs on both success and failure.
"""

import json
import os
from pathlib import Path
import selectors
import socket
import subprocess
import sys
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def worker(host, address4, address6):
    from src.core.sources import PsutilProcessSource
    source = PsutilProcessSource(host_id=host, network_interface="aq0", network_peers="ebpf",
                                network_scope="aquarium-integration")
    sockets = []
    for family, address in [(socket.AF_INET, address4), (socket.AF_INET6, address6)]:
        udp = socket.socket(family, socket.SOCK_DGRAM)
        udp.bind((address, 4848))
        sockets.append(udp)
        tcp = socket.socket(family, socket.SOCK_STREAM)
        tcp.bind((address, 4849))
        tcp.listen()
        sockets.append(tcp)

        def drain(listener=tcp):
            try:
                while True:
                    conn, _ = listener.accept()
                    with conn:
                        while conn.recv(65536):
                            pass
            except OSError:
                pass
        threading.Thread(target=drain, daemon=True).start()
    try:
        for line in sys.stdin:
            command = json.loads(line)
            if command["op"] == "sample":
                source._scan()
                print(source.get_snapshot().to_bytes().decode(), flush=True)
            elif command["op"] == "send":
                family = socket.AF_INET6 if ":" in command["address"] else socket.AF_INET
                kind = socket.SOCK_STREAM if command["tcp"] else socket.SOCK_DGRAM
                with socket.socket(family, kind) as outgoing:
                    outgoing.settimeout(5)
                    outgoing.connect((command["address"], 4849 if command["tcp"] else 4848))
                    outgoing.sendall(b"a" * command["size"])
                print("{}", flush=True)
    finally:
        source.shutdown()
        for sock in sockets:
            sock.close()


def check():
    from src.server import SnapshotStore, TelemetryHTTPServer
    from src.telemetry import snapshot_from_dict
    from src.transport import APIClient

    if sys.platform != "linux" or os.geteuid() != 0:
        raise SystemExit("This integration check requires Linux root, BCC, psutil and iproute2")
    tag = uuid.uuid4().hex[:8]
    namespaces = [f"aq-{tag}-a", f"aq-{tag}-b"]
    devices = [f"aq{tag}a", f"aq{tag}b"]
    children = []
    created = []
    server = None
    thread = None

    def ip(*args):
        subprocess.run(["ip", *args], check=True, timeout=10)

    def ask(child, **command):
        child.stdin.write(json.dumps(command) + "\n")
        child.stdin.flush()
        with selectors.DefaultSelector() as ready:
            ready.register(child.stdout, selectors.EVENT_READ)
            if not ready.select(30):
                raise RuntimeError("Collector timed out")
        line = child.stdout.readline()
        if not line:
            raise RuntimeError(f"Collector exited: {child.poll()}")
        return json.loads(line)

    def samples():
        return [snapshot_from_dict(ask(p, op="sample")) for p in children]

    try:
        for namespace in namespaces:
            ip("netns", "add", namespace)
            created.append(namespace)
        ip("link", "add", devices[0], "type", "veth", "peer", "name", devices[1])
        for index, (namespace, device) in enumerate(zip(namespaces, devices), 1):
            ip("link", "set", device, "netns", namespace)
            ip("-n", namespace, "link", "set", device, "name", "aq0")
            ip("-n", namespace, "addr", "add", f"198.18.0.{index}/24", "dev", "aq0")
            ip("-n", namespace, "-6", "addr", "add", f"fd42:abcd::{index}/64", "dev", "aq0", "nodad")
            ip("-n", namespace, "link", "set", "aq0", "up")
            ip("-n", namespace, "link", "set", "lo", "up")
            children.append(subprocess.Popen(["ip", "netns", "exec", namespace, sys.executable,
                str(Path(__file__).resolve()), "--worker", f"host-{index}", f"198.18.0.{index}",
                f"fd42:abcd::{index}"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True))
        # Avoid counting IPv6 neighbour advertisements as part of the controlled
        # UDP transfer; the production collector correctly counts those IP bytes.
        macs = [json.loads(subprocess.check_output(["ip", "-n", ns, "-j", "link", "show", "aq0"]))[0]["address"]
                for ns in namespaces]
        for i, namespace in enumerate(namespaces):
            other = 1 - i
            for address in [f"198.18.0.{other + 1}", f"fd42:abcd::{other + 1}"]:
                ip("-n", namespace, "neigh", "replace", address, "lladdr", macs[other], "dev", "aq0", "nud", "permanent")
        initial = samples()
        assert all(s.network_peers.status == "warming" for s in initial), initial

        # Exact small UDP/IP counts catch wrong byte order, L2 offsets and direction.
        ask(children[0], op="send", address="198.18.0.2", size=100, tcp=False)
        ask(children[1], op="send", address="fd42:abcd::1", size=200, tcp=False)
        time.sleep(.1)
        snapshots = samples()
        peers = [{p.address: p for p in s.network_peers.peers} for s in snapshots]
        assert peers[0]["198.18.0.2"].sent_bytes == 128, peers
        assert peers[1]["198.18.0.1"].received_bytes == 128, peers
        assert peers[1]["fd42:abcd::1"].sent_bytes == 248, peers
        assert peers[0]["fd42:abcd::2"].received_bytes == 248, peers

        server = TelemetryHTTPServer(("127.0.0.1", 0), store=SnapshotStore(), token="integration-only")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        client = APIClient(f"http://127.0.0.1:{server.server_port}", token="integration-only")
        for snapshot in snapshots:
            client.request("POST", "/api/v1/snapshots", snapshot.to_dict())
        links = client.request("GET", "/api/v1/transfers")["transfers"]
        assert [(p["source"]["host_id"], p["bytes"]) for p in links] == [("host-1", 128), ("host-2", 248)], links

        # TCP on both IP families exercises segmented payload and reverse ACKs.
        ask(children[0], op="send", address="fd42:abcd::2", size=128 * 1024, tcp=True)
        ask(children[1], op="send", address="198.18.0.1", size=64 * 1024, tcp=True)
        time.sleep(.2)
        tcp_snapshots = samples()
        peers = [{p.address: p for p in s.network_peers.peers} for s in tcp_snapshots]
        assert peers[0]["fd42:abcd::2"].sent_bytes >= 128 * 1024, peers
        assert peers[1]["198.18.0.1"].sent_bytes >= 64 * 1024, peers
        assert peers[1]["fd42:abcd::1"].received_bytes >= 128 * 1024, peers
        assert peers[0]["198.18.0.2"].received_bytes >= 64 * 1024, peers

        # Let delayed ACKs settle, then a fresh idle window must be empty.
        time.sleep(.3)
        samples()
        time.sleep(.1)
        idle = samples()
        assert all(s.network_peers.status == "ready" and not s.network_peers.peers for s in idle), idle
        for snapshot in idle:
            client.request("POST", "/api/v1/snapshots", snapshot.to_dict())
        assert client.request("GET", "/api/v1/transfers") == {"transfers": []}
        print("PASS: IPv4/IPv6 UDP exact IP byte counts, bidirectional TCP, agent snapshots, authenticated aggregation, idle")
    finally:
        if server:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
        for child in children:
            if child.poll() is None:
                child.stdin.close()
                try:
                    child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=5)
        for namespace in reversed(created):
            subprocess.run(["ip", "netns", "del", namespace], check=False, timeout=10)
        # Covers failure between veth creation and moving both ends into netns.
        subprocess.run(["ip", "link", "del", devices[0]], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, check=False, timeout=10)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        worker(*sys.argv[2:])
    else:
        check()
