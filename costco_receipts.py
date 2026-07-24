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

_cfg = configparser.ConfigParser()
_cfg.read(Path.home() / ".config" / "credentials.ini")
client = anthropic.Anthropic(api_key=_cfg["anthropic"]["token"])


def screenshot() -> str:
    subprocess.run(["screencapture", "-x", "-t", "png", "/tmp/screen.png"], capture_output=True)  # nosec B603 B607 B108 - local macOS tool, fixed args, temp file acceptable
    with open("/tmp/screen.png", "rb") as f:  # nosec B108 - temp file for screenshot, local use only
        return base64.standard_b64encode(f.read()).decode()


def run_tool(tool_name: str, tool_input: dict) -> str:  # NOSONAR - standalone script; complexity acceptable for this local automation tool
    if tool_name == "computer":
        action = tool_input["action"]

        if action == "screenshot":
            return screenshot()

        elif action == "left_click":
            x, y = tool_input["coordinate"]
            subprocess.run(["cliclick", f"c:{x},{y}"])  # nosec B603 B607 - local macOS automation tool, controlled args

        elif action == "double_click":
            x, y = tool_input["coordinate"]
            subprocess.run(["cliclick", f"dc:{x},{y}"])  # nosec B603 B607 - local macOS automation tool, controlled args

        elif action == "right_click":
            x, y = tool_input["coordinate"]
            subprocess.run(["cliclick", f"rc:{x},{y}"])  # nosec B603 B607 - local macOS automation tool, controlled args

        elif action == "mouse_move":
            x, y = tool_input["coordinate"]
            subprocess.run(["cliclick", f"m:{x},{y}"])  # nosec B603 B607 - local macOS automation tool, controlled args

        elif action == "type":
            subprocess.run(["cliclick", f"t:{tool_input['text']}"])  # nosec B603 B607 - local macOS automation tool, controlled args

        elif action == "key":
            key = tool_input["text"]
            subprocess.run(["cliclick", f"kp:{key}"])  # nosec B603 B607 - local macOS automation tool, controlled args

        elif action == "scroll":
            x, y = tool_input["coordinate"]
            direction = tool_input.get("direction", "down")
            amount = tool_input.get("amount", 3)
            flag = "u" if direction == "up" else "d"
            for _ in range(amount):
                subprocess.run(["cliclick", f"s{flag}:{x},{y}"])  # nosec B603 B607 - local macOS automation tool, controlled args

        # Always screenshot after actions so Claude can see the result
        time.sleep(0.5)
        return screenshot()

    elif tool_name == "bash":
        result = subprocess.run(tool_input["command"], shell=True, capture_output=True, text=True)  # nosec B602 B603 - shell=True intentional for bash tool passthrough in local automation script
        return result.stdout + result.stderr

    return ""


def main():  # NOSONAR - standalone script; complexity acceptable for this local automation tool
    print(f"Saving receipts to: {DOWNLOAD_DIR}\n")

    # Include initial screenshot so Claude can see the current screen state
    initial_screenshot = screenshot()

    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {"type": "base64", "media_type": "image/png", "data": initial_screenshot},
                },
                {
                    "type": "text",
                    "text": (
                        f"This is my current screen. Costco.ca is open and logged in in Microsoft Edge. "
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
                    ),
                },
            ],
        }
    ]

    tools = [
        {
            "type": "computer_20251124",
            "name": "computer",
            "display_width_px": 1920,
            "display_height_px": 1080,
            "display_number": 1,
        },
        {"type": "bash_20250124", "name": "bash"},
    ]

    turn = 0
    while True:
        turn += 1
        print(f"--- Turn {turn} ---")

        response = client.beta.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            tools=tools,
            messages=messages,
            betas=["computer-use-2025-11-24"],
        )

        tool_uses = []
        for block in response.content:
            if hasattr(block, "text"):
                print(f"Claude: {block.text}")
            elif block.type == "tool_use":
                print(f"Tool: {block.name} → {block.input.get('action', block.input)}")
                tool_uses.append(block)

        if not tool_uses or response.stop_reason == "end_turn":
            print("\nDone.")
            break

        messages.append({"role": "assistant", "content": response.content})

        tool_results = []
        for tool_use in tool_uses:
            result = run_tool(tool_use.name, tool_use.input)
            is_image = tool_use.name == "computer" and result
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_use.id,
                "content": (
                    [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": result}}]
                    if is_image
                    else result or "done"
                ),
            })

        messages.append({"role": "user", "content": tool_results})


if __name__ == "__main__":
    main()
