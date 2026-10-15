"""FastAPI application exposing the shorty URL shortener."""

import re
import secrets
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List, Optional
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, field_validator

from . import db

ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
CODE_LENGTH = 7
CUSTOM_CODE_RE = re.compile(r"[A-Za-z0-9_-]+")
# paths the app already serves; a link with one of these codes could never be reached
RESERVED_CODES = frozenset({"health", "links", "docs", "openapi.json", "redoc"})


def generate_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))


def validate_url(value: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("url must be a valid http or https URL")
    return value


class LinkCreate(BaseModel):
    url: str
    custom_code: Optional[str] = None

    @field_validator("url")
    @classmethod
    def check_url(cls, value: str) -> str:
        return validate_url(value)

    @field_validator("custom_code")
    @classmethod
    def check_custom_code(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value
        if value.lower() in RESERVED_CODES:
            raise ValueError(f"custom_code '{value}' is reserved")
        if not CUSTOM_CODE_RE.fullmatch(value):
            raise ValueError(
                "custom_code must be non-empty and contain only letters, "
                "digits, hyphens or underscores"
            )
        return value


class LinkStats(BaseModel):
    code: str
    url: str
    hits: int
    created_at: str


class LinkCreated(BaseModel):
    code: str
    url: str
    short_url: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="shorty", version="0.1.0", lifespan=lifespan)


def get_conn():
    conn = db.connect()
    try:
        yield conn
    finally:
        conn.close()


def fetch_link(conn: sqlite3.Connection, code: str) -> Optional[sqlite3.Row]:
    return conn.execute(
        "SELECT code, url, hits, created_at FROM links WHERE code = ?", (code,)
    ).fetchone()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/links", response_model=List[LinkStats])
def list_links(conn: sqlite3.Connection = Depends(get_conn)):
    rows = conn.execute(
        "SELECT code, url, hits, created_at FROM links ORDER BY created_at DESC, code"
    ).fetchall()
    return [dict(row) for row in rows]


@app.post("/links", response_model=LinkCreated, status_code=201)
def create_link(
    payload: LinkCreate,
    request: Request,
    conn: sqlite3.Connection = Depends(get_conn),
):
    created_at = datetime.now(timezone.utc).isoformat()

    if payload.custom_code is not None:
        code = payload.custom_code
        if fetch_link(conn, code) is not None:
            raise HTTPException(status_code=409, detail="custom code already in use")
    else:
        code = generate_code()
        while fetch_link(conn, code) is not None:
            code = generate_code()

    try:
        conn.execute(
            "INSERT INTO links (code, url, hits, created_at) VALUES (?, ?, 0, ?)",
            (code, payload.url, created_at),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="custom code already in use")

    return LinkCreated(
        code=code,
        url=payload.url,
        short_url=str(request.url_for("redirect", code=code)),
    )


@app.get("/links/{code}", response_model=LinkStats)
def link_stats(code: str, conn: sqlite3.Connection = Depends(get_conn)):
    row = fetch_link(conn, code)
    if row is None:
        raise HTTPException(status_code=404, detail="code not found")
    return dict(row)


@app.delete("/links/{code}", status_code=204)
def delete_link(code: str, conn: sqlite3.Connection = Depends(get_conn)):
    cur = conn.execute("DELETE FROM links WHERE code = ?", (code,))
    conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="code not found")
    return None


@app.get("/{code}", name="redirect")
def redirect(code: str, conn: sqlite3.Connection = Depends(get_conn)):
    row = fetch_link(conn, code)
    if row is None:
        raise HTTPException(status_code=404, detail="code not found")

    conn.execute("UPDATE links SET hits = hits + 1 WHERE code = ?", (code,))
    conn.commit()

    return RedirectResponse(url=row["url"], status_code=307)
