"""
Download Costco warehouse receipts >$200 using Claude computer use.
Flow: navigate to orders page -> View Receipts -> Print button -> Save as PDF
"""

import anthropic
import base64
import configparser
import subprocess
import time
from pathlib import Path

DOWNLOAD_DIR = Path.home() / "Desktop" / "costco_receipts"
DOWNLOAD_DIR.mkdir(exist_ok=True)

COSTCO_ORDERS_URL = "https://www.costco.ca/myaccount/#/app/e442e6e6-2602-4a39-937b-8b28b4457ed3/ordersandpurchases"

TASK_PROMPT = (
    "This is my current screen. Costco.ca is open and logged in in Microsoft Edge. "
    f"Navigate to: {COSTCO_ORDERS_URL}\n\n"
    "Then:\n"
    "1. Change the date range to show all of 2025\n"
    "2. Switch to the 'Warehouse' tab\n"
    "3. For each order over $200, click the 'View Receipts' button\n"
    "4. On the receipt page, click the 'Print' button\n"
    f"5. In the print dialog, save as PDF to {DOWNLOAD_DIR}, "
    "named costco_YYYY-MM-DD_$AMOUNT.pdf\n"
    "6. Go back and continue through ALL pages using pagination\n\n"
    "Take a screenshot after every click to confirm it worked before proceeding."
)

TOOLS = [
    {
        "type": "computer_20251124",
        "name": "computer",
        "display_width_px": 1920,
        "display_height_px": 1080,
        "display_number": 1,
    },
    {"type": "bash_20250124", "name": "bash"},
]

_cfg = configparser.ConfigParser()
_cfg.read(Path.home() / ".config" / "credentials.ini")
client = anthropic.Anthropic(api_key=_cfg["anthropic"]["token"])


def screenshot() -> str:
    subprocess.run(["screencapture", "-x", "-t", "png", "/tmp/screen.png"], capture_output=True)  # nosec B603 B607 B108 - local macOS tool, fixed args, temp file acceptable
    with open("/tmp/screen.png", "rb") as f:  # nosec B108 - temp file for screenshot, local use only
        return base64.standard_b64encode(f.read()).decode()


def _cliclick(*args: str) -> None:
    subprocess.run(["cliclick", *args])  # nosec B603 B607 - local macOS automation tool, controlled args


# Actions that take a "coordinate" input, mapped to their cliclick command prefix.
_COORDINATE_ACTIONS = {
    "left_click": "c",
    "double_click": "dc",
    "right_click": "rc",
    "mouse_move": "m",
}


def _run_computer_action(tool_input: dict) -> None:
    """Dispatch one computer-use action to cliclick."""
    action = tool_input["action"]

    prefix = _COORDINATE_ACTIONS.get(action)
    if prefix:
        x, y = tool_input["coordinate"]
        _cliclick(f"{prefix}:{x},{y}")
    elif action == "type":
        _cliclick(f"t:{tool_input['text']}")
    elif action == "key":
        _cliclick(f"kp:{tool_input['text']}")
    elif action == "scroll":
        x, y = tool_input["coordinate"]
        flag = "u" if tool_input.get("direction", "down") == "up" else "d"
        for _ in range(tool_input.get("amount", 3)):
            _cliclick(f"s{flag}:{x},{y}")


def _run_bash(command: str) -> str:
    result = subprocess.run(command, shell=True, capture_output=True, text=True)  # nosec B602 B603 - shell=True intentional for bash tool passthrough in local automation script
    return result.stdout + result.stderr


def run_tool(tool_name: str, tool_input: dict) -> str:
    if tool_name == "bash":
        return _run_bash(tool_input["command"])
    if tool_name != "computer":
        return ""
    if tool_input["action"] == "screenshot":
        return screenshot()

    _run_computer_action(tool_input)
    # Always screenshot after actions so Claude can see the result
    time.sleep(0.5)
    return screenshot()


def _initial_messages() -> list[dict]:
    """Build the opening user turn: current screen plus the receipt-download task."""
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": screenshot()},
                },
                {"type": "text", "text": TASK_PROMPT},
            ],
        }
    ]


def _print_blocks(content) -> list:
    """Echo Claude's text/tool blocks to stdout and return the tool_use blocks."""
    tool_uses = []
    for block in content:
        if hasattr(block, "text"):
            print(f"Claude: {block.text}")
        elif block.type == "tool_use":
            print(f"Tool: {block.name} → {block.input.get('action', block.input)}")
            tool_uses.append(block)
    return tool_uses


def _tool_result(tool_use) -> dict:
    """Run one tool call and wrap its output as a tool_result block."""
    result = run_tool(tool_use.name, tool_use.input)
    is_image = tool_use.name == "computer" and result
    content = (
        [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": result}}]
        if is_image
        else result or "done"
    )
    return {"type": "tool_result", "tool_use_id": tool_use.id, "content": content}


def main():
    print(f"Saving receipts to: {DOWNLOAD_DIR}\n")

    messages = _initial_messages()

    turn = 0
    while True:
        turn += 1
        print(f"--- Turn {turn} ---")

        response = client.beta.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            tools=TOOLS,
            messages=messages,
            betas=["computer-use-2025-11-24"],
        )

        tool_uses = _print_blocks(response.content)
        if not tool_uses or response.stop_reason == "end_turn":
            print("\nDone.")
            break

        messages.append({"role": "assistant", "content": response.content})
        messages.append({"role": "user", "content": [_tool_result(tu) for tu in tool_uses]})


if __name__ == "__main__":
    main()
