import { AquariumMenu, GameWindow } from "./menu.mjs";
import { appearance } from "./fish.mjs";
import { AquariumWorld, colorOf, keyOf, selectedProcesses } from "./world.mjs";
import { CanvasRenderer, createRenderer, freshCanvas } from "./renderer.mjs";
import { Camera, View, SHORTCUTS } from "./controls.mjs";
import {
  Multiverse,
  Journey,
  galaxyLayout,
  galaxyCamera,
  transitionRect,
  pollTanks,
} from "./multiverse.mjs";
import {
  BACKGROUNDS,
  drawBackground,
  backgroundFrame,
  drawSpace,
  drawPortalBackground,
  portalClip,
} from "./backgrounds.mjs";
import {
  prepareCanvas,
  drawUnderlay,
  drawOverlay as paintOverlay,
} from "./effects.mjs";

const $ = (id) => document.getElementById(id);
const universe = new Multiverse(location.origin);
const journey = new Journey();
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)");
let activeTank = null,
  world = new AquariumWorld();
const galaxyButtons = new Map();
let skyTime = 0;
const menu = new AquariumMenu();
const inspection = new GameWindow(document.getElementById("inspection"));
const portrait = new CanvasRenderer(document.getElementById("portrait"));
let inspectedKey;
let feedbackTimer;
const processRows = new Map();
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
let camera = new Camera();
const view = new View();
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
  $("notice").hidden = !message || universe.overview || journey.moving;
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
function activate(tank) {
  if (!tank || tank === activeTank) return;
  if (activeTank) activeTank.search = $("search").value;
  activeTank = universe.active = tank;
  hostId = tank.host;
  world = tank.world;
  camera = tank.camera;
  freshness = tank.freshness;
  $("search").value = tank.search;
  $("background").value = tank.background.kind;
  view.seaTime = tank.background.seaTime || "auto";
  $("sea-time").value = view.seaTime;
  $("host").value = hostId;
  processRows.clear();
  inspectedKey = null;
  syncControls();
  updateEmpty();
  updateMetrics();
  setStatus(freshness.mode, freshness.error);
  try {
    sessionStorage.setItem("aquarium-host", hostId);
  } catch {}
}
function populateHosts(hosts) {
  universe.catalog(hosts);
  for (const tank of universe.ordered) {
    if (tank.settingsLoaded) continue;
    tank.settingsLoaded = true;
    try {
      const saved = JSON.parse(
        localStorage.getItem(`aquarium-background:${tank.id}`),
      );
      if (saved && Object.hasOwn(BACKGROUNDS, saved.kind)) {
        tank.background.kind = saved.kind;
        if (["auto", "morning", "day", "evening", "night"].includes(saved.seaTime))
          tank.background.seaTime = saved.seaTime;
      }
    } catch {}
  }
  if (!activeTank) activate(hostId ? universe.select(hostId) : universe.active);
  const select = $("host");
  const choices = universe.ordered.map(
    (t) => new Option(`${t.name}${t.listed ? "" : " · 更新待ち"}`, t.host),
  );
  if (!choices.length) choices.push(new Option("接続を待っています…", ""));
  select.replaceChildren(...choices);
  select.value = hostId;
  select.title = select.selectedOptions[0]?.textContent || "";
}
function mapMode(open) {
  if (!activeTank) return;
  if (open || !universe.visible.includes(activeTank))
    universe.page = Math.floor(universe.ordered.indexOf(activeTank) / 6);
  universe.overview = open;
  journey.go(open ? 0 : 1, reducedMotion.matches);
  menu.close();
  drag = null;
  $("galaxy-toggle").setAttribute("aria-pressed", String(open));
  $("galaxy-toggle").setAttribute(
    "aria-label",
    open ? "水槽に戻る (V)" : "銀河の星図 (V)",
  );
  $("galaxy-toggle-label").textContent = open ? "水槽へ" : "星図";
  updateEmpty();
  updateDetails();
  updateNotice();
  poll();
  stage.focus({ preventScroll: true });
}
function enterTank(tank) {
  activate(tank);
  mapMode(false);
  feedback(tank.name);
}
const galaxyStatus = {
  waiting: "魚たちを待っています",
  stale: "更新を待っています",
  offline: "更新を待っています",
  auth: "接続を確認してください",
};
function updateGalaxies(rects, tanks) {
  const shown = journey.depth < 0.3;
  $("galaxies").hidden = !shown;
  $("galaxy-pages").hidden = !shown || universe.pages < 2;
  $("map-hint").hidden = !shown;
  $("galaxies").style.opacity = String(Math.max(0, 1 - journey.depth / 0.3));
  setText("galaxy-page", `${universe.page + 1} / ${universe.pages}`);
  $("previous-galaxies").disabled = universe.page === 0;
  $("next-galaxies").disabled = universe.page === universe.pages - 1;
  if (!shown) return;
  const ids = new Set(tanks.map((t) => t.id));
  for (const [id, b] of galaxyButtons)
    if (!ids.has(id)) {
      b.remove();
      galaxyButtons.delete(id);
    }
  tanks.forEach((tank, i) => {
    let button = galaxyButtons.get(tank.id);
    if (!button) {
      button = document.createElement("button");
      button.className = "galaxy";
      button.append(
        document.createElement("strong"),
        document.createElement("small"),
      );
      button.addEventListener("click", () => enterTank(tank));
      button.addEventListener(
        "wheel",
        (event) => {
          event.preventDefault();
          if (event.deltaY < 0) enterTank(tank);
        },
        { passive: false },
      );
      galaxyButtons.set(tank.id, button);
      $("galaxies").append(button);
    }
    const r = rects[i];
    Object.assign(button.style, {
      left: `${r.x}px`,
      top: `${r.y}px`,
      width: `${r.width}px`,
      height: `${r.height}px`,
    });
    button.style.setProperty("--galaxy-color", tank.sky.light);
    button.firstChild.textContent = tank.name;
    button.lastChild.textContent =
      galaxyStatus[tank.freshness.mode] ||
      (tank.world.snapshot?.processes.length ? "" : "魚たちを待っています");
    button.setAttribute(
      "aria-label",
      `${tank.name} の水槽へ${button.lastChild.textContent ? "・" + button.lastChild.textContent : ""}`,
    );
    button.setAttribute("aria-current", String(tank === activeTank));
  });
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
    if (!activeTank) {
      setStatus("waiting");
      updateEmpty();
      return;
    }
    const targets = journey.moving
      ? universe.ordered.slice(universe.page * 6, universe.page * 6 + 6)
      : universe.visible;
    await pollTanks(
      targets,
      (host) =>
        request(
          `api/v1/snapshot?host=${encodeURIComponent(host)}`,
          controller.signal,
        ),
      () => version === generation,
      () => performance.now(),
    );
    if (version !== generation) return;
    setStatus(freshness.mode, freshness.error);
    updateMetrics();
    updateEmpty();
  } catch (error) {
    if (version !== generation) return;
    if (error.authentication) {
      generation++;
      controller?.abort();
      setStatus("auth");
      showAuth(error.message);
    } else {
      const message =
        error.name === "AbortError"
          ? "接続を待っています。最後に届いた魚たちを表示しています。"
          : error.message;
      for (const tank of universe.tanks.values())
        Object.assign(tank.freshness, { mode: "offline", error: message });
      setStatus("offline", message);
    }
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
    universe.clear();
    activeTank = null;
    world = new AquariumWorld();
    camera = new Camera();
    freshness = { last: 0, mode: "waiting", error: "" };
    following = false;
    journey.go(1, true);
    universe.overview = false;
    galaxyButtons.clear();
    $("galaxies").replaceChildren();
    $("galaxy-toggle").setAttribute("aria-pressed", "false");
    $("galaxy-toggle").setAttribute("aria-label", "銀河の星図 (V)");
    setText("galaxy-toggle-label", "星図");
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
  $("empty").hidden =
    universe.overview || journey.moving || !(noData || noMatches);
  $("agent-command").hidden =
    Boolean(world.snapshot) || freshness.mode === "auth";
  if (world.snapshot) {
    setText(
      "empty-message",
      world.snapshot.processes.length
        ? "表示するプロセスがありません。メニューから表示設定を確認できます。"
        : "このホストから報告されているプロセスはありません。",
    );
  } else {
    setText(
      "empty-message",
      freshness.mode === "auth"
        ? "メニューの「接続」からアクセストークンを設定してください。"
        : "エージェントが接続すると、プロセスが泳ぎ始めます。",
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
    setText("visible-count", "プロセスの到着を待っています");
    processRows.clear();
    $("process-list").replaceChildren(
      Object.assign(document.createElement("p"), {
        className: "muted",
        textContent: "接続すると、ここから魚を探せます。",
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
  const visible = selectedProcesses(snapshot, {
    ...world.filters,
    limit: 50,
    search: $("search").value,
  });
  setText(
    "visible-count",
    `${number.format(visible.length)} 件${visible.length === 50 ? "まで表示" : ""}`,
  );
  stage.dataset.fishCount = String(
    [...world.fish.values()].filter((f) => !f.dying).length,
  );
  setText("source-label", `${snapshot.source} / ${snapshot.hostname}`);
  const labels = { cpu: "CPU", memory: "MEMORY", name: "NAME", pid: "PID" };
  setText(
    "list-label",
    `${labels[world.filters.sort]} · ${world.filters.order.toUpperCase()}`,
  );
  const wanted = new Set();
  const rows = visible.map((process) => {
    const key = keyOf(snapshot, process);
    wanted.add(key);
    let row = processRows.get(key);
    if (!row) {
      const button = document.createElement("button");
      const dot = Object.assign(document.createElement("span"), {
        className: "color-dot",
      });
      const name = Object.assign(document.createElement("span"), {
        className: "process-name",
      });
      const pid = Object.assign(document.createElement("span"), {
        className: "process-pid",
      });
      const value = Object.assign(document.createElement("span"), {
        className: "process-value",
      });
      button.append(dot, name, pid, value);
      button.addEventListener("click", () => {
        if (!world.focus(key)) return;
        const fish = world.selected();
        camera.x = fish.x;
        camera.y = fish.y;
        if (universe.overview) mapMode(false);
        menu.close();
        updateMetrics();
      });
      row = { button, dot, name, pid, value };
      processRows.set(key, row);
    }
    row.button.className = `process-row${key === world.selection ? " active" : ""}`;
    row.dot.style.background = rgb(colorOf(process.name));
    row.name.textContent = process.name;
    row.pid.textContent = process.pid;
    row.value.textContent = percent(
      world.filters.sort === "memory"
        ? process.memory_percent
        : process.cpu_percent,
    );
    return row.button;
  });
  const container = $("process-list");
  for (const [key, row] of processRows)
    if (!wanted.has(key)) {
      row.button.remove();
      processRows.delete(key);
    }
  for (const child of [...container.children])
    if (!rows.includes(child)) child.remove();
  rows.forEach((row, i) => {
    if (container.children[i] !== row)
      container.insertBefore(row, container.children[i] || null);
  });
  updateDetails();
  updateNotice();
}
function updateDetails() {
  const fish = world.selected();
  if (fish && inspectedKey !== world.selection) inspection.show();
  inspectedKey = world.selection;
  $("inspection").hidden = !fish || universe.overview || journey.moving;
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
  setText(
    "detail-shape",
    {
      shark: "サメ",
      tropical: "熱帯魚",
      ray: "エイ",
      dolphin: "イルカ",
      whale: "クジラ",
      eel: "ウナギ",
      fish: "さかな",
    }[fish.shape],
  );
  if ($("portrait").clientWidth) {
    // Same geometry and colour as the selected fish, fitted to its little window.
    const sample = {
      ...fish,
      x: 0,
      y: 0,
      angle: 0,
      spawn: 1,
      death: 0,
      dying: false,
      numThreads: 1,
      p: { ...fish.p, num_threads: 1 },
    };
    const scale = 25 / Math.max(1, appearance(sample).size);
    portrait.render(
      {
        fish: new Map([[0, sample]]),
        quality: "full",
        highlightSchools: false,
      },
      { x: 0, y: 0, zoom: scale },
      $("portrait").clientWidth,
      $("portrait").clientHeight,
    );
  }
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
  enterTank(universe.select($("host").value));
  poll();
});
$("galaxy-toggle").addEventListener("click", () => mapMode(!universe.overview));
$("open-galaxies").addEventListener("click", () => mapMode(true));
for (const [id, delta] of [
  ["previous-galaxies", -1],
  ["next-galaxies", 1],
])
  $(id).addEventListener("click", () => {
    universe.page = Math.max(
      0,
      Math.min(universe.pages - 1, universe.page + delta),
    );
    poll();
  });
function saveBackground() {
  if (!activeTank) return;
  try {
    localStorage.setItem(
      `aquarium-background:${activeTank.id}`,
      JSON.stringify(activeTank.background),
    );
  } catch {}
}
$("background").addEventListener("change", () => {
  if (activeTank) activeTank.background.kind = $("background").value;
  saveBackground();
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
$("auth-dialog").addEventListener("close", () => {
  if (!pending && !stopped) poll();
});
function togglePause() {
  paused = !paused;
  setText("pause-label", paused ? "泳ぎを再開" : "泳ぎを一時停止");
  $("paused-indicator").hidden = !paused;
  $("pause").setAttribute(
    "aria-label",
    paused ? "泳ぎを再開" : "泳ぎを一時停止",
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
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
      menu.close();
    } catch (error) {
      feedback(`フルスクリーンを開始できません: ${error.message}`);
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
    limit: `表示 ${world.filters.limit ? `${world.filters.limit} 匹` : "無制限"}`,
    sort: `ソート ${world.filters.sort}`,
    order: world.filters.order === "desc" ? "降順" : "昇順",
    ui: ["通常", "静かな水槽", "没入モード"][view.ui],
    labels: `名前 ${view.labels ? "ON" : "OFF"}`,
    preset: "表示プリセットを切替",
  };
  const message = messages[action.startsWith("limit:") ? "limit" : action];
  if (message) feedback(message);
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
$("sea-time").addEventListener("change", () => {
  view.seaTime = $("sea-time").value;
  if (activeTank) activeTank.background.seaTime = view.seaTime;
  saveBackground();
});
$("swim-speed").addEventListener("change", () => {
  view.speed = Number($("swim-speed").value);
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
  if (universe.overview || journey.moving || event.target.closest("button"))
    return;
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
      world.highlighted = new Set(bubble.partners);
      world.selection = bubble.fish.key;
    } else {
      const old = world.selection;
      const key = world.pick(
        (sx - rect.width / 2) / camera.zoom + camera.x,
        (sy - rect.height / 2) / camera.zoom + camera.y,
        24 / camera.zoom,
        world.scene.fish,
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
    if (universe.overview || journey.moving) return;
    if (camera.zoom <= 0.105 && event.deltaY > 0 && universe.tanks.size > 1) {
      mapMode(true);
      return;
    }
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
  if (event.target.closest("dialog")) return;
  if (event.key === "Escape") {
    event.preventDefault();
    if (menu.visible) menu.close();
    else if (universe.overview) {
      universe.page = Math.floor(universe.ordered.indexOf(activeTank) / 6);
      mapMode(false);
    } else if (world.selection) perform("escape");
    else menu.open();
    return;
  }
  if (event.target.closest("input,select,textarea")) return;
  if (event.key.toLowerCase() === "v") {
    event.preventDefault();
    mapMode(!universe.overview);
    return;
  }
  if (["[", "]"].includes(event.key) && universe.tanks.size) {
    event.preventDefault();
    const tanks = universe.ordered;
    const index =
      (tanks.indexOf(activeTank) +
        (event.key === "]" ? 1 : -1) +
        tanks.length) %
      tanks.length;
    universe.page = Math.floor(index / 6);
    enterTank(tanks[index]);
    poll();
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
function drawOverlay(scene, width, height) {
  const under = prepareCanvas($("underlay"), width, height);
  if (activeTank)
    drawBackground(
      under,
      activeTank.background,
      backgroundFrame(activeTank, camera, width, height, skyTime, new Date()),
    );
  drawUnderlay(under, scene, camera, width, height, {
    ...view,
    habitat: !activeTank,
  });
  const ctx = prepareCanvas(overlay, width, height);
  paintOverlay(ctx, scene, camera, width, height, view);
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
  const moving = !paused && !$("auth-dialog").open;
  const dt = Math.min(elapsed, 0.1);
  if (moving) skyTime += dt * view.speed;
  const wasMoving = journey.moving;
  // Navigation uses elapsed wall time; a background tab must not resume a
  // half-finished trip one simulation tick at a time.
  journey.step(elapsed);
  if (wasMoving && !journey.moving) {
    updateEmpty();
    updateDetails();
    updateNotice();
  }
  const width = stage.clientWidth,
    height = stage.clientHeight;
  const inMap = journey.depth < 1;
  const tanks = inMap
    ? universe.ordered.slice(universe.page * 6, universe.page * 6 + 6)
    : activeTank
      ? [activeTank]
      : [];
  view.adapt(fps, elapsed, world);
  const oldMode = camera.mode;
  for (const tank of tanks) {
    const w = tank.world;
    w.quality = world.quality;
    if (w.width !== width || w.height !== height) w.resize(width, height);
    if (moving) w.step(dt * view.speed);
    tank.scene = w.renderFrame(elapsed, moving);
    if (!inMap) tank.camera.update(tank.scene, elapsed);
  }
  if (camera.mode !== oldMode) syncControls();
  if (renderer && width && height) {
    try {
      if (inMap && tanks.length) {
        const rects = galaxyLayout(tanks.length, width, height),
          focus = rects[Math.max(0, tanks.indexOf(activeTank))];
        const under = prepareCanvas($("underlay"), width, height);
        prepareCanvas(overlay, width, height);
        view.bubbles = [];
        drawSpace(under, width, height, skyTime, journey.depth, {
          x: focus.centerX,
          y: focus.centerY,
        });
        const views = tanks.map((tank, i) => {
          const depth = tank === activeTank ? journey.depth : 0;
          const rect = transitionRect(
            rects[i],
            focus,
            journey.depth,
            width,
            height,
          );
          const far = galaxyCamera(tank.scene, rects[i].width, rects[i].height);
          const c = {
            x: far.x + (tank.camera.x - far.x) * depth,
            y: far.y + (tank.camera.y - far.y) * depth,
            zoom: Math.exp(
              Math.log(far.zoom) * (1 - depth) +
                Math.log(tank.camera.zoom) * depth,
            ),
          };
          drawPortalBackground(
            under,
            tank,
            rect,
            depth,
            c,
            skyTime,
            new Date(),
            width,
            height,
          );
          return {
            world: tank.scene,
            camera: c,
            rect,
            clip: portalClip(rect, depth),
            opacity: 0.75 + 0.25 * depth,
            minimumPixels: depth < 0.6 ? 1.6 : 0,
          };
        });
        renderer.renderViews(views, width, height);
        updateGalaxies(rects, tanks);
      } else {
        const scene = activeTank?.scene || world.renderFrame(elapsed, moving);
        renderer.render(scene, camera, width, height);
        drawOverlay(scene, width, height);
        updateGalaxies([], []);
      }
    } catch (error) {
      fallback(error.message);
    }
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
setTimeout(() => ($("first-hint").hidden = true), 8000);
syncControls();
updateEmpty();
poll();
renderer = await createRenderer($("aquarium"), fallback, {
  forceCanvas: parameters.get("renderer") === "canvas",
});
rendererLabel();
requestAnimationFrame(frame);
