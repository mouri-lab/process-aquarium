"""Construct the local monitoring backend independently of any presentation."""

from typing import Optional

from .process_manager import ProcessManager
from .sources import EbpfProcessSource, PsutilProcessSource


def create_process_manager(
    source: str,
    *,
    max_processes: int = 2000,
    process_limit: Optional[int] = None,
    sort_by: str = "cpu",
    sort_order: str = "desc",
) -> ProcessManager:
    """Select a local source, preserving the eBPF-to-psutil fallback."""
    if source not in ("psutil", "ebpf"):
        raise ValueError(f"Unknown process source: {source}")

    backend = None
    if source == "ebpf":
        try:
            candidate = EbpfProcessSource(enable=True, hybrid_mode=True)
        except Exception as exc:
            print(f"[eBPF] 初期化失敗: {exc} -> psutil フォールバック")
        else:
            if candidate.available:
                backend = candidate
                print("[eBPF] EbpfProcessSource 有効化（ハイブリッドモード）")
            else:
                try:
                    errors = []
                    for event in candidate.drain_lifecycle_events():
                        details = event.details or {}
                        message = details.get("error") or details.get("warning")
                        if message:
                            errors.append(str(message))
                    reason = f" - reason: {'; '.join(errors)}" if errors else ""
                    print(f"[eBPF] 利用不可のため psutil にフォールバック{reason}")
                finally:
                    candidate.shutdown()

    if backend is None:
        backend = PsutilProcessSource(max_processes=max_processes)
    manager = ProcessManager(max_processes=max_processes, source=backend)
    manager.set_process_limit(process_limit)
    manager.set_sort_config(sort_by, sort_order)
    return manager
