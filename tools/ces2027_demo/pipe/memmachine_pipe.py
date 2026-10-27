"""
title: MemMachine
version: 0.2.0
description: Shows the top-k memories from MemMachine, then answers with the same LLM as the no-memory model.
"""

# Open WebUI Pipe function for the CES 2027 demo (design section 5.2).
#
# Open WebUI loads this file as a "manifold" pipe: pipes() lists one model per
# chat model that the LLM server offers, and pipe() handles one request. For
# every question the pipe
#   1. searches MemMachine for the top-k episodes,
#   2. streams them into the chat as a numbered list inside a NOTE callout
#      (Open WebUI's built-in "> [!NOTE]" markup: a blue bar; raw HTML and
#      colours are escaped by Open WebUI, so this is the one coloured block
#      available), followed by a rule,
#   3. puts the same episodes into the system prompt and streams the LLM's
#      answer below the rule.
# The right-hand "no memory" model is the same LLM called by Open WebUI
# directly with the same base system prompt, so the only difference between
# the two answers is the memory block.
#
# Only packages that ship with the Open WebUI image are used (httpx, pydantic)
# plus Open WebUI's own chat table, which gives each memory its session title.
# scripts/setup_openwebui.py installs this file through the admin API.

import json
from datetime import datetime
from typing import AsyncGenerator, Awaitable, Callable

import httpx
from open_webui.models.chats import Chats
from pydantic import BaseModel, Field

# First line of the memory block in the system prompt. The development mock
# looks for this sentence to tell "with memory" requests apart.
MEMORY_BLOCK_HEADER = (
    "The following are memories retrieved from the user's past conversations. "
    "Use them when they are relevant."
)

EventEmitter = Callable[[dict], Awaitable[None]]


