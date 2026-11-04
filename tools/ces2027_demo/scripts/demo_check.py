"""Readiness check for the demo, one command after power-on (design section 5.5).

    python3 scripts/demo_check.py scenario/script_en.json

Prints one line per check and exits with a non-zero code if any failed:
  1. the LLM server(s), the embedding server, MemMachine, Open WebUI and the
     two database ports answer,
  2. the booth account sees the demo's model entries in Open WebUI (four per chat model in
     LLM_MODEL_ALLOW), and every one of those chat models is served by an LLM server,
  3. the Pipe is in the script's language (the last load used this script),
     its valves are at the defaults of the installed Pipe (a value saved in the
     admin UI survives a reinstall, so a changed one is listed as a warning),
     and for the first question and every follow-up of every demo topic the
     expected phrases are among the top-k memories that MemMachine retrieves
     from the loaded project, with the rank of each phrase (a rank beyond the
     valve SHOW_K reaches the LLM but is not shown on the screen),
  4. the Pipe's record mode (valve RECORD_MEMORY) is off,
  5. one question through the models: the memory model answers below its
     memory list, the no-memory model below its note (when the valve shows one),
     the step-by-step memory model below its third step.
"""

import json
import sys

from common import (REPLY_MARKERS, SCRIPT_VALVES, STEPS_SUFFIX, OpenWebUI, default_models, demo_models,
                    demo_questions, http_json, llm_model_ids, llm_model_names, llm_urls_for_scripts, load_env,
                    memmachine_url, no_memory_model_id, openwebui_url, pipe_model_id, port_open, read_script,
                    script_host)

failures = 0
PROBE_TIMEOUT = 5  # seconds for the server probes of section 1, so a powered-off server fails in seconds


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
        raise SystemExit("usage: demo_check.py <script_en.json | script_ko.json>")
    script = read_script(sys.argv[1])
    env = load_env()
    memmachine = memmachine_url(env)

    # 1. servers
    llm_models, embed_models = [], []
    key = env.get("LLM_API_KEY", "")  # a gateway that answers 401 to an anonymous probe needs it
    for url in llm_urls_for_scripts(env):
        check(f"LLM server {url}", lambda url=url: served_models(url, llm_models, key, llm_model_names(env)))
    embed = f"http://{script_host(env, 'EMBED_HOST')}:8001/v1"  # port fixed by design section 4.1, as in memmachine.yml
    check(f"embedding server {embed}", lambda: served_models(embed, embed_models))
    # The development mock embeds by word overlap, so expected phrases can only be
    # verified for real with the booth's embedding model; until then they warn.
    mock_embedder = embed_models and all(m.startswith("mock-") for m in embed_models)
    check("MemMachine", lambda: json.dumps(http_json("GET", f"{memmachine}/api/v2/health", timeout=PROBE_TIMEOUT)))
    check("Open WebUI", lambda: json.dumps(http_json("GET", f"{openwebui_url(env)}/health", timeout=PROBE_TIMEOUT)))
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
    expected_ids = {model_id for model_id, _, _ in demo_models(env)}
    check(f"the {len(expected_ids)} demo models visible to the booth account",
          lambda: booth_models(booth, expected_ids, bool(llm_models)))
    # One line per chat model the demo offers (LLM_MODEL_ALLOW), so a model that vanished from a gateway's list
    # is named instead of only the default being checked.
    missing_models = [name for name in llm_model_names(env) if name not in llm_models]
    report(not missing_models, "chat models served by the LLM server",
           ", ".join(llm_model_names(env)) if not missing_models else f"missing: {missing_models}")
    check("new chats open with the pair STEPS_BY_DEFAULT selects", lambda: default_pair_in_use(booth, env))

    # 3. the loaded language and the valves, then expected memories per question, in the project the Pipe searches
    try:
        defaults, stored = ui.valve_defaults(), ui.stored_valves()
    except RuntimeError as error:
        report(False, "the Pipe's valves", f"{error}; run setup_openwebui.py, then load_scenario.py")
        finish()
    valves = {**defaults, **stored}
    language = valves.get("LANGUAGE", "en")  # .get: an older installed Pipe has no such valve
    report(language == script["language"], "the Pipe is in the script's language",
           language if language == script["language"] else f"Pipe {language!r}, script {script['language']!r}: load this script first")
    # Values saved in the admin UI stay when the Pipe is reinstalled, so a default changed in the code does not
    # reach a server where the old value was saved once; list them so that nobody records with the wrong ones.
    changed = {name: value for name, value in stored.items() if name not in SCRIPT_VALVES and value != defaults.get(name)}
    report(not changed, "Pipe valves at the defaults of the installed Pipe",
           ", ".join(f"{name} {value!r} (default {defaults.get(name)!r})" if not secret_valve(name) else f"{name} (set)"
                     for name, value in changed.items())
           + "; set in Admin Panel > Functions > Valves" if changed else "", warn_only=True)
    project_id, top_k, show_k = valves["PROJECT_ID"], int(valves["TOP_K"]), int(valves.get("SHOW_K", 0))
    for demo in script["demos"]:
        for question in demo_questions(demo):
            check(f"top-{top_k} memories for '{question['text'][:50]}'",
                  lambda q=question: expected_memories(memmachine, project_id, top_k, show_k, q), warn_only=mock_embedder)
    if mock_embedder:
        print("     (mock embedder: expected phrases are matched by word overlap only; verify with the real embedder)")

    # 4. record mode off (while it is on, every question below would be stored as a memory)
    record_mode = bool(valves["RECORD_MEMORY"])
    report(not record_mode, "record mode (RECORD_MEMORY) is off")

    # 5. one answer through each model, recognised by the markers of the loaded language
    markers = REPLY_MARKERS.get(language, REPLY_MARKERS["en"])
    question = script["demos"][0]["first"]["text"]
    if record_mode:
        report(False, "answer from the Pipe model", "skipped: record mode would store the question")
    else:
        check("answer from the Pipe model", lambda: model_answer(ui, left, question, markers["memory_list"]))
    note = markers["no_memory_note"] if valves.get("SHOW_NO_MEMORY_NOTE", True) else None
    check("answer from the no-memory model", lambda: model_answer(ui, right, question, note))
    if not record_mode:
        check("answer from the step-by-step Pipe model",
              lambda: model_answer(ui, left + STEPS_SUFFIX, question, markers["last_step"]))
        check("second turn after a step-by-step answer: no card copied into the answer",
              lambda: second_turn_answer(ui, left + STEPS_SUFFIX, left, question, markers))
    finish()


