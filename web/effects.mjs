import { appearance, clamp, TAU, hash } from "./fish.mjs";
import { projectedFish, visibleFish } from "./geometry.mjs";

export function prepareCanvas(canvas, width, height, maxRatio = 2) {
  const ratio = Math.min(globalThis.devicePixelRatio || 1, maxRatio);
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
// Use local wall time, independently of the simulation's pause and speed.
const SEA_PHASES = [
  [0, [8, 20, 43], [4, 11, 24], [143, 182, 222], 0.018],
  [5, [20, 39, 63], [9, 23, 37], [205, 181, 185], 0.035],
  [7, [65, 103, 111], [18, 47, 63], [255, 222, 173], 0.075],
  [12, [40, 100, 116], [16, 44, 61], [211, 237, 205], 0.085],
  [16, [32, 77, 89], [16, 44, 61], [231, 230, 191], 0.055],
  [18, [86, 68, 89], [23, 31, 51], [255, 177, 136], 0.065],
  [21, [12, 27, 51], [5, 14, 28], [143, 182, 222], 0.022],
];
export function seaAppearance(date = new Date(), mode = "auto") {
  const presets = { morning: 7, day: 12, evening: 18, night: 0 };
  const hour = Object.hasOwn(presets, mode)
    ? presets[mode]
    : date.getHours() + date.getMinutes() / 60 + date.getSeconds() / 3600;
  let index = 0;
  while (index + 1 < SEA_PHASES.length && hour >= SEA_PHASES[index + 1][0]) index++;
  const from = SEA_PHASES[index], to = SEA_PHASES[(index + 1) % SEA_PHASES.length];
  let t = (hour - from[0]) / ((to[0] || 24) - from[0]);
  t = t * t * (3 - 2 * t);
  const mix = (a, b) => a.map((v, i) => Math.round(v + (b[i] - v) * t));
  const top = mix(from[1], to[1]);
  return {
    top,
    bottom: mix(from[2], to[2]),
    light: mix(from[3], to[3]),
    alpha: from[4] + (to[4] - from[4]) * t,
    floor: mix(top, [41, 78, 80]).map((v) => Math.round(v * 0.75)),
    plant: mix(top, [75, 119, 112]),
  };
}
const seaRgb = (color) => `rgb(${color.join(",")})`;
// The scenery stays in screen space with gentle camera parallax. All variation
// is deterministic so plants never jump when quality or viewport size changes.
const seaTint = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));
const seaRgba = (color, alpha) => `rgba(${color.join(",")},${alpha})`;
function seaweed(ctx, x, floor, h, breadth, phase, time, color, leafy) {
  const sway = Math.sin(time * 0.48 + phase) * h * 0.085;
  const bend = Math.sin(phase) * h * 0.12;
  const point = (t) => [
    x + bend * t + sway * t * t + Math.sin(t * 7 + phase + time * 0.38) * breadth * t,
    floor - h * t,
  ];
  // Tapered ribbons follow the same current, but each has its own phase.
  ctx.fillStyle = seaRgb(color);
  ctx.beginPath();
  ctx.moveTo(x - breadth * 0.4, floor);
  for (let i = 1; i <= 16; i++) {
    const t = i / 16, [px, py] = point(t);
    ctx.lineTo(px - breadth * (1 - t) * (0.65 + Math.sin(t * 8) * 0.2), py);
  }
  for (let i = 16; i >= 0; i--) {
    const t = i / 16, [px, py] = point(t);
    ctx.lineTo(px + breadth * (1 - t) * 0.6, py);
  }
  ctx.closePath();
  ctx.fill();
  if (leafy) {
    for (let j = 2; j < 9; j++) {
      const t = j / 10, [px, py] = point(t);
      const side = j % 2 ? -1 : 1;
      const length = h * (0.15 - t * 0.07);
      ctx.fillStyle = seaRgb(seaTint(color, [114, 156, 113], j % 2 ? 0.12 : 0.24));
      ctx.beginPath();
      ctx.moveTo(px, py + 4);
      ctx.quadraticCurveTo(px + side * length, py + length * 0.1,
        px + side * length * 0.85, py - length * 0.85);
      ctx.quadraticCurveTo(px + side * length * 0.22, py - length * 0.75, px, py + 4);
      ctx.fill();
    }
  }
  ctx.strokeStyle = seaRgba(seaTint(color, [160, 193, 139], 0.4), 0.35);
  ctx.lineWidth = Math.max(0.6, breadth * 0.12);
  ctx.beginPath();
  ctx.moveTo(x, floor);
  for (let i = 1; i <= 12; i++) ctx.lineTo(...point(i / 13));
  ctx.stroke();
}
function seabedRock(ctx, x, y, size, sea, seed) {
  const color = seaTint(sea.floor, [88, 117, 111], 0.36);
  ctx.fillStyle = seaRgba(sea.bottom, 0.55);
  ctx.beginPath();
  ctx.ellipse(x + size * 0.12, y + 3, size * 1.2, size * 0.23, 0, 0, TAU);
  ctx.fill();
  const shade = ctx.createLinearGradient(x, y - size, x, y + 5);
  shade.addColorStop(0, seaRgb(seaTint(color, sea.plant, 0.32)));
  shade.addColorStop(1, seaRgb(seaTint(color, sea.bottom, 0.65)));
  ctx.fillStyle = shade;
  ctx.beginPath();
  ctx.moveTo(x - size, y);
  ctx.bezierCurveTo(x - size * 1.12, y - size * 0.4,
    x - size * 0.55, y - size * 0.95, x - size * 0.15, y - size * 0.83);
  ctx.bezierCurveTo(x + size * 0.55, y - size * (0.9 + seed * 0.2),
    x + size * 0.75, y - size * 0.35, x + size, y);
  ctx.quadraticCurveTo(x + size * 0.2, y + size * 0.2, x - size, y);
  ctx.fill();
  ctx.strokeStyle = seaRgba(sea.plant, 0.22);
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(x - size * 0.7, y - size * 0.3);
  ctx.quadraticCurveTo(x - size * 0.4, y - size * 0.8, x + size * 0.1, y - size * 0.68);
  ctx.stroke();
}
export function habitat(ctx, width, height, time, camera, quality,
  sea = seaAppearance(), layer = "all") {
  const base = layer === "all" || layer === "base";
  const plants = layer === "all" || layer === "plants";
  const foreground = layer === "all" || layer === "foreground";
  ctx.save();
  const scale = Math.min(1.3, height / 780, width / 850);
  const floor = height * 0.91;
  const parallax = Math.sin(camera.x / 900) * 18 * scale;
  const tint = (color, amount) => seaRgb(seaTint(sea.bottom, color, amount));
  if (base && quality !== "minimal") {
    // A soft surface glow and overlapping shafts give the water volume.
    const glow = ctx.createRadialGradient(width * 0.38, -height * 0.12, 0,
      width * 0.38, 0, height * 0.95);
    glow.addColorStop(0, seaRgba(sea.light, sea.alpha * 1.7));
    glow.addColorStop(1, seaRgba(sea.light, 0));
    ctx.fillStyle = glow;
    ctx.fillRect(0, 0, width, height);
    for (let i = 0; i < 6; i++) {
      const x = width * (i * 0.23 - 0.18) + Math.sin(time * 0.09 + i) * 18;
      const light = ctx.createLinearGradient(x, 0, x + width * 0.2, height);
      light.addColorStop(0, seaRgba(sea.light, sea.alpha * (i % 2 ? 0.7 : 1.1)));
      light.addColorStop(1, seaRgba(sea.light, 0));
      ctx.fillStyle = light;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x + width * (i % 2 ? 0.025 : 0.07), 0);
      ctx.lineTo(x + width * 0.34, height);
      ctx.lineTo(x + width * 0.14, height);
      ctx.fill();
    }
    // Far reefs are deliberately low contrast, like silhouettes in sea haze.
    for (let layer = 0; layer < 2; layer++) {
      ctx.fillStyle = tint(sea.plant, 0.09 + layer * 0.055);
      ctx.beginPath();
      ctx.moveTo(0, height);
      for (let i = 0; i <= 60; i++) {
        const x = width * i / 60;
        const ridge = Math.sin(i * 0.21 + layer * 2) * 0.035 +
          Math.sin(i * 0.57 + layer) * 0.016;
        ctx.lineTo(x, height * (0.82 + layer * 0.055 + ridge));
      }
      ctx.lineTo(width, height);
      ctx.fill();
    }
    for (let i = 0; i < 24; i++) {
      const x = width * ((i * 0.137 + 0.04) % 1) + parallax * 0.35;
      seaweed(ctx, x, height * 0.925, (45 + (i * 31) % 100) * scale,
        3 * scale, i * 2.4, time * 0.7,
        seaTint(sea.bottom, sea.plant, 0.19), false);
    }
  }
  if (base) {
    const sand = ctx.createLinearGradient(0, floor - height * 0.04, 0, height);
    sand.addColorStop(0, seaRgb(seaTint(sea.floor, sea.plant, 0.12)));
    sand.addColorStop(1, seaRgb(seaTint(sea.floor, [106, 115, 99], 0.3)));
    ctx.fillStyle = sand;
    ctx.beginPath();
    ctx.moveTo(0, floor + height * 0.02);
    ctx.bezierCurveTo(width * 0.24, floor - height * 0.04,
      width * 0.38, floor + height * 0.045, width * 0.6, floor + height * 0.02);
    ctx.bezierCurveTo(width * 0.8, floor - height * 0.025,
      width * 0.9, floor + height * 0.005, width, floor - height * 0.01);
    ctx.lineTo(width, height);
    ctx.lineTo(0, height);
    ctx.fill();
  }
  if (quality === "minimal") {
    ctx.restore();
    return;
  }
  // Sand ripples and a subtle moving caustic shimmer across the seabed.
  ctx.lineWidth = 0.8;
  if (base) for (let i = 0; i < 28; i++) {
    const x = ((i * 0.173) % 1) * width;
    const y = floor + height * (0.034 + ((i * 0.317) % 1) * 0.064);
    ctx.strokeStyle = seaRgba(sea.light, 0.035 + sea.alpha * 0.45);
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.bezierCurveTo(x + 14 * scale, y - 3 * scale,
      x + 36 * scale, y + 4 * scale, x + 62 * scale, y);
    ctx.stroke();
  }
  if (quality === "full") {
    if (plants) for (let i = 0; i < 9; i++) {
      const x = width * (i / 8) + Math.sin(time * 0.2 + i) * 12;
      ctx.strokeStyle = seaRgba(sea.light, sea.alpha * 0.5);
      ctx.beginPath();
      ctx.ellipse(x, floor + height * 0.055, 65 * scale, 9 * scale,
        Math.sin(i + time * 0.1) * 0.08, 0.2, Math.PI * 0.9);
      ctx.stroke();
    }
    if (base) for (let i = 0; i < 150; i++) {
      const x = ((i * 0.618034) % 1) * width;
      const y = floor + height * (0.04 + ((i * 0.414214) % 1) * 0.06);
      ctx.fillStyle = seaRgba(i % 3 ? sea.plant : sea.light, 0.14);
      ctx.fillRect(x, y, (i % 3 + 1) * scale, scale);
    }
  }
  // Different heights, leaf shapes and depths make loose kelp gardens.
  if (plants) for (const [anchor, count, tall, depth] of [
    [0.045, 10, 245, 0], [0.155, 6, 145, 1],
    [0.78, 5, 125, 1], [0.94, 11, 275, 0], [0.58, 4, 62, 1],
  ]) {
    const base = height * (depth ? 0.945 : 0.98);
    for (let j = 0; j < count; j++) {
      const phase = j * 2.39 + anchor * 37;
      const x = width * anchor + (j - count / 2) * 13 * scale + parallax * (depth ? 0.6 : 1);
      const h = tall * (0.48 + (Math.sin(phase * 4) + 1) * 0.26) * scale;
      const color = seaTint(sea.bottom, seaTint(sea.plant, [58, 128, 99], 0.48),
        (depth ? 0.4 : 0.6) + (j % 3) * 0.1);
      seaweed(ctx, x, base, h, (j % 3 === 0 ? 7 : 4) * scale,
        phase, time, color, j % 3 === 0);
    }
  }
  if (foreground) {
    for (const [x, y, size, seed] of [
      [0.025, 0.986, 53, 0.3], [0.105, 0.984, 33, 0.7],
      [0.18, 0.963, 22, 0.4], [0.83, 0.966, 33, 0.6],
      [0.925, 0.99, 59, 0.9], [0.985, 0.98, 38, 0.2],
    ]) seabedRock(ctx, x * width + parallax, y * height, size * scale, sea, seed);
    // Small sea fans bring a muted warm accent to the cool green gardens.
    ctx.lineCap = "round";
    for (const anchor of [0.215, 0.865]) {
      const x = width * anchor + parallax, y = height * 0.972;
      const color = seaTint(sea.floor, [174, 124, 113], 0.42);
      for (let j = -2; j <= 2; j++) {
        const tipX = x + j * 12 * scale, tipY = y - (41 - Math.abs(j) * 6) * scale;
        ctx.strokeStyle = seaRgb(color);
        ctx.lineWidth = 2.6 * scale;
        ctx.beginPath();
        ctx.moveTo(x, y);
        ctx.quadraticCurveTo(x + j * 4 * scale, y - 22 * scale, tipX, tipY);
        ctx.stroke();
        for (const side of [-1, 1]) {
          ctx.lineWidth = 1.5 * scale;
          ctx.beginPath();
          ctx.moveTo(x + j * 7 * scale, y - 23 * scale);
          ctx.quadraticCurveTo(tipX + side * 5 * scale, tipY + 8 * scale,
            tipX + side * 8 * scale, tipY - 3 * scale);
          ctx.stroke();
        }
      }
    }
    for (const [u, v] of [[0.32, 0.971], [0.69, 0.987]]) {
      const x = width * u, y = height * v;
      ctx.fillStyle = seaRgb(seaTint(sea.floor, [185, 182, 151], 0.45));
      ctx.beginPath();
      ctx.moveTo(x, y + 3 * scale);
      ctx.bezierCurveTo(x - 18 * scale, y - 4 * scale, x - 9 * scale,
        y - 16 * scale, x, y - 12 * scale);
      ctx.bezierCurveTo(x + 9 * scale, y - 16 * scale, x + 18 * scale,
        y - 4 * scale, x, y + 3 * scale);
      ctx.fill();
      ctx.strokeStyle = seaRgba(sea.floor, 0.65);
      ctx.lineWidth = 0.8;
      for (let j = -2; j <= 2; j++) {
        ctx.beginPath();
        ctx.moveTo(x, y + 2 * scale);
        ctx.lineTo(x + j * 4 * scale, y - (12 - Math.abs(j) * 2) * scale);
        ctx.stroke();
      }
    }
  }
  ctx.restore();
}
export function drawUnderlay(ctx, world, camera, width, height, view) {
  const time = world.time,
    byPid = world.byPid();
  if (view.habitat !== false) {
    const sea = seaAppearance(new Date(), view.seaTime);
    const water = ctx.createLinearGradient(0, 0, 0, height);
    water.addColorStop(0, seaRgb(sea.top));
    water.addColorStop(1, seaRgb(sea.bottom));
    ctx.fillStyle = water;
    ctx.fillRect(0, 0, width, height);
    habitat(ctx, width, height, time, camera, world.quality, sea);
  }
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
    if (
      f.p.memory_percent >= 20 &&
      (Math.floor(f.age) % 30 === 0 || seed % 10 === 0)
    ) {
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
  const selected = world.selected(),
    conversations = [];
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
    if (world.quality !== "minimal" && f.talk > 0 && f.message)
      conversations.push({
        fish: f,
        x: p.x,
        y: p.y,
        size,
        selected: f === selected,
      });
  }
  view.bubbles = layoutConversations(conversations, width, height);
  for (const b of view.bubbles) {
    // A little chat puff, with its tail pointing toward the speaker. The
    // message/partner data stays on the hit region; no status label covers it.
    const bodyHeight = b.h - 6;
    const tail = clamp(b.anchorX - b.x, 12, b.w - 12);
    ctx.fillStyle = "#071c2955";
    ctx.beginPath();
    ctx.roundRect(b.x, b.y + 2, b.w, bodyHeight, 11);
    ctx.fill();
    ctx.fillStyle = b.fish === selected ? "#fff6d9" : "#ece8d0";
    ctx.strokeStyle = b.fish === selected ? "#adb98a" : "#969c7e";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.roundRect(b.x, b.y, b.w, bodyHeight, 11);
    ctx.fill();
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(b.x + tail - 4, b.y + bodyHeight - 1);
    ctx.lineTo(b.x + tail - 2, b.y + b.h - 1);
    ctx.quadraticCurveTo(
      b.x + tail + 3,
      b.y + b.h - 2,
      b.x + tail + 5,
      b.y + bodyHeight - 1,
    );
    ctx.fill();
    ctx.stroke();
    for (let i = 0; i < 3; i++) {
      const bounce = Math.max(
        0,
        Math.sin(world.time * 5 - i * 0.8 + b.fish.p.pid),
      );
      ctx.fillStyle = ["#ac9474", "#87a17d", "#bb967e"][i];
      circle(
        ctx,
        b.x + b.w / 2 + (i - 1) * 9,
        b.y + bodyHeight / 2 - bounce * 2,
        2.5,
      );
      ctx.fill();
    }
  }
}
export function layoutConversations(candidates, width, height) {
  const groups = new Map();
  candidates.sort((a, b) => Number(b.selected) - Number(a.selected));
  for (const candidate of candidates) {
    const key = `${Math.floor(candidate.x / 90)},${Math.floor(candidate.y / 65)}`;
    const group = groups.get(key) || {
      ...candidate,
      members: [],
      partners: new Set(),
    };
    group.members.push(candidate.fish);
    for (const pid of candidate.fish.partners) group.partners.add(pid);
    groups.set(key, group);
  }
  const result = [];
  const overlaps = (a, b) =>
    a.x < b.x + b.w + 4 &&
    a.x + a.w + 4 > b.x &&
    a.y < b.y + b.h + 4 &&
    a.y + a.h + 4 > b.y;
  for (const group of groups.values()) {
    const message =
      group.members.length > 1
        ? `通信中 · ${group.members.length}`
        : group.fish.message;
    const w = 46,
      h = 30;
    let box = null;
    for (const [ox, oy] of [
      [0, 0],
      [0, -32],
      [w / 2 + 12, 0],
      [-w / 2 - 12, 0],
      [0, -64],
    ]) {
      const candidate = {
        x: clamp(group.x - w / 2 + ox, 5, width - w - 5),
        y: clamp(group.y - group.size - h - 12 + oy, 5, height - h - 5),
        w,
        h,
      };
      if (!result.some((b) => overlaps(candidate, b))) {
        box = candidate;
        break;
      }
    }
    if (!box) {
      // Dense schools share a single clickable conversation marker. Every
      // partner remains discoverable through that marker and fish inspection.
      const nearest = result.reduce((a, b) =>
        Math.hypot(a.anchorX - group.x, a.anchorY - group.y) <
        Math.hypot(b.anchorX - group.x, b.anchorY - group.y)
          ? a
          : b,
      );
      nearest.members.push(...group.members);
      nearest.partners = [...new Set([...nearest.partners, ...group.partners])];
      nearest.message = `通信中 · ${nearest.members.length}`;
      continue;
    }
    result.push({
      ...box,
      message,
      fish: group.fish,
      members: group.members,
      partners: [...group.partners],
      anchorX: group.x,
      anchorY: group.y - group.size * 0.5,
    });
  }
  return result;
}
