import { AquariumWorld, colorOf, keyOf, selectedProcesses } from "./world.mjs";
import { CanvasRenderer, createRenderer, freshCanvas } from "./renderer.mjs";

const $ = (id) => document.getElementById(id);
const world = new AquariumWorld();
const stage = $("stage"),
  overlay = $("overlay"),
  overlayContext = overlay.getContext("2d");
const camera = { x: 0, y: 0, zoom: 0.9 };
const parameters = new URLSearchParams(location.search);
let token = "",
  hostId = parameters.get("host") || "",
  renderer;
try {
  token = sessionStorage.getItem("aquarium-token") || "";
  hostId ||= sessionStorage.getItem("aquarium-host") || "";
} catch {}
let paused = matchMedia("(prefers-reduced-motion: reduce)").matches;
let following = false,
  pending = false,
  generation = 0,
  controller,
  stopped = false;
let freshness = { last: 0, mode: "waiting", error: "" };
let timer,
  lastFrame = performance.now(),
  fps = 60,
  lastMetrics = 0;
const number = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });
const percent = (value) => `${number.format(value)}%`;
const rgb = (color) =>
  `rgb(${color.map((c) => Math.round(c * 255)).join(",")})`;
const setText = (id, value) => {
  $(id).textContent = value;
};

function showAuth(message = "") {
  setText("auth-error", message);
  if (!$("auth-dialog").open) $("auth-dialog").showModal();
}
function setStatus(mode, error = "") {
  freshness.mode = mode;
  freshness.error = error;
  const status = $("status");
  status.className = `status ${mode === "live" ? "" : mode === "offline" ? "offline" : "waiting"}`;
  status.textContent = {
    live: "Live",
    stale: "Stale · last known state",
    offline: "Offline · last known state",
    waiting: "Waiting for an agent",
    auth: "Access required",
  }[mode];
  stage.dataset.stale = String(mode !== "live");
  updateNotice();
}
function updateNotice() {
  let message = "";
  if (freshness.mode === "offline" || freshness.mode === "stale")
    message =
      freshness.error ||
      "Telemetry is stale. Showing the last known state; no process exits are inferred.";
  else if (world.eventsLost)
    message = `${number.format(world.eventsLost)} lifecycle events fell outside the replay window. Current process state is synchronized.`;
  else if (
    world.snapshot?.processes.length > 10000 &&
    world.filters.limit === 0
  )
    message =
      "Showing up to 10,000 fish. All process metrics remain available in the API.";
  $("notice").hidden = !message;
  setText("notice", message);
}
async function request(path, signal) {
  const headers = { Accept: "application/json" };
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(new URL(path, document.baseURI), {
    headers,
    signal,
    cache: "no-store",
  });
  if (response.status === 401) {
    const error = new Error("A valid server token is required.");
    error.authentication = true;
    throw error;
  }
  const text = await response.text();
  if (text.length > 17 * 1024 * 1024)
    throw new Error("Telemetry response is too large");
  let data;
  try {
    data = JSON.parse(text);
  } catch {
    throw new Error("Server returned invalid JSON");
  }
  if (!response.ok)
    throw new Error(data.error || `Server returned HTTP ${response.status}`);
  return data;
}
function populateHosts(hosts) {
  if (!Array.isArray(hosts)) throw new Error("Invalid host list");
  const select = $("host");
  const choices = hosts.map(
    (host) =>
      new Option(
        `${host.hostname} · ${host.host_id}${host.stale ? " · stale" : ""}`,
        host.host_id,
      ),
  );
  if (hostId && !hosts.some((host) => host.host_id === hostId))
    choices.push(new Option(`${hostId} · awaiting agent`, hostId));
  if (!choices.length) choices.push(new Option("Waiting for an agent…", ""));
  select.replaceChildren(...choices);
  if (!hostId && hosts.length) hostId = hosts[0].host_id;
  select.value = hostId;
  select.title = select.selectedOptions[0]?.textContent || "";
}
async function poll() {
  if (pending || stopped || $("auth-dialog").open || freshness.mode === "auth")
    return;
  pending = true;
  const version = generation;
  controller = new AbortController();
  const timeout = setTimeout(() => controller?.abort(), 5000);
  try {
    const hosts = await request("api/v1/hosts", controller.signal);
    if (version !== generation) return;
    populateHosts(hosts.hosts);
    if (!hostId) {
      setStatus("waiting");
      updateEmpty();
      return;
    }
    const selected = hostId;
    const envelope = await request(
      `api/v1/snapshot?host=${encodeURIComponent(selected)}`,
      controller.signal,
    );
    if (version !== generation || selected !== hostId) return;
    if (
      envelope.snapshot?.host_id !== selected ||
      typeof envelope.stale !== "boolean"
    )
      throw new Error("Unexpected telemetry host or freshness status");
    const changed = world.apply(envelope.snapshot);
    if (changed) freshness.last = performance.now();
    setStatus(envelope.stale ? "stale" : "live", envelope.error || "");
    updateMetrics();
    updateEmpty();
  } catch (error) {
    if (version !== generation) return;
    if (error.authentication) {
      setStatus("auth");
      showAuth(error.message);
    } else
      setStatus(
        "offline",
        error.name === "AbortError"
          ? "Connection timed out. Showing the last known state."
          : error.message,
      );
    updateEmpty();
  } finally {
    clearTimeout(timeout);
    pending = false;
    clearTimeout(timer);
    if (!stopped) timer = setTimeout(poll, document.hidden ? 2000 : 1000);
  }
}
function reconnect({ clear = false } = {}) {
  generation++;
  controller?.abort();
  clearTimeout(timer);
  if (clear) {
    world.clear();
    following = false;
    freshness.last = 0;
    camera.x = camera.y = 0;
  }
  setStatus("waiting");
  updateEmpty();
  updateMetrics();
  // A superseded request finishes before scheduling the next poll.
  if (!pending) poll();
}
function updateEmpty() {
  const noData = !world.snapshot;
  const noMatches =
    world.snapshot && ![...world.fish.values()].some((f) => !f.dying);
  $("empty").hidden = !(noData || noMatches);
  $("agent-command").hidden =
    Boolean(world.snapshot) || freshness.mode === "auth";
  if (world.snapshot) {
    setText(
      "empty-message",
      world.snapshot.processes.length
        ? "No processes match this view. Try a different filter."
        : "This host currently reports no processes.",
    );
  } else {
    setText(
      "empty-message",
      freshness.mode === "auth"
        ? "Use Access to connect with your server token."
        : "Connect an agent to bring this aquarium to life.",
    );
  }
  setText(
    "agent-command",
    `python main.py agent --server ${new URL(".", location.href).href.replace(/\/$/, "")}`,
  );
}
function updateMetrics() {
  const snapshot = world.snapshot;
  if (!snapshot) {
    for (const id of [
      "metric-processes",
      "metric-cpu",
      "metric-memory",
      "metric-threads",
    ])
      setText(id, "—");
    setText("visible-count", "waiting for telemetry");
    $("process-list").replaceChildren(
      Object.assign(document.createElement("p"), {
        className: "muted",
        textContent: "Processes will appear here.",
      }),
    );
    updateDetails();
    return;
  }
  const processes = snapshot.processes;
  setText("metric-processes", number.format(processes.length));
  setText(
    "metric-cpu",
    percent(processes.reduce((sum, p) => sum + p.cpu_percent, 0)),
  );
  setText(
    "metric-memory",
    percent(processes.reduce((sum, p) => sum + p.memory_percent, 0)),
  );
  setText(
    "metric-threads",
    number.format(processes.reduce((sum, p) => sum + p.num_threads, 0)),
  );
  const visible = selectedProcesses(snapshot, world.filters);
  setText("visible-count", `${number.format(visible.length)} fish in view`);
  stage.dataset.fishCount = String(visible.length);
  setText("source-label", `${snapshot.source} / ${snapshot.hostname}`);
  const labels = { cpu: "CPU", memory: "MEMORY", name: "NAME", pid: "PID" };
  setText(
    "list-label",
    `${labels[world.filters.sort]} · ${world.filters.order.toUpperCase()}`,
  );
  const rows = visible.slice(0, 10).map((process) => {
    const key = keyOf(snapshot, process),
      button = document.createElement("button");
    button.className = `process-row${key === world.selection ? " active" : ""}`;
    const dot = Object.assign(document.createElement("span"), {
      className: "color-dot",
    });
    dot.style.background = rgb(colorOf(process.name));
    const name = Object.assign(document.createElement("span"), {
      className: "process-name",
      textContent: process.name,
    });
    const pid = Object.assign(document.createElement("span"), {
      className: "process-pid",
      textContent: process.pid,
    });
    const metric =
      world.filters.sort === "memory"
        ? percent(process.memory_percent)
        : percent(process.cpu_percent);
    const value = Object.assign(document.createElement("span"), {
      className: "process-value",
      textContent: metric,
    });
    button.append(dot, name, pid, value);
    button.addEventListener("click", () => {
      world.selection = key;
      const fish = world.selected();
      if (fish) {
        camera.x = fish.x;
        camera.y = fish.y;
      }
      updateMetrics();
    });
    return button;
  });
  $("process-list").replaceChildren(...rows);
  updateDetails();
  updateNotice();
}
function updateDetails() {
  const fish = world.selected();
  $("details").hidden = !fish;
  $("inspect-empty").hidden = Boolean(fish);
  $("clear-selection").hidden = !fish;
  $("follow").disabled = !fish;
  if (!fish) following = false;
  $("follow").setAttribute("aria-pressed", String(following));
  if (!fish) return;
  const p = fish.p;
  setText("detail-name", p.name);
  setText("detail-status", p.status || "unknown");
  $("detail-dot").style.background = rgb(fish.color);
  setText("detail-pid", p.pid);
  setText("detail-ppid", p.ppid);
  setText("detail-cpu", percent(p.cpu_percent));
  setText("detail-memory", percent(p.memory_percent));
  setText("detail-threads", p.num_threads);
  setText(
    "detail-started",
    p.create_time
      ? new Date(p.create_time * 1000).toLocaleTimeString([], {
          hour: "2-digit",
          minute: "2-digit",
        })
      : "Unknown",
  );
  setText("detail-command", p.cmdline?.join(" ") || p.exe || p.name);
}
function applyFilters() {
  world.setFilters({
    search: $("search").value,
    sort: $("sort").value,
    limit: Number($("limit").value),
  });
  updateMetrics();
  updateEmpty();
}
$("search").addEventListener("input", applyFilters);
for (const id of ["sort", "limit"])
  $(id).addEventListener("change", applyFilters);
