// Host state belongs to a tank, not to the currently focused viewport.
import { AquariumWorld, keyOf } from './world.mjs';
import { Camera } from './controls.mjs';
import { hash } from './fish.mjs';
export const tankKey = (source, host) => JSON.stringify([source, host]);
export const processRef = (tank, p) => ({ tank: tank.id, boot: tank.world.snapshot.boot_id, pid: p.pid, started: p.create_time });
export const PALETTES = [
  ['#122d42', '#091322', '#8fd5cd', '#6494d9'],
  ['#29223d', '#100f22', '#c4a5da', '#799ad5'],
  ['#283634', '#0b1b24', '#b9d5a6', '#6da7ab'],
  ['#3c2c36', '#180f22', '#e2bd9c', '#ae82b5'],
  ['#1c3047', '#0b1328', '#a6bfe5', '#927dcb'],
  ['#353440', '#141827', '#d6d4a7', '#8cabbf'],
];
export function skyFor(id) {
  const seed = hash(id), colors = PALETTES[seed % PALETTES.length];
  return { seed, top: colors[0], bottom: colors[1], light: colors[2], cloud: colors[3] };
}
export class Tank {
  constructor(source, host) {
    this.id = tankKey(source, host);
    this.source = source; this.host = host; this.name = host;
    this.world = new AquariumWorld(); this.camera = new Camera();
    this.sky = skyFor(this.id);
    this.freshness = { mode: 'waiting', error: '', last: 0 };
    this.listed = false; this.search = '';
  }
  apply(envelope, now) {
    if (envelope.snapshot?.host_id !== this.host || typeof envelope.stale !== 'boolean')
      throw new Error('Unexpected telemetry host or freshness status');
    const before = this.world.snapshot;
    const changed = this.world.apply(envelope.snapshot);
    if (changed) {
      this.freshness.last = now;
      this.name = envelope.snapshot.hostname;
      if (before && before.boot_id !== envelope.snapshot.boot_id) this.camera.reset();
    }
    Object.assign(this.freshness, { mode: envelope.stale ? 'stale' : 'live', error: envelope.error || '' });
    return changed;
  }
}
export class Multiverse {
  constructor(source = 'local', capacity = 128) {
    this.source = source; this.capacity = capacity;
    this.tanks = new Map(); this.active = null;
    this.overview = false; this.page = 0;
  }
  ensure(host) {
    const id = tankKey(this.source, host);
    if (!this.tanks.has(id)) {
      if (this.tanks.size >= this.capacity) {
        const evict = [...this.tanks.values()].find(t => !t.listed && t !== this.active);
        if (!evict) return null;
        this.tanks.delete(evict.id);
      }
      this.tanks.set(id, new Tank(this.source, host));
    }
    return this.tanks.get(id);
  }
  catalog(hosts) {
    if (!Array.isArray(hosts) || hosts.length > this.capacity || hosts.some(h => typeof h.host_id !== 'string' || !h.host_id || h.host_id.length > 128 || typeof h.hostname !== 'string') || new Set(hosts.map(h => h.host_id)).size !== hosts.length)
      throw new Error('Invalid host list');
    const incoming = new Set(hosts.map(h => tankKey(this.source, h.host_id)));
    for (const t of this.tanks.values()) {
      t.listed = incoming.has(t.id);
      if (!t.listed) Object.assign(t.freshness, { mode: 'offline', error: 'ホストからの更新を待っています' });
    }
    for (const h of hosts) {
      const t = this.ensure(h.host_id); if (!t) continue;
      t.name = h.hostname; t.listed = true;
      if (h.stale) t.freshness.mode = 'stale';
    }
    this.active ||= this.tanks.values().next().value || null;
    this.page = Math.min(this.page, this.pages - 1);
  }
  select(host) {
    const tank = this.ensure(host);
    if (tank) this.active = tank;
    return tank;
  }
  get ordered() { return [...this.tanks.values()]; }
  get pages() { return Math.max(1, Math.ceil(this.tanks.size / 6)); }
  get visible() { return this.overview ? this.ordered.slice(this.page * 6, this.page * 6 + 6) : this.active ? [this.active] : []; }
  resolve(ref) {
    const tank = this.tanks.get(ref.tank), snapshot = tank?.world.snapshot;
    if (!snapshot || snapshot.boot_id !== ref.boot) return null;
    const key = keyOf(snapshot, { pid: ref.pid, create_time: ref.started });
    const process = tank.world.processes.get(key);
    return process ? { tank, process, fish: tank.world.fish.get(key) || null } : null;
  }
  clear() { this.tanks.clear(); this.active = null; this.page = 0; }
}
// Same bounded layout is used by painting, pointer targets and future flow paths.
export function galaxyLayout(count, width, height) {
  if (!count) return [];
  const columns = width < 620 ? Math.min(2, count) : count <= 3 ? count : 3;
  const rows = Math.ceil(count / columns), pad = width < 620 ? 12 : 48;
  const available = Math.max(180, height - 116);
  const cellW = (width - pad * 2) / columns, cellH = available / rows;
  return Array.from({ length: count }, (_, i) => {
    const inRow = Math.min(columns, count - Math.floor(i / columns) * columns);
    const size = Math.max(40, Math.min(cellW - 22, cellH - 30, 360));
    const x = width / 2 + (i % columns - (inRow - 1) / 2) * cellW;
    const y = 62 + (Math.floor(i / columns) + .5) * cellH;
    return { x: x - size / 2, y: y - size * .39, width: size, height: size * .78, centerX: x, centerY: y };
  });
}
export function galaxyCamera(world, width, height) {
  const fish = [...world.fish.values()].filter(f => !f.dying);
  if (!fish.length) return { x: 0, y: 0, zoom: .3 };
  const x = fish.reduce((s, f) => s + f.x, 0) / fish.length;
  const y = fish.reduce((s, f) => s + f.y, 0) / fish.length;
  let radius = 180;
  for (const f of fish) radius = Math.max(radius, Math.hypot(f.x - x, f.y - y) + f.size * 4);
  return { x, y, zoom: Math.min(1, Math.min(width, height) * .43 / radius) };
}

