import { test } from "node:test";
import assert from "node:assert/strict";
import {
  AquariumWorld,
  keyOf,
  selectedProcesses,
  validateSnapshot,
} from "../../web/world.mjs";

const process = (pid = 1, create_time = 1) => ({
  pid,
  create_time,
  ppid: 0,
  name: "test",
  exe: "/test",
  cpu_percent: pid,
  memory_percent: 1,
  num_threads: 2,
  cmdline: ["test"],
  status: "running",
});
const snapshot = (sequence = 1, processes = [process()], extra = {}) => ({
  schema_version: 1,
  host_id: "host",
  hostname: "test",
  boot_id: "boot",
  session_id: "session",
  source: "psutil",
  collected_at: 1,
  sequence,
  processes,
  events: [],
  connections: [],
  ...extra,
});

test("view changes hide fish without fabricating process exits", () => {
  const world = new AquariumWorld();
  world.apply(snapshot(1, [process(1), process(2)]));
  world.setFilters({ limit: 1, sort: "pid", order: "asc" });
  assert.equal([...world.fish.values()][0].p.pid, 1);
  world.setFilters({ order: "desc" });
  assert.equal([...world.fish.values()][0].p.pid, 2);
  assert.equal(
    [...world.fish.values()].some((f) => f.dying),
    false,
  );
  assert.equal(world.processes.size, 2);
});
test("PID reuse preserves independent identities and exit animation", () => {
  const world = new AquariumWorld();
  world.apply(snapshot());
  world.step(0.05);
  const oldKey = [...world.fish.keys()][0];
  world.apply(snapshot(2, [process(1, 2)]));
  assert.equal(world.fish.get(oldKey).dying, true);
  assert.equal([...world.fish.values()].filter((f) => !f.dying).length, 1);
  for (let i = 0; i < 30; i++) world.step(0.05);
  assert.equal(world.fish.has(oldKey), false);
});
test("collection failures cannot erase a healthy state", () => {
  const world = new AquariumWorld();
  world.apply(snapshot());
  assert.equal(
    world.apply(snapshot(2, [], { error: "collection failed" })),
    false,
  );
  assert.equal(world.processes.size, 1);
  assert.throws(() => world.apply(snapshot(1, [process(1), process(1)])));
});
test("event replay does not repeatedly trigger animations", () => {
  const world = new AquariumWorld();
  const event = { event_id: 1, event_type: "exec", pid: 1, create_time: 1 };
  world.apply(snapshot(1, [process()], { events: [event] }));
  world.step(0.05);
  const flash = [...world.fish.values()][0].flash;
  world.apply(snapshot(2, [process()], { events: [event] }));
  assert.equal([...world.fish.values()][0].flash, flash);
});
test("host switches clear selection and never collide on PID", () => {
  const world = new AquariumWorld();
  const first = snapshot();
  world.apply(first);
  world.selection = keyOf(first, process());
  world.apply(snapshot(1, [process()], { host_id: "other" }));
  assert.equal(world.selection, null);
  assert.equal(world.fish.size, 1);
});
test("simulation is finite and frame-rate independent for bounded time steps", () => {
  const world = new AquariumWorld();
  world.apply(
    snapshot(
      1,
      Array.from({ length: 500 }, (_, i) => process(i)),
    ),
  );
  for (let i = 0; i < 120; i++) world.step(1 / 60);
  for (const fish of world.fish.values()) {
    assert.ok(Number.isFinite(fish.x) && Number.isFinite(fish.y));
    assert.ok(fish.alpha >= 0 && fish.alpha <= 1);
  }
});

test("sorting and search apply before display limits", () => {
  const data = snapshot(1, [process(1), process(2), process(3)]);
  assert.deepEqual(
    selectedProcesses(data, { sort: "pid", order: "asc", limit: 2 }).map(
      (p) => p.pid,
    ),
    [1, 2],
  );
  assert.deepEqual(
    selectedProcesses(data, { search: "3", limit: 1 }).map((p) => p.pid),
    [3],
  );
});

test("large fish can be selected across their body", () => {
  const world = new AquariumWorld();
  world.apply(snapshot(1, [{ ...process(), memory_percent: 20 }]));
  const fish = [...world.fish.values()][0];
  assert.equal(world.pick(fish.x + 35, fish.y, 20), fish.key);
});

test("a lookup focus reveals a process outside the limit and survives refresh", () => {
  const world = new AquariumWorld(),
    data = snapshot(1, [process(1), process(2), process(3)]);
  world.setFilters({ limit: 1 });
  world.apply(data);
  const key = keyOf(data, process(1));
  assert.equal(world.fish.has(key), false);
  assert.equal(world.focus(key), true);
  assert.equal(world.selected().p.pid, 1);
  world.apply(snapshot(2, data.processes));
  assert.equal(world.selected().p.pid, 1);
  assert.equal(world.focus("nonexistent"), false);
  world.apply(snapshot(3, [process(1, 2)]));
  assert.equal(world.selection, null);
});

test("reused PIDs cannot inherit communication history or partner highlights", () => {
  const w = new AquariumWorld(),
    data = snapshot(1, [process(1), process(2)]);
  w.apply(data);
  w.history.set("[1,2]", [1, 2, 3]);
  w.highlighted.add(1);
  const partner = [...w.fish.values()].find((f) => f.p.pid === 2);
  partner.partners = [1];
  partner.talk = 60;
  w.apply(snapshot(2, [process(1, 2), process(2)], { collected_at: 4 }));
  assert.equal(w.history.size, 0);
  assert.equal(w.highlighted.has(1), false);
  assert.deepEqual(partner.partners, []);
  assert.equal(partner.talk, 0);
});

test("a visible parent flashes when a newly forked child is outside the limit", () => {
  const w = new AquariumWorld();
  w.setFilters({ limit: 1, sort: "pid", order: "asc" });
  w.apply(
    snapshot(1, [process(1), { ...process(2), ppid: 1 }], {
      events: [
        { event_id: 1, event_type: "fork", pid: 2, ppid: 1, create_time: 1 },
      ],
    }),
  );
  assert.equal(w.byPid().get(1).fork, 60);
  assert.equal(w.byPid().has(2), false);
});
