import asyncio
import sys

from codebridge.routing.helpers import HELPER_OUTPUT_LIMIT, run_limited_command


def test_run_limited_command_drains_large_stdout_without_timeout(tmp_path):
    async def run():
        out, err = await run_limited_command(
            str(tmp_path),
            [
                sys.executable,
                "-c",
                f"import sys; sys.stdout.buffer.write(b'x' * {HELPER_OUTPUT_LIMIT * 3}); sys.stdout.flush()",
            ],
            timeout=5.0,
        )
        assert err is None
        assert out.endswith("\n...(truncated)")
        assert len(out.encode("utf-8")) <= HELPER_OUTPUT_LIMIT + len("\n...(truncated)")

    asyncio.run(run())


def test_run_limited_command_drains_large_stderr_without_timeout(tmp_path):
    async def run():
        out, err = await run_limited_command(
            str(tmp_path),
            [
                sys.executable,
                "-c",
                f"import sys; sys.stderr.buffer.write(b'e' * {HELPER_OUTPUT_LIMIT * 3}); sys.stderr.flush()",
            ],
            timeout=5.0,
        )
        assert err is None
        assert out.endswith("\n...(truncated)")
        assert len(out.encode("utf-8")) <= HELPER_OUTPUT_LIMIT + len("\n...(truncated)")

    asyncio.run(run())


def test_run_limited_command_returns_nonzero_error_with_output(tmp_path):
    async def run():
        out, err = await run_limited_command(
            str(tmp_path),
            [sys.executable, "-c", "import sys; print('bad'); sys.exit(3)"],
            timeout=5.0,
        )
        assert out.strip() == "bad"
        assert isinstance(err, RuntimeError)
        assert str(err) == "exit 3"

    asyncio.run(run())


def test_run_limited_command_times_out_and_returns_partial_output(tmp_path):
    async def run():
        out, err = await run_limited_command(
            str(tmp_path),
            [sys.executable, "-c", "import time; print('start', flush=True); time.sleep(5)"],
            timeout=0.1,
        )
        assert "start" in out
        assert isinstance(err, asyncio.TimeoutError)

    asyncio.run(run())
