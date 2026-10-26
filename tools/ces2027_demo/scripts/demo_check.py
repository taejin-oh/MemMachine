"""Readiness check for the demo, one command after power-on (design section 5.5).

    python3 scripts/demo_check.py scenario/script.sample.json

Prints one line per check and exits with a non-zero code if any failed:
  1. the LLM server(s), the embedding server, MemMachine, Open WebUI and the
     two database ports answer,
  2. Open WebUI lists the chat model and its MemMachine counterpart,
  3. for every question in the script, the expected phrases are among the
     top-k memories that MemMachine retrieves from the loaded project,
  4. the Pipe's record mode (valve RECORD_MEMORY) is off,
  5. one question through Open WebUI reaches the Pipe and gets an answer.
"""

import json
import socket
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from common import OpenWebUI, http_json, load_env, memmachine_url, openwebui_url, pipe_model_id, script_host

failures = 0


def report(ok: bool, what: str, detail: str = "") -> None:
    global failures
    failures += 0 if ok else 1
    print(f"{'OK  ' if ok else 'FAIL'} {what}" + (f": {detail}" if detail else ""))


def check(what: str, probe):
    """Run a probe; a return value or exception becomes the OK/FAIL line."""
    try:
        detail = probe()
        report(True, what, detail or "")
        return True
    except Exception as error:
        report(False, what, str(error))
        return False


def port_open(host: str, port: int) -> str:
    with socket.create_connection((host, port), timeout=5):
        return f"{host}:{port}"


def llm_urls_for_scripts(env: dict) -> list[str]:
    """LLM_BASE_URLS as seen from this machine: the container name 'llm' becomes LLM_HOST."""
    urls = []
    for url in env["LLM_BASE_URLS"].split(";"):
        parts = urlsplit(url.strip())
        if not parts.netloc:
            continue
        netloc = parts.netloc.replace("llm", script_host(env, "LLM_HOST"), 1) if parts.hostname == "llm" else parts.netloc
        urls.append(urlunsplit((parts.scheme, netloc, parts.path, "", "")).rstrip("/"))
    return urls


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: demo_check.py <script.json>")
    script = json.loads(Path(sys.argv[1]).read_text())
    env = load_env()
    memmachine = memmachine_url(env)

    # 1. servers
    llm_models = []
    for url in llm_urls_for_scripts(env):
        def served_models(url=url):
            found = [m["id"] for m in http_json("GET", f"{url}/models")["data"]]
            llm_models.extend(found)
            return ", ".join(found)
        check(f"LLM server {url}", served_models)
    embed = f"http://{script_host(env, 'EMBED_HOST')}:8001/v1"  # port fixed by design section 4.1, as in memmachine.yml
    check(f"embedding server {embed}", lambda: ", ".join(m["id"] for m in http_json("GET", f"{embed}/models")["data"]))
    check("MemMachine", lambda: json.dumps(http_json("GET", f"{memmachine}/api/v2/health")))
    check("Open WebUI", lambda: json.dumps(http_json("GET", f"{openwebui_url(env)}/health")))
    check("PostgreSQL port", lambda: port_open(script_host(env, "DB_HOST"), 5432))
    check("Qdrant port", lambda: port_open(script_host(env, "DB_HOST"), 6333))

    # 2. models in Open WebUI
    ui = OpenWebUI(openwebui_url(env))
    if not check("sign in to Open WebUI", lambda: ui.login(env["ADMIN_NAME"], env["ADMIN_EMAIL"], env["ADMIN_PASSWORD"])["email"]):
        finish()
    left, right = pipe_model_id(env), env["LLM_MODEL_NAME"]
    check("both demo models listed in Open WebUI",
          lambda: f"{left}, {right}" if {left, right} <= {m["id"] for m in ui.call("GET", "/api/models")["data"]}
          else raise_error(f"missing: {left} or {right}"))
    report(right in llm_models, "chat model served by the LLM server", right)

    # 3. expected memories per question, in the project the Pipe searches
    valves = ui.get_valves()
    project_id, top_k = valves["PROJECT_ID"], int(valves["TOP_K"])
    for question in script["questions"]:
        check(f"top-{top_k} memories for '{question['text'][:50]}'", lambda q=question: expected_memories(memmachine, project_id, top_k, q))

    # 4. record mode off (while it is on, every question below would be stored as a memory)
    record_mode = bool(valves["RECORD_MEMORY"])
    report(not record_mode, "record mode (RECORD_MEMORY) is off")

    # 5. one answer through the Pipe
    if record_mode:
        report(False, "answer from the Pipe model", "skipped: record mode would store the question")
    else:
        check("answer from the Pipe model", lambda: pipe_answer(ui, left, script["questions"][0]["text"]))
    finish()


def expected_memories(memmachine: str, project_id: str, top_k: int, question: dict) -> str:
    result = http_json("POST", f"{memmachine}/api/v2/memories/search",
                       {"project_id": project_id, "query": question["text"], "top_k": top_k})
    texts = [e["content"] for e in result["content"]["episodic_memory"]["long_term_memory"]["episodes"]]
    missing = [phrase for phrase in question["expected"] if not any(phrase in t for t in texts)]
    if missing:
        raise_error(f"missing {missing} among {len(texts)} retrieved from {project_id}")
    return f"{len(texts)} retrieved from {project_id}"


def pipe_answer(ui: OpenWebUI, model_id: str, question: str) -> str:
    """The Pipe writes the memory list, a rule, then the answer; errors start with a fixed phrase."""
    reply = ui.call("POST", "/api/chat/completions",
                    {"model": model_id, "messages": [{"role": "user", "content": question}], "stream": False})
    content = reply.get("choices", [{}])[0].get("message", {}).get("content", "")
    for prefix in ("Memory search failed:", "LLM call failed:", "MemMachine pipe:"):
        if prefix in content:
            raise_error(content[content.index(prefix):][:200])
    memory_list, _, answer = content.partition("\n---\n")
    if not memory_list.startswith("**Memories retrieved") or not answer.strip():
        raise_error(f"unexpected reply: {content[:200]!r}")
    return answer.strip()[:80]


def raise_error(message: str):
    raise RuntimeError(message)


def finish() -> None:
    print(f"\n{failures} failed" if failures else "\nall checks passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
