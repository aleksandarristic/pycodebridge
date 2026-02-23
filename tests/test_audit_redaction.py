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


def test_redactor_default_patterns_cover_common_secret_assignments():
    redactor = Redactor()
    text = "secret: hello password = p@ss token = abc"
    redacted = redactor.apply_text(text)
    assert "secret: hello" not in redacted
    assert "password = p@ss" not in redacted
    assert "token = abc" not in redacted
