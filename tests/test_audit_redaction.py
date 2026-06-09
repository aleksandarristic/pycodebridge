from codebridge.observability.audit import Redactor


def test_redactor_default_patterns():
    redactor = Redactor()
    text = "token=abc123 sk-abcdefghijklmnopqrstuv xoxb-1234567890-abcdef"
    redacted = redactor.apply_text(text)
    assert "<redacted>" in redacted
    assert "token=abc123" not in redacted
    assert "sk-abcdefghijklmnopqrstuv" not in redacted
    assert "xoxb-1234567890-abcdef" not in redacted


def test_redactor_custom_patterns():
    redactor = Redactor(patterns=[r"SECRET_[A-Z]+"])
    text = "keep SECRET_VALUE and drop SECRET_TOKEN"
    redacted = redactor.apply_text(text)
    assert "SECRET_TOKEN" not in redacted
    assert "SECRET_VALUE" not in redacted


def test_redactor_custom_patterns_keep_default_patterns():
    redactor = Redactor(patterns=[r"SECRET_[A-Z]+"])
    text = "drop SECRET_TOKEN and --totp 123456"
    redacted = redactor.apply_text(text)
    assert "SECRET_TOKEN" not in redacted
    assert "123456" not in redacted


def test_redactor_default_patterns_cover_common_secret_assignments():
    redactor = Redactor()
    text = "secret: hello password = p@ss token = abc"
    redacted = redactor.apply_text(text)
    assert "secret: hello" not in redacted
    assert "password = p@ss" not in redacted
    assert "token = abc" not in redacted


def test_redactor_default_patterns_cover_totp_arguments():
    redactor = Redactor()
    text = "!c start --totp 123456 and totp=654321"
    redacted = redactor.apply_text(text)
    assert "123456" not in redacted
    assert "654321" not in redacted
    assert "<redacted>" in redacted


def test_redactor_redacts_sensitive_arg_list_values():
    redactor = Redactor()
    redacted = redactor.apply_obj({"args": ["exec", "--totp", "123456", "--token", "abc123"]})
    assert redacted["args"] == ["exec", "--totp", "<redacted>", "--token", "<redacted>"]


def test_redactor_does_not_redact_arg_after_inline_sensitive_value():
    redactor = Redactor()
    redacted = redactor.apply_obj({"args": ["exec", "--token=abc123", "keep"]})
    assert redacted["args"] == ["exec", "--<redacted>", "keep"]
