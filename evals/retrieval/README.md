# Course retrieval benchmark

`parallel_computing.json` is an authored test course, not a university lecture
capture or an independent sample of real student questions. It expands the
parallel-programming topic already present in `topics.json`. Four documents,
12 explicit logical pages and 25 questions cover performance, shared-memory
concurrency, MPI communication, and decomposition. Each of the five question
types has five cases. Existing normalization and page-local chunking produce
24 canonical chunks (1200-character target, 200-character overlap).

The text is original teaching prose. The dataset's `references` identify primary
technical sources used to check selected OpenMP/MPI semantics. The full corpus,
question wording, expected document/page/topic and evidence are inspectable in
one JSON file (current dataset ID: `parallel-computing-v2`). Logical pages model already-extracted text; PDF extraction, images,
equations in images, and OCR quality are not evaluated.

## Run

From `services/api`, set `OPENAI_API_KEY` in that worktree's `.env` or the process
environment. Use an explicit separate PostgreSQL database with pgvector >= 0.7
and schema/extension privileges. Keep credentials out of tracked files.

```bash
TEST_POSTGRES_URL='postgresql+psycopg://USER:PASSWORD@HOST:PORT/TEST_DB' \
  python -m app.retrieval_eval --benchmark \
  --output ../../evals/retrieval/results/parallel-computing-v2-live.json
```

The command seeds a unique temporary schema, uses the existing embedding backfill
for all 24 chunks, and calls `search_course` for each question using real query
embeddings. It always removes the schema after success or handled failure. It
never seeds normal Course tables. It does not call RAG, a reranker or hybrid search.
The original three-topic sanity command remains available without `--benchmark`.

Exit 0 means a complete measurement, **not** that quality passed an acceptance
threshold. Exit 2 means preflight blocked (missing key/database/configuration).
Exit 1 means evaluation could not complete. A blocked record contains null metrics,
null latency, no question results and an explicit blocker. `real_embeddings_used`
is false when preflight proves no calls were made, null when a failed attempt may
have made some calls, and true only after the whole provider-backed run completes.
Synthetic embeddings exist only in automated tests and never in this CLI.

## Metric definitions

Each question has **one golden source evidence unit**, identified by document,
logical page and evidence spans fixed before retrieval. `evidence` is the primary
span; optional `alternative_evidence` lists separately reviewed passages that answer
the same question. Any canonical chunk containing one of those spans on that page
is an acceptable alternative. Each span must resolve, and alternatives must be a list. A different page
or another passage in the same document is insufficient.

- Recall@K is the fraction of all questions with at least one acceptable chunk
  among the first K results. With one evidence unit per question this is also
  source Hit Rate@K; it is not the fraction of every potentially relevant chunk
  retrieved. Overlapping copies of the same evidence do not change the denominator.
- MRR is the mean of 1 / the first acceptable result's rank, with zero for a miss.
  The benchmark retrieves the entire 24-chunk course once per question, so this is
  uncensored MRR, not MRR@5. Validation limits fixtures to 6–50 chunks, matching the
  current internal search limit and ensuring Top 5 is meaningful.
- Top 1 and Top 3 are prefixes of `top_5`. Exact cosine sorting and deterministic
  ID ties are the existing production behavior. No score cutoff is added.
- Latency is one full-course search, including the query embedding network request,
  Course/candidate SQL and ranking; it excludes fixture setup and chunk backfill.
  It is approximate end-to-end latency, not isolated database time or a benchmark
  of HTTP endpoint overhead. Full-course top-k is 24 rather than the API default 5.
  Mean, median and nearest-rank p95 are reported over all 25 questions.

## Inspect weak and failed results

The JSON artifact includes dataset/configuration provenance, a SHA-256 of canonical
JSON, a canonical chunk manifest, full Top 5 passage text and scores, expected
chunk IDs, first relevant rank, relevant passages even beyond rank 5, and full
ranked Chunk IDs. Outcomes are `top_1`, `weak_top_5` (rank 2–5), or `miss_at_5`.

For every weak/missed question, compare its actual Top 5 with `expected_hits` and
the annotated page. Use these checks before attributing a cause:

| Possible cause | Evidence to inspect |
| --- | --- |
| Chunk boundary/context | Does the returned passage lose the explanation or dependency at its edge? Check neighboring chunks on the page. Golden spans must resolve before any API call. |
| Query wording mismatch | Does the question use an implicit concept the source never names? Compare the intended meaning with the retrieved passage. |
| Weak embedding similarity | Is valid evidence eligible but below semantically unrelated material? Inspect scores and full rank; similarity alone does not establish the cause. |
| Duplicate/shared Content | Check canonical Chunk IDs and Course-local Document metadata; use the existing shared-content regression tests. |
| Distance/score error | Higher score must correspond to smaller cosine distance; score is 1 minus distance, not a probability. |
| Top-k issue | Check whether the evidence is at rank 2–3, 4–5 or beyond 5; report each metric without changing the labels. |
| Course filtering | Verify each returned Chunk is reachable from the selected Course; existing PG tests include a closer foreign-Course vector. |
| Annotation gap | Independently verify source evidence; do not expand accepted labels merely to raise a score. Version and retain before/after evidence for justified corrections. |

