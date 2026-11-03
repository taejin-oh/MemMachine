"""Helpers shared by the demo scripts: reading deploy/.env and calling Open WebUI.

Standard library only, so the scripts run on any machine with Python 3.10 or
newer without a virtual environment.
"""

import json
import socket
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

DEMO_DIR = Path(__file__).resolve().parent.parent  # tools/ces2027_demo
ENV_FILE = DEMO_DIR / "deploy" / ".env"
PIPE_FILE = DEMO_DIR / "pipe" / "memmachine_pipe.py"
ASSETS_DIR = DEMO_DIR / "assets"
PIPE_ID = "memmachine_pipe"  # Open WebUI function id; its models are named "<PIPE_ID>.<model>"
# Keys every script needs from .env; a missing one stops the run with the key names instead of a traceback.
REQUIRED_ENV = ("APP_HOST", "OPENWEBUI_PORT", "MEMMACHINE_PORT", "DB_HOST", "LLM_HOST", "EMBED_HOST",
                "LLM_MODEL_NAME", "LLM_BASE_URLS", "ADMIN_NAME", "ADMIN_EMAIL", "ADMIN_PASSWORD",
                "BOOTH_NAME", "BOOTH_EMAIL", "BOOTH_PASSWORD")
# Valves the scripts write themselves (setup_openwebui.py and load_scenario.py); every other stored valve
# is a value someone set in the admin UI, which demo_check.py lists.
SCRIPT_VALVES = ("DEMO_DATE", "LLM_BASE_URLS", "BRAND_NAME", "PROJECT_ID", "LANGUAGE", "BASE_SYSTEM_PROMPT")
NO_MEMORY_SUFFIX = "--no-memory"  # the Pipe's id suffix for the right-hand model (pipe/memmachine_pipe.py)
STEPS_SUFFIX = "--steps"  # the Pipe's id suffix for the step-by-step form of either model
LANGUAGES = ("en", "ko")  # the Pipe's TEXT table has these; a script file names one
# Texts demo_check.py looks for in the Pipe's replies, per language: the start of
# the memory list, the no-memory note, and the third step. They mirror TEXT in
# pipe/memmachine_pipe.py (memories_retrieved, no_memory_note, step).
REPLY_MARKERS = {
    "en": {"memory_list": "**Memories retrieved", "no_memory_note": "**No memory used.**", "last_step": "Step 3 of 3"},
    "ko": {"memory_list": "**검색된 기억", "no_memory_note": "**기억을 쓰지 않았습니다.**", "last_step": "3단계 중 3단계"},
}


def pipe_model_id(env: dict[str, str]) -> str:
    """Id of the left (memory) model in Open WebUI."""
    return f"{PIPE_ID}.{env['LLM_MODEL_NAME']}"


def brand_name(env: dict[str, str]) -> str:
    """Name of the memory side as the screen shows it (BRAND_NAME in .env; ids and file names keep 'memmachine')."""
    return env.get("BRAND_NAME", "MemMachine")


def pipe_model_name(env: dict[str, str]) -> str:
    """Display name of the left (memory) model."""
    return f"{brand_name(env)} + {env['LLM_MODEL_NAME']}"


def no_memory_model_id(env: dict[str, str]) -> str:
    """Id of the right (no-memory) model in Open WebUI, also served by the Pipe."""
    return f"{PIPE_ID}.{env['LLM_MODEL_NAME']}{NO_MEMORY_SUFFIX}"


def no_memory_model_name(env: dict[str, str]) -> str:
    """Display name of the right (no-memory) model."""
    return f"{env['LLM_MODEL_NAME']} (no memory)"


def default_models(env: dict[str, str]) -> list[str]:
    """Ids a new chat opens with, as docker-compose.yml builds DEFAULT_MODELS from the same .env: the instant pair,
    or the step-by-step pair when STEPS_BY_DEFAULT=true. Compose can only test whether the value is empty, so any
    other value is an error here instead of a silent true."""
    value = env.get("STEPS_BY_DEFAULT", "")
    if value not in ("", "true"):
        raise ValueError(f"STEPS_BY_DEFAULT in .env must be true or empty, not {value!r} (compose reads any value as true)")
    suffix = STEPS_SUFFIX if value else ""
    return [pipe_model_id(env) + suffix, no_memory_model_id(env) + suffix]


def demo_models(env: dict[str, str]) -> list[tuple[str, str, str]]:
    """The four models the booth sees, as (id, display name, avatar PNG): the two above and their step-by-step
    forms, which show the memory search, the prompt and the LLM call before the answer. The avatars come from
    AVATAR_MEMORY and AVATAR_NO_MEMORY in .env, a file name in ../assets or an absolute path."""
    memory, no_memory = env.get("AVATAR_MEMORY", "memmachine.png"), env.get("AVATAR_NO_MEMORY", "no_memory.png")
    return [
        (pipe_model_id(env), pipe_model_name(env), memory),
        (no_memory_model_id(env), no_memory_model_name(env), no_memory),
        (pipe_model_id(env) + STEPS_SUFFIX, f"{pipe_model_name(env)} (step by step)", memory),
        (no_memory_model_id(env) + STEPS_SUFFIX, f"{env['LLM_MODEL_NAME']} (no memory, step by step)", no_memory),
    ]


def read_script(path: str) -> dict:
    """The script file (scenario/script_en.json or script_ko.json), checked for the keys every tool relies on."""
    script = json.loads(Path(path).read_text(encoding="utf-8"))
    if script.get("language") not in LANGUAGES:
        raise SystemExit(f"{path}: language must be one of {LANGUAGES}, not {script.get('language')!r}")
    if not isinstance(script.get("system_prompt"), str) or not script["system_prompt"].strip():
        raise SystemExit(f"{path}: system_prompt must be a non-empty string")
    for key in ("sessions", "demos"):
        if not isinstance(script.get(key), list) or not script[key]:
            raise SystemExit(f"{path}: {key} must be a non-empty list")
    for demo in script["demos"]:
        for question in demo_questions(demo):
            if not isinstance(question.get("text"), str) or not isinstance(question.get("expected"), list):
                raise SystemExit(f"{path}: every first question and follow-up needs text and expected (demo {demo.get('topic')!r})")
    return script


