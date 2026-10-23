"""Compatibility names for the presentation-independent telemetry records."""

from ..telemetry import Connection as IPCConnection
from ..telemetry import NetworkFlow as NetworkStream
from ..telemetry import LifecycleEvent as ProcessLifecycleEvent
from ..telemetry import ProcessRecord as ProcessInfo

__all__ = ["ProcessInfo", "ProcessLifecycleEvent", "IPCConnection", "NetworkStream"]
