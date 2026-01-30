from codebridge.audit_helpers import AuditHelper


class _FakeEntry:
    def __init__(self) -> None:
        self.codex = []
        self.out = []
        self.err = []
        self.closed = False

    def append_codex_line(self, line: str) -> None:
        self.codex.append(line)

    def append_discord_out(self, msg: str) -> None:
        self.out.append(msg)

    def append_stderr(self, msg: str) -> None:
        self.err.append(msg)

    def close(self) -> None:
        self.closed = True


class _FakeAudit:
    def __init__(self, entry: _FakeEntry) -> None:
        self.entry = entry
        self.calls = []

    def start(self, channel_id: str, session: str, thread_id: str, meta):
        self.calls.append((channel_id, session, thread_id, meta))
        return self.entry


class _FakeLogger:
    def __init__(self) -> None:
        self.errors = []

    def error(self, msg, extra=None):
        self.errors.append((msg, extra))


def test_audit_helper_start_and_append():
    entry = _FakeEntry()
    helper = AuditHelper(_FakeAudit(entry), _FakeLogger())
    opened = helper.start("chan", "sess", "thread", {"k": "v"})
    assert opened is entry
    helper.append_codex(entry, "line-1")
    helper.append_output(entry, "out-1")
    helper.append_stderr(entry, "err-1")
    helper.close(entry)
    assert entry.codex == ["line-1"]
    assert entry.out == ["out-1"]
    assert entry.err == ["err-1"]
    assert entry.closed is True


def test_audit_helper_start_handles_errors():
    class _BadAudit:
        def start(self, *_args, **_kwargs):
            raise RuntimeError("boom")

    logger = _FakeLogger()
    helper = AuditHelper(_BadAudit(), logger)
    assert helper.start("chan", "sess", "thread", {}) is None
    assert logger.errors