def secret_valve(name: str) -> bool:
    """A valve whose value must not reach the console (this output gets pasted into issues and screenshots)."""
    return any(word in name.upper() for word in ("KEY", "PASSWORD", "SECRET", "TOKEN"))


def served_models(base_url: str, into: list, key: str = "", wanted: list[str] | None = None) -> str:
    """Model ids an OpenAI-compatible server lists; also appended to `into` for later checks. A gateway's list is
    long (a company one serves 26 ids including embeddings and rerankers), so `wanted` names the demo's own and the
    rest is counted; llm_model_ids retries with the key when an anonymous probe gets 401."""
    found = llm_model_ids(base_url, key)
    into.extend(found)
    if not wanted:
        return ", ".join(found)
    named = [name for name in wanted if name in found]
    rest = len(found) - len(named)
    return ", ".join(named) + (f" (+{rest} more)" if rest else "") or ", ".join(found)


def booth_models(booth: OpenWebUI, expected_ids: set[str], llm_up: bool) -> str:
    """The four demo model ids, if the booth account's model list has them all.

    The Pipe lists its models only while it can reach the LLM server, so with that server down the entries
    are gone as well and come back by themselves; the hint says so instead of sending staff to the setup script.
    """
    visible = {m["id"] for m in booth.call("GET", "/api/models")["data"]}
    missing = sorted(expected_ids - visible)
    if missing and not llm_up:
        raise_error("none while the LLM server is down (see its line above); they return by themselves when it is up")
    if missing:
        raise_error(f"missing: {missing}; run setup_openwebui.py")
    return ", ".join(sorted(expected_ids))


