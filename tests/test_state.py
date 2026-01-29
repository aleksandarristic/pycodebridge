import json

from codebridge.state import Store, utc_now_iso


def test_state_save_load(tmp_path):
    store = Store(str(tmp_path))
    state = store.load()
    assert state.version >= 1

    def mutator(fs):
        from codebridge.state import ChannelState, SessionState

        ch = fs.channels.setdefault("chan", ChannelState())
        ch.sessions["default"] = SessionState(
            repo_name="repo",
            repo_path="/tmp/repo",
            thread_id="thread",
            created_at=utc_now_iso(),
            last_used_at=utc_now_iso(),
        )
        ch.sticky["user"] = "default"
        fs.channels["chan"] = ch

    store.update(mutator)
    loaded = store.load()
    assert "chan" in loaded.channels
    assert "default" in loaded.channels["chan"].sessions


def test_state_migrate_legacy(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "channels": {
                    "chan": {
                        "repo_name": "repo",
                        "repo_path": "/tmp/repo",
                        "thread_id": "thread",
                        "created_at": "now",
                        "last_used_at": "later",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    store = Store(str(tmp_path))
    state = store.load()
    assert "default" in state.channels["chan"].sessions
