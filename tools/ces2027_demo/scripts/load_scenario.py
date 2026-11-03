"""Load the scripted past sessions into Open WebUI and MemMachine (design section 5.4).

    python3 scripts/load_scenario.py scenario/script_en.json

Every run starts from scratch:
  1. all chats of the booth account (the one the booth screen signs in as) are deleted,
  2. each session of the script is imported as one chat with the script's date
     and one-minute spacing between turns, so the sidebar and the message
     timestamps show the past exactly as written,
  3. the same turns are stored as MemMachine episodes of a fresh project named
     ces-<date>-<time>, with the same timestamps and the new chat id as
     session_id, which the Pipe uses to show the title. A turn with
     "store": false is left out of the memory: it is shown in the chat only.
     The scripts use it for assistant acknowledgements, which would otherwise
     outrank the user's facts in the search,
  4. last, the new project id is written to the Pipe valve PROJECT_ID, so the
     left card searches only this load, together with the script's language
     and system_prompt (valves LANGUAGE and BASE_SYSTEM_PROMPT), so loading a
     script also switches the screen texts and the shared instruction to its
     language. Until this step the Pipe keeps searching the previous, complete
     load, so a run that stops halfway leaves a working screen (without the
     deleted chats' titles) and is repaired by running the script again.
     MemMachine cannot reuse a deleted project, so old ones just stay unused.

Run scripts/setup_openwebui.py first: it creates the accounts and installs the
Pipe. Reload the browser afterwards so the sidebar picks up the new chats.
"""

import sys
import uuid
from datetime import datetime, timedelta

from common import (OpenWebUI, http_json, load_env, memmachine_url, openwebui_url, pipe_model_id, pipe_model_name,
                    read_script)

TURN_SPACING = timedelta(minutes=1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: load_scenario.py <script_en.json | script_ko.json>")
    script = read_script(sys.argv[1])
    sessions = [timed_turns(session) for session in script["sessions"]]  # validates before anything is touched
    env = load_env()

    admin = OpenWebUI(openwebui_url(env))  # only an admin may write the Pipe valves
    booth = OpenWebUI(openwebui_url(env))  # the chats must belong to the account the booth screen uses
    try:
        # signin, not login: only setup_openwebui.py creates accounts.
        admin.signin(env["ADMIN_EMAIL"], env["ADMIN_PASSWORD"])
        booth.signin(env["BOOTH_EMAIL"], env["BOOTH_PASSWORD"])
    except RuntimeError as error:
        raise SystemExit(f"{error}\nrun scripts/setup_openwebui.py first; it creates both accounts") from None

    project_id = f"ces-{datetime.now():%Y%m%d-%H%M%S}"
    if not booth.call("DELETE", "/api/v1/chats/"):
        raise SystemExit("Open WebUI could not delete the previous chats")
    print(f"previous chats of {env['BOOTH_EMAIL']} deleted")

    for session, turns in zip(script["sessions"], sessions):
        chat_id = import_chat(booth, session["title"], turns, pipe_model_id(env), pipe_model_name(env))
        stored = [turn for turn in turns if turn.get("store", True)]
        store_episodes(memmachine_url(env), project_id, chat_id, stored)
        print(f"session '{session['title']}': {len(turns)} turns, {len(stored)} stored as memories, chat {chat_id}")

    # Last, so that a run that stopped above left the Pipe on the previous, complete load.
    admin.set_valves({"PROJECT_ID": project_id, "LANGUAGE": script["language"],
                      "BASE_SYSTEM_PROMPT": script["system_prompt"]})
    print(f"project {project_id}: Pipe valves set (language {script['language']}). "
          "done. Reload the browser to see the chats.")


def timed_turns(session: dict) -> list[dict]:
    """The session's turns with a datetime each: the session date, plus one minute per turn.

    Checks the script first, so a mistake stops the run before any chat is deleted.
    """
    title = session.get("title", "?")
    try:
        start = datetime.fromisoformat(session["date"])
    except (KeyError, TypeError, ValueError):
        raise SystemExit(f"session '{title}': date must look like 2026-11-03T19:12:00+09:00, "
                         f"not {session.get('date')!r}") from None
    if start.tzinfo is None:
        raise SystemExit(f"session '{title}': the date needs a UTC offset such as +09:00")
    if not isinstance(session.get("turns"), list) or not session["turns"]:
        raise SystemExit(f"session '{title}': turns must be a non-empty list")
    for turn in session["turns"]:
        if turn.get("role") not in ("user", "assistant"):
            raise SystemExit(f"session '{title}': role must be user or assistant, not {turn.get('role')!r}")
        if not isinstance(turn.get("content"), str) or not turn["content"].strip():
            raise SystemExit(f"session '{title}': every turn needs a non-empty content string")
        if not isinstance(turn.get("store", True), bool):
            raise SystemExit(f"session '{title}': 'store' must be true or false when given")
    return [{**turn, "time": start + index * TURN_SPACING} for index, turn in enumerate(session["turns"])]


def import_chat(ui: OpenWebUI, title: str, turns: list[dict], model_id: str, model_name: str) -> str:
    """Import one finished chat in the shape Open WebUI itself saves, and return its new id."""
    messages = {}       # id -> message, the tree Open WebUI renders
    ordered = []        # the same messages in order, kept by Open WebUI as a flat list
    parent_id = None
    for turn in turns:
        message_id = str(uuid.uuid4())
        message = {
            "id": message_id,
            "parentId": parent_id,
            "childrenIds": [],
            "role": turn["role"],
            "content": turn["content"],
            "timestamp": int(turn["time"].timestamp()),
        }
        if turn["role"] == "assistant":
            message.update({"model": model_id, "modelName": model_name, "modelIdx": 0, "done": True})
        else:
            message["models"] = [model_id]
        if parent_id:
            messages[parent_id]["childrenIds"].append(message_id)
        messages[message_id] = message
        ordered.append(message)
        parent_id = message_id

    chat = {
        "title": title,
        "models": [model_id],
        "params": {},
        "history": {"messages": messages, "currentId": parent_id},
        "messages": ordered,
        "tags": [],
        "timestamp": ordered[0]["timestamp"] * 1000,
    }
    form = {"chat": chat, "created_at": ordered[0]["timestamp"], "updated_at": ordered[-1]["timestamp"]}
    imported = ui.call("POST", "/api/v1/chats/import", {"chats": [form]})
    return imported[0]["id"]


def store_episodes(memmachine: str, project_id: str, chat_id: str, turns: list[dict]) -> None:
    """Store the turns as episodes of the project, tagged with the chat id (design section 5.1)."""
    if not turns:
        return
    messages = [
        {
            "content": turn["content"],
            "producer": turn["role"],
            "role": turn["role"],
            "timestamp": turn["time"].isoformat(),
            "metadata": {"session_id": chat_id},
        }
        for turn in turns
    ]
    http_json("POST", f"{memmachine}/api/v2/memories", {"project_id": project_id, "messages": messages})


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as error:
        # An Open WebUI or MemMachine call failed; the Pipe still points at the previous load (see step 4).
        raise SystemExit(f"load stopped: {error}\nThe Pipe still searches the previous load. Fix the cause "
                         "(docker compose logs openwebui / memmachine) and run this script again; "
                         "every run starts over.") from None
