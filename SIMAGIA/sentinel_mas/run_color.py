"""Colorized runner for SentinelMAS.

Use instead of 'python main.py' to get color-coded output per agent type.
All output is otherwise identical — this is a pure display wrapper.

    python run_color.py
"""

import os
import re
import subprocess
import sys

import colorama
from colorama import Fore, Style

colorama.init()

# Map regex patterns to ANSI color sequences --------------------------------
RULES: list[tuple[str, str]] = [
    (r"\[ZC:",          Fore.CYAN),
    (r"\[Patrol\]",     Fore.YELLOW),
    (r"NavStub",        Fore.YELLOW + Style.DIM),
    (r"\[Motion\]",     Fore.GREEN),
    (r"\[FaceID\]",     Fore.BLUE),
    (r"\[CyberSentinel\]", Fore.MAGENTA),
    (r"\[Alert\]",      Fore.RED),
    (r"\*\*\* ALERT",   Fore.RED + Style.BRIGHT),
    (r"\[StaffRequest\]", Fore.WHITE + Style.DIM),
    (r"SentinelMAS running", Fore.GREEN + Style.BRIGHT),
    (r"XMPP server up", Fore.GREEN),
    (r"desires:",       Fore.CYAN + Style.DIM),
    (r"intention adopted:", Fore.CYAN + Style.BRIGHT),
    (r"belief revision", Fore.CYAN + Style.DIM),
    (r"AGREE",          Fore.GREEN),
    (r"REFUSE",         Fore.RED + Style.DIM),
    (r"FAILURE",        Fore.RED),
]

COMPILED = [(re.compile(p), c) for p, c in RULES]


def colorize(line: str) -> str:
    for pattern, color in COMPILED:
        if pattern.search(line):
            return color + line.rstrip("\n") + Style.RESET_ALL + "\n"
    return line


# Force the child's stdout to be unbuffered (-u) and UTF-8, otherwise its
# startup output sits in a pipe buffer and nothing appears until it fills.
child_env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")

p = subprocess.Popen(
    [sys.executable, "-u", "main.py"],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    text=True,
    encoding="utf-8",
    errors="replace",
    bufsize=1,
    env=child_env,
)

try:
    for raw_line in iter(p.stdout.readline, ""):
        print(colorize(raw_line), end="", flush=True)
    p.wait()
except KeyboardInterrupt:
    p.terminate()
    p.wait()
