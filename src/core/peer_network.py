"""Optional Linux/BCC peer accounting, independent of process event collection."""

import ctypes
import errno
import ipaddress
import math
from pathlib import Path
import socket
import sys
import time

import psutil

from ..telemetry import MAX_NETWORK_PEERS, PeerNetworkActivity, PeerTraffic, ProtocolError, peer_address


class BccPeerCounter:
    """One cooked packet socket with a bounded, cumulative in-kernel map."""

    def __init__(self, interface, addresses):
        from bcc import BPF

        self.bpf = None
        self.socket = None
        try:
            self.bpf = BPF(src_file=str(Path(__file__).with_name("peer_traffic.bpf.c")).encode())
            table = self.bpf[b"local_addresses"]
            for text in addresses:
                address = ipaddress.ip_address(text)
                key = table.Key()
                key.family = address.version
                for i, value in enumerate(address.packed):
                    key.bytes[i] = value
                table[key] = table.Leaf(1)
            function = self.bpf.load_func(b"observe", BPF.SOCKET_FILTER)
            # Protocol zero keeps the socket inactive until bound. Attach first,
            # then enable ETH_P_ALL; no unfiltered packet queue during startup.
            self.socket = socket.socket(socket.AF_PACKET, socket.SOCK_DGRAM, 0)
            self.socket.setsockopt(socket.SOL_SOCKET, 50, function.fd)  # SO_ATTACH_BPF
            self.socket.bind((interface, 3))  # ETH_P_ALL, Python converts byte order
        except BaseException:
            self.close()
            raise

    def read(self):
        counters = {}
        for key, value in self.bpf[b"peer_bytes"].items():
            size = 4 if key.address.family == 4 else 16
            try:
                address = peer_address(str(ipaddress.ip_address(bytes(key.address.bytes)[:size])))
            except ProtocolError:
                continue
            counters[address, int(key.outgoing)] = int(value.value)
        lost = self.bpf[b"overflows"][ctypes.c_int(0)].value
        return counters, lost

    def close(self):
        if self.socket is not None:
            self.socket.close()
            self.socket = None
        if self.bpf is not None:
            self.bpf.cleanup()
            self.bpf = None


def interface_identity(interface):
    """Return NIC generation plus only its routable unicast address inventory."""
    stat = psutil.net_if_stats().get(interface)
    if stat is None or not stat.isup:
        raise OSError(errno.ENODEV, "Network interface is down or missing")
    addresses = set()
    for item in psutil.net_if_addrs().get(interface, ()):
        if item.family not in (socket.AF_INET, socket.AF_INET6):
            continue
        try:
            addresses.add(peer_address(item.address))
        except ProtocolError:
            continue
    if len(addresses) > 64:
        raise OSError("Too many interface addresses")
    return socket.if_nametoindex(interface), tuple(sorted(addresses))


class PeerNetworkSampler:
    def __init__(self, *, mode="auto", network_scope="default", clock=time.monotonic,
                 backend_factory=BccPeerCounter, inventory=interface_identity):
        if mode not in ("auto", "ebpf", "off"):
            raise ValueError("Unknown peer network collector")
        if (not isinstance(network_scope, str) or not 0 < len(network_scope) <= 128 or
                any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in network_scope)):
            raise ValueError("Network scope must be 1..128 printable characters")
        self.mode, self.network_scope = mode, network_scope
        self.clock, self.backend_factory, self.inventory = clock, backend_factory, inventory
        self.backend = None
        self.identity = None
        self.previous = None
        self.retry_at = 0
        self.failure = None

    def close(self):
        backend, self.backend = self.backend, None
        self.previous = None
        self.identity = None
        if backend is not None:
            backend.close()

    def reset(self):
        self.close()
        self.retry_at = 0
        self.failure = None
        return PeerNetworkActivity("unavailable", "", self.network_scope)

    def sample(self, activity):
        interface = activity.interface if activity else ""
        addresses = ()

        def result(status, interval=None, peers=(), error=None):
            return PeerNetworkActivity(status, interface, self.network_scope, addresses,
                                       interval, peers, error=error)

        try:
            if not interface or activity.status not in ("ready", "warming"):
                self.close()
                return result("disabled" if self.mode == "off" else
                              "ambiguous" if activity and activity.status == "ambiguous" else "unavailable")
            index, addresses = self.inventory(interface)
            identity = interface, index, addresses
            if identity != self.identity:
                self.close()
                self.failure = None
                self.retry_at = 0
                self.identity = identity
            if self.mode == "off":
                return result("disabled")
            if sys.platform != "linux":
                return result("unsupported", error="Peer accounting requires Linux and BCC")
            if not addresses:
                self.close()
                return result("unavailable", error="No eligible unicast address on selected interface")
            now = self.clock()
            if self.failure and now < self.retry_at:
                return result(*self.failure)
            if self.backend is None:
                self.backend = self.backend_factory(interface, addresses)
                self.previous = (self.clock(), self.backend.read()[0])
                self.failure = None
                return result("warming")
            counters, lost = self.backend.read()
            now = self.clock()
            previous_time, previous = self.previous
            self.previous = now, counters
            interval = now - previous_time
            if lost or len(counters) > MAX_NETWORK_PEERS:
                self.close()
                return result("overflow", error="Peer map capacity exceeded; restarting measurement")
            if not math.isfinite(interval) or interval <= 0:
                return result("warming")
            totals = {}
            for (address, outgoing), count in counters.items():
                delta = count - previous.get((address, outgoing), 0)
                if delta < 0 or delta > 2**53 - 1:
                    return result("warming")
                if delta and address not in addresses:
                    total = totals.setdefault(address, [0, 0])
                    total[0 if outgoing else 1] += delta
            peers = tuple(PeerTraffic(a, *values) for a, values in sorted(totals.items()))
            return result("ready", interval, peers)
        except Exception as exc:
            # BCC reports compilation/load failures as generic exceptions; keep
            # process telemetry alive and retry slowly instead of recompiling
            # once per frame. Permission errors retain a distinct status.
            status = "error"
            if isinstance(exc, (ImportError, NotImplementedError)):
                status = "unsupported"
            elif (isinstance(exc, PermissionError) or getattr(exc, "errno", None) in (errno.EPERM, errno.EACCES)
                  or any(s in str(exc).lower() for s in ("permission denied", "operation not permitted"))):
                status = "denied"
            elif getattr(exc, "errno", None) in (errno.ENODEV, errno.ENXIO):
                status = "unavailable"
            old_identity = self.identity
            self.close()
            self.identity = old_identity
            error = str(exc)[:1024] or type(exc).__name__
            self.failure = (status, None, (), error)
            self.retry_at = self.clock() + 30
            return result(status, error=error)
