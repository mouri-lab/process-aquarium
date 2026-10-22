import { appearance, clamp, TAU, hash } from "./fish.mjs";
import { projectedFish, visibleFish } from "./geometry.mjs";

export function prepareCanvas(canvas, width, height) {
  const ratio = Math.min(globalThis.devicePixelRatio || 1, 2);
  if (canvas.width !== Math.round(width * ratio))
    canvas.width = Math.max(1, Math.round(width * ratio));
  if (canvas.height !== Math.round(height * ratio))
    canvas.height = Math.max(1, Math.round(height * ratio));
  const ctx = canvas.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, width, height);
  return ctx;
}
const circle = (ctx, x, y, r) => {
  ctx.beginPath();
  ctx.arc(x, y, Math.max(0, r), 0, TAU);
};
export function drawUnderlay(ctx, world, camera, width, height, view) {
  const time = world.time,
    byPid = world.byPid();
  ctx.lineWidth = 1;
  for (let i = 0; i < view.particles; i++) {
    const x = (i * 179.3 + Math.sin(time * 0.1 + i) * 12) % width;
    const y = (((i * 137.2 - time * (9 + (i % 7))) % height) + height) % height;
    ctx.fillStyle = `rgba(100,150,200,${0.12 + (i % 4) * 0.04})`;
    circle(ctx, x, y, 1 + (i % 3));
    ctx.fill();
  }
  const point = (f) => [
    (f.x - camera.x) * camera.zoom + width / 2,
    (f.y - camera.y) * camera.zoom + height / 2,
  ];
  if (view.debug) {
    ctx.strokeStyle = "rgba(100,150,255,.2)";
    for (const f of byPid.values()) {
      const p = byPid.get(f.p.ppid);
      if (p) {
        ctx.beginPath();
        ctx.moveTo(...point(f));
        ctx.lineTo(...point(p));
        ctx.stroke();
      }
    }
  }
  if (view.ipc)
    for (const c of world.snapshot?.connections || []) {
      const a = byPid.get(c.pid_a),
        b = byPid.get(c.pid_b);
      if (!a || !b) continue;
      if (Math.hypot(a.x - b.x, a.y - b.y) > 400 / camera.zoom) continue;
      const intensity = clamp((a.p.cpu_percent + b.p.cpu_percent) / 200, 0, 1),
        alpha = (80 * (Math.sin(time * 3) * 0.3 + 0.7)) / 255;
      ctx.strokeStyle = `rgba(${100 + 155 * intensity},${150 - 50 * intensity},${200 - 100 * intensity},${alpha})`;
      ctx.lineWidth = 2;
      const [ax, ay] = point(a),
        [bx, by] = point(b);
      ctx.beginPath();
      ctx.moveTo(ax, ay);
      ctx.quadraticCurveTo(
        (ax + bx) / 2 + Math.sin(time * 2) * 20,
        (ay + by) / 2 + Math.cos(time * 2) * 20,
        bx,
        by,
      );
      ctx.stroke();
    }
  if (world.quality !== "full") return;
  for (const f of world.fish.values()) {
    if (!f.giant || !visibleFish(f, camera, width, height)) continue;
    const a = appearance(f, world.highlightSchools),
      size = a.size * camera.zoom,
      p = projectedFish(f, camera, width, height);
    if (size < 2) continue;
    if (f.p.memory_percent >= 5)
      for (let i = 0; i < 3; i++) {
        const radius =
          size *
          (3 + i * 1.2) *
          (1 + 0.5 * Math.sin(f.pulse + (i * Math.PI) / 4));
        const alpha =
          (clamp(Math.trunc(a.alpha * 255 * 0.45), 50, 200) *
            Math.max(0.3, 1 - i * 0.3)) /
          255;
        ctx.strokeStyle = `rgba(150,215,255,${alpha})`;
        ctx.lineWidth = 2;
        circle(ctx, p.x, p.y, radius);
        ctx.stroke();
      }
    // Deterministic per simulation frame: pause and high refresh rates cannot
    // change lightning frequency or consume the movement RNG.
    const seed = hash(f.key + Math.floor(world.time * 30));
    if (f.p.memory_percent >= 20 && (f.age % 30 === 0 || seed % 10 === 0)) {
      ctx.strokeStyle = `rgba(255,255,150,${Math.max(100, (a.alpha * 255) / 2) / 255})`;
      ctx.lineWidth = 2;
      for (let bolt = 0; bolt < 3 + (seed % 3); bolt++) {
        const angle = ((seed + bolt * 1171) % 6283) / 1000;
        const sx = p.x + Math.cos(angle) * size * 0.8,
          sy = p.y + Math.sin(angle) * size * 0.8;
        const ex = p.x + Math.cos(angle) * size * 2.5,
          ey = p.y + Math.sin(angle) * size * 2.5;
        ctx.beginPath();
        ctx.moveTo(sx, sy);
        for (let i = 1; i < 4; i++) {
          const noise = hash(`${seed},${bolt},${i}`);
          ctx.lineTo(
            sx + ((ex - sx) * i) / 4 + ((noise % 100) / 50 - 1) * size * 2,
            sy +
              ((ey - sy) * i) / 4 +
              (((noise >>> 8) % 100) / 50 - 1) * size * 2,
          );
        }
        ctx.lineTo(ex, ey);
        ctx.stroke();
      }
    }
  }
}
export function drawOverlay(ctx, world, camera, width, height, view) {
  view.bubbles = [];
  const selected = world.selected();
  for (const f of world.fish.values()) {
    if (!visibleFish(f, camera, width, height)) continue;
    const p = projectedFish(f, camera, width, height),
      size = appearance(f).size * camera.zoom;
    if (f === selected || world.highlighted.has(f.p.pid)) {
      ctx.strokeStyle =
        f === selected
          ? "rgba(255,255,255,.65)"
          : `rgba(0,255,0,${0.2 + (Math.sin(world.time * 8) * 0.5 + 0.5) * 0.6})`;
      ctx.lineWidth = f === selected ? 2 : 3;
      circle(ctx, p.x, p.y, f.size * camera.zoom + (f === selected ? 10 : 15));
      ctx.stroke();
    }
    if (view.labels || f === selected) {
      ctx.font = "11px ui-monospace,monospace";
      ctx.textAlign = "center";
      ctx.fillStyle = "#c8d8f2";
      ctx.fillText(`${f.p.name} · ${f.p.pid}`, p.x, p.y + size + 16);
    }
    if (world.quality !== "minimal" && f.talk > 0 && f.message) {
      ctx.font = "12px system-ui,sans-serif";
      const w = ctx.measureText(f.message).width + 14,
        h = 26;
      const x = clamp(p.x - w / 2, 5, width - w - 5),
        y = Math.max(5, p.y - h - 20);
      ctx.fillStyle = "rgba(0,0,0,.7)";
      ctx.beginPath();
      ctx.roundRect(x, y, w, h, 8);
      ctx.fill();
      ctx.fillStyle = "rgba(255,255,255,.9)";
      ctx.beginPath();
      ctx.roundRect(x + 2, y + 2, w - 4, h - 4, 6);
      ctx.fill();
      ctx.fillStyle = "#000";
      ctx.textAlign = "left";
      ctx.fillText(f.message, x + 7, y + 17);
      view.bubbles.push({ x, y, w, h, fish: f });
    }
  }
}
