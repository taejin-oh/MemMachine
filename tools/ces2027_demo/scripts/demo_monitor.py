"""Booth monitor: the state of every demo component on one screen, refreshed
every few seconds, with every change appended to a log (design section 6.4).

    python3 scripts/demo_monitor.py        # refresh every 10 seconds
    python3 scripts/demo_monitor.py 30     # every 30 seconds

Two groups of rows:
  1. the servers, probed over the network from this machine the way
     demo_check.py does (LLM, embedding, MemMachine, Open WebUI, the two
     database ports), so the monitor runs on any machine that has deploy/.env;
  2. the containers of deploy/docker-compose.yml on this machine, when docker
     is installed here, with their state and health. A container whose
     healthcheck says "unhealthy" is restarted: docker restarts a container
     that exited by itself but never one that hangs.

A row that changes is appended to scripts/demo_monitor.log with the time, so
what happened while nobody watched the screen can be read back. The monitor
only probes; it never sends a question to a model. Stop it with Ctrl-C.
"""

import json
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from common import DEMO_DIR, http_json, llm_urls_for_scripts, load_env, memmachine_url, openwebui_url, port_open, script_host

LOG_FILE = Path(__file__).resolve().parent / "demo_monitor.log"
COMPOSE = ["docker", "compose", "--project-directory", str(DEMO_DIR / "deploy")]
TIMEOUT = 5  # seconds per probe, so a dead server does not stall the screen


def main() -> None:
    interval = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    sys.stdout.reconfigure(line_buffering=True)  # the screen is complete even when redirected to a file
    env = load_env()
    probes = server_probes(env)
    docker_here = shutil.which("docker") is not None
    previous: dict[str, str] = {}
    while True:
        rows = [(name, *result(probe)) for name, probe in probes]
        if docker_here:
            rows += container_rows()
        print("\033[2J\033[H", end="")  # clear the terminal, cursor to the top
        print(f"CES 2027 demo monitor  {now()}  every {interval}s, changes go to {LOG_FILE.name}, Ctrl-C stops\n")
        for name, ok, detail in rows:
            line = f"{'OK  ' if ok else 'FAIL'} {name}: {detail}"
            print(line)
            if previous.get(name) != line:
                with LOG_FILE.open("a") as log:
                    log.write(f"{now()} {line}\n")
                previous[name] = line
        if not docker_here:
            print("\n(docker is not installed here, so the containers are not listed; run the monitor on the app server for that)")
        time.sleep(interval)


def server_probes(env: dict[str, str]) -> list:
    """The six servers of demo_check.py's first section, each as (name, probe)."""
    probes = [(f"LLM server {url}", lambda url=url: served_models(url)) for url in llm_urls_for_scripts(env)]
    embed = f"http://{script_host(env, 'EMBED_HOST')}:8001/v1"
    probes += [
        (f"embedding server {embed}", lambda: served_models(embed)),
        ("MemMachine", lambda: json.dumps(http_json("GET", f"{memmachine_url(env)}/api/v2/health", timeout=TIMEOUT))),
        ("Open WebUI", lambda: json.dumps(http_json("GET", f"{openwebui_url(env)}/health", timeout=TIMEOUT))),
        ("PostgreSQL port", lambda: port_open(script_host(env, "DB_HOST"), 5432)),
        ("Qdrant port", lambda: port_open(script_host(env, "DB_HOST"), 6333)),
    ]
    return probes


def served_models(base_url: str) -> str:
    return ", ".join(m["id"] for m in http_json("GET", f"{base_url}/models", timeout=TIMEOUT)["data"])


def result(probe) -> tuple[bool, str]:
    """(ok, detail) of one probe; the exception message is the detail of a failed one."""
    try:
        return True, probe()[:100]
    except Exception as error:
        return False, str(error)[:100]


def container_rows() -> list:
    """(name, ok, detail) per container of the compose project here, restarting the unhealthy ones."""
    listing = subprocess.run(COMPOSE + ["ps", "-a", "--format", "json"], capture_output=True, text=True)
    if listing.returncode != 0:
        return [("containers", False, listing.stderr.strip()[:100])]
    text = listing.stdout.strip()
    containers = json.loads(text) if text.startswith("[") else [json.loads(line) for line in text.splitlines()]
    rows = []
    for c in containers:
        # State and health only, e.g. "running (healthy)", "exited": the uptime in
        # c["Status"] would make every row a change on every refresh.
        health = c.get("Health") or ""  # absent in older compose versions and for services without a healthcheck
        detail = c["State"] + (f" ({health})" if health else "")
        if c["State"] == "running" and health == "unhealthy":  # hung; docker handles exited and restarting ones
            restart = subprocess.run(COMPOSE + ["restart", c["Service"]], capture_output=True, text=True)
            detail += ", restarted by the monitor" if restart.returncode == 0 else f", restart failed: {restart.stderr.strip()[:80]}"
        rows.append((f"container {c['Service']}", c["State"] == "running" and health != "unhealthy", detail))
    return rows


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


if __name__ == "__main__":
    main()
