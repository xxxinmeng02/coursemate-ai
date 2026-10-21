"use client";

import { FormEvent, useEffect, useRef, useState } from "react";
import { ApiError, searchCourse, type SearchResult } from "./course-api";

export default function RetrievalDebug({ courseId }: { courseId: number }) {
  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(5);
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [error, setError] = useState("");
  const [searching, setSearching] = useState(false);
  const controllerRef = useRef<AbortController | null>(null);

  useEffect(() => () => controllerRef.current?.abort(), []);

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalized = query.trim();
    if (!normalized) {
      setError("Enter a question to search.");
      return;
    }
    controllerRef.current?.abort();
    const controller = new AbortController();
    controllerRef.current = controller;
    setSearching(true);
    setResults(null);
    setError("");
    setSubmittedQuery(normalized);
    try {
      const data = await searchCourse(courseId, normalized, topK, controller.signal);
      if (!controller.signal.aborted) setResults(data.results);
    } catch (reason) {
      if (controller.signal.aborted) return;
      setError(reason instanceof ApiError
        ? `Error ${reason.status}: ${reason.message}`
        : "Cannot reach retrieval. Check that the API is running, then try again.");
    } finally {
      if (!controller.signal.aborted) setSearching(false);
    }
  }

  return (
    <details className="retrieval-debug">
      <summary>Retrieval debug <span>Internal testing</span></summary>
      <div className="retrieval-debug-body">
        <p>Inspect passages from this course. This tool retrieves sources without generating an answer.</p>
        <form onSubmit={handleSearch}>
          <label htmlFor="retrieval-query">Question</label>
          <textarea
            id="retrieval-query"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Why doesn't DFS always find the shortest route?"
            maxLength={2000}
            rows={3}
            disabled={searching}
            aria-describedby="retrieval-query-help"
          />
          <small id="retrieval-query-help">Up to 2,000 characters.</small>
          <div className="retrieval-controls">
            <label htmlFor="retrieval-top-k">Top K
              <select id="retrieval-top-k" value={topK} disabled={searching}
                onChange={(event) => setTopK(Number(event.target.value))}>
                {[3, 5, 10, 20, 50].map((value) => <option key={value}>{value}</option>)}
              </select>
            </label>
            <button className="button primary" type="submit" disabled={searching}>
              {searching ? "Searching…" : "Search passages"}
            </button>
          </div>
        </form>
        <div aria-live="polite" aria-busy={searching}>
          {error && <p className="upload-message upload-error" role="alert">{error}</p>}
          {results && (
            <>
              <p className="retrieval-query">Results for: <strong>{submittedQuery}</strong></p>
              {results.length === 0 ? (
                <p className="retrieval-empty" role="status">
                  No searchable passages returned. Check that this course has parsed, ready
                  documents with embeddings for the current model configuration.
                </p>
              ) : (
                <>
                  <p className="retrieval-score-note">Score is cosine similarity (higher is closer), not answer confidence. PDF pages start at 1.</p>
                  <ol className="retrieval-results">
                    {results.map((result, index) => (
                      <li key={result.chunk_id}>
                        <div className="retrieval-result-heading">
                          <strong>#{index + 1} · {result.document_name}</strong>
                          <span>Page {result.page_number ?? "unavailable"} · Score {result.score.toFixed(4)}</span>
                        </div>
                        <small>Chunk #{result.chunk_id} · Document #{result.document_id}</small>
                        <pre>{result.text}</pre>
                      </li>
                    ))}
                  </ol>
                </>
              )}
            </>
          )}
        </div>
      </div>
    </details>
  );
}
