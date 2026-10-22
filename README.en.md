# 🐠 Process Aquarium

English | [日本語 README](./README.md)

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Linux-lightgrey.svg)

Visualize your running processes as a living aquarium of fish. Each fish represents one process; size, glow, satellites, and subtle effects encode runtime metrics so you can spot anomalies at a glance.

## Features

**Visualization Overview**
- Each process is rendered as a "fish" with deterministic color/shape derived from its name
- Memory usage → fish size (log compression + relative share scaling)
- CPU usage → glow (emissive intensity) and max movement speed (color itself mostly stable)
- Thread count → orbiting satellites (up to 14) around the fish
- Spawn / exit → fade‑in and fade‑out animations

**Monitoring**
- Data source selectable: eBPF or psutil (`--source`)
- Periodic refresh of CPU / memory / thread stats
- Internally abstracted layer for future data source extensions

**Runtime Options**
- Change sort key (CPU / memory / name / PID)
- Limit number of displayed processes
- Headless mode (periodic textual statistics only)

## Quick Start

### 1. Requirements
- Python 3.10+
- Linux (to leverage eBPF fully)

### 2. Installation
```bash
# System dependencies (Ubuntu/Debian)
sudo apt install -y python3-bpfcc linux-headers-$(uname -r) \
    libbpf-dev clang llvm make gcc python3-venv

# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone repository
git clone https://github.com/mouri-lab/process-aquarium.git
cd process-aquarium
git switch main

# Create virtualenv (reuse system bpf packages)
uv venv -p /usr/bin/python3 --system-site-packages

# Install dependencies including the GUI extra
uv sync --extra gui
```

### 3. Run
```bash
# eBPF (recommended, requires root)
sudo ./.venv/bin/python3 main.py --source ebpf

# psutil (no root required)
./.venv/bin/python3 main.py --source psutil
```

### Run without GUI dependencies

Collection and statistics logging do not require pygame or SDL. For a server installation:

```bash
uv sync --no-dev
./.venv/bin/python3 main.py --source psutil --headless --headless-interval 2.0
```

eBPF still requires the system dependencies above and root privileges.
Monitoring currently targets the local host only; network transport, aggregation, and video streaming are not implemented yet.

⚠️ Notes
- eBPF mode: root (`sudo`) required for kernel‑level access
- Using `--system-site-packages` lets you reuse preinstalled bpf tooling
- Python version mismatch can cause eBPF load failures

A window opens and active processes appear as fish.

## Usage

### Basic Interaction
- Mouse move: perceive camera reference
- Left click: select fish & show detail panel
- Right click: set follow target
- Left drag: pan camera (cancels follow)
- Mouse wheel: zoom (0.1x–5x)
- F / F11: toggle fullscreen
- Esc: quit

### Key Map
| Key        | Action                      | Note                                   |
| ---------- | --------------------------- | -------------------------------------- |
| Esc        | Quit                        | Immediate exit                         |
| F / F11    | Toggle fullscreen           | Works windowed or fullscreen           |
| D          | Toggle debug overlay        | Parent/child link hints & internals    |
| I          | Toggle IPC visualization    | IPC lines / bubbles                    |
| T          | Toggle UI panels            | Hide/show help & info                  |
| Q          | Highlight schools           | Dim isolates                           |
| L          | Cycle process count limit   | Rotates preset caps                    |
| S          | Cycle sort field            | CPU→MEM→NAME→PID                       |
| O          | Toggle sort order           | Asc / desc                             |
| C          | Cycle camera mode           | Auto / follow / manual                 |
| R          | Reset camera                | Position / zoom / follow off           |
| Left click | Select fish                 | Updates detail panel                   |
| Right click| Set follow target           | Reclick to change                      |
| Wheel      | Zoom                        | Pivot around pointer                   |
| Drag (LMB) | Pan                         | Cancels follow                         |

### Visual Semantics
**Color / Shape**
- Initial color: hash of process name
- Shape: minor variation by simple name heuristics (e.g., system vs browser naming patterns)

**Size / Glow / Speed**
- Size: mapped from memory usage (log-compressed + relative weighting)
- Glow strength: exponential mapping of CPU usage (higher → brighter)
- Max speed: scaled exponentially by CPU usage

**Thread Satellites**
- Up to 14 orbiting dots indicating thread count distribution

**Special Effects**
- High memory (above threshold): gentle concentric ripple rings pulsing around the fish
- Extremely high memory (higher threshold): occasional brief lightning‑like streaks signaling dominance
- Purpose: let you visually detect outlier memory consumers within seconds without reading numbers

