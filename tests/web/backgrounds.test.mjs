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
import { drawUnderlay, prepareCanvas } from "../../web/effects.mjs";
function mockSurfaces(t) {
  const surfaces = [];
  const previous = globalThis.OffscreenCanvas;
  globalThis.OffscreenCanvas = class {
    constructor(width, height) {
      this.width = width;
      this.height = height;
      this.context = drawingContext();
      surfaces.push(this);
    }
    getContext() { return this.context.ctx; }
  };
  t.after(() => {
    if (previous === undefined) delete globalThis.OffscreenCanvas;
    else globalThis.OffscreenCanvas = previous;
  });
  return surfaces;
}
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
test("tank backgrounds render the detailed habitat for every palette, time and quality", (t) => {
  mockSurfaces(t);
  const camera = { x: 0, y: 0, zoom: 1 };
  for (const kind of Object.keys(BACKGROUNDS))
    for (const seaTime of ["auto", "morning", "day", "evening", "night"])
      for (const quality of ["full", "reduced", "minimal"]) {
        const tank = { sky: { seed: 1 }, world: { quality }, background: { kind, seaTime } };
        const { ctx, calls } = drawingContext();
        const frame = backgroundFrame(tank, camera, 390, 844, 20, new Date(2026, 0, 1, 12));
        assert.equal(frame.seaTime, seaTime);
        drawBackground(ctx, tank.background, frame);
        assert.ok(calls.some(([method]) => method === "drawImage"));
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

test("background reuses static layers while plants animate, and invalidates changed settings", (t) => {
  const surfaces = mockSurfaces(t);
  const { ctx, calls } = drawingContext();
  const frame = { width: 811, height: 613, time: 1, camera: { x: 0 },
    quality: "full", seaTime: "day", wallTime: 1760000000000 };
  drawBackground(ctx, { kind: "kelp" }, frame);
  assert.equal(surfaces.length, 2);
  const original = surfaces[0];
  const staticCalls = original.context.calls.length;
  calls.length = 0;
  drawBackground(ctx, { kind: "kelp" }, { ...frame, time: 2, camera: { x: 100 } });
  assert.equal(surfaces.length, 2);
  assert.equal(original.context.calls.length, staticCalls);
  assert.ok(calls.some(([method]) => method === "quadraticCurveTo"));
  assert.ok(!calls.some(([method]) => method === "createLinearGradient"));
  for (const changed of [{ quality: "reduced" }, { seaTime: "night" }, { width: 812 }]) {
    const count = surfaces.length;
    drawBackground(ctx, { kind: "kelp" }, { ...frame, ...changed });
    assert.equal(surfaces.length, count + 2);
  }
  const count = surfaces.length;
  drawBackground(ctx, { kind: "dusk" }, frame);
  assert.equal(surfaces.length, count + 2);
});

test("background raster cap leaves the default fish and overlay resolution intact", (t) => {
  const previous = globalThis.devicePixelRatio;
  globalThis.devicePixelRatio = 2;
  t.after(() => {
    if (previous === undefined) delete globalThis.devicePixelRatio;
    else globalThis.devicePixelRatio = previous;
  });
  const { ctx } = drawingContext();
  const background = { width: 0, height: 0, getContext: () => ctx };
  const overlay = { width: 0, height: 0, getContext: () => ctx };
  prepareCanvas(background, 800, 600, 1.5);
  prepareCanvas(overlay, 800, 600);
  assert.deepEqual([background.width, background.height], [1200, 900]);
  assert.deepEqual([overlay.width, overlay.height], [1600, 1200]);
});

test("measured currents animate over cached time-of-day scenery and can be switched off", (t) => {
  const surfaces = mockSurfaces(t);
  const tank = {
    sky: { seed: 23 }, world: { quality: "full" },
    background: { kind: "lagoon", seaTime: "evening" },
    tide: { sent: .8, received: 0, phase: .2 },
    transferDirections: [{ strength: .8, outgoing: true, angle: .4 }],
  };
  const frame = backgroundFrame(tank, { x: 0 }, 823, 617, 1, new Date(2026, 0, 1, 12),
    { reducedMotion: true });
  assert.equal(frame.seaTime, "evening");
  assert.equal(frame.transfers, tank.transferDirections);
  assert.equal(frame.reducedMotion, true);
  const { ctx, calls } = drawingContext();
  drawBackground(ctx, tank.background, frame);
  const images = calls.filter(([method]) => method === "drawImage");
  assert.equal(images.length, 5); // base, three current patches, foreground
  assert.equal(images[0][1], surfaces[0]);
  assert.equal(images.at(-1)[1], surfaces[1]);
  const positions = calls.filter(([method]) => method === "translate");
  const allocations = surfaces.length;
  const staticCalls = surfaces[0].context.calls.length;
  calls.length = 0;
  drawBackground(ctx, tank.background, { ...frame, tide: { ...tank.tide, phase: .3 } });
  assert.equal(surfaces.length, allocations);
  assert.equal(surfaces[0].context.calls.length, staticCalls);
  assert.notDeepEqual(calls.filter(([method]) => method === "translate"), positions);
  calls.length = 0;
  drawBackground(ctx, tank.background,
    backgroundFrame(tank, { x: 0 }, 823, 617, 1, new Date(2026, 0, 1, 12), { communication: false }));
  assert.equal(calls.filter(([method]) => method === "drawImage").length, 2);
  assert.equal(surfaces.length, allocations);
});
