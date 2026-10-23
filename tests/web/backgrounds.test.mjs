import { test } from "node:test";
import assert from "node:assert/strict";
import { backgroundFrame } from "../../web/backgrounds.mjs";
test("background providers receive separate simulation and wall clocks without changing the chosen background", () => {
  const tank = {
    sky: { seed: 1 },
    world: { quality: "full" },
    background: { kind: "dusk" },
  };
  const wall = new Date(2026, 0, 1, 6, 0),
    frame = backgroundFrame(tank, {}, 100, 100, 0, wall);
  assert.equal(frame.time, 0);
  assert.equal(frame.wallTime, wall.getTime());
  assert.deepEqual(tank.background, { kind: "dusk" });
});

import { BACKGROUNDS, drawBackground } from "../../web/backgrounds.mjs";
import { drawUnderlay } from "../../web/effects.mjs";
function drawingContext() {
  const calls = [];
  const ctx = new Proxy({}, {
    get: (_, method) => (...args) => {
      for (const arg of args)
        if (typeof arg === "number") assert.ok(Number.isFinite(arg), `${method}: ${arg}`);
      calls.push([method, ...args]);
      if (method === "createLinearGradient" || method === "createRadialGradient")
        return { addColorStop() {} };
    },
  });
  return { ctx, calls };
}
test("tank backgrounds render the detailed habitat for every palette, time and quality", () => {
  const camera = { x: 0, y: 0, zoom: 1 };
  for (const kind of Object.keys(BACKGROUNDS))
    for (const seaTime of ["auto", "morning", "day", "evening", "night"])
      for (const quality of ["full", "reduced", "minimal"]) {
        const tank = { sky: { seed: 1 }, world: { quality }, background: { kind, seaTime } };
        const { ctx, calls } = drawingContext();
        const frame = backgroundFrame(tank, camera, 390, 844, 20, new Date(2026, 0, 1, 12));
        assert.equal(frame.seaTime, seaTime);
        drawBackground(ctx, tank.background, frame);
        assert.ok(calls.some(([method]) => method === "bezierCurveTo"));
        assert.equal(calls.filter(([method]) => method === "save").length,
          calls.filter(([method]) => method === "restore").length);
      }
});
test("underlay preserves a tank background that has already been drawn", () => {
  const { ctx, calls } = drawingContext();
  const world = { time: 0, byPid: () => new Map(), fish: new Map(), quality: "full" };
  drawUnderlay(ctx, world, { x: 0, y: 0, zoom: 1 }, 800, 600,
    { habitat: false, particles: 2 });
  assert.ok(calls.some(([method]) => method === "arc"));
  assert.ok(!calls.some(([method]) => method === "fillRect" || method === "createLinearGradient"));
});
