// Pure client model: no DOM or GPU dependency. Complete host state precedes
// display selection; network failures never enter the reconciliation path.
export const MAX_VISIBLE = 10000;
export const keyOf = (snapshot, p) =>
  JSON.stringify([snapshot.host_id, snapshot.boot_id, p.pid, p.create_time]);
export function hash(text) {
  let value = 2166136261;
  for (const char of String(text))
    value = Math.imul(value ^ char.charCodeAt(0), 16777619);
  return value >>> 0;
}
export function colorOf(name) {
  const palette = [
    [0.22, 0.88, 0.77],
    [0.96, 0.63, 0.37],
    [0.42, 0.72, 0.98],
    [0.96, 0.49, 0.56],
    [0.69, 0.62, 0.96],
    [0.87, 0.83, 0.47],
  ];
  return palette[hash(name) % palette.length];
}
export function selectedProcesses(
  snapshot,
  { sort = "cpu", order = "desc", limit = 300, search = "" } = {},
) {
  const field =
    { cpu: "cpu_percent", memory: "memory_percent", name: "name", pid: "pid" }[
      sort
    ] || "cpu_percent";
  const query = search.toLowerCase().trim();
  const processes = snapshot.processes.filter(
    (p) =>
      !query ||
      p.name.toLowerCase().includes(query) ||
      String(p.pid).includes(query),
  );
  processes.sort((a, b) => {
    const left = a[field],
      right = b[field];
    const comparison =
      typeof left === "string"
        ? left.toLowerCase().localeCompare(right.toLowerCase())
        : left - right;
    return (comparison || a.pid - b.pid) * (order === "asc" ? 1 : -1);
  });
  return processes.slice(
    0,
    Math.min(limit > 0 ? limit : MAX_VISIBLE, MAX_VISIBLE),
  );
}

export function validateSnapshot(snapshot) {
  if (
    !snapshot ||
    snapshot.schema_version !== 1 ||
    !Array.isArray(snapshot.processes) ||
    snapshot.processes.length > 50000 ||
    !Number.isSafeInteger(snapshot.sequence) ||
    snapshot.sequence < 1 ||
    !["host_id", "boot_id", "session_id", "source"].every(
      (k) => typeof snapshot[k] === "string" && snapshot[k],
    )
  ) {
    throw new Error("Unsupported or incomplete telemetry snapshot");
  }
  const seen = new Set();
  for (const p of snapshot.processes) {
    if (
      !Number.isSafeInteger(p.pid) ||
      p.pid < 0 ||
      seen.has(p.pid) ||
      typeof p.name !== "string" ||
      ![
        "ppid",
        "memory_percent",
        "cpu_percent",
        "num_threads",
        "create_time",
      ].every((k) => Number.isFinite(p[k]) && p[k] >= 0) ||
      !Array.isArray(p.cmdline) ||
      !p.cmdline.every((arg) => typeof arg === "string")
    ) {
      throw new Error("Invalid process telemetry");
    }
    seen.add(p.pid);
  }
  let cursor = 0;
  if (!Array.isArray(snapshot.events) || snapshot.events.length > 2048)
    throw new Error("Invalid event history");
  for (const event of snapshot.events) {
    if (
      !Number.isSafeInteger(event.event_id) ||
      event.event_id <= cursor ||
      !["spawn", "fork", "exec", "exit"].includes(event.event_type)
    )
      throw new Error("Invalid lifecycle event");
    cursor = event.event_id;
  }
  return snapshot;
}

