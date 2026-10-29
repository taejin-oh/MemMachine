"""Install the trial step-by-step Pipe under one function id per style, for comparing the styles.

    python3 scripts/install_steps_variants.py           # install or update the three functions
    python3 scripts/install_steps_variants.py --remove  # delete them again

pipe/variants/memmachine_pipe_steps.py goes in as memmachine_pipe_status,
memmachine_pipe_timeline and memmachine_pipe_thinking, each with its STYLE
valve set and the main Pipe's valves copied (LLM address, project, prompt,
brand), so that all of them search the same memories. No workspace model
entries are made: the staff account sees Pipe models without them, the booth
account does not, so the booth screen is unaffected. Development only.
"""

import sys

from common import DEMO_DIR, PIPE_ID, OpenWebUI, load_env, openwebui_url

VARIANT_FILE = DEMO_DIR / "pipe" / "variants" / "memmachine_pipe_steps.py"
STYLES = ("status", "timeline", "thinking")
SHARED_VALVES = ("LLM_BASE_URLS", "PROJECT_ID", "BASE_SYSTEM_PROMPT", "BRAND_NAME", "TOP_K", "MEMORY_PREVIEW_CHARS")


def main() -> None:
    env = load_env()
    ui = OpenWebUI(openwebui_url(env))
    ui.login(env["ADMIN_NAME"], env["ADMIN_EMAIL"], env["ADMIN_PASSWORD"])
    if "--remove" in sys.argv:
        for style in STYLES:
            ui.call("DELETE", f"/api/v1/functions/id/{PIPE_ID}_{style}/delete")
            print(f"function {PIPE_ID}_{style}: deleted")
        return

    main_valves = ui.get_valves()
    shared = {name: main_valves[name] for name in SHARED_VALVES}
    for style in STYLES:
        function_id = f"{PIPE_ID}_{style}"
        form = {
            "id": function_id,
            "name": f"[{style}] {shared['BRAND_NAME']}",
            "content": VARIANT_FILE.read_text(),
            "meta": {"description": f"Trial of the step-by-step presentation, style '{style}'."},
        }
        try:
            function = ui.call("GET", f"/api/v1/functions/id/{function_id}")
        except RuntimeError:
            function = None
        if function is None:
            function = ui.call("POST", "/api/v1/functions/create", form)
            print(f"function {function_id}: created")
        else:
            function = ui.call("POST", f"/api/v1/functions/id/{function_id}/update", form)
            print(f"function {function_id}: updated")
        if not function.get("is_active"):
            ui.call("POST", f"/api/v1/functions/id/{function_id}/toggle")
        ui.set_valves({**shared, "STYLE": style}, function_id)
    print("done. Sign in as the staff account; the models are named '[<style>] ...'.")


if __name__ == "__main__":
    main()
