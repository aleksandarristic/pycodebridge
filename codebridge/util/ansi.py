import re

CSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
OSC_RE = re.compile(r"\x1b\][0-9]{0,2};.*?\x07")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def strip_control_codes(text: str) -> str:
    if not text:
        return text
    text = text.replace("\r", "\n")
    text = CSI_RE.sub("", text)
    text = OSC_RE.sub("", text)
    text = CONTROL_RE.sub("", text)
    return text

