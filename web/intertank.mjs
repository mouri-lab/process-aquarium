// Explicit fixtures and server-resolved measured peers. Never infer these paths
// from interface totals, socket counts, or the positions of real hosts.
import { Tide, lightPatch, scatter } from "./tides.mjs";
import { TAU, hash } from "./fish.mjs";

export function validateTransfers(snapshot) {
  const list = snapshot.simulated_transfers ?? [];
  if (!Array.isArray(list) || list.length > 32 || (list.length && snapshot.source !== "fixture"))
    throw new Error("Invalid simulated transfers");
  const seen = new Set();
  const id = (s) => typeof s === "string" && s.length > 0 && s.length <= 128;
  for (const p of list) {
    if (!p || !id(p.host_id) || !id(p.boot_id) || p.host_id === snapshot.host_id ||
        seen.has(p.host_id) || !Number.isFinite(p.interval_seconds) || p.interval_seconds <= 0 ||
        ![p.sent_bytes, p.received_bytes].every(n => Number.isSafeInteger(n) && n >= 0))
      throw new Error("Invalid simulated transfer");
    seen.add(p.host_id);
  }
}

export class TransferField {
  constructor() { this.peers = new Map(); this.identity = null; }
  accept(snapshot, now) {
    const identity = JSON.stringify([snapshot.host_id, snapshot.boot_id, snapshot.session_id]);
    if (identity !== this.identity) this.peers.clear();
    this.identity = identity;
    const incoming = new Set();
    for (const p of snapshot.simulated_transfers || []) {
      incoming.add(p.host_id);
      let peer = this.peers.get(p.host_id);
      if (!peer || peer.boot !== p.boot_id) {
        peer = { host: p.host_id, boot: p.boot_id, tide: new Tide() };
        this.peers.set(p.host_id, peer);
      }
      peer.tide.accept({ ...snapshot, network_activity: {
        scope: "interface", source: "psutil", status: "ready", interface: p.host_id,
        interval_seconds: p.interval_seconds, sent_bytes: p.sent_bytes, received_bytes: p.received_bytes,
      }}, now);
    }
    for (const [id, peer] of this.peers) {
      if (peer.measured && snapshot.source !== "fixture") continue;
      if (!incoming.has(id)) peer.tide.expires = -Infinity;
      if (!incoming.has(id) && (peer.tide.sent + peer.tide.received < .002 || this.peers.size > 64))
        this.peers.delete(id);
    }
  }
  step(dt, now, options, tanks) {
    for (const peer of this.peers.values()) {
      const target = tanks.find(t => t.host === peer.host);
      const live = options.live && target?.freshness.mode === "live" &&
        target.world.snapshot?.boot_id === peer.boot &&
        (peer.measured ? target.world.snapshot?.session_id === peer.session &&
          target.world.snapshot?.source !== "fixture" : target.world.snapshot?.source === "fixture");
      if (peer.measured) {
        peer.outgoing.step(dt, now, { ...options, live });
        peer.incoming.step(dt, now, { ...options, live });
        Object.assign(peer.tide, { sent: peer.outgoing.sent, received: peer.incoming.sent,
          phase: peer.outgoing.phase });
      } else peer.tide.step(dt, now, { ...options, live });
    }
  }
}

export function validateMeasuredTransfers(list) {
  if (!Array.isArray(list) || list.length > 512) throw new Error("Invalid measured transfers");
  const text = s => typeof s === "string" && s.length > 0 && s.length <= 128;
  const identity = p => p && [p.host_id, p.boot_id, p.session_id].every(text);
  const same = (a, b) => ["host_id", "boot_id", "session_id"].every(k => a[k] === b[k]);
  const seen = new Set();
  for (const p of list) {
    if (!p || !identity(p.source) || !identity(p.target) || !identity(p.observer) ||
        p.source.host_id === p.target.host_id ||
        (!same(p.observer, p.source) && !same(p.observer, p.target)) ||
        !text(p.observer.interface) || !Number.isSafeInteger(p.observer.sequence) || p.observer.sequence < 1 ||
        !text(p.network_scope) || p.byte_basis !== "observed_ip" ||
        !Number.isSafeInteger(p.bytes) || p.bytes < 0 ||
        !Number.isFinite(p.interval_seconds) || p.interval_seconds <= 0 ||
        !Number.isFinite(p.age_seconds) || p.age_seconds < 0)
      throw new Error("Invalid measured transfer");
    const key = JSON.stringify([p.source.host_id, p.target.host_id]);
    if (seen.has(key)) throw new Error("Duplicate measured direction");
    seen.add(key);
  }
}

