"""Helpers shared by the demo scripts: reading deploy/.env and calling Open WebUI.

Standard library only, so the scripts run on any machine with Python 3.10 or
newer without a virtual environment.
"""

import json
import urllib.error
import urllib.request
from pathlib import Path

DEMO_DIR = Path(__file__).resolve().parent.parent  # tools/ces2027_demo
ENV_FILE = DEMO_DIR / "deploy" / ".env"
PIPE_FILE = DEMO_DIR / "pipe" / "memmachine_pipe.py"
ASSETS_DIR = DEMO_DIR / "assets"
PIPE_ID = "memmachine_pipe"  # Open WebUI function id; its models are named "<PIPE_ID>.<model>"


def pipe_model_id(env: dict[str, str]) -> str:
    """Id of the left (memory) model in Open WebUI."""
    return f"{PIPE_ID}.{env['LLM_MODEL_NAME']}"


def pipe_model_name(env: dict[str, str]) -> str:
    """Display name of the left (memory) model."""
    return f"MemMachine + {env['LLM_MODEL_NAME']}"


def load_env(path: Path = ENV_FILE) -> dict[str, str]:
    """Parse KEY=VALUE lines, the same format docker compose reads. Quotes around a value are removed."""
    if not path.exists():
        raise SystemExit(f"{path} not found. Copy .env.example to .env in the same directory and edit it.")
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
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


def http_json(method: str, url: str, body=None, token: str | None = None):
    """One JSON request. Returns the parsed response; raises RuntimeError with the server's message on failure."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
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

    def login(self, name: str, email: str, password: str) -> dict:
        """Sign in as the staff account, creating it on the first run (the first sign-up becomes admin).

        Open WebUI allows 15 sign-ins per e-mail in 3 minutes, so each script signs in once per run.
        """
        try:
            user = self.call("POST", "/api/v1/auths/signin", {"email": email, "password": password})
        except RuntimeError as signin_error:
            try:
                user = self.call("POST", "/api/v1/auths/signup", {"name": name, "email": email, "password": password})
            except RuntimeError as signup_error:
                raise SystemExit(f"sign-in failed: {signin_error}\nsign-up failed too: {signup_error}") from None
        self.token = user["token"]
        return user

    def get_valves(self) -> dict:
        """The Pipe's effective valves: the defaults from its Valves class, overridden by what is stored."""
        spec = self.call("GET", f"/api/v1/functions/id/{PIPE_ID}/valves/spec") or {}
        defaults = {name: field.get("default") for name, field in spec.get("properties", {}).items()}
        stored = self.call("GET", f"/api/v1/functions/id/{PIPE_ID}/valves") or {}
        return {**defaults, **stored}

    def set_valves(self, changes: dict) -> None:
        """Update some Pipe valves. The API replaces the whole stored set, so merge with it to keep values set in the admin UI."""
        stored = self.call("GET", f"/api/v1/functions/id/{PIPE_ID}/valves") or {}
        self.call("POST", f"/api/v1/functions/id/{PIPE_ID}/valves/update", {**stored, **changes})
