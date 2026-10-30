import assert from "node:assert/strict";
import test from "node:test";
import { loopbackOrigin, reflowResponsesFetch } from "../adapters/pi/lib/openai-transport.mjs";

test("only plain loopback origins are accepted", () => {
  for (const origin of ["http://127.0.0.1:18517", "http://localhost:18517", "http://[::1]:18517"]) {
    assert.equal(loopbackOrigin(origin), origin);
  }
  for (const origin of ["https://localhost", "http://remote.invalid", "http://user:pass@localhost",
    "http://localhost/v1", "http://localhost?key=private", "http://localhost/#fragment"]) {
    assert.throws(() => reflowResponsesFetch(origin));
  }
});

test("request body, headers, query and response pass through without rewriting", async () => {
  let calls = 0;
  const response = new Response("synthetic stream", { status: 200 });
  const route = reflowResponsesFetch("http://127.0.0.1:18517", async (request) => {
    calls++;
    assert.equal(request.url, "http://127.0.0.1:18517/v1/responses?probe=1");
    assert.equal(request.method, "POST");
    assert.equal(request.headers.get("authorization"), "Bearer synthetic-oauth");
    assert.equal(request.headers.get("x-test"), "preserved");
    assert.equal(await request.text(), '{"stream":true,"store":false}');
    return response;
  });
  assert.equal(await route("https://api.openai.com/v1/responses?probe=1", {
    method: "POST", headers: { Authorization: "Bearer synthetic-oauth", "x-test": "preserved" },
    body: '{"stream":true,"store":false}',
  }), response);
  assert.equal(calls, 1);
});

test("non-Responses requests never reach the next fetch", async () => {
  let calls = 0;
  const route = reflowResponsesFetch("http://localhost:18517", async () => { calls++; });
  for (const url of ["https://api.openai.com/v1/models", "https://chatgpt.com/backend-api/codex/responses",
    "https://unrelated.invalid/v1/responses", "http://api.openai.com/v1/responses"]) {
    await assert.rejects(route(url, { method: "POST" }));
  }
  await assert.rejects(route("https://api.openai.com/v1/responses", { method: "GET" }));
  assert.equal(calls, 0);
});

test("caller cancellation reaches the forwarded Request", async () => {
  const controller = new AbortController();
  const reason = new Error("synthetic cancellation");
  const route = reflowResponsesFetch("http://localhost:18517", (request) => new Promise((resolve, reject) => {
    request.signal.addEventListener("abort", () => reject(request.signal.reason), { once: true });
  }));
  const pending = route("https://api.openai.com/v1/responses", { method: "POST", signal: controller.signal });
  controller.abort(reason);
  await assert.rejects(pending, (error) => error === reason);
});

test("a local transport failure is returned without direct upstream fallback", async () => {
  let calls = 0;
  const failure = new Error("synthetic Reflow unavailable");
  const route = reflowResponsesFetch("http://localhost:18517", async () => { calls++; throw failure; });
  await assert.rejects(route("https://api.openai.com/v1/responses", { method: "POST" }), (error) => error === failure);
  assert.equal(calls, 1);
});
