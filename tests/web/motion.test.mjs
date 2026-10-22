import { test } from "node:test";
import assert from "node:assert/strict";
import { AquariumWorld, interpolateFish, glidePose } from "../../web/world.mjs";
import { makeFish } from "../../web/fish.mjs";
import { View } from "../../web/controls.mjs";

function world() {
  const w = new AquariumWorld();
  const f = makeFish(
    "fish",
    {
      pid: 1,
      name: "python",
      cpu_percent: 20,
      memory_percent: 0.2,
      num_threads: 1,
    },
    0,
    0,
    1000,
  );
  f.spawn = 1;
  w.fish.set(f.key, f);
  return w;
}
test("display motion advances between simulation ticks without changing physics", () => {
  const w = world(),
    f = w.fish.get("fish");
  w.step(1 / 30);
  const current = { x: f.x, y: f.y, age: f.age };
  const start = { ...w.renderFrame().fish.get("fish") };
  w.step(1 / 120);
  const quarter = { ...w.renderFrame().fish.get("fish") };
  w.step(1 / 120);
  const half = w.renderFrame().fish.get("fish");
  assert.equal(half.age, f.age - 0.5);
  assert.ok(Math.abs((quarter.x - start.x) * 2 - (half.x - start.x)) < 1e-10);
  assert.notEqual(quarter.x, start.x);
  assert.deepEqual({ x: f.x, y: f.y, age: f.age }, current);
  assert.deepEqual(w.renderFrame().fish.get("fish"), half); // no time change while paused
  w.selection = "fish";
  assert.equal(w.renderFrame().selected(), half);
  assert.equal(w.pick(half.x, half.y, 1, w.scene.fish), "fish");
  w.clear();
  assert.equal(w.renderFrame().fish.size, 0);
});
test("angles cross the wrap boundary by the short arc", () => {
  const w = world(),
    f = w.fish.get("fish");
  f.previous = { ...f, angle: Math.PI - 0.1, pulse: Math.PI * 2 - 0.1 };
  f.angle = -Math.PI + 0.1;
  f.pulse = 0.1;
  const rendered = interpolateFish(f, 0.5);
  assert.ok(Math.abs(rendered.angle - Math.PI) < 1e-10);
  assert.ok(Math.abs(rendered.pulse - Math.PI * 2) < 1e-10);
});
test("normal speed remains identical at 30, 60 and 120 Hz", () => {
  const states = [30, 60, 120].map((hz) => {
    const w = world();
    for (let i = 0; i < hz * 4; i++) w.step(new View().speed / hz);
    const f = w.fish.get("fish");
    return [f.x, f.y, f.age];
  });
  assert.deepEqual(states[0], states[1]);
  assert.deepEqual(states[1], states[2]);
  assert.equal(states[0][2], 120);
});

test("gliding damps short steering changes, is refresh independent, and holds on pause", () => {
  const target = { x: 100, y: -50, angle: -0.3 };
  const start = { x: 0, y: 0, angle: 0.2 };
  const a = glidePose(start, target, 1 / 30);
  const b = glidePose(glidePose(start, target, 1 / 60), target, 1 / 60);
  for (const key of ["x", "y", "angle"])
    assert.ok(Math.abs(a[key] - b[key]) < 1e-10);
  assert.ok(a.x > 0 && a.x < 30);
  assert.ok(a.angle > -0.3 && a.angle < 0.2);
  assert.deepEqual(glidePose(a, target, 0), a);
  const w = world();
  w.step(1 / 30);
  w.renderFrame(1 / 60);
  w.step(1 / 30);
  const before = { ...w.renderFrame(1 / 60).fish.get("fish") };
  const stopped = w.renderFrame(1 / 60, false).fish.get("fish");
  assert.equal(stopped.x, before.x);
  assert.equal(stopped.y, before.y);
  assert.equal(stopped.tail, before.tail);
  assert.ok(Math.abs(stopped.tail) <= 0.2);
});
