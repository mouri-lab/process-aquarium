import { test } from "node:test";
import assert from "node:assert/strict";
import { Tide, activityStrength, tideMote, validateActivity } from "../../web/tides.mjs";
import { Tank } from "../../web/multiverse.mjs";
import { backgroundFrame } from "../../web/backgrounds.mjs";

const activity = (sent = 1048576, received = 0, extra = {}) => ({
  scope: "interface", source: "psutil", interface: "en0", status: "ready",
  interval_seconds: 1, sent_bytes: sent, received_bytes: received, ...extra,
});
const snapshot = (a, extra = {}) => ({ schema_version: 1, host_id: "a", hostname: "A",
  boot_id: "boot", session_id: "session", sequence: 1, source: "fixture",
  collected_at: 100, processes: [], connections: [], events: [], network_activity: a, ...extra });
const advance = (tide, seconds, start = 0, options = {}) => {
  for (let i = 0; i < seconds * 60; i++) tide.step(1 / 60, start + i * 1000 / 60, options);
};

test("idle sockets and old agents do not cause currents; measured directions stay separate", () => {
  const tide = new Tide();
  tide.accept(snapshot(null, {network_flows: [{state: "ESTABLISHED"}]}), 0);
  advance(tide, 2);
  assert.equal(tide.sent + tide.received, 0);
  tide.accept(snapshot(activity(), {sequence: 2}), 2000);
  advance(tide, 2, 2000);
  assert.ok(tide.sent > 0.2 && tide.sent < 0.5);
  assert.equal(tide.received, 0);
  tide.accept(snapshot(activity(0, 0), {sequence: 3}), 4000);
  advance(tide, 20, 4000);
  assert.ok(tide.sent < 0.002);
});

test("duplicate polls cannot renew activity and offline fades rather than flowing forever", () => {
  const tide = new Tide(), s = snapshot(activity(1048576, 1048576));
  tide.accept(s, 0);
  advance(tide, 4);
  const before = tide.sent;
  tide.accept(s, 4000);
  assert.equal(tide.expires, 5000);
  advance(tide, 20, 5000);
  assert.ok(tide.sent < 0.003);
  tide.accept({...s, sequence: 2}, 25000);
  advance(tide, 2, 25000);
  advance(tide, 20, 27000, {live: false});
  assert.ok(tide.sent < before / 100);
});

test("session and interface changes cannot inherit motion; unknown samples fade", () => {
  const tide = new Tide();
  tide.accept(snapshot(activity()), 0);
  advance(tide, 3);
  tide.accept(snapshot(activity(), {session_id: "new"}), 3000);
  assert.equal(tide.sent, 0);
  advance(tide, 1, 3000);
  tide.accept(snapshot(activity(0, 300, {interface: "eth0"}), {sequence: 2}), 4000);
  assert.equal(tide.sent + tide.received, 0);
  tide.accept(snapshot(activity(null, null, {status: "denied", interval_seconds: null}), {sequence: 3}), 5000);
  assert.equal(tide.targetSent + tide.targetReceived, 0);
});

test("volume changes intensity with bounded speed, pause freezes and reduced motion stops drift", () => {
  assert.equal(activityStrength(2**53 - 1, 0.001), 1);
  const tide = new Tide();
  tide.accept(snapshot(activity()), 0);
  advance(tide, 2);
  const before = {...tide};
  advance(tide, 1, 2000, {paused: true});
  assert.deepEqual({...tide}, before);
  advance(tide, 1, 3000, {reduced: true});
  assert.equal(tide.phase, before.phase);
  const a = tideMote(1, 2, .3, false), b = tideMote(1, 2, .3 + 1 / 60 / 64, false);
  assert.ok(Math.abs(b.x - a.x) < 0.0003);
  for (const hz of [30, 60, 120]) {
    const t = new Tide(); t.accept(snapshot(activity()), 0);
    for (let i = 0; i < hz * 2; i++) t.step(1 / hz, i * 1000 / hz);
    assert.ok(Math.abs(t.sent - before.sent) < 1e-10);
  }
});

test("host state is isolated and the communication switch removes activity from backgrounds", () => {
  const a = new Tank("local", "a"), b = new Tank("local", "b");
  a.apply({snapshot: snapshot(activity()), stale: false}, 0);
  b.apply({snapshot: snapshot(activity(0, 0), {host_id: "b"}), stale: false}, 0);
  advance(a.tide, 2); advance(b.tide, 2);
  assert.ok(a.tide.sent > 0); assert.equal(b.tide.sent, 0);
  const frame = backgroundFrame(a, {}, 800, 600, 0, new Date());
  assert.equal(frame.tide, a.tide);
  assert.equal(backgroundFrame(a, {}, 800, 600, 0, new Date(), {communication: false}).tide, null);
  a.apply({snapshot: snapshot(activity()), stale: true}, 4000);
  assert.equal(a.tide.expires, 5000);
});

test("malformed activity is rejected before replacing a healthy tank", () => {
  const tank = new Tank("local", "a");
  tank.apply({snapshot: snapshot(activity()), stale: false}, 0);
  for (const change of [{sent_bytes: -1}, {received_bytes: true}, {interval_seconds: 0},
    {interval_seconds: Infinity}, {scope: "peer"}, {source: "guess"},
    {status: "warming"}, {interface: ""}, {sent_bytes: null, received_bytes: null}]) {
    assert.throws(() => validateActivity(activity(100, 200, change)));
    assert.throws(() => tank.apply({snapshot: snapshot(activity(100, 200, change), {sequence: 2}), stale: false}, 1000));
    assert.equal(tank.world.snapshot.sequence, 1);
  }
  validateActivity(activity(null, 200));
});

test("floating motes spread through the water instead of forming dotted rows", () => {
  for (const seed of [1, 123, 87654]) {
    const cells = new Set(Array.from({length: 24}, (_, i) => {
      const p = tideMote(seed, i, 0, false);
      return `${Math.floor((p.x + .2) / .95 * 4)}:${Math.floor(p.y * 4)}`;
    }));
    assert.ok(cells.size >= 8);
  }
});
