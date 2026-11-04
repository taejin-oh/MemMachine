"""
title: MemMachine
version: 0.5.5
description: Four models per LLM: with and without memory, answering at once or showing the three steps (memory search, prompt, LLM) first. Screen text in English or Korean.
"""

# Open WebUI Pipe function for the CES 2027 demo (design section 5.2).
#
# Open WebUI loads this file as a "manifold" pipe: pipes() lists four models per
# chat model that the LLM server offers (or only those the valve LLM_MODEL_ALLOW
# names, when a shared gateway serves dozens of ids), "<BRAND_NAME> + <model>" and
# "<model> (no memory)" (id suffix NO_MEMORY_SUFFIX), each also in a step-by-step
# form (id suffix STEPS_SUFFIX), and pipe() handles one request. For every
# question the memory model
#   1. searches MemMachine for the top-k episodes (valve TOP_K),
#   2. streams them into the chat as a numbered list inside a NOTE callout
#      (Open WebUI's built-in "> [!NOTE]" markup: a blue bar; raw HTML and
#      colours are escaped by Open WebUI, so this is the one coloured block
#      available), followed by a rule,
#   3. puts the same episodes into the system prompt and streams the LLM's
#      answer below the rule.
# The LLM gets all TOP_K episodes, but everything the audience sees (the list,
# the counts in the status line and the step texts, the prompt block under
# step 2) shows only the best SHOW_K of them, as if that many had been found:
# the recorded demo keeps its five-line card while the answer draws on six.
# The no-memory model skips the search, writes a one-line grey note in place of
# the list (valve SHOW_NO_MEMORY_NOTE) and calls the same LLM with the same base
# system prompt, so the only difference between the two answers is the memory
# block. Both answers are capped by the valve MAX_TOKENS.
#
# The step-by-step models do the same work but write the three steps into the
# card as they happen ("Step 1 of 3: Searching memory ...", "Step 2 of 3:
# Composing the prompt ...", "Step 3 of 3: Asking <model>"), pause STEP_DELAY_MS
# between them so that each one can be seen, and show the exact prompt sent to
# the LLM in a collapsed block (SHOW_PROMPT). With PACE_NO_MEMORY the no-memory
# model walks the same three steps ("Skipped. This model has no memory."), so
# both cards move in one rhythm and what the right one lacks is visible as a
# step. The booth shows the at-once pair first and the step-by-step pair when
# the visitor wants to see how the answer is made.
#
# Everything the Pipe writes on the screen, and the memory instruction in the
# prompt, comes from TEXT in the language of the valve LANGUAGE (en or ko);
# scripts/load_scenario.py sets it from the script file together with the base
# system prompt, so loading a script switches the whole screen to its language.
# Error texts stay English: scripts/demo_check.py looks for their prefixes.
#
# Only packages that ship with the Open WebUI image are used (httpx, pydantic)
# plus Open WebUI's own chat table, which gives each memory its session title.
# scripts/setup_openwebui.py installs this file through the admin API.

import asyncio
import json
import time
from datetime import datetime
from typing import AsyncGenerator, Awaitable, Callable

import httpx
from open_webui.models.chats import Chats
from pydantic import BaseModel, Field

# Appended to the LLM model id to form the no-memory and the step-by-step models;
# scripts/common.py uses the same suffixes.
NO_MEMORY_SUFFIX = "--no-memory"
STEPS_SUFFIX = "--steps"
# Written between the card and the answer; strip_card() cuts the history at its first occurrence.
CARD_RULE = "---\n\n"

