"""Load the scripted past sessions into Open WebUI and MemMachine (design section 5.4).

    python3 scripts/load_scenario.py scenario/script.sample.json

Every run starts from scratch:
  1. a fresh MemMachine project named ces-<date>-<time> is chosen and written
     to the Pipe valve PROJECT_ID, so the left card searches only this load
     (MemMachine cannot reuse a deleted project, so old ones just stay unused),
  2. all chats of the staff account are deleted,
  3. each session of the script is imported as one chat with the script's date
     and one-minute spacing between turns, so the sidebar and the message
     timestamps show the past exactly as written,
  4. the same turns are stored as MemMachine episodes with the same timestamps
     and the new chat id as session_id, which the Pipe uses to show the title.

Reload the browser afterwards so the sidebar picks up the new chats.
"""

import json
import sys
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from common import PIPE_ID, OpenWebUI, http_json, load_env, memmachine_url, openwebui_url

TURN_SPACING = timedelta(minutes=1)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: load_scenario.py <script.json>")
    script = json.loads(Path(sys.argv[1]).read_text())
    env = load_env()
    model_id = f"{PIPE_ID}.{env['LLM_MODEL_NAME']}"
    model_name = f"MemMachine + {env['LLM_MODEL_NAME']}"

    ui = OpenWebUI(openwebui_url(env))
    ui.login(env["ADMIN_NAME"], env["ADMIN_EMAIL"], env["ADMIN_PASSWORD"])

    project_id = f"ces-{datetime.now():%Y%m%d-%H%M%S}"
    ui.set_valves({"PROJECT_ID": project_id})
    ui.call("DELETE", "/api/v1/chats/")
    print(f"project {project_id}: Pipe valve set, previous chats deleted")

    for session in script["sessions"]:
        turns = timed_turns(session)
        chat_id = import_chat(ui, session["title"], turns, model_id, model_name)
        store_episodes(memmachine_url(env), project_id, chat_id, turns)
        print(f"session '{session['title']}': {len(turns)} turns, chat {chat_id}")
    print("done. Reload the browser to see the chats.")


def timed_turns(session: dict) -> list[dict]:
    """The session's turns with a datetime each: the session date, plus one minute per turn."""
    start = datetime.fromisoformat(session["date"])
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
    main()
