// Pure client model: no DOM or GPU dependency. Complete host state precedes
// display selection; network failures never enter the reconciliation path.
export const MAX_VISIBLE = 10000;
export const keyOf = (snapshot, p) =>
  JSON.stringify([snapshot.host_id, snapshot.boot_id, p.pid, p.create_time]);
import { hash, colorOf, makeFish, updateMetrics, updateFish, worldSize, TAU } from './fish.mjs';
export { hash, colorOf } from './fish.mjs';
export function selectedProcesses(
  snapshot,
  { sort = "cpu", order = "desc", limit = 0, search = "" } = {},
) {
  const field =
    { cpu: "cpu_percent", memory: "memory_percent", name: "name", pid: "pid" }[
      sort
    ] || "cpu_percent";
  const query = search.toLowerCase().trim();
  const processes = snapshot.processes.filter(
    (p) =>
      !query ||
      p.name.toLowerCase().includes(query) ||
      String(p.pid).includes(query),
  );
  processes.sort((a, b) => {
    const left = a[field],
      right = b[field];
    const comparison =
      typeof left === "string"
        ? left.toLowerCase().localeCompare(right.toLowerCase())
        : left - right;
    return (comparison || a.pid - b.pid) * (order === "asc" ? 1 : -1);
  });
  return processes.slice(
    0,
    Math.min(limit > 0 ? limit : MAX_VISIBLE, MAX_VISIBLE),
  );
}

export function validateSnapshot(snapshot) {
  if (
    !snapshot ||
    snapshot.schema_version !== 1 ||
    !Array.isArray(snapshot.processes) ||
    snapshot.processes.length > 50000 ||
    !Number.isSafeInteger(snapshot.sequence) ||
    snapshot.sequence < 1 ||
    !["host_id", "boot_id", "session_id", "source"].every(
      (k) => typeof snapshot[k] === "string" && snapshot[k],
    )
  ) {
    throw new Error("Unsupported or incomplete telemetry snapshot");
  }
  const seen = new Set();
  for (const p of snapshot.processes) {
    if (
      !Number.isSafeInteger(p.pid) ||
      p.pid < 0 ||
      seen.has(p.pid) ||
      typeof p.name !== "string" ||
      ![
        "ppid",
        "memory_percent",
        "cpu_percent",
        "num_threads",
        "create_time",
      ].every((k) => Number.isFinite(p[k]) && p[k] >= 0) ||
      !Array.isArray(p.cmdline) ||
      !p.cmdline.every((arg) => typeof arg === "string")
    ) {
      throw new Error("Invalid process telemetry");
    }
    seen.add(p.pid);
  }
  let cursor = 0;
  if (!Array.isArray(snapshot.events) || snapshot.events.length > 2048)
    throw new Error("Invalid event history");
  for (const event of snapshot.events) {
    if (
      !Number.isSafeInteger(event.event_id) ||
      event.event_id <= cursor ||
      !["spawn", "fork", "exec", "exit"].includes(event.event_type)
    )
      throw new Error("Invalid lifecycle event");
    cursor = event.event_id;
  }
  return snapshot;
}

