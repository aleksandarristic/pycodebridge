import json

from codebridge.sessions.state import Store, utc_now_iso


def test_state_save_load(tmp_path):
    store = Store(str(tmp_path))
    state = store.load()
    assert state.version >= 1

    def mutator(fs):
        from codebridge.sessions.state import ChannelState, SessionState

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
        fs.dm_bindings["discord:dm-1"] = "repo"
        fs.runtime_options_global["show_reasoning_details"] = False
        fs.runtime_options_channels["chan"] = {"run_heartbeat_seconds": 90}

    store.update(mutator)
    loaded = store.load()
    assert "chan" in loaded.channels
    assert "default" in loaded.channels["chan"].sessions
    assert loaded.dm_bindings["discord:dm-1"] == "repo"
    assert loaded.runtime_options_global["show_reasoning_details"] is False
    assert loaded.runtime_options_channels["chan"]["run_heartbeat_seconds"] == 90


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


def test_state_load_normalizes_repo_names(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "channels": {
                    "chan": {
                        "sessions": {
                            "default": {
                                "repo_name": "ProbablyFine",
                                "repo_path": "/tmp/ProbablyFine",
                                "thread_id": "thread",
                            }
                        }
                    }
                },
                "dm_bindings": {"discord:dm-1": "ProbablyFine"},
            }
        ),
        encoding="utf-8",
    )
    store = Store(str(tmp_path))
    state = store.load()
    assert state.channels["chan"].sessions["default"].repo_name == "probablyfine"
    assert state.dm_bindings["discord:dm-1"] == "probablyfine"


def test_state_load_normalizes_runtime_boolean_strings(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "runtime_options_global": {"show_reasoning_details": "false"},
                "runtime_options_channels": {
                    "chan": {
                        "show_reasoning_details": "0",
                        "run_heartbeat_seconds": 120,
                    },
                    "chan2": {
                        "show_reasoning_details": "definitely",
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    store = Store(str(tmp_path))
    state = store.load()
    assert state.runtime_options_global["show_reasoning_details"] is False
    assert state.runtime_options_channels["chan"]["show_reasoning_details"] is False
    assert state.runtime_options_channels["chan"]["run_heartbeat_seconds"] == 120
    assert "chan2" not in state.runtime_options_channels


def test_state_load_reuses_cached_snapshot_when_file_unchanged(tmp_path, monkeypatch):
    store = Store(str(tmp_path))
    (tmp_path / "state.json").write_text(json.dumps({"version": 1, "channels": {}}), encoding="utf-8")
    reads = 0
    original = store._read_file_unlocked

    def wrapped():
        nonlocal reads
        reads += 1
        return original()

    monkeypatch.setattr(store, "_read_file_unlocked", wrapped)
    store.load()
    store.load()
    assert reads == 1


def test_state_load_invalidates_cache_after_external_write(tmp_path):
    store = Store(str(tmp_path))
    first = store.load()
    assert first.channels == {}

    path = tmp_path / "state.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "channels": {
                    "chan": {
                        "sessions": {
                            "default": {
                                "repo_name": "repo",
                                "repo_path": "/tmp/repo",
                                "thread_id": "thread-2",
                            }
                        },
                        "sticky": {},
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    loaded = store.load()
    assert loaded.channels["chan"].sessions["default"].thread_id == "thread-2"


def test_worktree_path_round_trips(tmp_path):
    store = Store(str(tmp_path))

    def mutator(fs):
        from codebridge.sessions.state import ChannelState, SessionState
        ch = ChannelState()
        ch.sessions["default"] = SessionState(
            repo_name="myrepo", repo_path="/repos/myrepo", thread_id="",
            worktree_path="/repos/myrepo-wt-ch1"
        )
        fs.channels["ch1"] = ch

    store.update(mutator)
    loaded = store.load()
    assert loaded.channels["ch1"].sessions["default"].worktree_path == "/repos/myrepo-wt-ch1"


def test_worktree_path_defaults_empty_for_old_state(tmp_path):
    import json
    path = tmp_path / "state.json"
    path.write_text(json.dumps({
        "version": 1,
        "channels": {"ch1": {"sessions": {"default": {
            "repo_name": "myrepo", "repo_path": "/repos/myrepo", "thread_id": "",
        }}, "sticky": {}}},
    }), encoding="utf-8")
    store = Store(str(tmp_path))
    loaded = store.load()
    assert loaded.channels["ch1"].sessions["default"].worktree_path == ""
    assert loaded.channels["ch1"].sessions["default"].fresh_start_required is False


def test_fresh_start_required_round_trips(tmp_path):
    store = Store(str(tmp_path))

    def mutator(fs):
        from codebridge.sessions.state import ChannelState, SessionState
        ch = ChannelState()
        ch.sessions["default"] = SessionState(
            repo_name="myrepo",
            repo_path="/repos/myrepo",
            thread_id="",
            fresh_start_required=True,
        )
        fs.channels["ch1"] = ch

    store.update(mutator)
    loaded = store.load()
    assert loaded.channels["ch1"].sessions["default"].fresh_start_required is True

    import json
    raw = json.loads((tmp_path / "state.json").read_text())
    assert raw["channels"]["ch1"]["sessions"]["default"]["fresh_start_required"] is True


def test_worktree_path_cleared_serializes_as_empty_string(tmp_path):
    store = Store(str(tmp_path))

    def mutator(fs):
        from codebridge.sessions.state import ChannelState, SessionState
        ch = ChannelState()
        ch.sessions["default"] = SessionState(
            repo_name="myrepo", repo_path="/repos/myrepo", thread_id="",
            worktree_path="",
        )
        fs.channels["ch1"] = ch

    store.update(mutator)
    import json
    raw = json.loads((tmp_path / "state.json").read_text())
    assert raw["channels"]["ch1"]["sessions"]["default"]["worktree_path"] == ""