Do not automatically infer a model failure from rank alone. Keep representative
successful, weak and missed question IDs plus their actual passages in the report.
The current blocked report has no real-model success/failure examples to inspect.

## Question catalogue

Evidence spans and full source text are in `parallel_computing.json`.

| ID | Type | Question | Expected document / page | Expected topic |
| --- | --- | --- | --- | --- |
| F01 | factual | A run drops from 80 seconds to 20 seconds using eight workers. Where is the definition needed to calculate its acceleration? | 01-performance-notes.txt / 1 | speedup |
| F02 | factual | What is the best theoretical acceleration if a tenth of a fixed job must stay sequential? | 01-performance-notes.txt / 2 | Amdahl limit |
| F03 | factual | Which protection can make a single shared-counter increment indivisible? | 02-shared-memory-notes.txt / 1 | atomic update |
| F04 | factual | Which communication operation sends the same initial parameters from the coordinator to all workers? | 03-message-passing-notes.txt / 2 | broadcast |
| F05 | factual | What are the extra border copies used by a worker updating its own piece of a simulation grid? | 04-decomposition-notes.txt / 2 | halo cells |
| P01 | paraphrase | Why does the input preparation step become the main obstacle after the rest of a simulation is made much faster? | 01-performance-notes.txt / 2 | serial bottleneck |
| P02 | paraphrase | Some loop items take far longer than others. How can finished workers pick up more items instead of waiting? | 02-shared-memory-notes.txt / 3 | dynamic scheduling |
| P03 | paraphrase | I changed a local array on one machine. Why does another MPI worker still see its old copy? | 03-message-passing-notes.txt / 1 | separate address spaces |
| P04 | paraphrase | All machines passed the rendezvous, but their timestamps disagree. What assumption in my timing method is wrong? | 03-message-passing-notes.txt / 3 | barrier versus clock synchronization |
| P05 | paraphrase | Each worker owns equally many cells, yet using more workers spends a larger fraction of time exchanging borders. Why? | 04-decomposition-notes.txt / 2 | surface-to-volume effect |
| T01 | terminology | What measure describes how effectively the allocated processor count is being used relative to the observed acceleration? | 01-performance-notes.txt / 1 | parallel efficiency |
| T02 | terminology | What do researchers call the experiment where each extra machine receives another equally sized piece of work? | 01-performance-notes.txt / 3 | weak scaling |
| T03 | terminology | What is the name for cache interference between threads that write different nearby counters? | 02-shared-memory-notes.txt / 3 | false sharing |
| T04 | terminology | What collective operation combines workers' values with a function such as maximum? | 03-message-passing-notes.txt / 2 | reduction |
| T05 | terminology | Which task-graph quantity describes the sequential dependency chain that no number of processors can bypass? | 04-decomposition-notes.txt / 1 | span |
| C01 | comparison | How do the fixed-input and growing-input scaling experiments differ in what they hold constant? | 01-performance-notes.txt / 3 | strong versus weak scaling |
| C02 | comparison | How does waiting for everyone to finish a phase differ from protecting a shared update against simultaneous access? | 02-shared-memory-notes.txt / 2 | barrier versus mutex |
| C03 | comparison | How is starting an asynchronous send different from knowing its memory buffer is safe to overwrite? | 03-message-passing-notes.txt / 1 | nonblocking start versus completion |
| C04 | comparison | Is splitting an image into tiles the same kind of parallel decomposition as assigning decoding and filtering to different workers? | 04-decomposition-notes.txt / 1 | data versus task decomposition |
| C05 | comparison | Why can a fast network handle a huge transfer well but still be poor for thousands of tiny transfers? | 03-message-passing-notes.txt / 3 | latency versus bandwidth |
| H01 | hard | My numerical output is correct, but an eight-worker version of a tiny loop takes longer. Which performance costs should I inspect? | 01-performance-notes.txt / 1 | parallel overhead |
| H02 | hard | Two workers intermittently freeze: one holds the table lock and needs the log, while the other holds the log and needs the table. What explains this? | 02-shared-memory-notes.txt / 2 | circular wait deadlock |
| H03 | hard | Every solver worker needs the largest error across all workers before deciding to stop. Why would gathering the numbers to one coordinator be insufficient? | 03-message-passing-notes.txt / 2 | all-reduce convergence |
| H04 | hard | An image encoder needs filtered pixels. Can it safely overlap with filtering, and which items may move through the stages together? | 04-decomposition-notes.txt / 3 | pipeline dependencies |
| H05 | hard | All accesses are synchronized, but changing the worker arrangement slightly changes the final sum. What explanation should I investigate before adding more locks? | 04-decomposition-notes.txt / 3 | floating point reproducibility |

## Annotation review before live measurement

Independent source review found that H02 and H03 each had a second complete
answer-bearing passage on the same page which v1 did not accept. v2 adds those
explicit alternative spans; corpus, question wording, single-unit denominator
and ranking/metric rules are unchanged. This happened before any real embeddings
or measured quality. Tests force each previously rejected answering passage to
rank first and check that it counts while unrelated pages/documents remain excluded.
The v1 and v2 blocked records are retained with different dataset hashes. The exact
v1 JSON can be reconstructed by setting the ID to `parallel-computing-v1` and
removing the two `alternative_evidence` fields; its canonical hash was verified.
