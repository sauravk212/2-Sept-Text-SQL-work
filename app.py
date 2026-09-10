"""
FastAPI wrapper around the LangGraph text-to-SQL agent.

Runs locally with:
    uvicorn app:app --reload

Runs on Databricks Apps via app.yaml (see README.md).
"""

import logging
import os
import time
from pathlib import Path
from typing import Any, List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

load_dotenv()

# Import after load_dotenv so OPENAI_API_KEY is present when the LLM client is built.
from main import run_question, safe_parse_generated_rows  # noqa: E402
from constants import DATABASE_NAME, DB_PATH  # noqa: E402

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("text-to-sql")

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(
    title="Text-to-SQL Agent",
    version="1.0.0",
    description="Ask a question in plain English, get SQL and results back.",
)


# ============================================================
# SCHEMAS
# ============================================================


class QueryRequest(BaseModel):
    # `schema` is a reserved attribute on pydantic BaseModel, so the field is
    # named schema_text and exposed to callers as "schema" via the alias.
    question: str = Field(..., min_length=1, max_length=2000)
    schema_text: Optional[str] = Field(default=None, alias="schema")

    model_config = {"populate_by_name": True}


class QueryResponse(BaseModel):
    question: str
    sql: str
    rows: List[Any]
    row_count: int
    retries: int
    error: Optional[str] = None
    database: str
    elapsed_ms: int


# ============================================================
# LIFECYCLE
# ============================================================


@app.on_event("startup")
def check_configuration() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        logger.warning("OPENAI_API_KEY is not set — every query will fail.")

    db_file = Path(DB_PATH)
    if not db_file.exists():
        logger.warning("Database file not found at %s", db_file.resolve())

    logger.info("Serving database %s from %s", DATABASE_NAME, DB_PATH)


# ============================================================
# ROUTES
# ============================================================


@app.get("/health")
def health() -> dict:
    """Liveness probe. Databricks Apps polls this after deployment."""
    return {
        "status": "ok",
        "database": DATABASE_NAME,
        "db_present": Path(DB_PATH).exists(),
        "openai_key_set": bool(os.getenv("OPENAI_API_KEY")),
    }


@app.post("/query", response_model=QueryResponse)
def query(payload: QueryRequest) -> QueryResponse:
    """Run one question through the graph and return the SQL plus the rows."""
    question = payload.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Ask a question to run a query.")

    started = time.perf_counter()

    try:
        state = run_question(question)
    except Exception as exc:  # graph blew up before producing anything usable
        logger.exception("Graph failed for question: %s", question)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)

    sql = state.get("sql", "")
    error = state.get("error") or None
    rows = [] if error else safe_parse_generated_rows(state.get("result", ""))

    return QueryResponse(
        question=question,
        sql=sql,
        rows=rows,
        row_count=len(rows),
        retries=state.get("retries", 0),
        error=error,
        database=DATABASE_NAME,
        elapsed_ms=elapsed_ms,
    )


@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """The query console."""
    page = STATIC_DIR / "index.html"
    if not page.exists():
        return HTMLResponse("<h1>Text-to-SQL API is running</h1><p>See /docs.</p>")
    return HTMLResponse(page.read_text(encoding="utf-8"))


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("DATABRICKS_APP_PORT", "8000"))
    uvicorn.run("app:app", host="0.0.0.0", port=port)
