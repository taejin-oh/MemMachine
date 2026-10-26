"""Configure Open WebUI for the demo through its admin API (design section 5.3).

Run after `docker compose --profile local up -d` (or `--profile app` in the
booth) and again whenever pipe/memmachine_pipe.py or deploy/.env changes.
Every step creates or updates, so running it twice is harmless.

    python3 scripts/setup_openwebui.py

Steps:
  1. sign in as the staff account (created on the first run; first user = admin)
  2. install or update the Pipe function and switch it on
  3. write the Pipe valves that come from .env (shared system prompt, LLM address)
  4. create or update the two model entries: display names, the same system
     prompt on the no-memory model, and the capability flags that stop Open
     WebUI from feeding past chats, notes or files to either model
"""

from common import PIPE_FILE, PIPE_ID, OpenWebUI, load_env, openwebui_url

# Blocks Open WebUI's builtin tools (search_chats, view_chat, ...) and the
# attach menu for a model; see the design document, section 5.3.
NO_PAST_CONTEXT = {"builtin_tools": False, "file_upload": False}


def main() -> None:
    env = load_env()
    ui = OpenWebUI(openwebui_url(env))
    user = ui.login(env["ADMIN_NAME"], env["ADMIN_EMAIL"], env["ADMIN_PASSWORD"])
    print(f"signed in as {user['email']} ({user['role']})")
    if user["role"] != "admin":
        raise SystemExit("this account is not an admin: remove the openwebui_data volume and run again")

    system_prompt = shared_system_prompt(env)
    install_pipe(ui, {"BASE_SYSTEM_PROMPT": system_prompt, "LLM_BASE_URLS": env["LLM_BASE_URLS"]})

    model = env["LLM_MODEL_NAME"]
    upsert_model(ui, f"{PIPE_ID}.{model}", f"MemMachine + {model}", params={})
    upsert_model(ui, model, f"{model} (no memory)", params={"system": system_prompt})
    print("done")


def shared_system_prompt(env: dict[str, str]) -> str:
    """Base prompt for both models, with the demo date when one is set."""
    prompt = env["BASE_SYSTEM_PROMPT"]
    if env.get("DEMO_DATE"):
        prompt += f"\nToday is {env['DEMO_DATE']}."
    return prompt


def install_pipe(ui: OpenWebUI, valves: dict) -> None:
    """Create or update the Pipe function from the source file, enable it, and set the given valves."""
    form = {
        "id": PIPE_ID,
        "name": "MemMachine",
        "content": PIPE_FILE.read_text(),
        "meta": {"description": "CES 2027 demo: top-k memories from MemMachine, then the answer."},
    }
    try:
        function = ui.call("GET", f"/api/v1/functions/id/{PIPE_ID}")
    except RuntimeError:
        function = None
    if function is None:
        function = ui.call("POST", "/api/v1/functions/create", form)
        print(f"function {PIPE_ID}: created")
    else:
        function = ui.call("POST", f"/api/v1/functions/id/{PIPE_ID}/update", form)
        print(f"function {PIPE_ID}: updated")
    if not function.get("is_active"):
        ui.call("POST", f"/api/v1/functions/id/{PIPE_ID}/toggle")
        print(f"function {PIPE_ID}: enabled")
    ui.set_valves(valves)


def upsert_model(ui: OpenWebUI, model_id: str, name: str, params: dict) -> None:
    """Create or update a workspace model entry that overrides how a base model is shown and prompted."""
    form = {
        "id": model_id,
        "base_model_id": None,
        "name": name,
        "meta": {"capabilities": NO_PAST_CONTEXT},
        "params": params,
        "is_active": True,
    }
    existing_ids = {entry["id"] for entry in ui.call("GET", "/api/v1/models/all")}
    if model_id in existing_ids:
        ui.call("POST", "/api/v1/models/model/update", form)
        print(f"model {model_id}: updated as '{name}'")
    else:
        ui.call("POST", "/api/v1/models/create", form)
        print(f"model {model_id}: created as '{name}'")


if __name__ == "__main__":
    main()
