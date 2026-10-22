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
function habitat(ctx, width, height, time, camera, quality) {
  if (quality !== "minimal") {
    // Broad, quiet shafts of light; their drift follows the animation clock.
    for (let i = 0; i < 3; i++) {
      const x = width * (0.12 + i * 0.33) + Math.sin(time * 0.09 + i) * 16;
      const light = ctx.createLinearGradient(
        x,
        0,
        x + width * 0.13,
        height * 0.9,
      );
      light.addColorStop(0, "rgba(211,237,205,.055)");
      light.addColorStop(1, "rgba(211,237,205,0)");
      ctx.fillStyle = light;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x + width * 0.06, 0);
      ctx.lineTo(x + width * 0.27, height);
      ctx.lineTo(x + width * 0.08, height);
      ctx.closePath();
      ctx.fill();
    }
  }
  const floor = height - Math.min(30, height * 0.045);
  ctx.fillStyle = "#294e50";
  ctx.beginPath();
  ctx.moveTo(0, floor - 10);
  ctx.bezierCurveTo(
    width * 0.3,
    floor + 22,
    width * 0.72,
    floor - 7,
    width,
    floor,
  );
  ctx.lineTo(width, height);
  ctx.lineTo(0, height);
  ctx.closePath();
  ctx.fill();
  if (quality === "minimal") return;
  const scale = Math.min(1, height / 650, width / 700);
  const parallax = Math.sin(camera.x / 900) * 16;
  const plants = [
    [42, 76, 1],
    [78, 115, -1],
    [106, 55, 1],
    [width - 74, 83, -1],
    [width - 39, 55, 1],
  ];
  for (const [base, tall, direction] of plants) {
    const x = base + parallax;
    const h = tall * scale;
    const sway = Math.sin(time * 0.36 + base) * 5 * scale;
    ctx.strokeStyle = "#4b7770";
    ctx.lineWidth = 3 * scale;
    ctx.lineCap = "round";
    ctx.beginPath();
    ctx.moveTo(x, floor + 8);
    ctx.quadraticCurveTo(
      x - direction * 12 * scale,
      floor - h * 0.6,
      x + sway,
      floor - h,
    );
    ctx.stroke();
    for (let j = 1; j <= 4; j++) {
      const side = j % 2 ? -1 : 1;
      const y = floor - (h * j) / 5;
      const stem = x + (sway * j) / 5 - direction * 4 * scale;
      ctx.fillStyle = j % 2 ? "#426c64" : "#507e6c";
      ctx.beginPath();
      ctx.moveTo(stem, y);
      ctx.quadraticCurveTo(
        stem + side * 25 * scale,
        y - 3 * scale,
        stem + side * 17 * scale,
        y - 20 * scale,
      );
      ctx.quadraticCurveTo(stem + side * 3 * scale, y - 16 * scale, stem, y);
      ctx.fill();
    }
  }
  // A few pebbles settle the corners without taking space away from the fish.
  for (const [x, y, rx, ry] of [
    [25, floor + 9, 19, 8],
    [102, floor + 14, 14, 6],
    [width - 50, floor + 9, 23, 9],
  ]) {
    ctx.fillStyle = "#52665a";
    ctx.beginPath();
    ctx.ellipse(x, y, rx * scale, ry * scale, -0.1, 0, TAU);
    ctx.fill();
  }
}
export function drawUnderlay(ctx, world, camera, width, height, view) {
  const time = world.time,
    byPid = world.byPid();
  if (view.habitat !== false)
    habitat(ctx, width, height, time, camera, world.quality);
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
