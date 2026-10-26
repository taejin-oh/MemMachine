"""Development stand-in for the two vLLM servers (chat model and embedder).

Serves the three OpenAI-compatible endpoints the demo stack calls:

    GET  /v1/models            two fake chat models, to try model switching
    POST /v1/chat/completions  a short streamed answer that reveals whether a
                               memory block reached the system prompt
    POST /v1/embeddings        deterministic bag-of-words vectors

Nothing here is a language model. Sentences that share words get similar
vectors, which is enough for top-k retrieval to look sensible while developing
without a GPU. The booth replaces this process with vLLM by changing addresses
in deploy/.env only.

Test switch: a user message containing "[llm-error]" makes the chat endpoint
answer HTTP 500, which exercises the Pipe's "LLM call failed" path.
"""

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import time
import uuid
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("mock_llm")

app = FastAPI(title="CES 2027 demo mock LLM")

# Model ids offered on /v1/models. The first one is what deploy/.env names.
MODEL_NAMES = [
    name.strip()
    for name in os.environ.get("MOCK_MODEL_NAMES", "mock-llm-a,mock-llm-b").split(",")
    if name.strip()
]
# Used when the embeddings request does not ask for a specific size.
DEFAULT_DIMENSIONS = 384
# The Pipe starts its memory block with this sentence (pipe/memmachine_pipe.py).
MEMORY_BLOCK_MARKER = "memories retrieved from the user's past conversations"


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/v1/models")
async def list_models() -> dict:
    return {
        "object": "list",
        "data": [{"id": name, "object": "model", "owned_by": "mock"} for name in MODEL_NAMES],
    }


# --- chat --------------------------------------------------------------------


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    if body.get("tools"):
        # The demo must never send tools. Seeing this means Open WebUI's
        # builtin tools are not switched off for the model (design section 5.3).
        names = [tool.get("function", {}).get("name") for tool in body["tools"]]
        log.warning("request for %s carries tools: %s", body.get("model"), names)

    model = body.get("model", "mock")
    messages = body.get("messages", [])
    if any("[llm-error]" in text_of(m) for m in messages if m.get("role") == "user"):
        return JSONResponse(status_code=500, content={"error": "failure requested with [llm-error]"})
    answer = compose_answer(messages)
    if body.get("stream"):
        return StreamingResponse(stream_chunks(model, answer), media_type="text/event-stream")
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "message": {"role": "assistant", "content": answer}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def compose_answer(messages: list[dict]) -> str:
    """Build a fixed-form answer that shows whether memories were in the prompt."""
    system_text = "\n".join(text_of(m) for m in messages if m.get("role") == "system")
    question = next((text_of(m) for m in reversed(messages) if m.get("role") == "user"), "")
    question = question[:60]

    if MEMORY_BLOCK_MARKER not in system_text:
        return f'(mock, no memory) I know nothing about you, so here is a generic answer to "{question}".'

    # Memory lines follow the marker and look like "[Nov 3, 2026 | title] user: ..."
    block = system_text.split(MEMORY_BLOCK_MARKER, 1)[1]
    memory_lines = [line for line in block.splitlines() if line.startswith("[")]
    first = memory_lines[0][:120] if memory_lines else "(none)"
    return (
        f"(mock, with memory) Using {len(memory_lines)} memories. The first one says: {first} ... "
        f'So, about "{question}": here is an answer grounded in those memories.'
    )


def text_of(message: dict) -> str:
    """Message content as plain text; Open WebUI may send a list of parts."""
    content = message.get("content", "")
    if isinstance(content, list):
        return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
    return content if isinstance(content, str) else ""


async def stream_chunks(model: str, answer: str) -> AsyncIterator[str]:
    """Yield the answer word by word as OpenAI-style server-sent events."""
    completion_id = f"chatcmpl-{uuid.uuid4().hex}"

    def chunk(delta: dict, finish_reason: str | None = None) -> str:
        payload = {
            "id": completion_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
        }
        return f"data: {json.dumps(payload)}\n\n"

    yield chunk({"role": "assistant", "content": ""})
    for word in answer.split(" "):
        yield chunk({"content": word + " "})
        await asyncio.sleep(0.03)  # looks like a model typing
    yield chunk({}, finish_reason="stop")
    yield "data: [DONE]\n\n"


# --- embeddings --------------------------------------------------------------


@app.post("/v1/embeddings")
async def embeddings(request: Request) -> dict:
    body = await request.json()
    texts = body.get("input", [])
    if isinstance(texts, str):
        texts = [texts]
    dimensions = int(body.get("dimensions") or DEFAULT_DIMENSIONS)
    return {
        "object": "list",
        "model": body.get("model", "embed"),
        "data": [
            {"object": "embedding", "index": i, "embedding": embed(str(text), dimensions)}
            for i, text in enumerate(texts)
        ],
        "usage": {"prompt_tokens": 0, "total_tokens": 0},
    }


def embed(text: str, dimensions: int) -> list[float]:
    """Bag-of-words hashing: each word adds 1 at a slot chosen by its hash.

    The same text always gives the same unit vector, and texts that share words
    have a higher dot product. It is lexical, not semantic: a question only
    finds memories that reuse its words, so expected phrases in a demo script
    are verified for real with the booth's embedding model (demo_check.py warns
    instead of failing while this mock is the embedder).
    """
    vector = [0.0] * dimensions
    for word in re.findall(r"[a-z0-9]+", text.lower().replace("'s", "")):
        digest = hashlib.md5(word.encode()).digest()
        vector[int.from_bytes(digest[:4], "little") % dimensions] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]
