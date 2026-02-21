from codebridge.handlers.system_helpers import _extract_line_version, _extract_version


def test_extract_version_finds_semver_in_codex_output():
    text = "WARNING: temp dir issue\ncodex-cli 0.101.0\n"
    assert _extract_version(text) == "0.101.0"


def test_extract_line_version_only_accepts_plain_semver_lines():
    text = "npm ERR! code EACCES\n9.2.0\n"
    assert _extract_line_version(text) == "9.2.0"
    assert _extract_line_version("npm ERR! something 9.2.0") == ""
