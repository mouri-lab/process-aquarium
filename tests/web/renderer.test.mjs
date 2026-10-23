import { test } from "node:test";
import assert from "node:assert/strict";
import { makeFish } from "../../web/fish.mjs";
import { viewPrimitives } from "../../web/renderer.mjs";
const fish = makeFish(
  "fish",
  {
    name: "chrome",
    cpu_percent: 1,
    memory_percent: 1,
    pid: 1,
    ppid: 0,
    num_threads: 1,
  },
  0,
  0,
  1000,
);
fish.spawn = 1;
const world = {
  fish: new Map([["fish", fish]]),
  quality: "full",
  highlightSchools: false,
};
test("multi-view geometry translates centers and vertices, never ellipse radii", () => {
  const a = viewPrimitives({
    world,
    camera: { x: 0, y: 0, zoom: 1 },
    rect: { x: 0, y: 0, width: 200, height: 200 },
  });
  const b = viewPrimitives({
    world,
    camera: { x: 0, y: 0, zoom: 1 },
    rect: { x: 300, y: 100, width: 200, height: 200 },
    opacity: 0.5,
  });
  assert.ok(a.some((s) => s.type === 0));
  assert.ok(a.some((s) => s.type === 1 || s.type === 2));
  a.forEach((s, i) => {
    assert.equal(b[i].points[0], s.points[0] + 300);
    assert.equal(b[i].points[1], s.points[1] + 100);
    assert.equal(b[i].color[3], s.color[3] * 0.5);
    if (s.type === 0) assert.equal(b[i].points[2], s.points[2]);
    else assert.equal(b[i].points[2], s.points[2] + 300);
  });
});
test("small fish remain visible as stars in the distant overview", () => {
  const args = {
    world,
    camera: { x: 0, y: 0, zoom: 0.02 },
    rect: { x: 10, y: 10, width: 100, height: 100 },
  };
  assert.equal(viewPrimitives(args).length, 0);
  assert.equal(viewPrimitives({ ...args, minimumPixels: 1.6 }).length, 1);
});
