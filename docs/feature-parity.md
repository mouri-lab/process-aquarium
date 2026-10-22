# Native → browser feature audit

Reference: `src/visuals/fish.py`, `src/visuals/aquarium.py`, and the original
collector in commit `3e98f97`. The distributed transport is retained. Visual
state and camera state belong exclusively to each client.

| Native behavior | Browser implementation / verification |
| --- | --- |
| Seven process-name silhouettes; HSV name colors | Shared Canvas/WebGPU geometry; native differential tests |
| Exponential memory size, CPU brightness/speed/swimming | Native formula comparison, including multicore CPU saturation |
| Spawn growth, exit shrink/fade, parent fork flash, exec rainbow | Fixed 30 Hz lifecycle simulation and replay tests |
| Giant pulsation, three memory rings, lightning at 20% | Renderer geometry and comparison scene |
| Up to 14 orbiting thread fish; logarithmic orbit radius | Native satellite-coordinate comparison |
| Family/sibling schools, name schools, isolates, leaders | Native graph traversal, boids and highlight tests |
| Separation/alignment/cohesion, energy avoidance, random targets/orbits, boundaries | Deterministic movement and force comparisons |
| IPC attraction, conversations, clickable partner bubbles, communication schools | Snapshot-driven connections and bounded 60-second history |
| Global parent-child debug lines and animated IPC curves | Independent D / I toggles and comparison scene |
| Selection, process details, age, statistics, event counters, source | Browser controls and live telemetry verification |
| Automatic centroid, selected follow, right-click follow, manual pan, zoom/reset | C/R, pointer interactions and camera tests |
| D/I/T/Q/F/F11/L/S/O shortcuts, full/compact/hidden UI | Keyboard and visible controls; browser interaction verification |
| Process limits, four sort fields/directions, dynamic world bounds | Same native presets and size formula; view-only reconciliation |
| Full/reduced/minimal quality, optional FPS adaptation, particles, high DPI | Explicit quality control and adaptive policy |
| Loopback TCP, Unix sockets, shared pipe/socket descriptors, parent-child fallback | Agent-side IPC collection tests; no OS inspection on remote clients |
| Fullscreen, resize, Japanese text | Browser fullscreen/resize and Japanese UI/help |

The old shared-memory detector is a placeholder returning an empty list; it is
not an implemented native feature. Browser Escape clears selection/exits
fullscreen rather than terminating the server. GPU backend selection is replaced
by WebGPU with the same geometry in the Canvas fallback. Process sampling and
event replay remain independent of rendering, including while paused/offline.

Completion evidence and commands are recorded below after verification.