class Pipe:
    class Valves(BaseModel):
        # Editable in the admin UI under Functions > MemMachine > Valves.
        MEMMACHINE_URL: str = Field(
            default="http://memmachine:8080",
            description="MemMachine server. Same compose network, so the service name works.",
        )
        LLM_BASE_URLS: str = Field(
            default="http://llm:8000/v1",
            description="OpenAI-compatible LLM servers, separated by ';'. Set by setup_openwebui.py from .env.",
        )
        PROJECT_ID: str = Field(
            default="universal",
            description="MemMachine project to search. load_scenario.py writes a fresh id here on every load.",
        )
        LLM_API_KEY: str = Field(default="dummy", description="Sent as a Bearer token; vLLM ignores it.")
        TOP_K: int = Field(default=5, description="How many memories to retrieve and show.")
        RECORD_MEMORY: bool = Field(
            default=False,
            description="Store every turn in MemMachine (record mode, design appendix D). Keep OFF during the demo.",
        )
        SHOW_SESSION_INFO: bool = Field(default=True, description="Show the date and session title of each memory.")
        MEMORY_PREVIEW_CHARS: int = Field(
            default=80,
            description="Longest memory text shown in the list, cut at a word and ended with '...'; about two lines "
            "in the comparison view. 0 shows the full text. The LLM always gets the full text.",
        )
        BASE_SYSTEM_PROMPT: str = Field(
            default="You are a helpful assistant. Answer briefly and concretely.",
            description="Set by setup_openwebui.py from .env; the no-memory model gets the same text.",
        )
        REQUEST_TIMEOUT: int = Field(default=60, description="Seconds allowed for a MemMachine or LLM response.")

    def __init__(self):
        self.valves = self.Valves()
        self._model_urls: dict[str, str] = {}  # model id -> LLM base URL, filled by pipes()

    # --- model list -----------------------------------------------------------

    async def pipes(self) -> list[dict]:
        """One entry per chat model on each LLM server; Open WebUI calls this when it refreshes its model list."""
        entries = []
        async with self._client() as client:
            for index, base_url in enumerate(self._base_urls()):
                try:
                    response = await client.get(f"{base_url}/models", headers=self._llm_headers())
                    response.raise_for_status()
                    for model in response.json().get("data", []):
                        self._model_urls[model["id"]] = base_url
                        # setup_openwebui.py gives the demo model its final display name.
                        entries.append({"id": model["id"], "name": f"MemMachine + {model['id']}"})
                except Exception as error:
                    # Show the problem in the model dropdown instead of hiding it.
                    entries.append({"id": f"error-{index}", "name": f"MemMachine pipe: cannot reach {base_url} ({error})"})
        return entries

    # --- one request ----------------------------------------------------------

    async def pipe(
        self,
        body: dict,
        __event_emitter__: EventEmitter | None = None,
        __task__: str | None = None,
        __chat_id__: str | None = None,
    ):
        # Open WebUI names the model "<function id>.<model id>".
        model_id = body["model"].split(".", 1)[-1]
        if model_id not in self._model_urls:
            await self.pipes()  # fills the map again after an Open WebUI restart
        base_url = self._model_urls.get(model_id)
        if base_url is None:
            return (f"MemMachine pipe: {model_id} is not offered by {self.valves.LLM_BASE_URLS} "
                    "(server unreachable or model name changed)")

        if __task__:
            # Background tasks (title generation and the like) are switched off
            # in the demo configuration. If one arrives anyway, answer without
            # touching memory so the task cannot leak into the comparison.
            return await self._complete(base_url, model_id, body["messages"])

        return self._answer_with_memories(base_url, model_id, body["messages"], __event_emitter__, __chat_id__)

    async def _answer_with_memories(
        self,
        base_url: str,
        model_id: str,
        messages: list[dict],
        emit: EventEmitter | None,
        chat_id: str | None,
    ) -> AsyncGenerator[str, None]:
        """Stream the memory list, a rule, then the LLM answer. Open WebUI turns each yielded string into a chunk."""
        question = last_user_text(messages)

        await send_status(emit, "Searching memories")
        try:
            memories = await self._search(question)
        except Exception as error:
            # Fail loudly: answering without memory would make both sides look alike.
            await send_status(emit, "Memory search failed", done=True)
            yield f"Memory search failed: {error}"
            return
        await send_status(emit, f"Retrieved {len(memories)} memories", done=True)

        yield render_memory_list(memories, self.valves.SHOW_SESSION_INFO, self.valves.MEMORY_PREVIEW_CHARS)

        prompt = self.valves.BASE_SYSTEM_PROMPT
        if memories:
            prompt += "\n\n" + MEMORY_BLOCK_HEADER + "\n" + "\n".join(memory_prompt_line(m) for m in memories)
        llm_messages = [{"role": "system", "content": prompt}] + [m for m in messages if m.get("role") != "system"]

        answer_parts = []
        try:
            async for token in self._stream(base_url, model_id, llm_messages):
                answer_parts.append(token)
                yield token
        except Exception as error:
            # Same rule as for memory: a visible error beats a card that stops silently.
            yield f"\n\nLLM call failed: {error}"
            return

        if self.valves.RECORD_MEMORY:
            try:
                await self._store(question, "".join(answer_parts), chat_id)
            except Exception as error:
                yield f"\n\nMemory write failed: {error}"

    # --- MemMachine -----------------------------------------------------------

    async def _search(self, query: str) -> list[dict]:
        """Top-k episodes for the query, each with the date and session title filled in."""
        payload = {"project_id": self.valves.PROJECT_ID, "query": query, "top_k": self.valves.TOP_K}
        async with self._client() as client:
            response = await client.post(f"{self.valves.MEMMACHINE_URL}/api/v2/memories/search", json=payload)
        response.raise_for_status()  # a project with nothing stored yet answers 200 with no episodes

        content = response.json().get("content") or {}
        episodes = ((content.get("episodic_memory") or {}).get("long_term_memory") or {}).get("episodes") or []

        titles: dict[str, str | None] = {}  # chat id -> title, looked up once per chat
        memories = []
        for episode in episodes:
            session_id = (episode.get("metadata") or {}).get("session_id")
            if session_id and session_id not in titles:
                chat = await Chats.get_chat_by_id(session_id)
                titles[session_id] = chat.title if chat else None
            memories.append(
                {
                    "text": episode.get("content", ""),
                    "role": episode.get("producer_role") or episode.get("producer_id") or "user",
                    "date": format_date(episode.get("created_at")),
                    "title": titles.get(session_id),
                }
            )
        return memories

    async def _store(self, question: str, answer: str, chat_id: str | None) -> None:
        """Record mode: save the user turn and the answer as two episodes of this chat."""
        now = datetime.now().astimezone().isoformat()
        metadata = {"session_id": chat_id} if chat_id else {}
        payload = {
            "project_id": self.valves.PROJECT_ID,
            "messages": [
                {"content": question, "producer": "user", "role": "user", "timestamp": now, "metadata": metadata},
                {"content": answer, "producer": "assistant", "role": "assistant", "timestamp": now, "metadata": metadata},
            ],
        }
        async with self._client() as client:
            response = await client.post(f"{self.valves.MEMMACHINE_URL}/api/v2/memories", json=payload)
        response.raise_for_status()

    # --- LLM server -----------------------------------------------------------

    async def _stream(self, base_url: str, model_id: str, messages: list[dict]) -> AsyncGenerator[str, None]:
        """Yield the content tokens of a streaming chat completion."""
        payload = {"model": model_id, "messages": messages, "stream": True}
        async with self._client() as client:
            async with client.stream(
                "POST", f"{base_url}/chat/completions", json=payload, headers=self._llm_headers()
            ) as response:
                if response.status_code >= 400:
                    await response.aread()  # the body holds vLLM's reason, e.g. context length
                    raise RuntimeError(f"HTTP {response.status_code} from {base_url}: {response.text[:300]}")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[len("data:"):].strip()
                    if data == "[DONE]":
                        break
                    choices = json.loads(data).get("choices") or []
                    if choices and choices[0].get("delta", {}).get("content"):
                        yield choices[0]["delta"]["content"]

    async def _complete(self, base_url: str, model_id: str, messages: list[dict]) -> str:
        """Non-streaming chat completion; only used for background tasks."""
        payload = {"model": model_id, "messages": messages, "stream": False}
        async with self._client() as client:
            response = await client.post(f"{base_url}/chat/completions", json=payload, headers=self._llm_headers())
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]

    def _client(self) -> httpx.AsyncClient:
        """HTTP client with a short connect timeout: Open WebUI calls pipes() on every model-list refresh,
        so an unreachable LLM server must fail in seconds, not in REQUEST_TIMEOUT."""
        return httpx.AsyncClient(timeout=httpx.Timeout(self.valves.REQUEST_TIMEOUT, connect=5))

    def _base_urls(self) -> list[str]:
        return [url.strip().rstrip("/") for url in self.valves.LLM_BASE_URLS.split(";") if url.strip()]

    def _llm_headers(self) -> dict:
        return {"Authorization": f"Bearer {self.valves.LLM_API_KEY}"}


