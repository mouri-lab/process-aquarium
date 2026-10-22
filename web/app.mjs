import { AquariumMenu } from "./menu.mjs";
import { AquariumWorld, colorOf, keyOf, selectedProcesses } from "./world.mjs";
import { CanvasRenderer, createRenderer, freshCanvas } from "./renderer.mjs";
import { Camera, View, SHORTCUTS } from "./controls.mjs";
import {
  prepareCanvas,
  drawUnderlay,
  drawOverlay as paintOverlay,
} from "./effects.mjs";

const $ = (id) => document.getElementById(id);
const world = new AquariumWorld();
const menu = new AquariumMenu();
let feedbackTimer;
function feedback(message) {
  clearTimeout(feedbackTimer);
  setText("feedback", message);
  $("feedback").classList.add("visible");
  feedbackTimer = setTimeout(
    () => $("feedback").classList.remove("visible"),
    1800,
  );
}
const stage = $("stage"),
  overlay = $("overlay");
const camera = new Camera(),
  view = new View();
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
    camera.reset();
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
    setText("source-label", "PROCESS AQUARIUM");
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
      menu.close();
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
  $("inspection").hidden = !fish;
  $("details").hidden = !fish;
  $("inspect-empty").hidden = Boolean(fish);
  $("clear-selection").hidden = !fish;
  $("follow").disabled = !fish;
  following = camera.mode === 1;
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
  $("cpu-fill").style.width = `${Math.max(0, Math.min(100, p.cpu_percent))}%`;
  $("memory-fill").style.width =
    `${Math.max(0, Math.min(100, p.memory_percent))}%`;
  setText("detail-threads", p.num_threads);
  setText(
    "detail-age",
    `${fish.age} フレーム (${(fish.age / 30).toFixed(1)} 秒)`,
  );
  setText(
    "detail-school",
    fish.isolatedSchool
      ? "孤立プロセス群"
      : fish.school.length > 1
        ? `${fish.school.length} 匹 · リーダー PID ${Math.min(...fish.school)}`
        : "単独",
  );
  setText("detail-shape", fish.shape);
  setText("detail-partners", fish.partners.join(", ") || "—");
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
  setText("pause-label", paused ? "泳ぎを再開" : "泳ぎを一時停止");
  $("paused-indicator").hidden = !paused;
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
  camera.reset();
  syncControls();
}
async function perform(action) {
  if (action === "pause") togglePause();
  else if (action === "fullscreen") {
    menu.close();
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.querySelector(".workspace").requestFullscreen();
    } catch (error) {
      setText("notice", `フルスクリーンを開始できません: ${error.message}`);
      $("notice").hidden = false;
    }
  } else view.action(action, world, camera);
  syncControls();
  updateMetrics();
  updateEmpty();
  const messages = {
    debug: `親子のつながり ${view.debug ? "ON" : "OFF"}`,
    ipc: `通信の流れ ${view.ipc ? "ON" : "OFF"}`,
    schools: `群れの強調 ${world.highlightSchools ? "ON" : "OFF"}`,
    reset: "視点をリセット",
    camera: ["自動センタリング", "選択した魚を追従", "自由に移動"][camera.mode],
    limit: `表示 ${world.filters.limit || "無制限"}`,
    sort: `ソート ${world.filters.sort}`,
    order: world.filters.order === "desc" ? "降順" : "昇順",
    ui: ["通常", "静かな水槽", "没入モード"][view.ui],
    labels: `名前 ${view.labels ? "ON" : "OFF"}`,
    preset: "表示プリセットを切替",
  };
  if (messages[action]) feedback(messages[action]);
}
function syncControls() {
  document.documentElement.dataset.ui = String(view.ui);
  setText(
    "ui-mode-label",
    [
      "通常 · 選択時だけ詳細を表示",
      "静かな水槽 · 詳細とヒントを隠す",
      "没入モード · 水槽だけを表示",
    ][view.ui],
  );
  $("sort").value = world.filters.sort;
  $("limit").value = String(world.filters.limit);
  setText("order", world.filters.order === "desc" ? "↓" : "↑");
  for (const [id, value] of [
    ["debug", view.debug],
    ["ipc", view.ipc],
    ["schools", world.highlightSchools],
    ["labels", view.labels],
  ])
    $(id).setAttribute("aria-pressed", String(value));
  $("camera-mode").value = String(camera.mode);
  following = camera.mode === 1;
  $("follow").setAttribute("aria-pressed", String(following));
}
for (const action of ["debug", "ipc", "schools", "ui", "fullscreen", "labels"])
  $(action).addEventListener("click", () => perform(action));
