import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { afterEach, test } from "node:test";
import ts from "typescript";

// Use the project's compiler, including parameter-property syntax, on Node 20+.
const source = readFileSync(new URL("./course-api.ts", import.meta.url), "utf8");
const { outputText } = ts.transpileModule(source, {
  compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext },
});
const { ApiError, processDocument, searchCourse } = await import(
  "data:text/javascript;base64," + Buffer.from(outputText).toString("base64"));

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

test("search sends the selected course, query, top_k and cancellation signal", async () => {
  const controller = new AbortController();
  const result = { results: [{
    chunk_id: 11, text: "source passage", document_id: 3,
    document_name: "lecture.pdf", page_number: 4, score: 0.75,
  }] };
  globalThis.fetch = async (url, options) => {
    assert.ok(String(url).endsWith("/courses/42/search"));
    assert.equal(options.method, "POST");
    assert.equal(options.headers["Content-Type"], "application/json");
    assert.equal(options.signal, controller.signal);
    assert.deepEqual(JSON.parse(options.body), { query: "Student question?", top_k: 10 });
    return Response.json(result);
  };
  assert.deepEqual(await searchCourse(42, "Student question?", 10, controller.signal), result);
});

test("an empty result remains empty instead of becoming a fabricated answer", async () => {
  globalThis.fetch = async () => Response.json({ results: [] });
  assert.deepEqual(await searchCourse(1, "question"), { results: [] });
});

for (const status of [404, 503]) {
  test(`HTTP ${status} preserves the safe API error detail`, async () => {
    globalThis.fetch = async () => Response.json(
      { detail: "Retrieval service unavailable" }, { status });
    await assert.rejects(searchCourse(1, "question"), (error) => {
      assert.ok(error instanceof ApiError);
      assert.equal(error.status, status);
      assert.equal(error.message, "Retrieval service unavailable");
      return true;
    });
  });
}

test("FastAPI validation errors keep their message and 422 status", async () => {
  globalThis.fetch = async () => Response.json(
    { detail: [{ msg: "query must not be blank" }] }, { status: 422 });
  await assert.rejects(searchCourse(1, ""), (error) =>
    error instanceof ApiError && error.status === 422 && /blank/.test(error.message));
});

test("an abort is propagated rather than disguised as an API response", async () => {
  globalThis.fetch = async () => { throw new DOMException("Cancelled", "AbortError"); };
  await assert.rejects(searchCourse(1, "question"), { name: "AbortError" });
});

test("retrying processing posts to the document's process endpoint", async () => {
  const queued = { id: 7, name: "lecture.pdf", created_at: "2026-10-30T00:00:00Z",
    status: "ready", processing_state: "processing" };
  globalThis.fetch = async (url, options) => {
    assert.ok(String(url).endsWith("/courses/3/documents/7/process"));
    assert.equal(options.method, "POST");
    return Response.json(queued, { status: 202 });
  };
  assert.deepEqual(await processDocument(3, 7), queued);
});

test("a retry rejected by the backend surfaces its 409 detail", async () => {
  globalThis.fetch = async () => Response.json({ detail: "Document is indexed" }, { status: 409 });
  await assert.rejects(processDocument(3, 7), (error) =>
    error instanceof ApiError && error.status === 409 && error.message === "Document is indexed");
});