# --- formatting helpers ---------------------------------------------------------


def render_memory_list(memories: list[dict], show_session_info: bool, preview_chars: int) -> str:
    """The block shown above the answer: a NOTE callout with the memories, then a rule. No scores on purpose."""
    lines = [f"**Memories retrieved ({len(memories)})**", ""]
    if not memories:
        lines.append("_No memories found._")
    for number, memory in enumerate(memories, start=1):
        label = memory_label(memory) if show_session_info else ""
        lines.append(f"{number}. {label}".rstrip())
        lines.append(f'   "{preview(memory["text"], preview_chars)}"')
    callout = ["> [!NOTE]"] + [f"> {line}".rstrip() for line in lines]
    return "\n".join(callout) + "\n\n---\n\n"


def preview(text: str, max_chars: int) -> str:
    """The text on one line, cut at a word boundary to max_chars and ended with '...'. 0 means no cut."""
    text = " ".join(text.split())  # a line break inside the callout would end the blockquote
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "..."


def memory_label(memory: dict) -> str:
    """'**Nov 3, 2026** (Session title)'; the title is left out when unknown."""
    label = f"**{memory['date']}**" if memory["date"] else ""
    if memory["title"]:
        label += f" ({memory['title']})"
    return label.strip()


def memory_prompt_line(memory: dict) -> str:
    """One memory as the LLM sees it: '[Nov 3, 2026 | Session title] user: ...'."""
    where = " | ".join(part for part in (memory["date"], memory["title"]) if part)
    return f"[{where}] {memory['role']}: {memory['text']}"


def format_date(created_at: str | None) -> str:
    """ISO timestamp from MemMachine to 'Nov 3, 2026' in the container's time zone (TZ in .env).

    MemMachine stores UTC; converting keeps the list consistent with the chat
    timestamps the browser shows in the display device's local time.
    """
    if not created_at:
        return ""
    try:
        moment = datetime.fromisoformat(created_at).astimezone()
    except ValueError:
        return ""
    return f"{moment.strftime('%b')} {moment.day}, {moment.year}"


def last_user_text(messages: list[dict]) -> str:
    """Text of the latest user message; Open WebUI may send content as a list of parts."""
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        content = message.get("content", "")
        if isinstance(content, list):
            return " ".join(part.get("text", "") for part in content if isinstance(part, dict))
        return content if isinstance(content, str) else ""
    return ""


async def send_status(emit: EventEmitter | None, description: str, done: bool = False) -> None:
    """Show a status line above the answer ("Searching memories", "Retrieved 5 memories")."""
    if emit:
        await emit({"type": "status", "data": {"description": description, "done": done}})
