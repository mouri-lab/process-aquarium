"""Presentation/collection boundary, importable without psutil or pygame."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from ..telemetry import Snapshot


@dataclass(frozen=True)
class SourceStatus:
    stale: bool = True
    error: Optional[str] = None


class IProcessSource(ABC):
    name: str

    @abstractmethod
    def update(self) -> None:
        """Start/advance acquisition without blocking the rendering loop."""

    @abstractmethod
    def get_snapshot(self) -> Optional[Snapshot]:
        """Atomic complete sample, or None before the first sample."""

    @property
    @abstractmethod
    def status(self) -> SourceStatus:
        """Stale data differs from an empty process list."""

    @abstractmethod
    def shutdown(self) -> None:
        pass
