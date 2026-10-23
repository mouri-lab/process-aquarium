// Interface activity becomes ambient water motion, never fish-to-fish paths.
import { TAU, hash } from "./fish.mjs";

export function validateActivity(a) {
  if (a == null) return;
  const states = ["ready", "warming", "unavailable", "ambiguous", "denied", "unsupported", "error"];
  const bytes = (v) => v === null || (Number.isSafeInteger(v) && v >= 0);
  if (typeof a !== "object" || !states.includes(a.status) ||
      a.scope !== "interface" || a.source !== "psutil" ||
      typeof a.interface !== "string" || a.interface.length > 128 ||
      (["ready", "warming"].includes(a.status) && !a.interface) ||
      (a.status === "ready"
        ? !Number.isFinite(a.interval_seconds) || a.interval_seconds <= 0 ||
          !bytes(a.sent_bytes) || !bytes(a.received_bytes) ||
          (a.sent_bytes === null && a.received_bytes === null)
        : [a.interval_seconds, a.sent_bytes, a.received_bytes].some((v) => v != null)))
    throw new Error("Invalid network activity");
}

export function activityStrength(bytes, seconds) {
  if (bytes === null) return 0; // Unknown stays unknown in telemetry.
  return Math.min(1, Math.log1p(bytes / seconds / 1024) / Math.log1p(10240));
}

export class Tide {
  constructor() {
    this.identity = null;
    this.revision = null;
    this.expires = -Infinity;
    this.sent = this.received = 0;
    this.targetSent = this.targetReceived = 0;
    this.phase = 0;
  }
  accept(snapshot, now) {
    const a = snapshot.network_activity;
    validateActivity(a);
    const revision = JSON.stringify([snapshot.host_id, snapshot.boot_id, snapshot.session_id, snapshot.sequence]);
    const identity = JSON.stringify([snapshot.host_id, snapshot.boot_id, snapshot.session_id, a?.interface]);
    this.acceptSample(identity, revision, snapshot.error ? null : a, now);
  }
  // Wire validation belongs to each caller; all activity shares this smoother.
  acceptSample(identity, revision, a, now) {
    if (revision === this.revision) return;
    this.revision = revision;
    if (identity !== this.identity) {
      this.sent = this.received = 0;
      this.identity = identity;
    }
    this.targetSent = this.targetReceived = 0;
    this.expires = -Infinity;
    if (a?.status === "ready") {
      this.targetSent = activityStrength(a.sent_bytes, a.interval_seconds);
      this.targetReceived = activityStrength(a.received_bytes, a.interval_seconds);
      this.expires = now + Math.max(5000, Math.min(30000, a.interval_seconds * 3000));
    }
  }
  step(dt, now, { live = true, paused = false, reduced = false } = {}) {
    if (paused) return;
    const fresh = live && now < this.expires;
    const blend = 1 - Math.exp(-Math.max(0, dt) / 3.5);
    this.sent += ((fresh ? this.targetSent : 0) - this.sent) * blend;
    this.received += ((fresh ? this.targetReceived : 0) - this.received) * blend;
    // Transfer volume changes opacity, never the speed of the water.
    if (!reduced) this.phase = (this.phase + Math.max(0, dt) / 64) % 1;
  }
}

const fraction = (n) => n - Math.floor(n);
export function scatter(value) {
  // Avalanche neighbouring indices; raw string hashes put adjacent motes in
  // little dotted rows, which would look like the discarded connection paths.
  let n = hash(value);
  n = Math.imul(n ^ (n >>> 16), 0x7feb352d);
  n = Math.imul(n ^ (n >>> 15), 0x846ca68b);
  return ((n ^ (n >>> 16)) >>> 0) / 2 ** 32;
}
export function tideMote(seed, index, phase, outgoing, angle = null) {
  const a = scatter(`${seed}:${index}`);
  const b = scatter(`${seed}:depth:${index}`);
  const u = fraction(phase + a);
  const point = {
    // Receive from the left, release to the right. These are visual directions,
    // not geographical locations or a claim about any particular peer.
    x: (outgoing ? 0.25 : -0.2) + u * 0.95,
    y: 0.14 + b * 0.65 + Math.sin(u * TAU + b * 3) * 0.045,
    alpha: Math.sin(Math.PI * u) ** 2,
    radius: 0.8 + b * 1.3,
  };
  if (angle !== null) {
    const distance = outgoing ? .15 + u : 1.15 - u;
    const lane = (b - .5) * .40 + Math.sin(u * TAU + b) * .035;
    point.x = .5 + Math.cos(angle) * distance * .65 - Math.sin(angle) * lane;
    point.y = .48 + Math.sin(angle) * distance * .65 + Math.cos(angle) * lane;
  }
  return point;
}

// Cache one feathered light patch per palette. No full-screen blur filters or
// per-pixel work on each frame; Canvas underlays also serve the WebGPU client.
const lights = new Map();
export function lightPatch(color) {
  if (lights.has(color)) return lights.get(color);
  const canvas = typeof OffscreenCanvas === "function"
    ? new OffscreenCanvas(192, 192) : document.createElement("canvas");
  canvas.width = canvas.height = 192;
  const ctx = canvas.getContext("2d");
  const glow = ctx.createRadialGradient(96, 96, 0, 96, 96, 96);
  glow.addColorStop(0, color + "ff");
  glow.addColorStop(0.35, color + "80");
  glow.addColorStop(0.7, color + "20");
  glow.addColorStop(1, color + "00");
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, 192, 192);
  lights.set(color, canvas);
  // Automatic lighting introduces new colours over the day; bound raster memory.
  if (lights.size > 12) lights.delete(lights.keys().next().value);
  return canvas;
}
export function drawTide(ctx, frame, color) {
  const tide = frame.tide;
  if (!tide || frame.quality === "minimal") return;
  const { width: w, height: h, seed } = frame;
  const phases = frame.transfers?.length ? frame.transfers.map(p => [p.strength, p.outgoing, p.angle])
    : [[tide.received, false, null], [tide.sent, true, null]];
  ctx.save();
  for (const [strength, outgoing, angle] of phases) {
    if (strength < 0.002) continue;
    const offset = outgoing ? 37 : 0;
    for (let i = 0; i < 3; i++) {
      const p = tideMote(seed, i * 13 + offset, tide.phase, outgoing, angle);
      ctx.globalAlpha = strength * p.alpha * 0.10;
      ctx.save();
      ctx.translate(p.x * w, p.y * h);
      ctx.rotate(angle ?? (-0.18 + Math.sin(p.y * 4) * 0.08));
      ctx.drawImage(lightPatch(color), -w * 0.42, -h * 0.19, w * 0.84, h * 0.38);
      ctx.restore();
    }
    if (frame.reducedMotion) continue;
    const count = frame.quality === "full" ? 24 : 12;
    ctx.fillStyle = color;
    for (let i = 0; i < count; i++) {
      const p = tideMote(seed, i + offset, tide.phase, outgoing, angle);
      ctx.globalAlpha = strength * p.alpha * 0.28;
      ctx.beginPath();
      ctx.ellipse(p.x * w, p.y * h, p.radius * 1.4, p.radius, -0.18, 0, TAU);
      ctx.fill();
    }
  }
  ctx.restore();
}
