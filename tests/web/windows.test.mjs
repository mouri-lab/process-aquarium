import { test } from "node:test";
import assert from "node:assert/strict";
import { clampWindow } from "../../web/menu.mjs";

test("dragged windows stay reachable after moving or shrinking the viewport", () => {
  assert.deepEqual(clampWindow(-100, -50, 488, 460, 1464, 800), { x: 6, y: 6 });
  assert.deepEqual(clampWindow(1300, 700, 488, 460, 1464, 800), {
    x: 970,
    y: 334,
  });
  // CSS constrains the window size, then resize clamps its former desktop position.
  assert.deepEqual(clampWindow(970, 334, 374, 460, 390, 844), {
    x: 10,
    y: 334,
  });
  assert.deepEqual(clampWindow(970, 334, 374, 288, 390, 300), { x: 10, y: 6 });
});