def demo_questions(demo: dict) -> list[dict]:
    """The first question of a demo topic followed by its follow-up candidates."""
    return [demo["first"], *demo.get("follow_ups", [])]


def load_env(path: Path = ENV_FILE) -> dict[str, str]:
    """Parse KEY=VALUE lines the way docker compose reads them: a matching pair of quotes around a value is
    removed, and an unquoted value ends at ' #' (an inline comment). Stops when a required key is missing."""
    if not path.exists():
        raise SystemExit(f"{path} not found. Copy .env.example to .env in the same directory and edit it.")
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) > 1 and value[0] in "'\"" and value.endswith(value[0]):
            value = value[1:-1]
        else:
            value = value.split(" #", 1)[0].rstrip()
        values[key.strip()] = value
    missing = [key for key in REQUIRED_ENV if not values.get(key)]
    if missing:
        raise SystemExit(f"{path}: missing {', '.join(missing)}; copy those lines from .env.example and fill them in")
    return values


def script_host(env: dict[str, str], key: str) -> str:
    """Address of a server for a script running outside Docker.

    docker-compose.yml accepts 'host-gateway' in .env to mean 'this machine';
    outside Docker that is simply 127.0.0.1.
    """
    host = env[key]
    return "127.0.0.1" if host == "host-gateway" else host


def openwebui_url(env: dict[str, str]) -> str:
    """Open WebUI as seen from a script running outside Docker."""
    return f"http://{env['APP_HOST']}:{env['OPENWEBUI_PORT']}"


def memmachine_url(env: dict[str, str]) -> str:
    """MemMachine as seen from a script running outside Docker."""
    return f"http://{env['APP_HOST']}:{env['MEMMACHINE_PORT']}"


def llm_urls_for_scripts(env: dict[str, str]) -> list[str]:
    """LLM_BASE_URLS as seen from this machine: the container name 'llm' becomes LLM_HOST."""
    urls = []
    for url in env["LLM_BASE_URLS"].split(";"):
        parts = urlsplit(url.strip())
        if not parts.netloc:
            continue
        netloc = parts.netloc.replace("llm", script_host(env, "LLM_HOST"), 1) if parts.hostname == "llm" else parts.netloc
        urls.append(urlunsplit((parts.scheme, netloc, parts.path, "", "")).rstrip("/"))
    return urls


def port_open(host: str, port: int) -> str:
    """Connect to a TCP port and return 'host:port'; raises when nothing listens there."""
    with socket.create_connection((host, port), timeout=5):
        return f"{host}:{port}"


def http_json(method: str, url: str, body=None, token: str | None = None, timeout: int = 60):
    """One JSON request. Returns the parsed response; raises RuntimeError with the server's message on failure."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode()
    except urllib.error.HTTPError as error:
        detail = error.read().decode(errors="replace")[:300]
        raise RuntimeError(f"{method} {url} -> HTTP {error.code}: {detail}") from None
    except urllib.error.URLError as error:
        raise RuntimeError(f"{method} {url} -> {error.reason}") from None
    return json.loads(text) if text else None


class OpenWebUI:
    """Minimal client for the parts of the Open WebUI API the demo scripts use."""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.token: str | None = None

    def call(self, method: str, path: str, body=None):
        return http_json(method, self.base_url + path, body, self.token)

    def signin(self, email: str, password: str) -> dict:
        """Sign in as an existing account. Open WebUI allows 15 sign-ins per e-mail in 3 minutes, so each script signs in once per account per run."""
        user = self.call("POST", "/api/v1/auths/signin", {"email": email, "password": password})
        self.token = user["token"]
        return user

    def login(self, name: str, email: str, password: str) -> dict:
        """Sign in as the staff account, creating it on the first run (the first sign-up becomes admin)."""
        try:
            return self.signin(email, password)
        except RuntimeError as signin_error:
            if "HTTP 429" in str(signin_error):
                raise SystemExit("Open WebUI is limiting sign-ins for this e-mail (15 in 3 minutes): "
                                 "wait 3 minutes and run again") from None
            try:
                user = self.call("POST", "/api/v1/auths/signup", {"name": name, "email": email, "password": password})
            except RuntimeError as signup_error:
                raise SystemExit(f"sign-in failed: {signin_error}\nsign-up failed too: {signup_error}") from None
        self.token = user["token"]
        return user

    def valve_defaults(self) -> dict:
        """The defaults of the installed Pipe's Valves class."""
        spec = self.call("GET", f"/api/v1/functions/id/{PIPE_ID}/valves/spec") or {}
        return {name: field.get("default") for name, field in spec.get("properties", {}).items()}

    def stored_valves(self) -> dict:
        """The valves written by the scripts or saved in the admin UI; they survive a reinstall of the Pipe."""
        return self.call("GET", f"/api/v1/functions/id/{PIPE_ID}/valves") or {}

    def get_valves(self) -> dict:
        """The Pipe's effective valves: the defaults, overridden by what is stored."""
        return {**self.valve_defaults(), **self.stored_valves()}

    def set_valves(self, changes: dict) -> None:
        """Update some Pipe valves. The API replaces the whole stored set, so merge with it to keep values set in the admin UI."""
        self.call("POST", f"/api/v1/functions/id/{PIPE_ID}/valves/update", {**self.stored_valves(), **changes})
