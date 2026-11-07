"""Tests for `local-ai doctor`: run it as a real subprocess (not just an
in-process function call) so we actually exercise argument parsing, process
exit codes, and the CLI entry point, the same way an end user invokes it.
"""

from __future__ import annotations

import socket
import subprocess
import sys


def test_doctor_passes_in_healthy_tmp_data_dir(tmp_path):
    # Pick a free, unlikely-to-collide port to probe so the "port free"
    # check reliably passes regardless of what's running on the host.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        free_port = probe.getsockname()[1]

    result = subprocess.run(
        [sys.executable, "-m", "local_ai_workspace.cli.main", "doctor", "--port", str(free_port)],
        env={"LOCAL_AI_WORKSPACE_HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "Python version" in result.stdout
    assert "Data directory" in result.stdout
    assert "Secrets master key" in result.stdout
    assert "Result: PASS" in result.stdout


def test_doctor_warns_on_port_in_use(tmp_path):
    # Occupy a port, then point doctor at it: expect a WARN (not FAIL, since
    # the port check is best-effort/informational), and still exit 0.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as occupied:
        occupied.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        occupied.bind(("127.0.0.1", 0))
        occupied.listen(1)
        busy_port = occupied.getsockname()[1]

        result = subprocess.run(
            [sys.executable, "-m", "local_ai_workspace.cli.main", "doctor", "--port", str(busy_port)],
            env={"LOCAL_AI_WORKSPACE_HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
            capture_output=True,
            text=True,
            timeout=30,
        )

    assert result.returncode == 0, f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    assert "WARN" in result.stdout
    assert f"{busy_port} availability" in result.stdout
