import { test } from "node:test";
import assert from "node:assert/strict";
import { Tank } from "../../web/multiverse.mjs";
import { validateTransfers, transferLinks, transferDirections, streamPoint, streamWidth } from "../../web/intertank.mjs";
import { tideMote } from "../../web/tides.mjs";

const peer = (extra = {}) => ({host_id: "b", boot_id: "boot-b", interval_seconds: 1,
  sent_bytes: 4 * 1024**2, received_bytes: 0, ...extra});
const snapshot = (host, peers = [], extra = {}) => ({schema_version: 1, host_id: host,
  hostname: host, boot_id: `boot-${host}`, session_id: "demo", sequence: 1, collected_at: 1,
  source: "fixture", processes: [], connections: [], events: [], simulated_transfers: peers, ...extra});
const rects = [{centerX: 100, centerY: 200, width: 300}, {centerX: 600, centerY: 200, width: 300}];
function tanks() {
  const a = new Tank("local", "a"), b = new Tank("local", "b");
  a.apply({snapshot: snapshot("a", [peer()]), stale: false}, 0);
  b.apply({snapshot: snapshot("b"), stale: false}, 0);
  return [a, b];
}
function advance(list, count = 120, start = 0) {
  for (let i = 0; i < count; i++)
    for (const tank of list) tank.transfers.step(1/60, start + i * 1000/60,
      {live: tank.freshness.mode === "live"}, list);
}

test("only explicit fixture peers make links; reverse observations cannot double a pair", () => {
  const list = tanks(); advance(list);
  let links = transferLinks(list, rects);
  assert.equal(links.length, 1); assert.ok(links[0].sent > 0); assert.equal(links[0].received, 0);
  list[1].apply({snapshot: snapshot("b", [peer({host_id:"a", boot_id:"boot-a"})], {sequence:2}), stale:false}, 2000);
  assert.equal(transferLinks(list, rects).length, 1);
  assert.equal(transferLinks([list[0]], [rects[0]]).length, 0);
  assert.throws(() => validateTransfers(snapshot("a", [peer()], {source: "psutil"})));
  assert.equal(transferLinks([new Tank("local", "a"), new Tank("local", "b")], rects).length, 0);
});

test("entering either tank keeps the current pointed toward its peer", () => {
  const list = tanks(); advance(list);
  const links = transferLinks(list, rects);
  const from = transferDirections(list[0], links)[0], to = transferDirections(list[1], links)[0];
  assert.equal(from.outgoing, true); assert.equal(from.angle, 0);
  assert.equal(to.outgoing, false); assert.equal(to.angle, Math.PI);
  const start = streamPoint(links[0], 0, 0), end = streamPoint(links[0], 1, 0);
  assert.equal(start.x, rects[0].centerX); assert.equal(end.x, rects[1].centerX);
  // The same advancing phase moves away from the sender and into the receiver.
  const p1 = tideMote(123, 1, .2, true, 0), p2 = tideMote(123, 1, .2001, true, 0);
  assert.ok(p2.x > p1.x);
  const r1 = tideMote(123, 1, .2, false, Math.PI), r2 = tideMote(123, 1, .2001, false, Math.PI);
  assert.ok(r2.x > r1.x);
});

test("greater activity broadens the cloud without changing its path or speed", () => {
  const list = tanks(), link = transferLinks(list, rects)[0];
  const weak = {...link, sent:.1}, strong = {...link, sent:1};
  assert.ok(streamWidth(strong) > streamWidth(weak) * 1.8);
  assert.ok(streamWidth(strong) <= 90);
  assert.deepEqual(streamPoint(weak, .4, 1), streamPoint(strong, .4, 1));
});

test("missing or stale peer fades the flow and a reboot cannot inherit it", () => {
  const list = tanks(); advance(list);
  const tide = list[0].transfers.peers.get("b").tide;
  const before = tide.sent;
  list[1].freshness.mode = "stale";
  advance(list, 1200, 2000);
  assert.ok(tide.sent < before / 100);
  list[1].apply({snapshot: snapshot("b", [], {boot_id:"new",session_id:"new"}), stale:false}, 22000);
  assert.equal(transferLinks(list, rects).length, 0);
});

test("malformed, duplicated and self-referencing simulation peers are rejected", () => {
  for (const change of [{host_id:"a"}, {host_id:""}, {boot_id:""}, {sent_bytes:-1},
    {received_bytes:true}, {interval_seconds:0}, {interval_seconds:Infinity}])
    assert.throws(() => validateTransfers(snapshot("a", [peer(change)])));
  assert.throws(() => validateTransfers(snapshot("a", [peer(),peer()])));
  assert.throws(() => validateTransfers(snapshot("a", Array(33).fill(peer()))));
});
