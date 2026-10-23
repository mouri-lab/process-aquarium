import { clamp } from "./fish.mjs";
export const LIMITS = [0, 10, 20, 50, 100, 200, 400];
export const SORTS = ["cpu", "memory", "name", "pid"];
export const SHORTCUTS = {
  0: "limit:0",
  1: "limit:10",
  2: "limit:20",
  3: "limit:50",
  4: "limit:100",
  5: "limit:200",
  6: "limit:400",
  d: "debug",
  i: "ipc",
  t: "ui",
  q: "schools",
  f: "fullscreen",
  F11: "fullscreen",
  l: "limit",
  s: "sort",
  o: "order",
  c: "camera",
  r: "reset",
  m: "preset",
  " ": "pause",
  Escape: "escape",
};
export class Camera {
  constructor() {
    this.reset();
  }
  reset() {
    this.x = 0;
    this.y = 0;
    this.zoom = 1;
    this.mode = 0;
    this.followKey = null;
    this.lastFollowKey = null;
  }
  manual() {
    this.mode = 2;
    this.followKey = null;
    this.lastFollowKey = null;
  }
  follow(key) {
    this.followKey = key;
    this.mode = key ? 1 : 2;
  }
  update(world, dt) {
    let target = null,
      factor = 0.01;
    if (this.mode === 0 && world.fish.size) {
      const fs = [...world.fish.values()];
      target = {
        x: fs.reduce((s, f) => s + f.x, 0) / fs.length,
        y: fs.reduce((s, f) => s + f.y, 0) / fs.length,
      };
    } else if (this.mode === 1) {
      target = this.followKey
        ? world.fish.get(this.followKey)
        : world.selected();
      factor = 0.08;
      if (target) this.lastFollowKey = target.key;
      else if (this.lastFollowKey) {
        this.mode = 0;
        this.followKey = null;
        this.lastFollowKey = null;
      }
    }
    if (target) {
      const lerp = 1 - (1 - factor) ** (Math.max(0, Math.min(dt, 0.25)) * 30);
      this.x += (target.x - this.x) * lerp;
      this.y += (target.y - this.y) * lerp;
    }
  }
  zoomAt(x, y, factor) {
    const next = clamp(this.zoom * factor, 0.1, 5);
    this.x += x / this.zoom - x / next;
    this.y += y / this.zoom - y / next;
    this.zoom = next;
  }
}
export class View {
  constructor() {
    this.debug = false;
    this.ipc = true;
    this.ui = 0;
    this.labels = false;
    this.particles = 50;
    this.bubbles = [];
    this.quality = "full";
    this.speed = 1;
    this.seaTime = "auto";
    this.samples = [];
    this.elapsed = 0;
  }
  adapt(fps, dt, world) {
    this.elapsed += Math.min(dt, 0.25);
    this.samples.push(fps);
    if (this.samples.length > 60) this.samples.shift();
    if (this.quality !== "auto") {
      world.quality = this.quality;
      return;
    }
    if (this.samples.length < 15 || this.elapsed < 1) return;
    this.elapsed = 0;
    const avg = this.samples.reduce((a, b) => a + b, 0) / this.samples.length;
    let quality = avg <= 18 ? "minimal" : avg <= 25 ? "reduced" : "full";
    if (world.quality === "minimal" && avg < 21) quality = "minimal";
    if (world.quality === "reduced" && quality === "full" && avg < 28)
      quality = "reduced";
    world.quality = quality;
    this.particles =
      quality === "minimal" ? 20 : quality === "reduced" ? 35 : 50;
  }
  action(action, world, camera) {
    if (action.startsWith("limit:"))
      world.setFilters({ limit: Number(action.slice(6)) });
    if (["debug", "ipc", "labels"].includes(action))
      this[action] = !this[action];
    if (action === "ui") this.ui = (this.ui + 1) % 3;
    if (action === "schools") world.highlightSchools = !world.highlightSchools;
    if (action === "camera") {
      camera.mode = (camera.mode + 1) % 3;
      camera.followKey = null;
    }
    if (action === "reset") camera.reset();
    if (action === "limit")
      world.setFilters({
        limit:
          LIMITS[(LIMITS.indexOf(world.filters.limit) + 1) % LIMITS.length],
      });
    if (action === "sort")
      world.setFilters({
        sort: SORTS[(SORTS.indexOf(world.filters.sort) + 1) % SORTS.length],
      });
    if (action === "order")
      world.setFilters({
        order: world.filters.order === "desc" ? "asc" : "desc",
      });
    if (action === "escape") {
      world.selection = null;
      world.highlighted.clear();
    }
    if (action === "preset") {
      const presets = [
        { limit: 20, sort: "cpu" },
        { limit: 50, sort: "memory" },
        { limit: 100, sort: "name" },
        { limit: 0, sort: "cpu" },
      ];
      this.preset = ((this.preset ?? -1) + 1) % presets.length;
      world.setFilters({ ...presets[this.preset], order: "desc" });
    }
  }
}
