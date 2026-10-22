"""Text-only monitoring; deliberately has no dependency on the visual layer."""

import math
import time

from .presentation import ProcessManager


class HeadlessMonitor:
    """Print periodic statistics from an externally owned process manager."""

    def __init__(self, process_manager: ProcessManager, interval: float = 1.0):
        if not math.isfinite(interval) or interval <= 0:
            raise ValueError("Headless interval must be a finite positive number")
        self.process_manager = process_manager
        self.interval = interval
        self.running = True

    def run(self) -> None:
        print("[Headless] Running in headless mode. Only statistics will be printed. Press Ctrl+C to exit.")
        try:
            while self.running:
                start = time.monotonic()
                self.process_manager.update()
                stats = self.process_manager.get_process_statistics()
                data_source = stats.get("data_source", "unknown")
                message = (
                    f"[stats|{data_source}] procs={stats['total_processes']} "
                    f"new={stats['new_processes']} dying={stats['dying_processes']} "
                    f"mem={stats['total_memory_percent']:.2f}% "
                    f"cpu_avg={stats['average_cpu_percent']:.2f}% "
                    f"threads={stats['total_threads']}"
                )
                if "ebpf_events" in stats:
                    message += f" events=[{stats['ebpf_events']}]"
                if stats.get("host_id"):
                    message += f" host={stats['host_id']}"
                if stats.get("stale"):
                    message += " [STALE]"
                if stats.get("error"):
                    message += f" error={stats['error']}"
                print(message, flush=True)
                remaining = self.interval - (time.monotonic() - start)
                if self.running and remaining > 0:
                    time.sleep(remaining)
        except KeyboardInterrupt:
            print("[Headless] 中断されました。終了します。")
