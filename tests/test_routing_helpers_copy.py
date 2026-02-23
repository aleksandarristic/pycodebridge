import builtins
import os

from codebridge.routing import helpers


class _GuardedReader:
    def __init__(self, fh) -> None:
        self._fh = fh

    def __enter__(self):
        self._fh.__enter__()
        return self

    def __exit__(self, exc_type, exc, tb):
        return self._fh.__exit__(exc_type, exc, tb)

    def read(self, size: int = -1):
        if size == -1:
            raise AssertionError("copy_file must not use unbounded read()")
        return self._fh.read(size)

    def __getattr__(self, name):
        return getattr(self._fh, name)


def test_copy_file_uses_chunked_reads(tmp_path, monkeypatch):
    src = tmp_path / "src.bin"
    dst = tmp_path / "nested" / "dst.bin"
    payload = os.urandom(2 * 1024 * 1024 + 137)
    src.write_bytes(payload)

    real_open = builtins.open

    def guarded_open(path, mode="r", *args, **kwargs):
        fh = real_open(path, mode, *args, **kwargs)
        if os.fspath(path) == str(src) and "rb" in mode:
            return _GuardedReader(fh)
        return fh

    monkeypatch.setattr(builtins, "open", guarded_open)
    helpers.copy_file(str(src), str(dst))
    assert dst.read_bytes() == payload
