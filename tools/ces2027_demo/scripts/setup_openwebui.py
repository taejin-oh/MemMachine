"""Configure Open WebUI for the demo through its admin API (design section 5.3).

Run after `docker compose --profile local up -d` (or `--profile app` in the
booth) and again whenever pipe/memmachine_pipe.py or deploy/.env changes.
Every step creates or updates, so running it twice is harmless.

    python3 scripts/setup_openwebui.py

Steps:
  1. sign in as the staff account (created on the first run; first user = admin)
  2. install or update the Pipe function and switch it on
  3. write the Pipe valves that come from .env (shared system prompt, LLM
     address, brand name shown on the memory side)
  4. create or update the four model entries, all served by the Pipe (with and
     without memory, at once and step by step): display names, avatars from
     ../assets, the capability flags that stop Open WebUI from feeding past
     chats, notes or files to any of them, and read access for every account
     (the system prompt comes from the Pipe valve); entries of this Pipe that an
     earlier .env produced (another LLM_MODEL_NAME) are removed
  5. create the booth account if it is missing: a regular user, so that the
     USER_PERMISSIONS_* variables in docker-compose.yml apply to it and it
     sees only these two models (Open WebUI never restricts an admin)
  6. settings of both accounts: no release-notes pop-up on first login, an
     empty personal system prompt so nothing extra reaches either model, and
     temporary chats by default so nothing a visitor types is saved and the
     sidebar keeps showing only the loaded past chats, and wide screen mode so
     the two comparison cards use the whole display
"""

import base64
from datetime import date

from common import (ASSETS_DIR, PIPE_FILE, PIPE_ID, OpenWebUI, brand_name, default_models, demo_models, load_env,
                    openwebui_url)

# Blocks Open WebUI's builtin tools (search_chats, view_chat, ...) and the
# attach menu for a model; see the design document, section 5.3.
NO_PAST_CONTEXT = {"builtin_tools": False, "file_upload": False}
# Lets every account, in particular the booth account, see a model entry.
# Without a grant only admins see it. Grants have their own endpoint; the
# model update endpoint leaves them untouched.
PUBLIC_READ = [{"principal_type": "user", "principal_id": "*", "permission": "read"}]


def main() -> None:
    env = load_env()
    try:
        default_pair = default_models(env)  # validated first: compose reads the same key when openwebui starts
    except ValueError as error:
        raise SystemExit(str(error)) from None
    ui = OpenWebUI(openwebui_url(env))
    user = ui.login(env["ADMIN_NAME"], env["ADMIN_EMAIL"], env["ADMIN_PASSWORD"])
    print(f"signed in as {user['email']} ({user['role']})")
    if user["role"] != "admin":
        raise SystemExit("this account is not an admin: remove the openwebui_data volume and run again")

    brand = brand_name(env)
    install_pipe(ui, brand, {"BASE_SYSTEM_PROMPT": shared_system_prompt(env), "LLM_BASE_URLS": env["LLM_BASE_URLS"],
                             "BRAND_NAME": brand})

    # All entries are Pipe models; the Pipe gives each its system prompt, so no params here.
    models = demo_models(env)
    for model_id, name, avatar in models:
        upsert_model(ui, model_id, name, avatar)
    remove_stale_models(ui, {model_id for model_id, _, _ in models})
    print(f"new chats open with {', '.join(default_pair)} (STEPS_BY_DEFAULT; demo_check.py verifies the running container)")
    booth = ensure_booth_account(ui, env)
    temporary = env.get("TEMPORARY_CHAT", "true") == "true"
    quiet_account(ui, env["ADMIN_EMAIL"], temporary)
    quiet_account(booth, env["BOOTH_EMAIL"], temporary)
    print("done")


def shared_system_prompt(env: dict[str, str]) -> str:
    """Base prompt for both models, with the demo date when one is set.

    The weekday is spelled out so that "this Saturday" needs no calendar arithmetic from the model.
    """
    prompt = env["BASE_SYSTEM_PROMPT"]
    if env.get("DEMO_DATE"):
        try:
            demo_date = date.fromisoformat(env["DEMO_DATE"])
        except ValueError:
            raise SystemExit(f"DEMO_DATE in .env must look like 2027-01-06, not {env['DEMO_DATE']!r}") from None
        prompt += f"\nToday is {demo_date:%A}, {demo_date.isoformat()}."
    return prompt


def install_pipe(ui: OpenWebUI, name: str, valves: dict) -> None:
    """Create or update the Pipe function from the source file under the given title, enable it, and set the given valves."""
    form = {
        "id": PIPE_ID,
        "name": name,
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
        try:
            ui.call("POST", "/api/v1/auths/add", {"name": env["BOOTH_NAME"], "email": env["BOOTH_EMAIL"],
                                                  "password": env["BOOTH_PASSWORD"], "role": "user"})
        except RuntimeError as error:
            # The usual cause: the account exists but BOOTH_PASSWORD in .env was changed afterwards.
            raise SystemExit(f"booth account {env['BOOTH_EMAIL']} could not be created; if it already exists, "
                             f"BOOTH_PASSWORD in .env does not match it: {error}") from None
        booth.signin(env["BOOTH_EMAIL"], env["BOOTH_PASSWORD"])
        print(f"booth account {env['BOOTH_EMAIL']}: created")
    return booth


def quiet_account(ui: OpenWebUI, email: str, temporary: bool) -> None:
    """Keep the demo screen clean (design section 5.3): no "What's New" pop-up, no personal system prompt,
    wide screen mode, and new chats temporary (TEMPORARY_CHAT in .env) so that a visitor's questions are
    never saved and the sidebar keeps only the loaded past chats."""
    settings = ui.call("GET", "/api/v1/users/user/settings") or {}
    settings["ui"] = {**(settings.get("ui") or {}), "showChangelog": False, "system": "",
                      "temporaryChatByDefault": temporary, "widescreenMode": True}
    ui.call("POST", "/api/v1/users/user/settings/update", settings)
    print(f"account settings of {email}: release notes off, personal system prompt empty, "
          f"new chats {'temporary' if temporary else 'saved'}, wide screen mode")


def upsert_model(ui: OpenWebUI, model_id: str, name: str, avatar: str) -> None:
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
        "params": {},
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


def remove_stale_models(ui: OpenWebUI, keep: set[str]) -> None:
    """Delete entries of this Pipe that the current .env does not produce, e.g. from an earlier LLM_MODEL_NAME;
    they would stay in the staff account's model list under the old name."""
    for entry in ui.call("GET", "/api/v1/models/all"):
        if entry["id"].startswith(PIPE_ID + ".") and entry["id"] not in keep:
            ui.call("POST", "/api/v1/models/model/delete", {"id": entry["id"]})
            print(f"model {entry['id']}: removed (not made from the current .env)")


if __name__ == "__main__":
    main()
