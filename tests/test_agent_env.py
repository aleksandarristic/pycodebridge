from codebridge.agents.base import _merge_env


def test_merge_env_forwards_python_cache_vars(monkeypatch):
    monkeypatch.setenv("XDG_CACHE_HOME", "/workspace/state/cache")
    monkeypatch.setenv("PIP_CACHE_DIR", "/workspace/state/cache/pip")
    monkeypatch.setenv("UV_CACHE_DIR", "/workspace/state/cache/uv")

    env = _merge_env({}, {})

    assert env["XDG_CACHE_HOME"] == "/workspace/state/cache"
    assert env["PIP_CACHE_DIR"] == "/workspace/state/cache/pip"
    assert env["UV_CACHE_DIR"] == "/workspace/state/cache/uv"