$("order").addEventListener("click", () => {
  world.setFilters({ order: world.filters.order === "desc" ? "asc" : "desc" });
  setText("order", world.filters.order === "desc" ? "↓" : "↑");
  updateMetrics();
});
$("host").addEventListener("change", () => {
  hostId = $("host").value;
  try {
    sessionStorage.setItem("aquarium-host", hostId);
  } catch {}
  reconnect({ clear: true });
});
$("auth-button").addEventListener("click", () => showAuth());
$("auth-form").addEventListener("submit", (event) => {
  event.preventDefault();
  token = $("token").value.trim();
  $("token").value = "";
  try {
    sessionStorage.setItem("aquarium-token", token);
  } catch {}
  $("auth-dialog").close();
  reconnect();
});
$("cancel-auth").addEventListener("click", () => {
  $("auth-dialog").close();
  poll();
});
$("forget-token").addEventListener("click", () => {
  token = "";
  $("token").value = "";
  try {
    sessionStorage.removeItem("aquarium-token");
  } catch {}
  $("auth-dialog").close();
  reconnect({ clear: true });
});
function togglePause() {
  paused = !paused;
  setText("pause", paused ? "▶" : "Ⅱ");
  $("pause").setAttribute(
    "aria-label",
    paused ? "Resume movement" : "Pause movement",
  );
  $("pause").setAttribute("aria-pressed", String(paused));
}
$("pause").addEventListener("click", togglePause);
if (paused) {
  paused = false;
  togglePause();
}
function resetCamera() {
  camera.x = camera.y = 0;
  camera.zoom = 0.9;
  following = false;
  updateDetails();
}
$("reset").addEventListener("click", resetCamera);
$("follow").addEventListener("click", () => {
  following = !following;
  updateDetails();
});
$("clear-selection").addEventListener("click", () => {
  world.selection = null;
  updateMetrics();
});
let drag = null;
stage.addEventListener("pointerdown", (event) => {
  if (event.button !== 0) return;
  drag = {
    x: event.clientX,
    y: event.clientY,
    cx: camera.x,
    cy: camera.y,
    moved: false,
  };
  stage.setPointerCapture(event.pointerId);
});
stage.addEventListener("pointermove", (event) => {
  if (!drag) return;
  const dx = event.clientX - drag.x,
    dy = event.clientY - drag.y;
  if (Math.hypot(dx, dy) > 4) {
    drag.moved = true;
    following = false;
  }
  if (drag.moved) {
    camera.x = drag.cx - dx / camera.zoom;
    camera.y = drag.cy - dy / camera.zoom;
  }
});
stage.addEventListener("pointerup", (event) => {
  if (!drag) return;
  if (!drag.moved) {
    const rect = stage.getBoundingClientRect();
    world.pick(
      (event.clientX - rect.left - rect.width / 2) / camera.zoom + camera.x,
      (event.clientY - rect.top - rect.height / 2) / camera.zoom + camera.y,
      24 / camera.zoom,
    );
    updateMetrics();
  }
  drag = null;
  updateDetails();
});
stage.addEventListener("pointercancel", () => {
  drag = null;
});
stage.addEventListener(
  "wheel",
  (event) => {
    event.preventDefault();
    following = false;
    const rect = stage.getBoundingClientRect(),
      x = event.clientX - rect.left - rect.width / 2,
      y = event.clientY - rect.top - rect.height / 2;
    const next = Math.max(
      0.08,
      Math.min(6, camera.zoom * Math.exp(-event.deltaY * 0.001)),
    );
    camera.x += x / camera.zoom - x / next;
    camera.y += y / camera.zoom - y / next;
    camera.zoom = next;
  },
  { passive: false },
);
window.addEventListener("keydown", (event) => {
  if (event.target.closest("input,select,button,dialog")) return;
  if (event.code === "Space") {
    event.preventDefault();
    togglePause();
  }
  if (event.key.toLowerCase() === "r") resetCamera();
  if (event.key === "Escape") {
    world.selection = null;
    updateMetrics();
  }
});
function drawOverlay(width, height) {
  const ratio = Math.min(devicePixelRatio || 1, 2),
    ctx = overlayContext;
  if (overlay.width !== Math.round(width * ratio))
    overlay.width = Math.round(width * ratio);
  if (overlay.height !== Math.round(height * ratio))
    overlay.height = Math.round(height * ratio);
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  ctx.strokeStyle = "#9bd9da14";
  ctx.lineWidth = 0.7;
  for (let i = 0; i < 35; i++) {
    const x = (i * 179.3 + Math.sin(world.time * 0.1 + i) * 12) % width;
    const y =
      (((i * 137.2 - world.time * (3 + (i % 4))) % height) + height) % height;
    ctx.beginPath();
    ctx.arc(x, y, 1 + (i % 3) * 0.5, 0, Math.PI * 2);
    ctx.stroke();
  }
  const selected = world.selected();
  const point = (f) => [
    (f.x - camera.x) * camera.zoom + width / 2,
    (f.y - camera.y) * camera.zoom + height / 2,
  ];
  if (selected) {
    const byPid = new Map(
      [...world.fish.values()].filter((f) => !f.dying).map((f) => [f.p.pid, f]),
    );
    const partners = new Set([selected.p.ppid]);
    for (const p of world.snapshot.processes)
      if (p.ppid === selected.p.pid) partners.add(p.pid);
    for (const c of world.snapshot.connections || []) {
      if (c.pid_a === selected.p.pid) partners.add(c.pid_b);
      if (c.pid_b === selected.p.pid) partners.add(c.pid_a);
    }
    ctx.strokeStyle = "#7de9c13d";
    ctx.setLineDash([3, 6]);
    ctx.lineWidth = 1;
    for (const pid of partners) {
      const other = byPid.get(pid);
      if (!other) continue;
      ctx.beginPath();
      ctx.moveTo(...point(selected));
      ctx.lineTo(...point(other));
      ctx.stroke();
    }
    ctx.setLineDash([]);
  }
  const labels = [...world.fish.values()]
    .filter((f) => !f.dying)
    .sort((a, b) => b.p.cpu_percent - a.p.cpu_percent)
    .slice(0, 6);
  if (selected && !labels.includes(selected)) labels.push(selected);
  ctx.font = "10px ui-monospace,monospace";
  ctx.textAlign = "center";
  for (const fish of labels) {
    if (camera.zoom < 0.4 && fish !== selected) continue;
    const [x, y] = point(fish);
    if (x < 0 || x > width || y < 0 || y > height) continue;
    ctx.fillStyle = fish === selected ? "#c8f2e5" : "#8bb4bf99";
    const name =
      fish.p.name.length > 23 ? fish.p.name.slice(0, 22) + "…" : fish.p.name;
    ctx.fillText(name, x, y + fish.size * camera.zoom * 1.65 + 12);
  }
  if (world.snapshot) {
    ctx.textAlign = "left";
    ctx.font = "9px sans-serif";
    ctx.fillStyle = "#61858f99";
    ctx.fillText(
      "DRAG TO EXPLORE  ·  SCROLL TO ZOOM  ·  SELECT A FISH",
      20,
      height - 18,
    );
  }
}
function rendererLabel() {
  setText("renderer", renderer.name);
  $("renderer").title =
    renderer.fallbackReason ||
    "Instanced GPU rendering · simulation stays on this client";
  document.documentElement.dataset.renderer =
    renderer.name === "WebGPU" ? "webgpu" : "canvas";
}
function fallback(reason) {
  if (renderer instanceof CanvasRenderer) return;
  const canvas = renderer?.canvas || $("aquarium");
  renderer?.destroy();
  renderer = new CanvasRenderer(freshCanvas(canvas));
  renderer.fallbackReason = reason;
  rendererLabel();
}
function frame(now) {
  if (stopped) return;
  const elapsed = (now - lastFrame) / 1000;
  lastFrame = now;
  if (elapsed > 0) fps = fps * 0.95 + Math.min(120, 1 / elapsed) * 0.05;
  if (!paused) world.step(elapsed);
  const selected = world.selected();
  if (following && selected) {
    camera.x += (selected.x - camera.x) * 0.08;
    camera.y += (selected.y - camera.y) * 0.08;
  }
  const width = stage.clientWidth,
    height = stage.clientHeight;
  if (renderer && width && height) {
    try {
      renderer.render(world, camera, width, height);
    } catch (error) {
      fallback(error.message);
    }
    drawOverlay(width, height);
  }
  if (now - lastMetrics > 500) {
    setText("fps", `${Math.round(fps)} fps`);
    setText("zoom", `${Math.round(camera.zoom * 100)}%`);
    setText(
      "sample-age",
      freshness.last
        ? `${Math.floor((now - freshness.last) / 1000)}s since update`
        : "No samples",
    );
    lastMetrics = now;
  }
  requestAnimationFrame(frame);
}
window.addEventListener("pagehide", () => {
  stopped = true;
  controller?.abort();
  clearTimeout(timer);
  renderer?.destroy();
});
window.addEventListener("pageshow", (event) => {
  if (event.persisted) location.reload();
});
updateEmpty();
poll();
renderer = await createRenderer($("aquarium"), fallback, {
  forceCanvas: parameters.get("renderer") === "canvas",
});
rendererLabel();
requestAnimationFrame(frame);
