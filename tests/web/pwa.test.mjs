import { test } from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import vm from "node:vm";

const source = await readFile(new URL("../../web/sw.js", import.meta.url), "utf8");
function worker({ failInstall = false } = {}) {
  const listeners = {}, stored = new Map(), deleted = [];
  const cache = {
    async addAll(requests) {
      if (failInstall) throw new Error("offline");
      for (const r of requests) stored.set(r.url, new Response(r.url));
    },
    async match(key) { return stored.get(key)?.clone(); },
  };
  let claimed = false;
  vm.runInNewContext(source, {
    URL, Request,
    self: { registration: { scope: "https://aquarium.test/" },
      clients: { async claim() { claimed = true; } },
      addEventListener(name, handler) { listeners[name] = handler; } },
    caches: { async open() { return cache; },
      async keys() { return ["process-aquarium-shell-v0", "process-aquarium-shell-v1", "unrelated"]; },
      async delete(key) { deleted.push(key); } },
    fetch() { throw new Error("network unavailable"); },
  });
  return { stored, deleted, get claimed() { return claimed; },
    async lifecycle(name) {
      let pending;
      listeners[name]({ waitUntil(p) { pending = p; } });
      await pending;
    },
    fetch(path, options = {}) {
      let response;
      const request = { url: new URL(path, "https://aquarium.test").href,
        method: "GET", mode: "cors", headers: new Headers(), ...options };
      listeners.fetch({ request, respondWith(p) { response = p; } });
      return response;
    } };
}

test("offline shell includes every module, HTML, manifest and icons", async () => {
  const sw = worker();
  await sw.lifecycle("install");
  const { readdir } = await import("node:fs/promises");
  for (const file of await readdir(new URL("../../web/", import.meta.url))) {
    if (!file.endsWith(".mjs")) continue;
    assert.equal((await sw.fetch(`/${file}`)).status, 200, file);
  }
  const home = await sw.fetch("/?host=host-b", { mode: "navigate" });
  assert.equal(await home.text(), "https://aquarium.test/");
  assert(![...sw.stored.keys()].some(k => k.includes("?")));
  for (const path of ["/manifest.webmanifest", "/icons/icon-192.png", "/icons/icon-512.png"])
    assert.equal((await sw.fetch(path)).status, 200);
});

test("all API hosts, auth failures, health and uploads bypass the worker", async () => {
  const sw = worker();
  await sw.lifecycle("install");
  for (const path of ["/api/v1/hosts", "/api/v1/snapshot?host=a", "/api/v1/snapshot?host=b",
    "/api/v1/flows", "/api/v1/transfers", "/healthz", "/unknown",
    "https://other.test/app.mjs", "/app.mjs?token=secret"])
    assert.equal(sw.fetch(path), undefined, path);
  assert.equal(sw.fetch("/api/v1/snapshots", { method: "POST" }), undefined);
  assert.equal(sw.fetch("/", { headers: new Headers({ Authorization: "Bearer secret" }) }), undefined);
  assert(![...sw.stored.keys()].some(k => k.includes("/api/")));
});

test("activation removes only obsolete aquarium caches", async () => {
  const sw = worker();
  await sw.lifecycle("activate");
  assert.deepEqual(sw.deleted, ["process-aquarium-shell-v0"]);
  assert(sw.claimed);
});

test("incomplete shell installation fails instead of activating", async () => {
  await assert.rejects(worker({ failInstall: true }).lifecycle("install"), /offline/);
});
