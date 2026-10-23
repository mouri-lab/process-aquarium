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