# Screen and prompt texts per language (valve LANGUAGE). scripts/common.py
# repeats the three markers that demo_check.py looks for (memories_retrieved,
# no_memory_note, step) and mock/mock_llm.py the start of memory_header: change
# them together.
TEXT = {
    "en": {
        # First line of the memory block in the system prompt.
        "memory_header": "The following are memories retrieved from the user's past conversations. Use every "
                         "memory that is relevant and state the specific facts you take from it (names, numbers, "
                         "days, places).",
        # "Today is Wednesday, 2027-01-06."; {weekday} is the English weekday name.
        "today": "Today is {weekday}, {date}.",
        # Shown above the no-memory answer as the counterpart of the memory list: a plain
        # (grey) blockquote, so the coloured NOTE block stays unique to the memory side.
        "no_memory_note": "> **No memory used.** This model answers without {brand}.\n\n",
        # Date of a memory as the list and the prompt show it, "Nov 3, 2026"; {month} is the short English month name.
        "date": "{month} {day}, {year}",
        "memories_retrieved": "**Memories retrieved ({count})**",
        "no_memories": "_No memories found._",
        "status_searching": "Searching memories",
        "status_retrieved": "Retrieved {count} memories",
        "status_answered": "Answered in {seconds:.1f} s",  # the LLM call only, without the step pauses
        "status_search_failed": "Memory search failed",
        "step": "Step {number} of {total}: {text}",
        "step_search": 'Searching memory for "{question}"',
        "step_search_done": "{count} memories found in {seconds:.1f} s",
        "step_search_skipped_title": "Searching memory",
        "step_search_skipped": "Skipped. This model has no memory.",
        "step_compose": "Composing the prompt from the system prompt, {memories} and your question",
        "memories_some": "{count} memories",
        "memories_none": "no memories",
        "step_ask": "Asking {model}",
        "prompt_summary": "Prompt sent to the LLM",
    },
    "ko": {
        "memory_header": "다음은 사용자의 과거 대화에서 찾은 기억이다. 관련 있는 기억은 모두 쓰고, 거기서 가져온 구체적인 "
                         "사실(이름, 숫자, 요일, 장소)을 답에 밝혀라.",
        "today": "오늘은 {date} {weekday}이다.",
        "no_memory_note": "> **기억을 쓰지 않았습니다.** 이 모델은 {brand} 없이 답합니다.\n\n",
        "date": "{year}년 {month_number}월 {day}일",
        "memories_retrieved": "**검색된 기억 ({count}개)**",
        "no_memories": "_찾은 기억이 없습니다._",
        "status_searching": "기억을 검색하는 중",
        "status_retrieved": "기억 {count}개를 찾았습니다",
        "status_answered": "{seconds:.1f}초 만에 답했습니다",
        "status_search_failed": "기억 검색 실패",
        "step": "{total}단계 중 {number}단계: {text}",
        "step_search": '기억을 검색합니다: "{question}"',
        "step_search_done": "{seconds:.1f}초 만에 기억 {count}개를 찾았습니다",
        "step_search_skipped_title": "기억 검색",
        "step_search_skipped": "건너뜁니다. 이 모델에는 기억이 없습니다.",
        "step_compose": "시스템 프롬프트, {memories}, 질문으로 프롬프트를 만듭니다",
        "memories_some": "기억 {count}개",
        "memories_none": "기억 없음",
        "step_ask": "{model}에 묻습니다",
        "prompt_summary": "LLM에 보낸 프롬프트",
    },
}
WEEKDAYS_KO = ["월요일", "화요일", "수요일", "목요일", "금요일", "토요일", "일요일"]

EventEmitter = Callable[[dict], Awaitable[None]]


