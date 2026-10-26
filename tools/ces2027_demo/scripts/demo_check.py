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

from common import PIPE_ID, OpenWebUI, http_json, load_env, memmachine_url, openwebui_url, script_host

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
        host = script_host(env, "LLM_HOST") if parts.hostname == "llm" else parts.hostname
        urls.append(urlunsplit((parts.scheme, f"{host}:{parts.port}", parts.path, "", "")).rstrip("/"))
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
    embed = f"http://{script_host(env, 'EMBED_HOST')}:8001/v1"
    check(f"embedding server {embed}", lambda: ", ".join(m["id"] for m in http_json("GET", f"{embed}/models")["data"]))
    check("MemMachine", lambda: json.dumps(http_json("GET", f"{memmachine}/api/v2/health")))
    check("Open WebUI", lambda: json.dumps(http_json("GET", f"{openwebui_url(env)}/health")))
    check("PostgreSQL port", lambda: port_open(script_host(env, "DB_HOST"), 5432))
    check("Qdrant port", lambda: port_open(script_host(env, "DB_HOST"), 6333))

    # 2. models in Open WebUI
    ui = OpenWebUI(openwebui_url(env))
    ui.login(env["ADMIN_NAME"], env["ADMIN_EMAIL"], env["ADMIN_PASSWORD"])
    left, right = f"{PIPE_ID}.{env['LLM_MODEL_NAME']}", env["LLM_MODEL_NAME"]
    ids = {m["id"] for m in ui.call("GET", "/api/models")["data"]}
    report(right in ids and left in ids, "both demo models listed in Open WebUI", f"{left}, {right}")
    report(right in llm_models, "chat model served by the LLM server", right)

    # 3. expected memories per question, in the project the Pipe searches
    valves = ui.get_valves()
    project_id, top_k = valves.get("PROJECT_ID", "universal"), int(valves.get("TOP_K", 5))
    for question in script["questions"]:
        result = http_json("POST", f"{memmachine}/api/v2/memories/search",
                           {"project_id": project_id, "query": question["text"], "top_k": top_k})
        texts = [e["content"] for e in result["content"]["episodic_memory"]["long_term_memory"]["episodes"]]
        missing = [phrase for phrase in question["expected"] if not any(phrase in t for t in texts)]
        report(not missing, f"top-{top_k} memories for '{question['text'][:50]}'",
               f"missing {missing}" if missing else f"{len(texts)} retrieved from {project_id}")

    # 4. record mode off
    report(not valves.get("RECORD_MEMORY", False), "record mode (RECORD_MEMORY) is off")

    # 5. one answer through the Pipe
    question = script["questions"][0]["text"]
    answer = ui.call("POST", "/api/chat/completions",
                     {"model": left, "messages": [{"role": "user", "content": question}], "stream": False})
    content = answer.get("choices", [{}])[0].get("message", {}).get("content", "")
    report("Memories retrieved" in content and "failed" not in content, "answer from the Pipe model",
           content.splitlines()[0] if content else json.dumps(answer)[:200])

    print(f"\n{failures} failed" if failures else "\nall checks passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