def default_pair_in_use(booth: OpenWebUI, env: dict[str, str]) -> str:
    """The pair .env asks for, if the running Open WebUI opens new chats with it (DEFAULT_MODELS is read at start)."""
    wanted = ",".join(default_models(env))
    actual = booth.call("GET", "/api/config").get("default_models") or ""
    if actual != wanted:
        raise_error(f"Open WebUI opens {actual!r}: after changing STEPS_BY_DEFAULT run "
                    "'docker compose --profile app up -d openwebui'")
    return wanted


def expected_memories(memmachine: str, project_id: str, top_k: int, show_k: int, question: dict) -> str:
    """The same search the Pipe makes; every expected phrase must occur in one of the retrieved texts.

    The detail names the rank of each phrase (1 = best). The LLM gets all top_k, but the card lists only the
    first show_k, so a phrase beyond that is used in the answer without being seen on the screen.
    """
    result = http_json("POST", f"{memmachine}/api/v2/memories/search",
                       {"project_id": project_id, "query": question["text"], "top_k": top_k})
    texts = [e["content"] for e in result["content"]["episodic_memory"]["long_term_memory"]["episodes"]]
    ranks = {phrase: next((number for number, text in enumerate(texts, start=1) if phrase in text), None)
             for phrase in question["expected"]}
    missing = [phrase for phrase, rank in ranks.items() if rank is None]
    if missing:
        raise_error(f"missing {missing} among {len(texts)} retrieved from {project_id}")
    detail = f"{len(texts)} retrieved from {project_id}; rank " + ", ".join(f"{p} {r}" for p, r in ranks.items())
    unseen = [phrase for phrase, rank in ranks.items() if show_k and rank > show_k]
    if unseen:
        detail += f"; {unseen} beyond SHOW_K {show_k}: used in the answer, not shown on the screen"
    return detail


def model_answer(ui: OpenWebUI, model_id: str, question: str, header: str | None) -> str:
    """Both Pipe models write a block (memory list or no-memory note), a rule, then the answer.

    header: text the block must contain, or None when the model writes no block. Errors start with a fixed phrase.
    """
    content = pipe_reply(ui, model_id, [{"role": "user", "content": question}])
    block, rule, answer = content.partition("\n---\n")
    if header is None:
        answer = content
    elif header not in block or not rule:
        raise_error(f"unexpected reply: {content[:200]!r}")
    if not answer.strip():
        raise_error(f"empty answer: {content[:200]!r}")
    return answer.strip()[:80]


def second_turn_answer(ui: OpenWebUI, first_model: str, second_model: str, question: str, markers: dict) -> str:
    """The question again, in a chat whose history holds the first answer card and all, as Open WebUI sends it.

    The Pipe cuts the card out of the history before the LLM sees it; without that the LLM copied the step
    titles and the memory list into its answer (issue #45). The answer part must contain none of the markers.
    """
    first = pipe_reply(ui, first_model, [{"role": "user", "content": question}])
    content = pipe_reply(ui, second_model, [{"role": "user", "content": question},
                                            {"role": "assistant", "content": first},
                                            {"role": "user", "content": question}])
    block, rule, answer = content.partition("\n---\n")
    copied = [marker for marker in markers.values() if marker in answer]
    if not rule or copied:
        raise_error(f"card markers {copied} in the second answer: {content[:200]!r}")
    if not answer.strip():
        raise_error(f"empty second answer: {content[:200]!r}")
    return answer.strip()[:80]


def pipe_reply(ui: OpenWebUI, model_id: str, messages: list[dict]) -> str:
    """Content of one non-streamed completion from a Pipe model; the Pipe's own errors start with a fixed phrase."""
    reply = ui.call("POST", "/api/chat/completions", {"model": model_id, "messages": messages, "stream": False})
    content = reply.get("choices", [{}])[0].get("message", {}).get("content", "")
    for prefix in ("Memory search failed:", "LLM call failed:", "MemMachine pipe:"):
        if prefix in content:
            raise_error(content[content.index(prefix):][:200])
    return content


def raise_error(message: str):
    raise RuntimeError(message)


def finish() -> None:
    print(f"\n{failures} failed" if failures else "\nall checks passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
