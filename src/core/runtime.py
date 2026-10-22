"""Composition helpers. Importing them never loads OS or GUI dependencies."""

from typing import Optional

from ..presentation import ProcessManager


def create_local_source(source: str, *, max_processes=2000, host_id=None, interval=1.0):
    if source not in ("psutil", "ebpf"):
        raise ValueError(f"Unknown process source: {source}")
    try:
        from .sources import EbpfProcessSource, PsutilProcessSource
    except ModuleNotFoundError as exc:
        if exc.name == "psutil":
            raise RuntimeError("Local collection requires 'uv sync --extra agent'") from None
        raise
    options = dict(max_processes=max_processes, host_id=host_id, interval=interval)
    if source == "ebpf":
        try:
            candidate = EbpfProcessSource(enable=True, hybrid_mode=True, **options)
        except Exception as exc:
            print(f"[eBPF] 初期化失敗: {exc} -> psutil フォールバック", flush=True)
        else:
            if candidate.available:
                print("[eBPF] EbpfProcessSource 有効化（ハイブリッドモード）", flush=True)
                return candidate
            reason = candidate.error
            candidate.shutdown()
            print(f"[eBPF] 利用不可のため psutil にフォールバック - reason: {reason}", flush=True)
    return PsutilProcessSource(**options)


def create_process_manager(
    source: str, *, max_processes: int = 2000, process_limit: Optional[int] = None,
    sort_by: str = "cpu", sort_order: str = "desc",
) -> ProcessManager:
    backend = create_local_source(source, max_processes=max_processes)
    return configure_manager(backend, max_processes=max_processes, process_limit=process_limit,
                             sort_by=sort_by, sort_order=sort_order)


def configure_manager(backend, *, max_processes=2000, process_limit=None,
                      sort_by="cpu", sort_order="desc"):
    try:
        manager = ProcessManager(max_processes=max_processes, source=backend)
        manager.set_process_limit(process_limit)
        manager.set_sort_config(sort_by, sort_order)
        return manager
    except BaseException:
        backend.shutdown()
        raise
