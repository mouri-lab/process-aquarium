"""Versioned, presentation-independent telemetry shared by every process.

Snapshots are complete host states. Events are a bounded replay window, with
monotonically increasing IDs within one agent session. Neither carries fish,
animation, sorting, nor display-limit state.
"""

from dataclasses import asdict, dataclass, field
import json
import math
from typing import Any, Optional


SCHEMA_VERSION = 1
MAX_BODY_BYTES = 16 * 1024 * 1024
MAX_RESPONSE_BYTES = MAX_BODY_BYTES + 1024 * 1024
MAX_EVENTS = 2048
MAX_PROCESSES = 50000
MAX_NETWORK_FLOWS = 4096


@dataclass(frozen=True)
class ProcessRecord:
    pid: int
    ppid: int
    name: str
    exe: str
    memory_percent: float
    cpu_percent: float
    num_threads: int
    create_time: float
    status: str
    cmdline: tuple[str, ...]

    @property
    def identity(self) -> tuple[int, float]:
        return self.pid, self.create_time


@dataclass(frozen=True)
class LifecycleEvent:
    event_type: str
    pid: int
    ppid: Optional[int]
    timestamp: float
    details: Optional[dict[str, Any]] = None
    event_id: int = 0
    create_time: float = 0.0


@dataclass(frozen=True)
class Connection:
    pid_a: int
    pid_b: int
    kind: str
    metadata: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class NetworkFlow:
    """One observed socket endpoint owned by a process.

    A listener may omit the remote endpoint. This is an observation, not a
    bandwidth estimate; both ends can be correlated by an aggregation server.
    """

    pid: int
    create_time: float
    transport: str
    local_address: str
    local_port: int
    remote_address: str = ""
    remote_port: int = 0
    state: str = ""


@dataclass(frozen=True)
class NetworkActivity:
    """Measured byte deltas for one interface, never inferred from sockets."""

    status: str
    interface: str = ""
    interval_seconds: Optional[float] = None
    sent_bytes: Optional[int] = None
    received_bytes: Optional[int] = None
    scope: str = "interface"
    source: str = "psutil"


@dataclass(frozen=True)
class Snapshot:
    host_id: str
    hostname: str
    boot_id: str
    session_id: str
    sequence: int
    collected_at: float
    source: str
    processes: tuple[ProcessRecord, ...]
    events: tuple[LifecycleEvent, ...] = ()
    connections: tuple[Connection, ...] = ()
    event_stats: dict[str, int] = field(default_factory=dict)
    error: Optional[str] = None
    network_flows: tuple[NetworkFlow, ...] = ()
    network_activity: Optional[NetworkActivity] = None

    @property
    def revision(self) -> tuple[str, str, int]:
        return self.host_id, self.session_id, self.sequence

    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, **asdict(self)}

    def to_bytes(self) -> bytes:
        # psutil can return surrogate-escaped OS strings for non-UTF-8 argv.
        return json.dumps(self.to_dict(), ensure_ascii=True, allow_nan=False,
                          separators=(",", ":")).encode("utf-8")


class ProtocolError(ValueError):
    """The peer supplied unsupported or malformed telemetry."""


def _object(value: Any, name: str) -> dict:
    if not isinstance(value, dict):
        raise ProtocolError(f"{name} must be an object")
    return value