// A failed agent never stalls its neighbours. The generation guard also covers
// responses that complete after credentials are replaced or forgotten.
export async function pollTanks(tanks, request, current, now) {
  const queue = [...tanks];
  await Promise.all(Array.from({length: Math.min(3, queue.length)}, async () => {
    while (queue.length && current()) {
      const tank = queue.shift();
      try {
        const envelope = await request(tank.host);
        if (current()) tank.apply(envelope, now());
      } catch (error) {
        if (!current()) return;
        if (error.authentication) throw error;
        Object.assign(tank.freshness, {mode:'offline', error:error.name === 'AbortError' ? '更新を待っています' : error.message});
      }
    }
  }));
}
export const smooth = x => { x = Math.max(0, Math.min(1, x)); return x*x*(3-2*x); };
export class Journey {
  constructor() { this.depth = 1; this.target = 1; this.start = 1; this.elapsed = 0; }
  go(target, immediate=false) { this.start=this.depth;this.target=target;this.elapsed=0;if(immediate)this.depth=target; }
  step(dt) { this.elapsed+=Math.max(0,dt);this.depth=this.start+(this.target-this.start)*smooth(this.elapsed/1.6);return this.depth; }
  get moving() { return this.depth !== this.target; }
}
export function transitionRect(rect, focus, depth, width, height) {
  const sx=1+(width/focus.width-1)*depth,sy=1+(height/focus.height-1)*depth;
  const x=(rect.centerX-focus.centerX)*sx+focus.centerX+(width/2-focus.centerX)*depth;
  const y=(rect.centerY-focus.centerY)*sy+focus.centerY+(height/2-focus.centerY)*depth;
  const w=rect.width*sx,h=rect.height*sy;
  return {x:x-w/2,y:y-h/2,width:w,height:h,centerX:x,centerY:y};
}