$("reset").addEventListener("click", resetCamera);
$("camera-mode").addEventListener("change", () => {
  camera.mode = Number($("camera-mode").value);
  camera.followKey = null;
  syncControls();
});
$("quality").addEventListener("change", () => {
  view.quality = $("quality").value;
});
$("follow").addEventListener("click", () => {
  if (camera.mode === 1) camera.manual();
  else camera.follow(world.selection);
  syncControls();
});
$("clear-selection").addEventListener("click", () => perform("escape"));
document.addEventListener("fullscreenchange", () => {
  const active = Boolean(document.fullscreenElement);
  $("fullscreen").setAttribute("aria-pressed", String(active));
  setText(
    "fullscreen-label",
    active ? "フルスクリーンを終了" : "フルスクリーン",
  );
});
let drag = null;
stage.addEventListener("pointerdown", (event) => {
  if (event.button !== 0 && event.button !== 2) return;
  drag = {
    x: event.clientX,
    y: event.clientY,
    cx: camera.x,
    cy: camera.y,
    moved: false,
    button: event.button,
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
    camera.manual();
    syncControls();
  }
  if (drag.moved) {
    camera.x = drag.cx - dx / camera.zoom;
    camera.y = drag.cy - dy / camera.zoom;
  }
});
stage.addEventListener("pointerup", (event) => {
  if (!drag) return;
  if (!drag.moved) {
    const rect = stage.getBoundingClientRect(),
      sx = event.clientX - rect.left,
      sy = event.clientY - rect.top;
    const bubble = view.bubbles
      .slice()
      .reverse()
      .find(
        (b) => sx >= b.x && sx <= b.x + b.w && sy >= b.y && sy <= b.y + b.h,
      );
    if (bubble && drag.button === 0) {
      world.highlighted = new Set(bubble.fish.partners);
      world.selection = bubble.fish.key;
    } else {
      const old = world.selection;
      const key = world.pick(
        (sx - rect.width / 2) / camera.zoom + camera.x,
        (sy - rect.height / 2) / camera.zoom + camera.y,
        24 / camera.zoom,
      );
      world.highlighted.clear();
      if (drag.button === 2) {
        camera.follow(key);
        world.selection = old;
      }
    }
    syncControls();
    updateMetrics();
  }
  drag = null;
  updateDetails();
});
stage.addEventListener("contextmenu", (event) => event.preventDefault());
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
    camera.zoomAt(x, y, Math.exp(-event.deltaY * 0.001));
  },
  { passive: false },
);
window.addEventListener("keydown", (event) => {
  if (event.ctrlKey || event.metaKey || event.altKey || event.repeat) return;
  if (event.target.closest("input,select,textarea,dialog")) return;
  if (event.key === "Escape") {
    event.preventDefault();
    if (world.selection) perform("escape");
    else menu.open();
    return;
  }
  if (event.key === "/" || event.key === "?") {
    event.preventDefault();
    menu.open(event.key === "/" ? "processes" : "help");
    return;
  }
  if (event.target.closest("button") && event.key === " ") return;
  const action = SHORTCUTS[event.key] || SHORTCUTS[event.key.toLowerCase()];
  if (action) {
    event.preventDefault();
    perform(action);
  }
});
function drawOverlay(width, height) {
  const under = prepareCanvas($("underlay"), width, height);
  drawUnderlay(under, world, camera, width, height, view);
  const ctx = prepareCanvas(overlay, width, height);
  paintOverlay(ctx, world, camera, width, height, view);
  if (view.ui !== 2 && world.snapshot) {
    const visible = [...world.fish.values()].filter((f) => !f.dying);
    const mean =
      visible.reduce((n, f) => n + f.p.cpu_percent, 0) /
      Math.max(1, visible.length);
    setText(
      "compact-stats",
      `プロセス ${world.processes.size} / 魚 ${visible.length} · 平均CPU ${mean.toFixed(2)}% · ${Math.round(fps)} fps · ${world.quality}`,
    );
    setText(
      "camera-info",
      `${["自動センタリング", "追従", "手動"][camera.mode]} · (${camera.x.toFixed(0)}, ${camera.y.toFixed(0)}) · ${camera.zoom.toFixed(2)}×`,
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
  if (!paused && !menu.visible && !$("auth-dialog").open) world.step(elapsed);
  const oldMode = camera.mode;
  if (!menu.visible) camera.update(world, elapsed);
  if (camera.mode !== oldMode) syncControls();
  view.adapt(fps, elapsed, world);
  const width = stage.clientWidth,
    height = stage.clientHeight;
  if (world.width !== width || world.height !== height)
    world.resize(width, height);
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
    const counters = world.snapshot?.event_stats || {};
    setText(
      "event-stats",
      Object.entries(counters)
        .map(([k, v]) => `${k}: ${v}`)
        .join(" · ") || "—",
    );
    updateDetails();
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
syncControls();
updateEmpty();
poll();
renderer = await createRenderer($("aquarium"), fallback, {
  forceCanvas: parameters.get("renderer") === "canvas",
});
rendererLabel();
requestAnimationFrame(frame);
