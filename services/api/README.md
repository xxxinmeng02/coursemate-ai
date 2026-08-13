# CourseMate AI API

Minimal FastAPI backend for local CourseMate AI development.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

The API runs at <http://localhost:8000>. Swagger documentation is available at <http://localhost:8000/docs>.
