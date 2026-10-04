import assert from "node:assert/strict";
import { test } from "node:test";

// A removed deadline, concurrent tick, or missed abort must fail these tests.
async function pollingFactory() {
  const pollingModule = await import("./document-polling.ts").catch(() => null);
  assert.ok(pollingModule?.createDocumentPolling, "The document polling controller must exist");
  return pollingModule.createDocumentPolling;
}

const flush = async () => { await Promise.resolve(); await Promise.resolve(); };

test("polls every three seconds, never overlaps, and stops on terminal data", async (t) => {
  const create = await pollingFactory();
  t.mock.timers.enable({ apis: ["setTimeout", "Date"], now: 0 });
  let calls = 0;
  let resolveRequest;
  const received = [];
  const polling = create({
    fetch: () => { calls++; return new Promise((resolve) => { resolveRequest = resolve; }); },
    onData: (data) => { received.push(data); return data === "processing"; },
    onError: assert.fail,
    onTimeout: () => assert.fail("unexpected timeout"),
  });
  t.after(() => polling.stop());
  polling.restart();
  t.mock.timers.tick(2999);
  assert.equal(calls, 0);
  t.mock.timers.tick(1);
  assert.equal(calls, 1);
  t.mock.timers.tick(15000);
  assert.equal(calls, 1);
  resolveRequest("processing");
  await flush();
  t.mock.timers.tick(3000);
  assert.equal(calls, 2);
  resolveRequest("ready");
  await flush();
  t.mock.timers.tick(120000);
  assert.equal(calls, 2);
  assert.deepEqual(received, ["processing", "ready"]);
});

test("aborts a hung request at two minutes and ignores its late result", async (t) => {
  const create = await pollingFactory();
  t.mock.timers.enable({ apis: ["setTimeout", "Date"], now: 0 });
  let signal;
  let resolveRequest;
  let timeouts = 0;
  const polling = create({
    fetch: (requestSignal) => { signal = requestSignal; return new Promise((resolve) => { resolveRequest = resolve; }); },
    onData: () => assert.fail("late data must be ignored"),
    onError: assert.fail,
    onTimeout: () => { timeouts++; },
  });
  polling.restart();
  t.mock.timers.tick(3000);
  t.mock.timers.tick(117000);
  assert.equal(signal.aborted, true);
  assert.equal(timeouts, 1);
  resolveRequest("ready");
  await flush();
  t.mock.timers.tick(120000);
  assert.equal(timeouts, 1);
});

test("explicit restart renews the deadline without overlapping an active request", async (t) => {
  const create = await pollingFactory();
  t.mock.timers.enable({ apis: ["setTimeout", "Date"], now: 0 });
  let calls = 0;
  let resolveRequest;
  let timeouts = 0;
  const received = [];
  const polling = create({
    fetch: () => { calls++; return new Promise((resolve) => { resolveRequest = resolve; }); },
    onData: (data) => { received.push(data); return data === "processing"; },
    onError: assert.fail,
    onTimeout: () => { timeouts++; },
  });
  polling.restart();
  t.mock.timers.tick(119000);
  polling.restart(true);
  assert.equal(calls, 1);
  resolveRequest("ready");
  await flush();
  assert.deepEqual(received, [], "a result from before restart must not undo the new retry status");
  t.mock.timers.tick(3000);
  assert.equal(calls, 2);
  t.mock.timers.tick(116999);
  assert.equal(timeouts, 0);
  t.mock.timers.tick(1);
  assert.equal(timeouts, 1);
});

test("ordinary pending responses do not renew the two-minute deadline", async (t) => {
  const create = await pollingFactory();
  t.mock.timers.enable({ apis: ["setTimeout", "Date"], now: 0 });
  let calls = 0;
  let timeouts = 0;
  const polling = create({
    fetch: async () => { calls++; return "processing"; },
    onData: () => true,
    onError: assert.fail,
    onTimeout: () => { timeouts++; },
  });
  polling.restart();
  for (let check = 0; check < 40; check++) {
    t.mock.timers.tick(3000);
    await flush();
  }
  assert.equal(timeouts, 1);
  const callsAtTimeout = calls;
  t.mock.timers.tick(120000);
  await flush();
  assert.equal(calls, callsAtTimeout);
});

test("stops after a polling error and permits an immediate resume check", async (t) => {
  const create = await pollingFactory();
  t.mock.timers.enable({ apis: ["setTimeout", "Date"], now: 0 });
  const errors = [];
  let calls = 0;
  const polling = create({
    fetch: async () => { calls++; if (calls === 1) throw new Error("offline"); return "ready"; },
    onData: () => false,
    onError: (error) => errors.push(error.message),
    onTimeout: () => assert.fail("unexpected timeout"),
  });
  polling.restart();
  t.mock.timers.tick(3000);
  await flush();
  t.mock.timers.tick(120000);
  assert.equal(calls, 1);
  assert.deepEqual(errors, ["offline"]);
  polling.restart(true);
  t.mock.timers.tick(0);
  await flush();
  assert.equal(calls, 2);
});

test("cleanup aborts in-flight requests and cancels scheduled work", async (t) => {
  const create = await pollingFactory();
  t.mock.timers.enable({ apis: ["setTimeout", "Date"], now: 0 });
  let signal;
  let calls = 0;
  const polling = create({
    fetch: (requestSignal) => { calls++; signal = requestSignal; return new Promise(() => {}); },
    onData: assert.fail,
    onError: assert.fail,
    onTimeout: assert.fail,
  });
  polling.restart();
  t.mock.timers.tick(3000);
  polling.stop();
  assert.equal(signal.aborted, true);
  t.mock.timers.tick(240000);
  assert.equal(calls, 1);
});
