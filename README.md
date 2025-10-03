# Process Aquarium

Process Aquarium is an application visualizing processes as fish in an aquarium. Each fish represents a running process on your system.

## 🚀 GPU Acceleration with Pyglet

**Process Aquarium now uses Pyglet for GPU-accelerated rendering!** This provides:

- **Hardware-accelerated graphics** via OpenGL for smooth 60 FPS rendering even with hundreds of processes
- **Better performance** with efficient vertex batching and GPU blending
- **Anti-aliased lines and shapes** for crisp visuals
- **Lower CPU usage** compared to software-rendered Pygame

### Rendering Backend

By default, Process Aquarium uses Pyglet (GPU-accelerated). You can switch backends using the `AQUARIUM_BACKEND` environment variable:

```bash
# Use Pyglet (default, GPU-accelerated) 🚀
python main.py

# Use Pygame (software rendering, fallback)
AQUARIUM_BACKEND=pygame python main.py
```

The Pygame version is preserved for compatibility, but Pyglet is recommended for better performance.

## eBPF Integration (Design Draft)

This branch introduces an abstraction layer to allow future event–driven
monitoring using eBPF instead of (or combined with) psutil polling.

### Current Layers

| Layer | Responsibility |
|-------|----------------|
| `src/core/types.py` | Shared dataclasses (`ProcessInfo`, lifecycle / IPC events) |
| `src/core/sources.py` | `IProcessSource` interface + `PsutilProcessSource` implementation |
| `src/core/process_manager.py` | Backwards compatible wrapper exposing legacy API |
| `src/visuals/*_pyglet.py` | **GPU-accelerated** visualization with Pyglet/OpenGL (default) |
| `src/visuals/*_pygame.py` | Software-rendered visualization with Pygame (fallback) |

### Lifecycle Events
`ProcessLifecycleEvent` normalizes: `spawn`, `fork` (derived), `exec`, `exit`.
The psutil source synthesizes `spawn` & `exec`; `fork` is inferred when a
`spawn` has a known parent already present. An eBPF source will map directly to
`sched_process_fork`, `sched_process_exec`, `sched_process_exit` for near-zero
loss.

### IPC Abstraction
`IPCConnection(kind= ...)` allows heterogeneous comms (tcp, unix, pipe,
parent-child) to be rendered uniformly. The psutil implementation keeps the
existing simplified heuristic; eBPF can add richer socket / pipe attribution.

### Why eBPF?

| Aspect | Polling (psutil) | eBPF (planned) |
|--------|------------------|---------------|
| Fork/Exec latency | Up to poll interval | Near real-time (sub-ms) |
| Short-lived process capture | Often missed | Captured reliably |
| IPC visibility | Limited (loopback & unix aggregate) | Fine grained sockets / pipes / future shared mem |
| Overhead pattern | Periodic full scan O(N) | Event-driven incremental |
| Complexity | Low | Higher (toolchain, kernel features) |

### Hybrid Strategy
1. eBPF emits high fidelity lifecycle + socket events.
2. Lightweight periodic psutil snapshot fills in CPU%, memory%, thread counts.
3. Merge by PID into unified `ProcessInfo` map.

### Next Steps
1. Implement `EbpfProcessSource` skeleton: load BPF programs (fork/exec/exit).
2. Add ring buffer consumer & translation to `ProcessLifecycleEvent`.
3. Hybrid merger (enrich eBPF-only processes with periodic psutil metrics).
4. Extended IPC kinds (pipe, unix, tcp, udp) color-coding in visualization.
5. Optional config toggle: `AQUARIUM_SOURCE=ebpf`.

If you are interested in contributing the eBPF backend, start from
`src/core/sources.py::EbpfProcessSource`.

## Headless Mode

The aquarium can run on servers / CI without a display:

```
python main.py --headless --headless-interval 2.0
```

Environment fallback: when `--headless` is used we set `SDL_VIDEODRIVER=dummy`
and only print periodic aggregate stats (process count, memory %, avg CPU, etc.).
Use cases:
* Remote monitoring via `tmux` / `ssh`
* Data capture pipeline (redirect stdout to log)
* CI regression check for lifecycle event tracking

Optional flags:
* `--width / --height` still accepted (affects internal surfaces only)
* `--headless-interval <seconds>` controls stats print frequency (default 1.0)

## Process Limiting and Sorting

You can limit the number of processes displayed and sort them by various criteria:

### Command-line Options

```bash
# Display top 20 processes by CPU usage
python main.py --limit 20 --sort-by cpu --sort-order desc

# Display top 10 processes by memory usage
python main.py --limit 10 --sort-by memory --sort-order desc

# Display processes sorted by name in ascending order
python main.py --sort-by name --sort-order asc

# Display top 50 processes by PID
python main.py --limit 50 --sort-by pid
```

**Available options:**
* `--limit N` - Limit the number of processes displayed (default: no limit)
* `--sort-by {cpu,memory,name,pid}` - Sort processes by field (default: cpu)
* `--sort-order {asc,desc}` - Sort order ascending or descending (default: desc)

### Runtime Keyboard Controls

When running in GUI mode, you can dynamically change the display settings:

* **L** - Cycle through process limits (None → 10 → 20 → 50 → 100 → 200 → None)
* **S** - Cycle through sort fields (CPU → Memory → Name → PID → CPU)
* **O** - Toggle sort order (ascending ↔ descending)

The current limit and sort settings are displayed in the statistics panel in the upper left corner.

### Use Cases

* **Performance monitoring**: Display only the top N CPU or memory consumers
* **Debugging**: Focus on specific processes by limiting the display
* **Large systems**: Reduce visual clutter by showing only relevant processes

## eBPF Source (Experimental)

You can switch the backend from psutil polling to an experimental eBPF based
event stream (Linux only):

```
pip install bcc   # if not installed; requires kernel headers & privileges
sudo python main.py --source ebpf
```

Or via environment variable:

```
export AQUARIUM_SOURCE=ebpf
python main.py
```

If eBPF initialization fails (missing bcc, insufficient privileges, unsupported
kernel) the application automatically falls back to the psutil source and logs
a warning.

Currently captured via eBPF (MVP):
* fork (as spawn + inferred fork relation)
* exec
* exit

Planned additions:
* Socket connect / accept
* Unix / pipe IPC mapping
* Hybrid enrichment: psutil metrics fused with eBPF lifecycle precision

Security / Permissions:
* Running under root or with CAP_BPF/CAP_SYS_ADMIN may be required depending on distro
* For production, consider a minimal privileged sidecar emitting events over a UNIX socket

Fallback Behavior:
* Any failure during BPF load → logged lifecycle event (pid=0) + revert to psutil
* Headless mode works the same: `--headless --source ebpf`