def _text(value: Any, name: str, *, nonempty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > 16384 or (nonempty and not value):
        raise ProtocolError(f"{name} must be {'nonempty ' if nonempty else ''}text (at most 16384 characters)")
    return value


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum or value > 2**53 - 1:
        raise ProtocolError(f"{name} must be an integer >= {minimum}")
    return value


def _number(value: Any, name: str) -> float:
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value >= 0
    except OverflowError:
        valid = False
    if not valid:
        raise ProtocolError(f"{name} must be a finite nonnegative number")
    return float(value)


def _port(value: Any, name: str) -> int:
    value = _integer(value, name)
    if value > 65535:
        raise ProtocolError(f"{name} must be at most 65535")
    return value


def _short_text(value: Any, name: str) -> str:
    value = _text(value, name)
    if len(value) > 64:
        raise ProtocolError(f"{name} must be at most 64 characters")
    return value


def _identifier(value: Any, name: str) -> str:
    value = _text(value, name, nonempty=True)
    if len(value) > 128 or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ProtocolError(f"{name} must be at most 128 characters")
    return value


def _metadata(value: Any, name: str, depth: int = 0) -> Any:
    if depth > 4:
        raise ProtocolError(f"{name} is nested too deeply")
    if value is None or type(value) is bool:
        return value
    if isinstance(value, str):
        return _text(value, name)
    if type(value) in (int, float):
        try:
            if math.isfinite(value):
                return value
        except OverflowError:
            pass
        raise ProtocolError(f"{name} contains a non-finite number")
    if isinstance(value, dict) and len(value) <= 64:
        return {_text(k, name): _metadata(v, name, depth + 1) for k, v in value.items()}
    if isinstance(value, (list, tuple)) and len(value) <= 64:
        return [_metadata(v, name, depth + 1) for v in value]
    raise ProtocolError(f"{name} must contain bounded JSON values")


def _array(value: Any, name: str, limit: int) -> list:
    if not isinstance(value, (list, tuple)) or len(value) > limit:
        raise ProtocolError(f"{name} must be an array of at most {limit} items")
    return value


def snapshot_from_dict(value: Any) -> Snapshot:
    """Validate untrusted JSON before admitting it to the host state."""
    data = _object(value, "snapshot")
    if type(data.get("schema_version")) is not int or data["schema_version"] != SCHEMA_VERSION:
        raise ProtocolError(f"Unsupported schema_version (expected {SCHEMA_VERSION})")
    processes = []
    pids = set()
    for raw in _array(data.get("processes"), "processes", MAX_PROCESSES):
        item = _object(raw, "process")
        pid = _integer(item.get("pid"), "pid")
        if pid in pids:
            raise ProtocolError("Duplicate process PID")
        pids.add(pid)
        processes.append(ProcessRecord(
            pid=pid, ppid=_integer(item.get("ppid"), "ppid"),
            name=_text(item.get("name"), "name"), exe=_text(item.get("exe"), "exe"),
            memory_percent=_number(item.get("memory_percent"), "memory_percent"),
            cpu_percent=_number(item.get("cpu_percent"), "cpu_percent"),
            num_threads=_integer(item.get("num_threads"), "num_threads"),
            create_time=_number(item.get("create_time"), "create_time"),
            status=_text(item.get("status"), "status"),
            cmdline=tuple(_text(arg, "cmdline argument") for arg in
                          _array(item.get("cmdline"), "cmdline", 4096)),
        ))
    events = []
    last_id = 0
    for raw in _array(data.get("events", []), "events", MAX_EVENTS):
        item = _object(raw, "event")
        kind = item.get("event_type")
        if kind not in ("spawn", "fork", "exec", "exit"):
            raise ProtocolError("Unsupported lifecycle event")
        event_id = _integer(item.get("event_id"), "event_id", 1)
        if event_id <= last_id:
            raise ProtocolError("Event IDs must be strictly increasing")
        last_id = event_id
        details = item.get("details")
        ppid = item.get("ppid")
        events.append(LifecycleEvent(
            event_type=kind, pid=_integer(item.get("pid"), "event pid"),
            ppid=None if ppid is None else _integer(ppid, "event ppid"),
            timestamp=_number(item.get("timestamp"), "event timestamp"),
            details=None if details is None else _metadata(_object(details, "event details"), "event details"),
            event_id=event_id, create_time=_number(item.get("create_time", 0), "event create_time"),
        ))
    connections = []
    for raw in _array(data.get("connections", []), "connections", 10000):
        item = _object(raw, "connection")
        metadata = item.get("metadata")
        connections.append(Connection(
            pid_a=_integer(item.get("pid_a"), "pid_a"),
            pid_b=_integer(item.get("pid_b"), "pid_b"),
            kind=_text(item.get("kind"), "kind", nonempty=True),
            metadata=None if metadata is None else _metadata(_object(metadata, "connection metadata"), "connection metadata"),
        ))
    network_flows = []
    for raw in _array(data.get("network_flows", []), "network_flows", MAX_NETWORK_FLOWS):
        item = _object(raw, "network flow")
        remote_address = _short_text(item.get("remote_address", ""), "remote_address")
        network_flows.append(NetworkFlow(
            pid=_integer(item.get("pid"), "network pid"),
            create_time=_number(item.get("create_time"), "network create_time"),
            transport=_short_text(item.get("transport"), "transport"),
            local_address=_short_text(item.get("local_address"), "local_address"),
            local_port=_port(item.get("local_port"), "local_port"),
            remote_address=remote_address,
            remote_port=_port(item.get("remote_port", 0), "remote_port"),
            state=_short_text(item.get("state", ""), "network state"),
        ))
    stats = _object(data.get("event_stats", {}), "event_stats")
    if len(stats) > 32:
        raise ProtocolError("Too many event statistics")
    error = data.get("error")
    activity = network_activity_from_dict(data.get("network_activity"))
    return Snapshot(
        host_id=_identifier(data.get("host_id"), "host_id"),
        hostname=_text(data.get("hostname"), "hostname", nonempty=True),
        boot_id=_identifier(data.get("boot_id"), "boot_id"),
        session_id=_identifier(data.get("session_id"), "session_id"),
        sequence=_integer(data.get("sequence"), "sequence", 1),
        collected_at=_number(data.get("collected_at"), "collected_at"),
        source=_text(data.get("source"), "source", nonempty=True),
        processes=tuple(processes), events=tuple(events), connections=tuple(connections),
        event_stats={_text(k, "statistic"): _integer(v, "statistic") for k, v in stats.items()},
        error=None if error is None else _text(error, "error"),
        network_flows=tuple(network_flows),
        network_activity=activity,
    )


def network_activity_from_dict(raw: Any) -> Optional[NetworkActivity]:
    if raw is None:
        return None
    item = _object(raw, "network_activity")
    status = item.get("status")
    if status not in ("ready", "warming", "unavailable", "ambiguous", "denied", "unsupported", "error"):
        raise ProtocolError("Invalid network activity status")
    if item.get("scope") != "interface" or item.get("source") != "psutil":
        raise ProtocolError("Unsupported network activity scope or source")
    interface = _text(item.get("interface"), "network interface")
    if len(interface) > 128 or (status in ("ready", "warming") and not interface):
        raise ProtocolError("Invalid network interface")
    interval, sent, received = (item.get(k) for k in
                                ("interval_seconds", "sent_bytes", "received_bytes"))
    if status == "ready":
        interval = _number(interval, "network interval")
        if interval <= 0 or (sent is None and received is None):
            raise ProtocolError("Measured activity needs an interval and byte counters")
        sent = None if sent is None else _integer(sent, "sent_bytes")
        received = None if received is None else _integer(received, "received_bytes")
    elif any(v is not None for v in (interval, sent, received)):
        raise ProtocolError("Unmeasured activity cannot contain byte counters")
    return NetworkActivity(status, interface, interval, sent, received)


def decode_json(payload: bytes, *, limit: int = MAX_BODY_BYTES) -> Any:
    if len(payload) > limit:
        raise ProtocolError("JSON body exceeds the size limit")
    try:
        def reject_constant(value):
            raise ProtocolError(f"Non-finite JSON value: {value}")

        return json.loads(payload, parse_constant=reject_constant)
    except (ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise ProtocolError(f"Invalid JSON: {exc}") from exc


def snapshot_from_bytes(payload: bytes) -> Snapshot:
    return snapshot_from_dict(decode_json(payload))
