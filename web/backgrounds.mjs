// Background providers know nothing about navigation. A future image/video or
// animated habitat implements the same draw(ctx, frame) interface; galaxy
// portals reveal that exact background as the observer approaches.
import { TAU } from "./fish.mjs";
import { drawTide } from "./tides.mjs";
const smooth = (x) => {
  x = Math.max(0, Math.min(1, x));
  return x * x * (3 - 2 * x);
};
import { habitat, seaAppearance } from "./effects.mjs";
export const BACKGROUNDS = {
  kelp: {
    name: "こもれびの海",
    top: "#174a58",
    bottom: "#0a222e",
    glow: "#b6dbbb",
  },
  lagoon: {
    name: "あおい入り江",
    top: "#235367",
    bottom: "#0a203e",
    glow: "#94cbdc",
  },
  dusk: {
    name: "ゆうぐれの海",
    top: "#51404f",
    bottom: "#191f38",
    glow: "#e5b9a8",
  },
};
export function backgroundFrame(tank, camera, width, height, time, wallTime, options = {}) {
  return {
    seed: tank.sky.seed,
    camera,
    width,
    height,
    time,
    quality: tank.world.quality,
    tide: options.communication === false ? null : tank.tide,
    transfers: tank.transferDirections,
    reducedMotion: Boolean(options.reducedMotion),
    seaTime: tank.background.seaTime || "auto",
    wallTime: wallTime.getTime(),
  };
}
// Store only two palettes at a time. A capped raster scale keeps large and
// Retina viewports from allocating several full-resolution scene textures.
const oceans = new Map();
function ocean(ctx, frame, palette) {
  const { width: w, height: h, time, camera, quality } = frame;
  const ratio = Math.min(globalThis.devicePixelRatio || 1, 1.5);
  const sea = seaAppearance(new Date(Math.floor(frame.wallTime / 30000) * 30000), frame.seaTime);
  const channels = (hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  const blend = (color, hex) => {
    const target = channels(hex);
    return color.map((v, i) => Math.round(v * 0.6 + target[i] * 0.4));
  };
  sea.top = blend(sea.top, palette.top);
  sea.bottom = blend(sea.bottom, palette.bottom);
  sea.light = blend(sea.light, palette.glow);
  const key = JSON.stringify([w, h, ratio, quality, palette.top, sea]);
  let cached = oceans.get(key);
  if (!cached) {
    const base = surface(Math.ceil(w * ratio), Math.ceil(h * ratio));
    const paint = base.getContext("2d");
    paint.scale(ratio, ratio);
    const gradient = paint.createLinearGradient(0, 0, 0, h);
    gradient.addColorStop(0, `rgb(${sea.top.join(",")})`);
    gradient.addColorStop(1, `rgb(${sea.bottom.join(",")})`);
    paint.fillStyle = gradient;
    paint.fillRect(0, 0, w, h);
    if (quality !== "minimal") {
      const glow = paint.createRadialGradient(w * 0.35, -h * 0.2, 0,
        w * 0.35, -h * 0.2, h * 1.2);
      glow.addColorStop(0, palette.glow + "32");
      glow.addColorStop(1, palette.glow + "00");
      paint.fillStyle = glow;
      paint.fillRect(0, 0, w, h);
    }
    const fixedCamera = { x: 0 };
    habitat(paint, w, h, 0, fixedCamera, quality, sea, "base");
    // Rocks and shells occupy just the bottom strip, not another full canvas.
    const frontY = Math.floor(h * 0.8);
    const front = surface(Math.ceil(w * ratio), Math.ceil((h - frontY) * ratio));
    const detail = front.getContext("2d");
    detail.scale(ratio, ratio);
    detail.translate(0, -frontY);
    habitat(detail, w, h, 0, fixedCamera, quality, sea, "foreground");
    cached = { base, front, frontY };
    oceans.set(key, cached);
    if (oceans.size > 2) oceans.delete(oceans.keys().next().value);
  }
  ctx.drawImage(cached.base, 0, 0, w, h);
  // Currents remain live between the cached scenery and foreground plants.
  // Never bake measured traffic into the static background texture.
  drawTide(ctx, frame, palette.glow);
  habitat(ctx, w, h, time, camera, quality, sea, "plants");
  const parallax = Math.sin(camera.x / 900) * 18 * Math.min(1.3, h / 780, w / 850);
  ctx.drawImage(cached.front, parallax, cached.frontY, w, h - cached.frontY);
}
const providers = new Map(
  Object.entries(BACKGROUNDS).map(([id, p]) => [
    id,
    (ctx, frame) => ocean(ctx, frame, p),
  ]),
);
export function drawBackground(ctx, descriptor, frame) {
  (providers.get(descriptor.kind) || providers.get("kelp"))(ctx, frame);
}
function random(seed) {
  let n = seed;
  return () => {
    n = (Math.imul(n, 1664525) + 1013904223) >>> 0;
    return n / 4294967296;
  };
}
const fields = new Map();
function field(seed) {
  if (!fields.has(seed)) {
    const r = random(seed);
    fields.set(
      seed,
      Array.from({ length: 180 }, () => [r(), r(), r(), r()]),
    );
    if (fields.size > 129) fields.delete(fields.keys().next().value);
  }
  return fields.get(seed);
}
export function drawSpace(ctx, w, h, time, depth, focus) {
  ctx.fillStyle = "#151e2e";
  ctx.fillRect(0, 0, w, h);
  const center = focus || { x: w / 2, y: h / 2 };
  for (const [x, y, size, phase] of field(317)) {
    const scale = 1 + depth * 3,
      px = (x * w - center.x) * scale + center.x,
      py = (y * h - center.y) * scale + center.y;
    ctx.globalAlpha =
      (0.15 + size * 0.45) *
      (1 - depth) *
      (0.85 + 0.15 * Math.sin(time * 0.3 + phase * TAU));
    ctx.fillStyle = size > 0.8 ? "#d8ddc8" : "#abbcd6";
    ctx.beginPath();
    ctx.arc(px, py, 0.45 + size * 1.05, 0, TAU);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}
export function portalClip(rect, depth = 0) {
  const growth = 1 + depth * depth * 0.6;
  return {
    x: rect.x + rect.width / 2,
    y: rect.y + rect.height / 2,
    rx: rect.width * 0.5 * growth,
    ry: rect.height * 0.5 * growth,
  };
}
export function clipPortal(ctx, clip) {
  ctx.beginPath();
  ctx.ellipse(clip.x, clip.y, clip.rx, clip.ry, 0, 0, TAU);
  ctx.clip();
}
// Rasterize soft spiral clouds once per seed; keep animation cheap even with
// six galaxies. Rounded stars and muted sea-glass colours match the game HUD.
const nebulae = new Map();
function surface(width, height) {
  const canvas =
    typeof OffscreenCanvas === "function"
      ? new OffscreenCanvas(width, height)
      : document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  return canvas;
}
function nebula(sky) {
  if (nebulae.has(sky.seed)) return nebulae.get(sky.seed);
  const canvas = surface(640, 480),
    ctx = canvas.getContext("2d"),
    r = random(sky.seed);
  ctx.translate(320, 240);
  ctx.scale(1, 0.65);
  // Very soft, overlapping wisps instead of a bounded disk or a ring.
  for (let arm = 0; arm < 3; arm++)
    for (let i = 0; i < 52; i++) {
      const u = i / 52,
        angle = u * 5 + (arm * TAU) / 3 + (sky.seed % 9);
      const radius = 18 + u * 216,
        x = Math.cos(angle) * radius,
        y = Math.sin(angle) * radius;
      const size = 18 + u * 24,
        glow = ctx.createRadialGradient(x, y, 0, x, y, size);
      glow.addColorStop(0, sky.cloud + "13");
      glow.addColorStop(0.45, sky.cloud + "09");
      glow.addColorStop(1, sky.cloud + "00");
      ctx.fillStyle = glow;
      ctx.fillRect(x - size, y - size, size * 2, size * 2);
    }
  const core = ctx.createRadialGradient(0, 0, 0, 0, 0, 100);
  core.addColorStop(0, sky.light + "68");
  core.addColorStop(0.25, sky.light + "2a");
  core.addColorStop(1, sky.light + "00");
  ctx.fillStyle = core;
  ctx.fillRect(-100, -100, 200, 200);
  for (let i = 0; i < 95; i++) {
    const u = r(),
      a =
        u * 5 +
        (Math.floor(r() * 3) * TAU) / 3 +
        (sky.seed % 9) +
        (r() - 0.5) * 0.7;
    const radius = 15 + u * 215,
      x = Math.cos(a) * radius,
      y = Math.sin(a) * radius;
    ctx.globalAlpha = 0.12 + r() * 0.4;
    ctx.fillStyle = i % 4 ? "#e3dfc8" : sky.light;
    ctx.beginPath();
    ctx.ellipse(x, y, 0.8 + r(), 1.2 + r(), 0, 0, TAU);
    ctx.fill();
  }
  nebulae.set(sky.seed, canvas);
  if (nebulae.size > 12) nebulae.delete(nebulae.keys().next().value);
  return canvas;
}
export function drawGalaxy(ctx, tank, rect, depth, time) {
  ctx.save();
  ctx.globalAlpha = 1 - smooth(depth);
  const drift = Math.sin(time * 0.07 + tank.sky.seed) * 2;
  ctx.drawImage(
    nebula(tank.sky),
    rect.x - rect.width * 0.25,
    rect.y - rect.height * 0.25 + drift,
    rect.width * 1.5,
    rect.height * 1.5,
  );
  ctx.restore();
}
let backgroundSurface;
export function drawPortalBackground(
  ctx,
  tank,
  rect,
  depth,
  camera,
  time,
  wallTime,
  width,
  height,
  options = {},
) {
  drawGalaxy(ctx, tank, rect, depth, time);
  if (depth <= 0.08) return;
  const ratio = Math.min(globalThis.devicePixelRatio || 1, 1.5),
    w = Math.round(width * ratio),
    h = Math.round(height * ratio);
  backgroundSurface ||= surface(w, h);
  if (backgroundSurface.width !== w) backgroundSurface.width = w;
  if (backgroundSurface.height !== h) backgroundSurface.height = h;
  const paint = backgroundSurface.getContext("2d");
  paint.setTransform(ratio, 0, 0, ratio, 0, 0);
  paint.clearRect(0, 0, width, height);
  // Always cover the viewport, then reveal it through a feathered mask. No
  // rectangular texture edge can emerge as the portal grows or changes aspect.
  const cx = rect.x + rect.width / 2,
    cy = rect.y + rect.height / 2,
    scale = 1.2 - 0.2 * depth;
  paint.save();
  paint.translate(cx * (1 - scale), cy * (1 - scale));
  paint.scale(scale, scale);
  drawBackground(
    paint,
    tank.background,
    backgroundFrame(tank, camera, width, height, time, wallTime, options),
  );
  paint.restore();
  paint.save();
  paint.globalCompositeOperation = "destination-in";
  const grow = 1 + 1.6 * depth ** 3,
    rx = rect.width * 0.55 * grow,
    ry = rect.height * 0.55 * grow;
  paint.translate(cx, cy);
  paint.scale(rx, ry);
  const mask = paint.createRadialGradient(0, 0, 0, 0, 0, 1);
  mask.addColorStop(0, "#fff");
  mask.addColorStop(0.5, "#fff");
  mask.addColorStop(0.72, "#ffffffbb");
  mask.addColorStop(1, "#ffffff00");
  paint.fillStyle = mask;
  paint.fillRect(
    -width / rx - 2,
    -height / ry - 2,
    (width / rx) * 2 + 4,
    (height / ry) * 2 + 4,
  );
  paint.restore();
  ctx.save();
  ctx.globalAlpha = smooth((depth - 0.08) / 0.8);
  ctx.drawImage(backgroundSurface, 0, 0, width, height);
  ctx.restore();
}
