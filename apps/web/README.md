# CourseMate Web

Next.js frontend for CourseMate.

## Local development

1. Start PostgreSQL and the API from `services/api`.
2. Install frontend dependencies:

```bash
npm install
```

3. Start the frontend:

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

The frontend calls `http://localhost:8000` by default. To use a different API, create `.env.local`:

```env
NEXT_PUBLIC_API_URL=http://localhost:8000
```

## Course flow

The Courses workspace uses the real backend API for:

- listing courses;
- creating a course;
- viewing course details, including documents and processing status;
- uploading PDFs up to 10 MiB;
- deleting a course after confirmation.

FastAPI error details are shown in the interface. Upload errors retain their
HTTP status so invalid PDFs (`400`), missing courses (`404`), duplicate files
(`409`), and files over the size limit (`413`) are clear to the user.

## Verification

Course detail pages include a collapsed **Retrieval debug** panel. It calls
`POST /courses/{id}/search` with a query and top_k, and displays the returned
chunks, PDF names, 1-based pages and cosine similarity scores. Scores are not
answer confidence. No chat or LLM generation is included. An empty response may
mean that parsing/backfill has not run; see the
[real-course retrieval runbook](../../docs/REAL_COURSE_RETRIEVAL.md).

```bash
npm run lint
npm test
npm run build
```
