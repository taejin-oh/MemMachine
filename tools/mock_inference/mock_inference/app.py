"""ASGI application: the four endpoints of design doc §9.

Plain ASGI, no framework. uvicorn imports this module in every worker
process, so the configuration comes from the MOCKINF_* environment
variables that `serve.py` sets (design doc §10.2).
"""

from __future__ import annotations

import base64
import logging
import os
import secrets
import sys
from pathlib import Path

import orjson

from . import vecstream

log = logging.getLogger("mock_inference")


class BadRequest(Exception):
    """A 400 whose message goes back to the client."""


def _env(name: str) -> str:
    try:
        return os.environ[name]
    except KeyError:
        raise RuntimeError(f"{name} is not set; start the server with `python -m mock_inference serve`") from None


VECTORS = Path(_env("MOCKINF_VECTORS"))
MODE = _env("MOCKINF_MODE")
CHUNK = int(_env("MOCKINF_CHUNK"))
WORKERS = int(_env("MOCKINF_WORKERS"))
_state_dir = _env("MOCKINF_STATE_DIR")
_affinity = _env("MOCKINF_AFFINITY")
STATE_DIR = Path(_state_dir) if _state_dir else None
AFFINITY = [int(core) for core in _affinity.split(",")] if _affinity else None
TOTAL, DIM = vecstream.open_vectors(VECTORS).shape
START, END = vecstream.parse_range(_env("MOCKINF_RANGE"), TOTAL)
STREAM = (
    vecstream.HashStream(VECTORS, START, END)
    if MODE == "hash"
    else vecstream.Stream(VECTORS, START, END, CHUNK, STATE_DIR)
)


# --- endpoints ---------------------------------------------------------------


def embeddings(req: dict) -> dict:
    keys, prompt_tokens = _embedding_input(req.get("input"))
    dims = req.get("dimensions")
    if dims is not None and dims != DIM:
        raise BadRequest(f"dimensions {dims} not supported; this mock serves {DIM}-dim vectors")
    fmt = "base64" if req.get("encoding_format") is None else req["encoding_format"]
    if fmt not in ("base64", "float"):
        raise BadRequest(f"encoding_format must be 'base64' or 'float', got {fmt!r}")

    vecs = STREAM.take(keys)
    if fmt == "float":
        encoded = vecs.tolist()
    else:
        encoded = [base64.b64encode(vec.tobytes()).decode() for vec in vecs]
    return {
        "id": "embd-" + secrets.token_hex(8),
        "object": "list",
        "model": req.get("model") or "mock-embed",
        "data": [{"object": "embedding", "index": i, "embedding": e} for i, e in enumerate(encoded)],
        "usage": {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens},
    }


def _embedding_input(value: object) -> tuple[list[str], int]:
    """One key per requested vector, plus the prompt_tokens to report (design §9.1 table)."""
    if isinstance(value, str):
        return [value], len(value) // 4
    if isinstance(value, list) and value:
        if all(isinstance(x, str) for x in value):
            return value, sum(len(x) for x in value) // 4
        if all(_is_int(x) for x in value):  # one row of token ids
            return [str(value)], len(value)
        if all(isinstance(x, list) and x and all(_is_int(t) for t in x) for x in value):  # rows of token ids
            return [str(x) for x in value], sum(len(x) for x in value)
    raise BadRequest("input must be a string, a list of strings, a list of token ids, or a list of token-id lists")


def _is_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)  # JSON true/false are ints too


def rerank(req: dict) -> dict:
    query = req.get("query") or ""
    documents = req.get("documents")
    if not isinstance(query, str) or not isinstance(documents, list):
        raise BadRequest("query must be a string and documents a list")
    texts = [_document_text(doc) for doc in documents]
    n = len(texts)
    top_n = n if req.get("top_n") is None else req["top_n"]
    if not _is_int(top_n) or top_n < 0:
        raise BadRequest("top_n must be a non-negative integer")

    results = [{"index": i, "relevance_score": 1 - i / n} for i in range(min(top_n, n))]
    if req.get("return_documents"):
        for result in results:
            result["document"] = {"text": texts[result["index"]]}
    chars = len(query) + sum(len(text) for text in texts)
    return {
        "id": "rerank-" + secrets.token_hex(8),
        "model": req.get("model") or "mock-rerank",
        "usage": {"total_tokens": chars // 4},
        "results": results,
    }


def _document_text(doc: object) -> str:
    if isinstance(doc, str):
        return doc
    if isinstance(doc, dict) and isinstance(doc.get("text"), str):
        return doc["text"]
    raise BadRequest("each document must be a string or an object with a text field")


def models() -> dict:
    return {
        "object": "list",
        "data": [
            {"id": "mock-embed", "object": "model", "owned_by": "mock"},
            {"id": "mock-rerank", "object": "model", "owned_by": "mock"},
        ],
    }


def health() -> dict:
    state = STREAM.health()
    info = {"status": "ok", "dim": DIM, "total": TOTAL, "mode": MODE, "range": [START, END]}
    if "next" in state:  # hash mode has no position
        info["next"], info["wraps"] = state["next"], state["wraps"]
    info |= {"workers": WORKERS, "chunk": CHUNK, "platform": sys.platform, "affinity": AFFINITY}
    return info


# --- routing -----------------------------------------------------------------


def _openai_error(message: str) -> dict:
    return {"error": {"message": message, "type": "invalid_request_error", "param": None, "code": None}}


def _plain_error(message: str) -> dict:
    return {"message": message}


GET_ROUTES = {"/v1/models": models, "/health": health}
POST_ROUTES = {
    "/v1/embeddings": (embeddings, _openai_error),
    "/v2/rerank": (rerank, _plain_error),
    "/v1/rerank": (rerank, _plain_error),
    "/rerank": (rerank, _plain_error),
}


async def app(scope: dict, receive, send) -> None:
    if scope["type"] != "http":
        return
    try:
        status, body = await _respond(scope, receive)
    except Exception as e:
        log.error("request to %s failed: %s", scope.get("path"), e)
        status, body = 503, orjson.dumps(_plain_error(str(e)))
    headers = [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    await send({"type": "http.response.start", "status": status, "headers": headers})
    # HEAD gets the same headers as GET (design doc §9) but no body.
    await send({"type": "http.response.body", "body": b"" if scope["method"] == "HEAD" else body})


async def _respond(scope: dict, receive) -> tuple[int, bytes]:
    path, method = scope["path"], scope["method"]
    if path in GET_ROUTES:
        if method not in ("GET", "HEAD"):
            return 405, orjson.dumps(_plain_error(f"{method} is not allowed on {path}"))
        return 200, orjson.dumps(GET_ROUTES[path]())
    if path in POST_ROUTES:
        handler, error = POST_ROUTES[path]
        if method != "POST":
            return 405, orjson.dumps(_plain_error(f"{method} is not allowed on {path}"))
        try:
            return 200, orjson.dumps(handler(_json_object(await _read_body(receive))))
        except BadRequest as e:
            return 400, orjson.dumps(error(str(e)))
    return 404, orjson.dumps(_plain_error(f"no route for {path}"))


async def _read_body(receive) -> bytes:
    chunks = []
    while True:
        message = await receive()
        chunks.append(message.get("body", b""))
        if not message.get("more_body"):
            return b"".join(chunks)


def _json_object(body: bytes) -> dict:
    try:
        payload = orjson.loads(body)
    except orjson.JSONDecodeError:
        raise BadRequest("request body is not valid JSON") from None
    if not isinstance(payload, dict):
        raise BadRequest("request body must be a JSON object")
    return payload
