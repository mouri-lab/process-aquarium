"""Best-effort agent-side IPC discovery; never imported by remote clients."""

from collections import defaultdict
from itertools import combinations
import re
import subprocess
import tempfile
import time

import psutil

from ..telemetry import Connection, NetworkFlow


def descriptor_groups(output, visible):
    """Parse lsof's field format, preserving paths containing whitespace.

    Only resource identities are joined. Generic names such as 'pipe'/'socket'
    and unrelated endpoints using the same port are not evidence of shared IPC.
    """
    groups = defaultdict(set)
    pid, record = None, {}

    def finish():
        if pid not in visible:
            return
        kind = record.get("t", "")
        name = record.get("n", "")
        if kind == "PIPE":
            identifiers = re.findall(
                r"0x[0-9a-fA-F]+", record.get("D", "") + " " + name
            )
            if record.get("i"):
                identifiers.append("inode:" + record.get("D", "") + ":" + record["i"])
            for identity in identifiers:
                groups[("pipe", identity)].add(pid)
        elif kind in ("unix", "sock") and name and name not in ("socket", "sock"):
            groups[("unix", name)].add(pid)

    for line in output.splitlines():
        if not line:
            continue
        field, value = line[0], line[1:]
        if field == "p":
            finish()
            try:
                pid = int(value)
            except ValueError:
                pid = None
            record = {}
        elif field == "f":
            finish()
            record = {}
        elif field in "tnDi":
            record[field] = value
    finish()
    return groups


class IPCDetector:
    def __init__(self):
        self.descriptors = {}
        self.last_descriptors = float("-inf")
        self.network_flows = ()

    def read_descriptors(self, processes):
        # Disk-backed capture bounds memory even for hosts with many descriptors.
        try:
            with tempfile.TemporaryFile() as output:
                subprocess.run(
                    ["lsof", "-n", "-P", "+c", "0", "-F", "pftnDi"],
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                    check=False,
                )
                output.seek(0)
                data = output.read(2 * 1024 * 1024).decode("utf-8", "replace")
            return descriptor_groups(data.rsplit("\n", 1)[0], processes)
        except (OSError, subprocess.TimeoutExpired):
            return {}

    def detect(self, processes, limit=100):
        groups = defaultdict(set)
        network_flows = []
        for kind in ("inet", "unix"):
            try:
                for conn in psutil.net_connections(kind=kind):
                    if conn.pid not in processes:
                        continue
                    if kind == "unix":
                        if conn.laddr:
                            groups[("unix", str(conn.laddr))].add(conn.pid)
                        continue
                    process = processes[conn.pid]
                    local = conn.laddr
                    remote = conn.raddr
                    if local and len(network_flows) < 4096:
                        network_flows.append(NetworkFlow(
                            pid=conn.pid, create_time=process.create_time,
                            transport="tcp", local_address=str(local.ip),
                            local_port=int(local.port),
                            remote_address=str(remote.ip) if remote else "",
                            remote_port=int(remote.port) if remote else 0,
                            state=str(getattr(conn, "status", "") or ""),
                        ))
                    if (
                        not conn.laddr
                        or not conn.raddr
                        or conn.laddr.ip not in ("127.0.0.1", "::1")
                        or conn.raddr.ip not in ("127.0.0.1", "::1")
                    ):
                        continue
                    endpoints = tuple(
                        sorted(
                            (
                                (conn.laddr.ip, conn.laddr.port),
                                (conn.raddr.ip, conn.raddr.port),
                            )
                        )
                    )
                    groups[("tcp-loop", endpoints)].add(conn.pid)
            except (psutil.Error, OSError, NotImplementedError):
                continue
        self.network_flows = tuple(network_flows)
        now = time.monotonic()
        if now - self.last_descriptors >= 10:
            raw = self.read_descriptors(processes)
            # Cached ownership carries create_time so PID reuse cannot join an
            # old pipe owner to an unrelated new process.
            self.descriptors = {
                key: {(pid, processes[pid].create_time) for pid in owners}
                for key, owners in raw.items()
            }
            self.last_descriptors = now
        for key, owners in self.descriptors.items():
            groups[key].update(
                pid
                for pid, created in owners
                if pid in processes and processes[pid].create_time == created
            )
        result, seen = [], set()
        for (kind, _), owners in groups.items():
            for a, b in combinations(sorted(owners), 2):
                if (a, b, kind) in seen:
                    continue
                seen.add((a, b, kind))
                result.append(Connection(a, b, kind))
                if len(result) >= limit:
                    return result
        pairs = {(c.pid_a, c.pid_b) for c in result}
        for proc in processes.values():
            pair = tuple(sorted((proc.ppid, proc.pid)))
            if proc.ppid in processes and proc.ppid != proc.pid and pair not in pairs:
                result.append(Connection(proc.ppid, proc.pid, "parent-child"))
                pairs.add(pair)
                if len(result) >= limit:
                    break
        return result