export class AquariumWorld {
  constructor() {
    this.snapshot = null;
    this.fish = new Map();
    this.processes = new Map();
    this.selection = null;
    this.filters = { sort: "cpu", order: "desc", limit: 0, search: "" };
    this.time = 0;
    this.eventSession = null;
    this.eventCursor = 0;
    this.eventsLost = 0;
    this.extent = 3072;
    this.width=1200;this.height=800;this.accumulator=0;
    this.highlightSchools=false;this.quality='full';
    this.history=new Map();this.highlighted=new Set();
  }
  clear() {
    this.snapshot = null;
    this.fish.clear();
    this.processes.clear();
    this.selection = null;
    this.eventSession = null;
    this.eventCursor = 0;
    this.eventsLost = 0;
    this.history.clear();this.highlighted.clear();this.accumulator=0;
  }
  apply(raw) {
    const snapshot = validateSnapshot(raw);
    if (snapshot.error) return false;
    const previous = this.snapshot;
    if (
      previous?.host_id === snapshot.host_id &&
      previous?.session_id === snapshot.session_id
    ) {
      if (snapshot.sequence < previous.sequence)
        throw new Error("Server returned an older snapshot");
      if (snapshot.sequence === previous.sequence) return false;
    }
    if (
      previous &&
      (previous.host_id !== snapshot.host_id ||
        previous.boot_id !== snapshot.boot_id)
    )
      this.clear();
    const old = this.processes;
    this.snapshot = snapshot;
    this.processes = new Map(
      snapshot.processes.map((p) => [keyOf(snapshot, p), p]),
    );
    if (this.selection && !this.processes.has(this.selection))
      this.selection = null;
    this.reconcileView(old);
    const session = JSON.stringify([snapshot.host_id, snapshot.session_id]);
    if (session !== this.eventSession) {
      this.eventSession = session;
      this.eventCursor = 0;
    }
    if (
      this.eventCursor &&
      snapshot.events[0]?.event_id > this.eventCursor + 1
    ) {
      this.eventsLost += snapshot.events[0].event_id - this.eventCursor - 1;
    }
    const byPid = new Map(
      [...this.fish.values()].filter((f) => !f.dying).map((f) => [f.p.pid, f]),
    );
    for (const event of snapshot.events) {
      if (event.event_id <= this.eventCursor) continue;
      const fish = byPid.get(event.pid);
      if (
        fish &&
        (!event.create_time || event.create_time === fish.p.create_time)
      ) {
        if (event.event_type === "exec") { fish.exec = 30; fish.flash = 1; }
        if (event.event_type === "fork" || event.event_type === "spawn") {
          const parent = byPid.get(event.ppid);
          if (parent) parent.fork = 60;
        }
      }
      this.eventCursor = event.event_id;
    }
    this.recordCommunication();
    return true;
  }
  setFilters(patch) {
    Object.assign(this.filters, patch);
    if (this.snapshot) this.reconcileView(this.processes);
  }
  reconcileView(previous) {
    const visible = new Map(
      selectedProcesses(this.snapshot, this.filters).map((p) => [
        keyOf(this.snapshot, p),
        p,
      ]),
    );
    for (const [key, fish] of this.fish) {
      if (!this.processes.has(key)) fish.dying = true;
      else if (!visible.has(key)) this.fish.delete(key); // Hidden != dead.
    }
    // Bound exit animations as well as live instances, including rapid churn.
    let dying = [...this.fish.values()].filter((f) => f.dying);
    for (const fish of dying.slice(0, Math.max(0, dying.length - 1000)))
      this.fish.delete(fish.key);
    for (const [key, p] of visible) {
      let fish = this.fish.get(key);
      if (!fish) {
        const seed=hash(key), angle=seed/2**32*TAU;
        const radius=100+(hash(key+'r')%1000)/1000*Math.max(0,Math.min(this.extent*.6,600)-100);
        const parent=[...this.fish.values()].find(f=>!f.dying&&f.p.pid===p.ppid);
        const x=parent?parent.x+(hash(key+'x')%101)-50:Math.cos(angle)*radius;
        const y=parent?parent.y+(hash(key+'y')%101)-50:Math.sin(angle)*radius;
        fish=makeFish(key,p,x,y,this.extent);
        if(parent&&!previous.has(key))parent.fork=60;
        this.fish.set(key,fish);
      }
      updateMetrics(fish,p);
      fish.dying=false;
    }
    this.resize(this.width,this.height);
    this.formSchools();
  }
  resize(width,height) {
    this.width=width;this.height=height;
    this.extent=worldSize(this.filters.limit,[...this.fish.values()].filter(f=>!f.dying).length,width,height);
    for(const f of this.fish.values())f.extent=this.extent;
  }
  byPid() {return new Map([...this.fish.values()].filter(f=>!f.dying).map(f=>[f.p.pid,f]));}
  formSchools() {
    const byPid=this.byPid(), families=new Map(), processed=new Set();
    // Same traversal as ProcessManager.get_related_processes: depth 2, max 8.
    for(const f of byPid.values()) {
      f.school=[];f.isolated=false;f.isolatedSchool=false;
      const list=families.get(f.p.ppid)||[];list.push(f.p.pid);families.set(f.p.ppid,list);
    }
    const assign=(group,isolated=false)=>{const leader=Math.min(...group);for(const pid of group){const f=byPid.get(pid);f.school=group;f.leader=pid===leader;f.isolated=isolated;f.isolatedSchool=isolated;processed.add(pid);}};
    for(const f of byPid.values()){
      if(processed.has(f.p.pid)||f.p.ppid<=1)continue;
      const group=[],visited=new Set();
      const collect=(pid,d)=>{if(d>2||visited.has(pid)||group.length>=8)return;visited.add(pid);const o=byPid.get(pid);if(!o)return;group.push(pid);for(const child of families.get(pid)||[])collect(child,d+1);for(const sibling of families.get(o.p.ppid)||[])collect(sibling,d+1);};
      collect(f.p.pid,0);if(group.length>1)assign(group);
    }
    const names=new Map(),isolates=[];
    for(const f of byPid.values())if(!processed.has(f.p.pid)){const name=f.p.name.split(/\s+/)[0]||'unknown';const group=names.get(name)||[];group.push(f.p.pid);names.set(name,group);}
    for(const group of names.values())if(group.length>1)assign(group);else isolates.push(...group);
    if(isolates.length>1)assign(isolates,true);else if(isolates.length)byPid.get(isolates[0]).isolated=true;
    this.communicationSchools(byPid);
  }
  recordCommunication() {
    const now=this.snapshot.collected_at;
    for(const [key,times] of this.history){const recent=times.filter(t=>t>=now-60);if(recent.length)this.history.set(key,recent);else this.history.delete(key);}
    for(const c of this.snapshot.connections||[]){const key=JSON.stringify([Math.min(c.pid_a,c.pid_b),Math.max(c.pid_a,c.pid_b)]);const times=this.history.get(key)||[];if(times.at(-1)!==now)times.push(now);this.history.set(key,times.slice(-60));}
    // Bound history even when snapshots report rapidly changing connections.
    while(this.history.size>4096)this.history.delete(this.history.keys().next().value);
    this.communicationSchools(this.byPid());
  }
  communicationSchools(byPid) {
    for(const [key,times] of this.history)if(times.length>=3){const [a,b]=JSON.parse(key).map(pid=>byPid.get(pid));if(a&&b&&!a.school.length&&!b.school.length){a.school=b.school=[a.p.pid,b.p.pid];a.leader=true;b.leader=false;}}
  }
  step(seconds) {
    this.accumulator+=Math.max(0,Math.min(seconds,.25));
    while(this.accumulator>=1/30-1e-10){this.tick();this.accumulator-=1/30;}
  }
  tick() {
    this.time+=1/30;
    const byPid=this.byPid(),forces=new Map(),grid=new Map(),cell=100;
    for(const f of byPid.values()) {const key=`${Math.floor(f.x/cell)},${Math.floor(f.y/cell)}`;const bucket=grid.get(key)||[];bucket.push(f);grid.set(key,bucket);}
    for(const c of this.snapshot?.connections||[]){const a=byPid.get(c.pid_a),b=byPid.get(c.pid_b);if(!a||!b)continue;
      const dx=b.x-a.x,dy=b.y-a.y,d=Math.hypot(dx,dy);
      if(d>5){const strength=.008*(d<80?.6:d>250?3:d>150?1.5:1);for(const [f,sign] of [[a,1],[b,-1]]){const force=forces.get(f)||[0,0];force[0]+=dx/d*strength*sign;force[1]+=dy/d*strength*sign;forces.set(f,force);}}
      if(d<120){for(const [f,o,message] of [[a,b,'通信中…'],[b,a,'データ送信']]){f.talk=60;f.message=message;if(!f.partners.includes(o.p.pid))f.partners.push(o.p.pid);}}
    }
    for(const [key,f] of this.fish){const nearby=[];
      if(this.quality==='full'&&!f.dying){const gx=Math.floor(f.x/cell),gy=Math.floor(f.y/cell);outer:for(let x=-1;x<=1;x++)for(let y=-1;y<=1;y++)for(const o of grid.get(`${gx+x},${gy+y}`)||[]){if(o!==f&&(f.x-o.x)**2+(f.y-o.y)**2<10000){nearby.push(o);if(nearby.length===16)break outer;}}}
      if(!updateFish(f,nearby,forces.get(f)))this.fish.delete(key);
    }
  }

  pick(x, y, radius = 30) {
    let best = null,
      distance = Infinity;
    for (const fish of this.fish.values()) {
      if (fish.dying) continue;
      const d = (fish.x - x) ** 2 + (fish.y - y) ** 2;
      if (d < Math.max(radius, fish.size) ** 2 && d < distance) {
        best = fish.key;
        distance = d;
      }
    }
    this.selection = best;
    return best;
  }
  selected() {
    return this.selection ? this.fish.get(this.selection) : null;
  }
}
