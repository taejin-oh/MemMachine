"""Readiness check for the demo, one command after power-on (design section 5.5).

    python3 scripts/demo_check.py scenario/script.sample.json

Prints one line per check and exits with a non-zero code if any failed:
  1. the LLM server(s), the embedding server, MemMachine, Open WebUI and the
     two database ports answer,
  2. the booth account sees the chat model and its MemMachine counterpart in Open WebUI,
  3. for every question in the script, the expected phrases are among the
     top-k memories that MemMachine retrieves from the loaded project,
  4. the Pipe's record mode (valve RECORD_MEMORY) is off,
  5. one question through each model: the memory model answers below its
     memory list, the no-memory model below its note (when the valve shows one).
"""

import json
import sys
from pathlib import Path

from common import (OpenWebUI, http_json, llm_urls_for_scripts, load_env, memmachine_url, no_memory_model_id,
                    openwebui_url, pipe_model_id, port_open, script_host)

failures = 0


def report(ok: bool, what: str, detail: str = "", warn_only: bool = False) -> None:
    """Print one result line. A failure counts unless warn_only, which prints WARN instead of FAIL."""
    global failures
    if ok:
        label = "OK  "
    elif warn_only:
        label = "WARN"
    else:
        label = "FAIL"
        failures += 1
    print(f"{label} {what}" + (f": {detail}" if detail else ""))


def check(what: str, probe, warn_only: bool = False):
    """Run a probe; its return value or exception becomes the result line."""
    try:
        detail = probe()
        report(True, what, detail or "")
        return True
    except Exception as error:
        report(False, what, str(error), warn_only)
        return False


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: demo_check.py <script.json>")
    script = json.loads(Path(sys.argv[1]).read_text())
    env = load_env()
    memmachine = memmachine_url(env)

    # 1. servers
    llm_models, embed_models = [], []
    for url in llm_urls_for_scripts(env):
        check(f"LLM server {url}", lambda url=url: served_models(url, llm_models))
    embed = f"http://{script_host(env, 'EMBED_HOST')}:8001/v1"  # port fixed by design section 4.1, as in memmachine.yml
    check(f"embedding server {embed}", lambda: served_models(embed, embed_models))
    # The development mock embeds by word overlap, so expected phrases can only be
    # verified for real with the booth's embedding model; until then they warn.
    mock_embedder = embed_models and all(m.startswith("mock-") for m in embed_models)
    check("MemMachine", lambda: json.dumps(http_json("GET", f"{memmachine}/api/v2/health")))
    check("Open WebUI", lambda: json.dumps(http_json("GET", f"{openwebui_url(env)}/health")))
    check("PostgreSQL port", lambda: port_open(script_host(env, "DB_HOST"), 5432))
    check("Qdrant port", lambda: port_open(script_host(env, "DB_HOST"), 6333))

    # 2. models in Open WebUI
    ui = OpenWebUI(openwebui_url(env))
    # signin, not login: a check must never create the admin account on a fresh volume.
    if not check("sign in to Open WebUI", lambda: ui.signin(env["ADMIN_EMAIL"], env["ADMIN_PASSWORD"])["email"]):
        finish()
    booth = OpenWebUI(openwebui_url(env))
    check("sign in as the booth account", lambda: booth.signin(env["BOOTH_EMAIL"], env["BOOTH_PASSWORD"])["email"])
    left, right = pipe_model_id(env), no_memory_model_id(env)
    check("both demo models visible to the booth account",
          lambda: f"{left}, {right}" if {left, right} <= {m["id"] for m in booth.call("GET", "/api/models")["data"]}
          else raise_error(f"missing: {left} or {right}"))
    report(env["LLM_MODEL_NAME"] in llm_models, "chat model served by the LLM server", env["LLM_MODEL_NAME"])

    # 3. expected memories per question, in the project the Pipe searches
    valves = ui.get_valves()
    project_id, top_k = valves["PROJECT_ID"], int(valves["TOP_K"])
    for question in script["questions"]:
        check(f"top-{top_k} memories for '{question['text'][:50]}'",
              lambda q=question: expected_memories(memmachine, project_id, top_k, q), warn_only=mock_embedder)
    if mock_embedder:
        print("     (mock embedder: expected phrases are matched by word overlap only; verify with the real embedder)")

    # 4. record mode off (while it is on, every question below would be stored as a memory)
    record_mode = bool(valves["RECORD_MEMORY"])
    report(not record_mode, "record mode (RECORD_MEMORY) is off")

    # 5. one answer through each model
    question = script["questions"][0]["text"]
    if record_mode:
        report(False, "answer from the Pipe model", "skipped: record mode would store the question")
    else:
        check("answer from the Pipe model", lambda: model_answer(ui, left, question, "**Memories retrieved"))
    note = "**No memory used.**" if valves.get("SHOW_NO_MEMORY_NOTE", True) else None  # .get: an older installed Pipe has no such valve
    check("answer from the no-memory model", lambda: model_answer(ui, right, question, note))
    finish()


def served_models(base_url: str, into: list) -> str:
    """Model ids an OpenAI-compatible server lists; also appended to `into` for later checks."""
    found = [m["id"] for m in http_json("GET", f"{base_url}/models")["data"]]
    into.extend(found)
    return ", ".join(found)


def expected_memories(memmachine: str, project_id: str, top_k: int, question: dict) -> str:
    result = http_json("POST", f"{memmachine}/api/v2/memories/search",
                       {"project_id": project_id, "query": question["text"], "top_k": top_k})
    texts = [e["content"] for e in result["content"]["episodic_memory"]["long_term_memory"]["episodes"]]
    missing = [phrase for phrase in question["expected"] if not any(phrase in t for t in texts)]
    if missing:
        raise_error(f"missing {missing} among {len(texts)} retrieved from {project_id}")
    return f"{len(texts)} retrieved from {project_id}"


def model_answer(ui: OpenWebUI, model_id: str, question: str, header: str | None) -> str:
    """Both Pipe models write a block (memory list or no-memory note), a rule, then the answer.

    header: text the block must contain, or None when the model writes no block. Errors start with a fixed phrase.
    """
    reply = ui.call("POST", "/api/chat/completions",
                    {"model": model_id, "messages": [{"role": "user", "content": question}], "stream": False})
    content = reply.get("choices", [{}])[0].get("message", {}).get("content", "")
    for prefix in ("Memory search failed:", "LLM call failed:", "MemMachine pipe:"):
        if prefix in content:
            raise_error(content[content.index(prefix):][:200])
    block, rule, answer = content.partition("\n---\n")
    if header is None:
        answer = content
    elif header not in block or not rule:
        raise_error(f"unexpected reply: {content[:200]!r}")
    if not answer.strip():
        raise_error(f"empty answer: {content[:200]!r}")
    return answer.strip()[:80]


def raise_error(message: str):
    raise RuntimeError(message)


def finish() -> None:
    print(f"\n{failures} failed" if failures else "\nall checks passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
