"""Free, offline embeddings for the MIT benchmark; evaluation use only.

Production code is unchanged: this module swaps ``app.embeddings.embed_text`` in
the current process for a local fastembed model, then runs either the existing
API or ``prepare_mit_course.py``. Vectors are stored under a separate
``EMBEDDING_REVISION`` so they never mix with OpenAI vectors; the stored
identifier still begins with ``openai:`` because the core config fixes it.
The model's 384 dimensions are zero-padded to the 1536-dimensional column,
which leaves cosine similarity unchanged.

Run from the repository root (``pip install fastembed`` first; the model is
downloaded from Hugging Face on first use, about 67 MB):

    services/api/.venv/Scripts/python.exe evals/retrieval/local_embeddings.py prepare --course-id 1
    services/api/.venv/Scripts/python.exe evals/retrieval/local_embeddings.py api --port 8000

Results measure this local model, not the production OpenAI model.
"""
import argparse
import os
from pathlib import Path
import sys

MODEL = "BAAI/bge-small-en-v1.5"
REVISION = "local-bge-small-en-v1.5"

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "api"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ["EMBEDDING_REVISION"] = REVISION  # before app/.env reads it

from app import embeddings  # noqa: E402

_model = None


def local_embed_text(text, *, config=None):
    global _model
    if not isinstance(text, str) or not text.strip():
        raise embeddings.EmbeddingError("Embedding input must not be blank")
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(MODEL)
    vector = [float(value) for value in next(iter(_model.embed([text])))]
    vector += [0.0] * (embeddings.EMBEDDING_DIMENSIONS - len(vector))
    return embeddings.validate_embedding(vector)


embeddings.embed_text = local_embed_text


def main(argv=None):
    parser = argparse.ArgumentParser(description="Run the benchmark with local embeddings")
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare", help="Parse and embed the benchmark Course")
    prepare.add_argument("--course-id", type=int, required=True)
    api = sub.add_parser("api", help="Serve the unchanged API with local query embeddings")
    api.add_argument("--port", type=int, default=8000)
    api.add_argument("--allow-origin", action="append", default=[],
                     help="Extra CORS origin, e.g. a web dev server on another port")
    args = parser.parse_args(argv)

    if args.command == "prepare":
        import prepare_mit_course
        return prepare_mit_course.main(["--course-id", str(args.course_id)])

    import uvicorn
    from fastapi.middleware.cors import CORSMiddleware
    from app.main import app
    for middleware in app.user_middleware:
        if middleware.cls is CORSMiddleware and args.allow_origin:
            middleware.kwargs["allow_origins"] = [*middleware.kwargs["allow_origins"], *args.allow_origin]
    uvicorn.run(app, host="127.0.0.1", port=args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