class Pipe:
    class Valves(BaseModel):
        # Editable in the admin UI under Functions > <BRAND_NAME> > Valves.
        BRAND_NAME: str = Field(
            default="MemMachine",
            description="Name of the memory side as the screen shows it: model names from pipes() and the "
            "no-memory note. Set by setup_openwebui.py from .env.",
        )
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
        LLM_MODEL_ALLOW: str = Field(
            default="",
            description="Served model ids the model list offers, separated by ',', or empty for every id the servers "
            "list. A gateway that serves dozens of ids (embeddings and rerankers included) would otherwise put four "
            "entries per id in the dropdown. setup_openwebui.py writes LLM_MODEL_ALLOW from .env; the ids it makes "
            "workspace entries for come from the same key, so listing one here that is missing there hides it from "
            "the booth account but not from an admin.",
        )
        TOP_K: int = Field(default=6, description="How many memories to retrieve and give to the LLM.")
        SHOW_K: int = Field(
            default=5,
            description="How many of the retrieved memories the screen shows, best first: the card list, the counts "
            "in the status line and the step texts, and the prompt block under step 2. The rest are not mentioned. "
            "0 shows all. The LLM always gets all TOP_K.",
        )
        RECORD_MEMORY: bool = Field(
            default=False,
            description="Store every turn in MemMachine (record mode, design appendix D). Keep OFF during the demo.",
        )
        SHOW_SESSION_INFO: bool = Field(default=True, description="Show the date and session title of each memory.")
        MEMORY_PREVIEW_CHARS: int = Field(
            default=60,
            description="Longest memory text shown in the list, cut at a word and ended with '...'; one line in the "
            "comparison view in wide screen mode at 1600px (about 40 without wide screen mode). 0 shows the full text. The LLM always gets the full text.",
        )
        SHOW_NO_MEMORY_NOTE: bool = Field(
            default=True,
            description="Start the no-memory model's answer with a one-line note that no memory was used, "
            "as the counterpart of the memory list.",
        )
        LANGUAGE: str = Field(
            default="en",
            description="Language of the screen texts and of the memory instruction in the prompt: en or ko. "
            "Set by load_scenario.py from the script file.",
        )
        BASE_SYSTEM_PROMPT: str = Field(
            default="You are a helpful assistant. Keep every answer under 80 words, plain and concrete. Answer from "
            "what you know. Only when something essential is missing, say so in one sentence and ask one question.",
            description="Set by load_scenario.py from the script file; both models get the same text.",
        )
        DEMO_DATE: str = Field(
            default="",
            description="Date of the demo as 2027-01-06; both models are told 'Today is <weekday>, <date>.' in the "
            "screen language, so 'this Saturday' needs no calendar arithmetic. Empty: no such line. "
            "Set by setup_openwebui.py from .env.",
        )
        MAX_TOKENS: int = Field(
            default=300,
            description="Longest answer in tokens for both models; BASE_SYSTEM_PROMPT asks for a short answer and "
            "this is the safety net behind it. 0 sends no limit.",
        )
        DISABLE_THINKING: bool = Field(
            default=False,
            description="Send chat_template_kwargs {enable_thinking: false} with the LLM request, for reasoning "
            "models served by vLLM (the operator does the same with --default-chat-template-kwargs). Without it a "
            "thinking model can spend the whole MAX_TOKENS budget on reasoning and answer with nothing. Off = ask "
            "nothing. vLLM hands the key to the chat template, and templates that do not use it ignore it.",
        )
        REQUEST_TIMEOUT: int = Field(default=60, description="Seconds allowed for a MemMachine or LLM response.")
        # Step-by-step models only.
        STEP_DELAY_MS: int = Field(
            default=2000,
            description="Step-by-step models: pause between a step and the next thing on the card, so that each "
            "step can be read. The answer starts after three pauses. 0 runs at full speed.",
        )
        SHOW_PROMPT: bool = Field(
            default=True,
            description="Step-by-step models: show the exact prompt sent to the LLM in a collapsed block under step 2.",
        )
        PACE_NO_MEMORY: bool = Field(
            default=True,
            description="Step-by-step models: the no-memory model walks the same three steps ('Skipped. This model "
            "has no memory.') so that both cards move in one rhythm. Off: it answers at once with its one-line note.",
        )

    def __init__(self):
        self.valves = self.Valves()
        self._model_urls: dict[str, str] = {}  # model id -> LLM base URL, filled by pipes()

    # --- model list -----------------------------------------------------------

    async def pipes(self) -> list[dict]:
        """Four entries (with and without memory, at once and step by step) per chat model on each LLM server;
        Open WebUI calls this when it refreshes its model list."""
        entries = []
        allowed = self._allowed_models()
        async with self._client() as client:
            for index, base_url in enumerate(self._base_urls()):
                try:
                    response = await client.get(f"{base_url}/models", headers=self._llm_headers())
                    response.raise_for_status()
                    for model in response.json().get("data", []):
                        name = model["id"]
                        if allowed and name not in allowed:
                            continue  # a gateway that also serves embeddings and rerankers lists dozens of ids
                        self._model_urls[name] = base_url
                        # setup_openwebui.py gives the four demo models their final display names.
                        entries.append({"id": name, "name": f"{self.valves.BRAND_NAME} + {name}"})
                        entries.append({"id": name + NO_MEMORY_SUFFIX, "name": f"{name} (no memory)"})
                        entries.append({"id": name + STEPS_SUFFIX, "name": f"{self.valves.BRAND_NAME} + {name} (step by step)"})
                        entries.append({"id": name + NO_MEMORY_SUFFIX + STEPS_SUFFIX, "name": f"{name} (no memory, step by step)"})
                except Exception as error:
                    # Show the problem in the model dropdown instead of hiding it.
                    entries.append({"id": f"error-{index}", "name": f"{self.valves.BRAND_NAME}: cannot reach {base_url} ({error})"})
        return entries

    # --- one request ----------------------------------------------------------

    async def pipe(
        self,
        body: dict,
        __event_emitter__: EventEmitter | None = None,
        __task__: str | None = None,
        __chat_id__: str | None = None,
    ):
        # Open WebUI names the model "<function id>.<model id>"; the demo models
        # are the LLM model id plus NO_MEMORY_SUFFIX and/or STEPS_SUFFIX.
        model_id = body["model"].split(".", 1)[-1]
        in_steps = model_id.endswith(STEPS_SUFFIX)
        model_id = model_id.removesuffix(STEPS_SUFFIX)
        with_memory = not model_id.endswith(NO_MEMORY_SUFFIX)
        llm_model = model_id.removesuffix(NO_MEMORY_SUFFIX)
        if llm_model not in self._model_urls:
            await self.pipes()  # fills the map again after the module is reloaded (restart, update, toggle)
        base_url = self._model_urls.get(llm_model)
        if base_url is None:
            return (f"MemMachine pipe: {llm_model} is not offered by {self.valves.LLM_BASE_URLS} "
                    "(server unreachable or model name changed)")

        if __task__:
            # Background tasks (title generation and the like) are switched off
            # in the demo configuration. If one arrives anyway, answer without
            # touching memory so the task cannot leak into the comparison.
            return await self._complete(base_url, llm_model, body["messages"])

        return self._answer(base_url, llm_model, body["messages"], with_memory, in_steps, __event_emitter__, __chat_id__)

    async def _answer(
        self,
        base_url: str,
        model_id: str,
        messages: list[dict],
        with_memory: bool,
        in_steps: bool,
        emit: EventEmitter | None,
        chat_id: str | None,
    ) -> AsyncGenerator[str, None]:
        """Stream the memory list (or the no-memory note), a rule, then the LLM answer; the step-by-step models
        write the three steps around them.

        Open WebUI turns each yielded string into a chunk.
        """
        question = last_user_text(messages)
        steps = Steps(emit, self.valves.STEP_DELAY_MS / 1000, self._text("step")) if in_steps else None
        # The no-memory model walks the steps as well when PACE_NO_MEMORY is on, so both cards keep one rhythm.
        paced = steps is not None and (with_memory or self.valves.PACE_NO_MEMORY)

        memories: list[dict] = []  # all retrieved, for the LLM
        shown: list[dict] = []     # the SHOW_K best, for the screen
        if with_memory:
            if steps:
                async for chunk in steps.start(1, self._text("step_search", question=preview(question, 60))):
                    yield chunk
            else:
                await send_status(emit, self._text("status_searching"))
            search_started = time.monotonic()
            try:
                memories = await self._search(question)
            except Exception as error:
                # Fail loudly: answering without memory would make both sides look alike.
                await send_status(emit, self._text("status_search_failed"), done=True)
                yield f"Memory search failed: {error}"
                return
            # The screen shows the best SHOW_K as if only those had been found; the LLM gets them all.
            shown = memories[:self.valves.SHOW_K] if self.valves.SHOW_K > 0 else memories
            if steps:
                async for chunk in steps.finish(self._text("step_search_done", count=len(shown),
                                                           seconds=time.monotonic() - search_started)):
                    yield chunk
            else:
                await send_status(emit, self._text("status_retrieved", count=len(shown)), done=True)
            yield render_memory_list(shown, self.valves.SHOW_SESSION_INFO, self.valves.MEMORY_PREVIEW_CHARS,
                                     self._text("memories_retrieved", count=len(shown)), self._text("no_memories"))
        elif paced:
            async for chunk in steps.start(1, self._text("step_search_skipped_title")):
                yield chunk
            async for chunk in steps.finish(self._text("step_search_skipped")):
                yield chunk
        elif self.valves.SHOW_NO_MEMORY_NOTE:
            yield self._text("no_memory_note", brand=self.valves.BRAND_NAME)

        prompt = self._system_prompt(memories)
        llm_messages = [{"role": "system", "content": prompt}] + [strip_card(m) for m in messages
                                                                  if m.get("role") != "system"]

        if paced:
            parts = self._text("memories_some", count=len(shown)) if shown else self._text("memories_none")
            async for chunk in steps.start(2, self._text("step_compose", memories=parts)):
                yield chunk
            if self.valves.SHOW_PROMPT:
                # The block shows the prompt with the SHOW_K memories the card listed, not the full TOP_K.
                yield render_prompt(self._system_prompt(shown), question, self._text("prompt_summary"))
            async for chunk in steps.start(3, self._text("step_ask", model=model_id)):
                yield chunk
        yield CARD_RULE

        answer_parts = []
        llm_started = time.monotonic()
        try:
            async for token in self._stream(base_url, model_id, llm_messages):
                answer_parts.append(token)
                yield token
        except Exception as error:
            # Same rule as for memory: a visible error beats a card that stops silently.
            await send_status(emit, "LLM call failed", done=True)  # else the step-3 status keeps spinning
            yield f"\n\nLLM call failed: {error}"
            return
        if steps:
            await send_status(emit, self._text("status_answered", seconds=time.monotonic() - llm_started), done=True)

        if with_memory and self.valves.RECORD_MEMORY:
            try:
                await self._store(question, "".join(answer_parts), chat_id)
            except Exception as error:
                yield f"\n\nMemory write failed: {error}"

    # --- language -------------------------------------------------------------

    def _text(self, key: str, **values) -> str:
        """A screen or prompt text in the valve language; an unknown language falls back to English.
        Without values the template itself is returned, for Steps to fill in later."""
        template = TEXT.get(self.valves.LANGUAGE, TEXT["en"])[key]
        return template.format(**values) if values else template

    def _system_prompt(self, memories: list[dict]) -> str:
        """The base prompt, the date line when DEMO_DATE is set, and the memory block when there are memories."""
        prompt = self.valves.BASE_SYSTEM_PROMPT
        if self.valves.DEMO_DATE:
            try:
                day = datetime.fromisoformat(self.valves.DEMO_DATE).date()
            except ValueError:
                day = None  # setup_openwebui.py validates the value; a bad one typed into the valve is ignored
            if day:
                weekday = WEEKDAYS_KO[day.weekday()] if self.valves.LANGUAGE == "ko" else f"{day:%A}"
                prompt += "\n" + self._text("today", weekday=weekday, date=day.isoformat())
        if memories:
            prompt += "\n\n" + self._text("memory_header") + "\n" + "\n".join(memory_prompt_line(m) for m in memories)
        return prompt

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
                    "date": format_date(episode.get("created_at"), self._text("date")),
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
        if self.valves.MAX_TOKENS > 0:
            payload["max_tokens"] = self.valves.MAX_TOKENS
        if self.valves.DISABLE_THINKING:
            payload["chat_template_kwargs"] = {"enable_thinking": False}
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

    def _allowed_models(self) -> set[str]:
        """The ids LLM_MODEL_ALLOW names, or an empty set when it is empty (= offer every served id)."""
        return {name.strip() for name in self.valves.LLM_MODEL_ALLOW.split(",") if name.strip()}

    def _llm_headers(self) -> dict:
        """Bearer token for the LLM servers; no header at all when no key is set, so a plain vLLM sees the
        same request it saw before the key existed rather than an empty one."""
        return {"Authorization": f"Bearer {self.valves.LLM_API_KEY}"} if self.valves.LLM_API_KEY else {}