export class AquariumWorld {
  constructor() {
    this.snapshot = null;
    this.fish = new Map();
    this.processes = new Map();
    this.selection = null;
    this.filters = { sort: "cpu", order: "desc", limit: 300, search: "" };
    this.time = 0;
    this.eventSession = null;
    this.eventCursor = 0;
    this.eventsLost = 0;
    this.extent = 900;
  }
  clear() {
    this.snapshot = null;
    this.fish.clear();
    this.processes.clear();
    this.selection = null;
    this.eventSession = null;
    this.eventCursor = 0;
    this.eventsLost = 0;
  }
  apply(raw) {
    const snapshot = validateSnapshot(raw);
    if (snapshot.error) return false;
    const previous = this.snapshot;
    if (
      previous?.host_id === snapshot.host_id &&
      previous?.session_id === snapshot.session_id
    ) {
      if (snapshot.sequence < previous.sequence)
        throw new Error("Server returned an older snapshot");
      if (snapshot.sequence === previous.sequence) return false;
    }
    if (
      previous &&
      (previous.host_id !== snapshot.host_id ||
        previous.boot_id !== snapshot.boot_id)
    )
      this.clear();
    const old = this.processes;
    this.snapshot = snapshot;
    this.processes = new Map(
      snapshot.processes.map((p) => [keyOf(snapshot, p), p]),
    );
    if (this.selection && !this.processes.has(this.selection))
      this.selection = null;
    this.extent = Math.max(
      900,
      Math.sqrt(Math.min(snapshot.processes.length, MAX_VISIBLE)) * 65,
    );
    this.reconcileView(old);
    const session = JSON.stringify([snapshot.host_id, snapshot.session_id]);
    if (session !== this.eventSession) {
      this.eventSession = session;
      this.eventCursor = 0;
    }
    if (
      this.eventCursor &&
      snapshot.events[0]?.event_id > this.eventCursor + 1
    ) {
      this.eventsLost += snapshot.events[0].event_id - this.eventCursor - 1;
    }
    const byPid = new Map(
      [...this.fish.values()].filter((f) => !f.dying).map((f) => [f.p.pid, f]),
    );
    for (const event of snapshot.events) {
      if (event.event_id <= this.eventCursor) continue;
      const fish = byPid.get(event.pid);
      if (
        fish &&
        (!event.create_time || event.create_time === fish.p.create_time)
      ) {
        if (event.event_type === "exec") fish.flash = 1;
        if (event.event_type === "fork" || event.event_type === "spawn") {
          const parent = byPid.get(event.ppid);
          if (parent) parent.flash = 0.6;
        }
      }
      this.eventCursor = event.event_id;
    }
    return true;
  }
  setFilters(patch) {
    Object.assign(this.filters, patch);
    if (this.snapshot) this.reconcileView(this.processes);
  }
  reconcileView(previous) {
    const visible = new Map(
      selectedProcesses(this.snapshot, this.filters).map((p) => [
        keyOf(this.snapshot, p),
        p,
      ]),
    );
    for (const [key, fish] of this.fish) {
      if (!this.processes.has(key)) fish.dying = true;
      else if (!visible.has(key)) this.fish.delete(key); // Hidden != dead.
    }
    // Bound exit animations as well as live instances, including rapid churn.
    let dying = [...this.fish.values()].filter((f) => f.dying);
    for (const fish of dying.slice(0, Math.max(0, dying.length - 1000)))
      this.fish.delete(fish.key);
    for (const [key, p] of visible) {
      let fish = this.fish.get(key);
      if (!fish) {
        const seed = hash(key),
          angle = (seed / 2 ** 32) * Math.PI * 2;
        const radius =
          ((0.12 + (hash(key + "r") % 1000) / 1400) * this.extent) / 2;
        fish = {
          key,
          p,
          x: Math.cos(angle) * radius * 1.4,
          y: Math.sin(angle) * radius,
          angle,
          phase: seed % 100,
          alpha: previous.has(key) ? 1 : 0,
          flash: 0,
          dying: false,
          color: colorOf(p.name),
        };
        this.fish.set(key, fish);
      }
      fish.p = p;
      fish.color = colorOf(p.name);
      fish.dying = false;
      fish.size = 10 + Math.min(35, Math.log1p(p.memory_percent * 5) * 8);
    }
  }
  step(seconds) {
    const dt = Math.max(0, Math.min(seconds, 0.05));
    this.time += dt;
    const grid = new Map(),
      cell = 70;
    for (const fish of this.fish.values()) {
      if (fish.dying) continue;
      const key = `${Math.floor(fish.x / cell)},${Math.floor(fish.y / cell)}`;
      const bucket = grid.get(key) || [];
      if (bucket.length < 12) bucket.push(fish);
      grid.set(key, bucket);
    }
    for (const [key, fish] of this.fish) {
      fish.flash = Math.max(0, fish.flash - dt);
      fish.alpha = Math.min(1, fish.alpha + (fish.dying ? -1.5 : 1.5) * dt);
      if (fish.alpha <= 0 && fish.dying) {
        this.fish.delete(key);
        continue;
      }
      if (fish.dying) continue;
      const group = hash(
        fish.p.ppid > 1 ? `parent:${fish.p.ppid}` : fish.p.name,
      );
      const groupAngle = (group / 2 ** 32) * Math.PI * 2;
      const cx = Math.cos(groupAngle) * this.extent * 0.25;
      const cy = Math.sin(groupAngle) * this.extent * 0.17;
      const speed = 16 + Math.min(fish.p.cpu_percent, 200) * 0.38;
      let dx = Math.cos(fish.angle) * speed + (cx - fish.x) * 0.08;
      let dy =
        Math.sin(fish.angle) * speed +
        (cy - fish.y) * 0.08 +
        Math.sin(this.time * 0.8 + fish.phase) * 7;
      const gx = Math.floor(fish.x / cell),
        gy = Math.floor(fish.y / cell);
      for (let x = -1; x <= 1; x++)
        for (let y = -1; y <= 1; y++) {
          for (const other of grid.get(`${gx + x},${gy + y}`) || []) {
            if (other === fish) continue;
            const xx = fish.x - other.x,
              yy = fish.y - other.y,
              distance = xx * xx + yy * yy;
            if (distance > 0 && distance < 1600) {
              dx += (xx / distance) * 90;
              dy += (yy / distance) * 90;
            }
          }
        }
      const target = Math.atan2(dy, dx),
        difference = Math.atan2(
          Math.sin(target - fish.angle),
          Math.cos(target - fish.angle),
        );
      fish.angle += difference * Math.min(1, dt * 2);
      fish.x += dx * dt;
      fish.y += dy * dt;
    }
  }
  pick(x, y, radius = 30) {
    let best = null,
      distance = Infinity;
    for (const fish of this.fish.values()) {
      if (fish.dying) continue;
      const d = (fish.x - x) ** 2 + (fish.y - y) ** 2;
      if (d < Math.max(radius, fish.size) ** 2 && d < distance) {
        best = fish.key;
        distance = d;
      }
    }
    this.selection = best;
    return best;
  }
  selected() {
    return this.selection ? this.fish.get(this.selection) : null;
  }
}
