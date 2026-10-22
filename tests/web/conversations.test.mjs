import { test } from "node:test";
import assert from "node:assert/strict";
import { layoutConversations } from "../../web/effects.mjs";

test("nearby conversation markers merge without losing clickable partners", () => {
  const fish = (pid) => ({
    p: { pid },
    partners: [pid + 100],
    message: "通信中…",
  });
  const boxes = layoutConversations(
    [1, 2, 3].map((pid, i) => ({
      fish: fish(pid),
      x: 210 + i * 4,
      y: 200,
      size: 12,
    })),
    600,
    400,
  );
  assert.equal(boxes.length, 1);
  assert.equal(boxes[0].members.length, 3);
  assert.deepEqual(boxes[0].partners, [101, 102, 103]);
  assert.equal(boxes[0].message, "通信中 · 3");
});

test("conversation hit regions stay on screen and do not overlap", () => {
  const candidates = Array.from({ length: 40 }, (_, i) => ({
    fish: { p: { pid: i }, partners: [i + 100], message: "データ送信" },
    x: 10 + (i % 8) * 70,
    y: 12 + Math.floor(i / 8) * 45,
    size: 14,
  }));
  const boxes = layoutConversations(candidates, 600, 400);
  assert.equal(
    boxes.reduce((n, b) => n + b.members.length, 0),
    40,
  );
  for (const [i, a] of boxes.entries()) {
    assert.ok(a.x >= 0 && a.y >= 0 && a.x + a.w <= 600 && a.y + a.h <= 400);
    for (const b of boxes.slice(i + 1))
      assert.ok(
        !(
          a.x < b.x + b.w &&
          a.x + a.w > b.x &&
          a.y < b.y + b.h &&
          a.y + a.h > b.y
        ),
      );
  }
});