**Schools (Flocking)**
- Goal: visually cluster related processes for contextual grouping
- Behavior: separation / alignment / cohesion produce natural schooling motion
- Highlight (Q): dims outsiders to focus on clustered group(s)
- Typical uses: monitoring many workers, spotting bursty short‑lived spawners, observing restart reshaping
- Limits: does not geometrically encode parent-child or IPC topology directly
- Suggested workflow: Q → L → S/O → click for details

**Lifecycle**
- Birth: spawn animation (fade / scale‑in)
- Termination: fade‑out (marked internally as dying)
- fork/exec: transient glow or regenerated color accent

## Command Line Examples
```bash
# Set window size
sudo ./.venv/bin/python3 main.py --source ebpf --width 1600 --height 1000

# Limit displayed processes
sudo ./.venv/bin/python3 main.py --source ebpf --limit 50

# Sort by CPU ascending
sudo ./.venv/bin/python3 main.py --source ebpf --sort-by cpu --sort-order asc

# Sort by memory
ysudo ./.venv/bin/python3 main.py --source ebpf --sort-by memory

# Headless (no GUI) with 2s interval
sudo ./.venv/bin/python3 main.py --source ebpf --headless --headless-interval 2.0

# psutil mode (no root)
./.venv/bin/python3 main.py --source psutil --limit 50
```

### Options
| Option | Description | Default |
| ------ | ----------- | ------- |
| `--width` | Window width | 1200 |
| `--height` | Window height | 800 |
| `--limit` | Max displayed processes | Unlimited |
| `--sort-by` | Sort key (`cpu`, `memory`, `name`, `pid`) | `cpu` |
| `--sort-order` | Sort order (`asc`, `desc`) | `desc` |
| `--source` | Data source (`psutil`, `ebpf`) | `ebpf` |
| `--headless` | Headless mode | false |
| `--headless-interval` | Interval seconds (headless) | 1.0 |

## For Developers

### Project Layout
```
process-aquarium/
├── main.py                # Entry point
├── pyproject.toml         # Project config
├── src/
│   ├── headless.py             # Statistics logging without GUI imports
│   ├── core/
│   │   ├── runtime.py          # Backend construction and fallback
│   │   ├── process_manager.py  # Process management
│   │   ├── sources.py          # Data source abstraction
│   │   └── types.py            # Type definitions
│   └── visuals/
│       ├── aquarium.py         # Aquarium visualization controller
│       └── fish.py             # Fish rendering & animation
├── fork_bomb.py          # Stress test process spawner
└── README.md             # Japanese README
```

`main.py` constructs the collection backend and passes the same `ProcessManager` interface to either `Aquarium` or `HeadlessMonitor`.
`Aquarium` does not select or initialize data sources. The entry point owns the backend and shuts it down on normal exit, interruption, or failure.
Process types and display selection retain their existing structure for a subsequent separation step.

```bash
# Run regression tests without installing the GUI extra
uv sync
uv run python -m pytest -q
```

### Stress Tool
Use `fork_bomb.py` to spawn many processes (for visualization testing):
```bash
# Spawn 30 children (safe range)
python fork_bomb.py --max-children 30

# Recursive spawning (each child spawns more)
python fork_bomb.py --recursive --max-children 20

# Auto-stop after duration
python fork_bomb.py --duration 60
```
⚠️ Caution: High load (CPU/memory/thread count). Do NOT use in production systems.

### Dependencies
- numpy (≥2.2.6)
- psutil (≥7.1.0)
- pygame-ce (≥2.5.2), optional GUI dependency (`--extra gui`)
- pytest (≥8.4.2), development dependency (omit with `--no-dev`)

### Environment Variables
```bash
export AQUARIUM_SOURCE="ebpf"
export AQUARIUM_LIMIT="100"
export AQUARIUM_SORT_BY="memory"
export AQUARIUM_SORT_ORDER="desc"
```

## Contributing
1. Fork repository
2. Create branch (`git checkout -b feature/amazing-feature`)
3. Commit changes (`git commit -m 'Add some amazing feature'`)
4. Push branch (`git push origin feature/amazing-feature`)
5. Open a PR (target `dev` branch)

## License
MIT License. See [LICENSE](LICENSE).

## Support
- Bug reports: GitHub Issues
- Feature requests: GitHub Discussions
- Questions: Issue or Discussion

---
"Watch your system's processes swim gracefully inside a living, data‑driven aquarium." 🐠✨