# --- step-by-step presentation ----------------------------------------------------


class Steps:
    """Writes the three steps of the step-by-step models into the card and mirrors them in the status line."""

    TOTAL = 3

    def __init__(self, emit: EventEmitter | None, delay: float, label: str):
        self.emit = emit
        self.delay = delay
        self.label = label  # TEXT["step"] of the language: "Step {number} of {total}: {text}"

    async def start(self, number: int, text: str) -> AsyncGenerator[str, None]:
        # The first title goes out as soon as the question arrives, so the card shows it is working; the
        # pauses come before every later step and between a step and its result (finish()).
        if self.delay and number > 1:
            await asyncio.sleep(self.delay)
        line = self.label.format(number=number, total=self.TOTAL, text=text)
        await send_status(self.emit, line)
        yield f"**{line}**\n\n"

    async def finish(self, result: str) -> AsyncGenerator[str, None]:
        # The result follows its step after one pause, so it reads as the outcome of the line above.
        if self.delay:
            await asyncio.sleep(self.delay)
        await send_status(self.emit, result, done=True)
        yield f"{result}\n\n"


def render_prompt(prompt: str, question: str, summary: str) -> str:
    """The exact text the LLM receives, in a collapsed block: the system prompt (with the memories) and the question."""
    return (
        f"<details>\n<summary>{summary}</summary>\n\n"
        f"```text\n[system]\n{prompt}\n\n[user]\n{question}\n```\n\n</details>\n\n"
    )


