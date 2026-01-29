import re

PROMPT_RE = re.compile(r"(?i)^(approve|proceed|continue|confirm|apply|run|press enter|y/n|yes/no|select option|choose)(\b|:)")


def needs_user_input(line: str) -> bool:
    if PROMPT_RE.search(line or ""):
        return True
    line = (line or "").rstrip()
    return line.endswith("?")

