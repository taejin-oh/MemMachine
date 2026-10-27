"""Configure Open WebUI for the demo through its admin API (design section 5.3).

Run after `docker compose --profile local up -d` (or `--profile app` in the
booth) and again whenever pipe/memmachine_pipe.py or deploy/.env changes.
Every step creates or updates, so running it twice is harmless.

    python3 scripts/setup_openwebui.py

Steps:
  1. sign in as the staff account (created on the first run; first user = admin)
  2. install or update the Pipe function and switch it on
  3. write the Pipe valves that come from .env (shared system prompt, LLM address)
  4. create or update the two model entries: display names, avatars from
     ../assets, the same system prompt on the no-memory model, the capability
     flags that stop Open WebUI from feeding past chats, notes or files to
     either model, and read access for every account
  5. create the booth account if it is missing: a regular user, so that the
     USER_PERMISSIONS_* variables in docker-compose.yml apply to it and it
     sees only these two models (Open WebUI never restricts an admin)
  6. settings of both accounts: no release-notes pop-up on first login, and an
     empty personal system prompt so nothing extra reaches either model
"""

import base64

from common import ASSETS_DIR, PIPE_FILE, PIPE_ID, OpenWebUI, load_env, openwebui_url, pipe_model_id, pipe_model_name

# Blocks Open WebUI's builtin tools (search_chats, view_chat, ...) and the
# attach menu for a model; see the design document, section 5.3.
NO_PAST_CONTEXT = {"builtin_tools": False, "file_upload": False}
# Lets every account, in particular the booth account, see a model entry.
# Without a grant only admins see it. Grants have their own endpoint; the
# model update endpoint leaves them untouched.
PUBLIC_READ = [{"principal_type": "user", "principal_id": "*", "permission": "read"}]


def main() -> None:
    env = load_env()
    ui = OpenWebUI(openwebui_url(env))
    user = ui.login(env["ADMIN_NAME"], env["ADMIN_EMAIL"], env["ADMIN_PASSWORD"])
    print(f"signed in as {user['email']} ({user['role']})")
    if user["role"] != "admin":
        raise SystemExit("this account is not an admin: remove the openwebui_data volume and run again")

    system_prompt = shared_system_prompt(env)
    install_pipe(ui, {"BASE_SYSTEM_PROMPT": system_prompt, "LLM_BASE_URLS": env["LLM_BASE_URLS"]})

    upsert_model(ui, pipe_model_id(env), pipe_model_name(env), "memmachine.png", params={})
    upsert_model(ui, env["LLM_MODEL_NAME"], f"{env['LLM_MODEL_NAME']} (no memory)", "no_memory.png",
                 params={"system": system_prompt})
    booth = ensure_booth_account(ui, env)
    quiet_account(ui, env["ADMIN_EMAIL"])
    quiet_account(booth, env["BOOTH_EMAIL"])
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


def ensure_booth_account(ui: OpenWebUI, env: dict[str, str]) -> OpenWebUI:
    """Create the booth account (a regular user) when it does not exist yet; return a client signed in as it."""
    booth = OpenWebUI(ui.base_url)
    try:
        booth.signin(env["BOOTH_EMAIL"], env["BOOTH_PASSWORD"])
        print(f"booth account {env['BOOTH_EMAIL']}: exists")
    except RuntimeError:
        ui.call("POST", "/api/v1/auths/add", {"name": env["BOOTH_NAME"], "email": env["BOOTH_EMAIL"],
                                              "password": env["BOOTH_PASSWORD"], "role": "user"})
        booth.signin(env["BOOTH_EMAIL"], env["BOOTH_PASSWORD"])
        print(f"booth account {env['BOOTH_EMAIL']}: created")
    return booth


def quiet_account(ui: OpenWebUI, email: str) -> None:
    """Keep the demo screen clean: no "What's New" pop-up, no personal system prompt (design section 5.3)."""
    settings = ui.call("GET", "/api/v1/users/user/settings") or {}
    settings["ui"] = {**(settings.get("ui") or {}), "showChangelog": False, "system": ""}
    ui.call("POST", "/api/v1/users/user/settings/update", settings)
    print(f"account settings of {email}: release notes off, personal system prompt empty")


def upsert_model(ui: OpenWebUI, model_id: str, name: str, avatar: str, params: dict) -> None:
    """Create or update a workspace model entry that overrides how a base model is shown and prompted."""
    # Open WebUI serves only raster avatars (SVG falls back to its logo), hence PNG.
    png = (ASSETS_DIR / avatar).read_bytes()
    form = {
        "id": model_id,
        "base_model_id": None,
        "name": name,
        "meta": {
            "capabilities": NO_PAST_CONTEXT,
            "profile_image_url": "data:image/png;base64," + base64.b64encode(png).decode(),
        },
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
    ui.call("POST", "/api/v1/models/model/access/update", {"id": model_id, "access_grants": PUBLIC_READ})


if __name__ == "__main__":
    main()
