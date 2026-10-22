import {test} from "node:test";
import assert from "node:assert/strict";
import {backgroundFrame} from "../../web/backgrounds.mjs";
test("background time is supplied explicitly and is independent of simulation time", () => {
  const tank = {
    sky: { seed: 1 },
    world: { quality: "full" },
    background: { clock: "local", phase: 0.5 },
  };
  const wall = new Date(2026, 0, 1, 6, 0);
  assert.equal(backgroundFrame(tank, {}, 100, 100, 0, wall).dayPhase, 0.25);
  tank.background.clock = "fixed";
  assert.equal(backgroundFrame(tank, {}, 100, 100, 200, wall).dayPhase, 0.5);
});