# --- formatting helpers ---------------------------------------------------------


def render_memory_list(memories: list[dict], show_session_info: bool, preview_chars: int, header: str, empty: str) -> str:
    """The block shown above the answer: a NOTE callout with the memories (the SHOW_K best). No scores on purpose."""
    lines = [header, ""]
    if not memories:
        lines.append(empty)
    for number, memory in enumerate(memories, start=1):
        label = memory_label(memory) if show_session_info else ""
        lines.append(f"{number}. {label}".rstrip())
        lines.append(f'   "{preview(memory["text"], preview_chars)}"')
    callout = ["> [!NOTE]"] + [f"> {line}".rstrip() for line in lines]
    return "\n".join(callout) + "\n\n"


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


def format_date(created_at: str | None, template: str) -> str:
    """ISO timestamp from MemMachine to the language's date form (TEXT "date", e.g. 'Nov 3, 2026') in the
    container's time zone (TZ in .env).

    MemMachine stores UTC and sends the offset ("2026-11-09T12:05:00Z"); converting keeps the list consistent
    with the chat timestamps the browser shows in the display device's local time. A value without an offset
    would be taken as local time by astimezone(), so the offset matters.
    """
    if not created_at:
        return ""
    try:
        moment = datetime.fromisoformat(created_at).astimezone()
    except ValueError:
        return ""
    return template.format(month=moment.strftime("%b"), month_number=moment.month, day=moment.day, year=moment.year)


def strip_card(message: dict) -> dict:
    """An earlier Pipe answer without its card, for the history the LLM sees.

    Open WebUI stores everything the Pipe streamed as the assistant message, card included, and sends it back
    in the next turn's messages. Left in, the LLM copies the card pattern (step titles, memory list) into its
    next answer instead of answering. The card ends at the first rule, which the Pipe writes before any answer
    token; the part before it is empty or starts like a step title or a blockquote, which leaves answers from
    other models alone.
    """
    content = message.get("content")
    if message.get("role") != "assistant" or not isinstance(content, str):
        return message
    card, rule, answer = content.partition(CARD_RULE)
    if not rule or (card and not card.startswith(("**", "> "))):
        return message
    return {**message, "content": answer}


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
    """Show a status line above the answer ("Searching memories", "Step 1 of 3: ...")."""
    if emit:
        await emit({"type": "status", "data": {"description": description, "done": done}})
