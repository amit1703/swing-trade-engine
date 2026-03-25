import os
import wexpect as pexpect
from openai import OpenAI

_api_key = os.environ.get("OPENAI_API_KEY")
if not _api_key:
    raise EnvironmentError("OPENAI_API_KEY environment variable is not set.")
client = OpenAI(api_key=_api_key)

PROJECT_CONTEXT = """
You are supervising Claude Code while it develops a stock trading scanner.

Project goals:
- Scan US stocks
- Rank them based on technical strength
- Focus on momentum stocks

Ranking factors:
1. Relative Strength vs SPY
2. Momentum (price trend)
3. Volume expansion
4. Technical structure (breakouts, consolidations)

Rules:
- Prefer extending existing modules instead of rewriting everything
- Keep code modular
- Avoid unnecessary complexity
- Focus on reliable trading signals
- If Claude presents numbered options, choose the best one and explain briefly.

Relative Strength should use SPY as the main benchmark.

Do not invent new features unless Claude explicitly asks.
Focus only on answering the question asked.
"""

# מילים שמרמזות ש-Claude מחכה להחלטה
QUESTION_HINTS = [
    "should",
    "would you like",
    "choose",
    "select",
    "pick",
    "which option",
    "do you want",
    "confirm"
]
ERROR_HINTS = [
    "traceback",
    "error",
    "exception",
    "failed",
    "module not found",
]

claude = pexpect.spawn("claude", encoding="utf-8")

def looks_like_error(text):
    lower = text.lower()

    for word in ERROR_HINTS:
        if word in lower:
            return True

    return False

def looks_like_question(text):
    lower = text.lower()

    if "?" in lower:
        return True

    for word in QUESTION_HINTS:
        if word in lower:
            return True

    # זיהוי אופציות 1) 2) 3)
    if "1)" in lower and "2)" in lower:
        return True

    return False


while True:
    try:
        output = claude.read_nonblocking(1024)
        if not output:
            continue
        if "? for shortcuts" in output:
            continue
        print("Claude:", output)

        if looks_like_question(output):

            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": PROJECT_CONTEXT},
                    {"role": "user", "content": output}
                ]
            )

            answer = response.choices[0].message.content

            print("GPT:", answer)

            claude.sendline(answer)

    except KeyboardInterrupt:
        print("Stopped.")
        break
    