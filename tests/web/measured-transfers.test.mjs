import { test } from "node:test";
import assert from "node:assert/strict";
import { Tank } from "../../web/multiverse.mjs";
import { applyMeasuredTransfers, transferLinks, validateMeasuredTransfers } from "../../web/intertank.mjs";
import { activityStrength } from "../../web/tides.mjs";

const identity = host => ({ host_id: host, boot_id: `boot-${host}`, session_id: `session-${host}` });
const snapshot = host => ({ ...identity(host), schema_version: 1, hostname: host, source: "eBPF",
  sequence: 1, collected_at: 1, processes: [], connections: [], events: [] });
const transfer = (extra = {}) => ({ source: identity("a"), target: identity("b"),
  observer: { ...identity("a"), sequence: 1, interface: "eth0" }, network_scope: "lab",
  byte_basis: "observed_ip", bytes: 1024**2, interval_seconds: 1, age_seconds: 0, ...extra });
const rects = [{ centerX: 0, centerY: 0, width: 300 }, { centerX: 600, centerY: 0, width: 300 }];
function tanks() {
  return ["a", "b"].map(id => {
    const t = new Tank("local", id);
    t.apply({ snapshot: snapshot(id), stale: false }, 0);
    return t;
  });
}
function advance(list, now = 1000) {
  for (const t of list) t.transfers.step(1, now, { live: true }, list);
}

test("measured directions share one soft current with independent intervals", () => {
  const list = tanks();
  const reverse = transfer({ source: identity("b"), target: identity("a"),
    observer: { ...identity("b"), sequence: 2, interface: "eth0" }, interval_seconds: 4 });
  applyMeasuredTransfers(list, [transfer(), reverse], 0);
  const peer = list[0].transfers.peers.get("b");
  assert.equal(peer.outgoing.targetSent, activityStrength(1024**2, 1));
  assert.equal(peer.incoming.targetSent, activityStrength(1024**2, 4));
  advance(list);
  const links = transferLinks(list, rects);
  assert.equal(links.length, 1);
  assert.ok(links[0].sent > links[0].received && links[0].received > 0);
  list[0].apply({ snapshot: { ...snapshot("a"), sequence: 2 }, stale: false }, 1000);
  assert.equal(list[0].transfers.peers.get("b"), peer);
});

test("observer age and duplicate polls cannot extend measured activity", () => {
  const list = tanks();
  applyMeasuredTransfers(list, [transfer({ age_seconds: 2 })], 2000);
  const peer = list[0].transfers.peers.get("b");
  assert.equal(peer.outgoing.expires, 5000);
  applyMeasuredTransfers(list, [transfer({ age_seconds: 4 })], 4000);
  assert.equal(peer.outgoing.expires, 5000);
  advance(list);
  const before = peer.tide.sent;
  for (let n = 0; n < 20; n++) advance(list, 6000 + n * 1000);
  assert.ok(peer.tide.sent < before / 100);
});

test("missing direction fades; changed observation source rebaselines", () => {
  const list = tanks();
  applyMeasuredTransfers(list, [transfer()], 0); advance(list);
  const peer = list[0].transfers.peers.get("b");
  applyMeasuredTransfers(list, [], 1000);
  assert.equal(peer.outgoing.expires, -Infinity);
  applyMeasuredTransfers(list, [transfer({ observer: { ...identity("b"), sequence: 2, interface: "eth0" } })], 2000);
  assert.equal(peer.outgoing.sent, 0);
  assert.equal(peer.outgoing.expires, 7000);
});

test("wrong boot/session, fixtures, different server and invisible tanks cannot link", () => {
  for (const change of [
    s => ({ ...s, boot_id: "new" }), s => ({ ...s, session_id: "new" }), s => ({ ...s, source: "fixture" }),
  ]) {
    const list = tanks();
    list[1].world.snapshot = change(list[1].world.snapshot);
    applyMeasuredTransfers(list, [transfer()], 0);
    assert.equal(transferLinks(list, rects).length, 0);
  }
  const list = tanks();
  list[1].source = "other-server";
  applyMeasuredTransfers(list, [transfer()], 0);
  assert.equal(transferLinks(list, rects).length, 0);
  applyMeasuredTransfers([list[0]], [transfer()], 0);
  assert.equal(transferLinks([list[0]], [rects[0]]).length, 0);
});

test("malformed response is rejected before touching existing currents", () => {
  const list = tanks();
  applyMeasuredTransfers(list, [transfer()], 0);
  const peer = list[0].transfers.peers.get("b");
  for (const extra of [{ bytes: -1 }, { bytes: true }, { bytes: 2**53 }, { age_seconds: -1 },
    { interval_seconds: 0 }, { byte_basis: "payload" }, { observer: { ...identity("c"), sequence: 1, interface: "eth0" } }])
    assert.throws(() => applyMeasuredTransfers(list, [transfer(), transfer(extra)], 0));
  assert.equal(list[0].transfers.peers.get("b"), peer);
  assert.throws(() => validateMeasuredTransfers([transfer(), transfer()]));
});
