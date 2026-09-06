"""Thin HTTP client for the Freshness-Aware RAG FastAPI backend.

The Streamlit UI talks ONLY to these endpoints — the UI never imports pipeline
code directly, keeping the backend API the single source of truth.
"""

import os

import httpx

API_URL = os.getenv("API_URL", "http://127.0.0.1:8000")


def _client() -> httpx.Client:
    return httpx.Client(base_url=API_URL, timeout=120.0)


def health() -> bool:
    try:
        with _client() as c:
            return c.get("/health").status_code == 200
    except httpx.HTTPError:
        return False


def list_sources() -> list[dict]:
    with _client() as c:
        return c.get("/sources").json()


def create_source(name: str, url: str, interval_seconds: int | None = None) -> dict:
    payload: dict = {"name": name, "url": url}
    if interval_seconds:
        payload["interval_seconds"] = interval_seconds
    with _client() as c:
        resp = c.post("/sources", json=payload)
        resp.raise_for_status()
        return resp.json()


def delete_source(source_id: int) -> None:
    with _client() as c:
        c.delete(f"/sources/{source_id}").raise_for_status()


def run_source(source_id: int) -> dict:
    with _client() as c:
        resp = c.post(f"/sources/{source_id}/run")
        resp.raise_for_status()
        return resp.json()


def query(question: str, top_k: int) -> list[dict]:
    with _client() as c:
        resp = c.post("/query", json={"question": question, "top_k": top_k})
        resp.raise_for_status()
        return resp.json()["results"]


def history(source_id: int) -> list[dict]:
    with _client() as c:
        resp = c.get(f"/sources/{source_id}/history")
        resp.raise_for_status()
        return resp.json()["changes"]
