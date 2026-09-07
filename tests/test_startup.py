import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("failed_stage", ["alembic", "python", None])
def test_startup_stops_on_failure_and_execs_server(tmp_path, failed_stage):
    calls = tmp_path / "calls"
    for command in ("alembic", "python", "uvicorn"):
        executable = tmp_path / command
        executable.write_text(
            '#!/bin/sh\n'
            f'echo "{command} $*" >> "$CALLS"\n'
            'echo "$$" > "$LAST_PID"\n'
            + ("exit 17\n" if command == failed_stage else "exit 0\n")
        )
        executable.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{tmp_path}:{os.environ['PATH']}",
        "CALLS": str(calls),
        "LAST_PID": str(tmp_path / "pid"),
    }
    process = subprocess.Popen(
        ["sh", str(ROOT / "scripts/start-api.sh")],
        env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    stdout, stderr = process.communicate(timeout=10)
    commands = calls.read_text().splitlines()
    expected = [
        "alembic upgrade head",
        "python -m scripts.seed",
        "uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log",
    ]
    if failed_stage:
        assert process.returncode == 17
        assert commands == expected[:1 if failed_stage == "alembic" else 2]
        assert f"during {'migrations' if failed_stage == 'alembic' else 'seed'}" in stderr
        assert "starting FastAPI" not in stdout
    else:
        assert process.returncode == 0, stderr
        assert commands == expected
        assert int((tmp_path / "pid").read_text()) == process.pid