export function applyMeasuredTransfers(tanks, list, now) {
  validateMeasuredTransfers(list); // Validate the complete response before mutation.
  const byHost = new Map(tanks.map(t => [t.host, t]));
  const updated = new Set();
  const matches = (tank, id) => tank?.world.snapshot?.source !== "fixture" &&
    tank?.world.snapshot?.boot_id === id.boot_id && tank?.world.snapshot?.session_id === id.session_id;
  for (const p of list) {
    const source = byHost.get(p.source.host_id), target = byHost.get(p.target.host_id);
    if (!matches(source, p.source) || !matches(target, p.target) || source.source !== target.source) continue;
    const [owner, other] = [source, target].sort((a, b) => a.host.localeCompare(b.host));
    let peer = owner.transfers.peers.get(other.host);
    const snapshot = other.world.snapshot;
    if (!peer?.measured || peer.boot !== snapshot.boot_id || peer.session !== snapshot.session_id) {
      peer = { measured: true, host: other.host, boot: snapshot.boot_id, session: snapshot.session_id,
        tide: new Tide(), outgoing: new Tide(), incoming: new Tide() };
      owner.transfers.peers.set(other.host, peer);
    }
    const tide = owner === source ? peer.outgoing : peer.incoming;
    const identity = JSON.stringify([p.source, p.target, p.network_scope,
      p.observer.host_id, p.observer.boot_id, p.observer.session_id, p.observer.interface]);
    tide.acceptSample(identity, JSON.stringify([identity, p.observer.sequence]), {
      status: "ready", interval_seconds: p.interval_seconds, sent_bytes: p.bytes, received_bytes: 0,
    }, now - p.age_seconds * 1000);
    updated.add(tide);
  }
  for (const tank of tanks) for (const [id, peer] of tank.transfers.peers) {
    if (!peer.measured) continue;
    for (const tide of [peer.outgoing, peer.incoming])
      if (!updated.has(tide)) tide.expires = -Infinity;
    if (!updated.has(peer.outgoing) && !updated.has(peer.incoming) &&
        peer.tide.sent + peer.tide.received < .002) tank.transfers.peers.delete(id);
  }
}

export function transferLinks(tanks, rects) {
  const visible = new Map(tanks.map((tank, i) => [tank.host, { tank, rect: rects[i] }]));
  const links = [], seen = new Set();
  for (const source of [...tanks].sort((a, b) => a.host.localeCompare(b.host))) {
    for (const peer of source.transfers.peers.values()) {
      const target = visible.get(peer.host);
      if (!target?.rect || target.tank.source !== source.source ||
          target.tank.world.snapshot?.boot_id !== peer.boot ||
          (peer.measured ? target.tank.world.snapshot?.session_id !== peer.session ||
            source.world.snapshot?.source === "fixture" || target.tank.world.snapshot?.source === "fixture"
            : source.world.snapshot?.source !== "fixture" || target.tank.world.snapshot?.source !== "fixture")) continue;
      const key = JSON.stringify([source.host, peer.host].sort());
      if (seen.has(key)) continue;
      seen.add(key);
      links.push({ key, seed: hash(key), source, target: target.tank,
        a: visible.get(source.host).rect, b: target.rect,
        sent: peer.tide.sent, received: peer.tide.received, phase: peer.tide.phase });
    }
  }
  return links.slice(0, 18);
}

export function transferDirections(tank, links) {
  const result = [];
  for (const link of links) {
    if (tank !== link.source && tank !== link.target) continue;
    const owner = tank === link.source;
    const angle = Math.atan2(link.b.centerY - link.a.centerY, link.b.centerX - link.a.centerX) + (owner ? 0 : Math.PI);
    result.push({ strength: owner ? link.sent : link.received, outgoing: true, angle },
      { strength: owner ? link.received : link.sent, outgoing: false, angle });
  }
  return result.sort((a, b) => b.strength - a.strength).slice(0, 6);
}

export function streamPoint(link, u, time, lane = 0) {
  const dx = link.b.centerX - link.a.centerX, dy = link.b.centerY - link.a.centerY;
  const length = Math.max(1, Math.hypot(dx, dy));
  const nx = -dy / length, ny = dx / length;
  const bend = Math.sin(u * Math.PI) * (Math.min(65, length * .18) + Math.sin(time * .15 + link.seed) * 7);
  return { x: link.a.centerX + dx * u + nx * (bend + lane),
    y: link.a.centerY + dy * u + ny * (bend + lane), angle: Math.atan2(dy, dx) };
}

export function streamWidth(link) {
  const strength = Math.max(link.sent, link.received);
  const room = Math.max(24, Math.min(90, link.a.width * .30, link.b.width * .30));
  return room * (.3 + .7 * Math.sqrt(strength));
}

export function drawBetweenTides(ctx, links, time, { depth = 0, quality = "full", reduced = false } = {}) {
  if (quality === "minimal" || depth >= 1) return;
  ctx.save();
  const fade = 1 - depth * depth * (3 - 2 * depth);
  const flowTime = reduced ? 0 : time;
  for (const link of links) {
    const strength = Math.max(link.sent, link.received);
    if (strength < .002) continue;
    const width = streamWidth(link);
    // Overlapping feathered clouds form a broad current. No hard path or edge.
    for (let i = 0; i <= 24; i++) {
      const u = i / 24, p = streamPoint(link, u, flowTime);
      const swell = .85 + .15 * Math.sin(u * 10 - link.phase * TAU * 2);
      ctx.globalAlpha = fade * strength * .115 * Math.sin(Math.PI * u) ** .6;
      ctx.drawImage(lightPatch(i < 12 ? link.source.sky.light : link.target.sky.light),
        p.x - width * 1.5, p.y - width * swell, width * 3, width * 2 * swell);
    }
    if (reduced) continue;
    for (const [outgoing, intensity] of [[true, link.sent], [false, link.received]]) {
      const count = quality === "full" ? 26 : 12;
      for (let i = 0; i < count; i++) {
        const seed = `${link.key}:${outgoing}:${i}`;
        let u = (scatter(seed) + link.phase) % 1;
        if (!outgoing) u = 1 - u;
        const lane = (scatter(seed + "lane") - .5) * width * 1.35;
        const p = streamPoint(link, u, flowTime, lane);
        ctx.globalAlpha = fade * intensity * Math.sin(Math.PI * u) ** 2 * .45;
        ctx.fillStyle = outgoing ? link.source.sky.light : link.target.sky.light;
        ctx.beginPath();
        ctx.ellipse(p.x, p.y, 1.5 + scatter(seed + "size"), .9, p.angle, 0, TAU);
        ctx.fill();
      }
    }
  }
  ctx.restore();
}
