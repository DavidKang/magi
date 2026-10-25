import os
import subprocess
import sys
import threading

from builders import ROOT
from tarkon.adapters import process


def test_parallel_runs_one_wave():
    barrier = threading.Barrier(12, timeout=5)
    assert process.parallel(lambda i: barrier.wait() >= 0, range(12)) == [True] * 12, "twelve calls run at once, in one wave"


def test_missing_tools(tmp_path):
    for args in ([], ["html"]):
        try:
            result = subprocess.run([sys.executable, "-m", "tarkon", *args], capture_output=True, text=True,
                                    cwd=ROOT, env={**os.environ, "HOME": str(tmp_path), "PATH": "/usr/bin:/bin"},
                                    timeout=15)
        except subprocess.TimeoutExpired:
            result = subprocess.CompletedProcess(args, None, "", "timed out")
        assert result.returncode == 1, f"missing gh and acli are explained before {' '.join(args) or 'the TUI'} starts"
        assert "gh not found" in result.stderr, f"missing gh and acli are explained before {' '.join(args) or 'the TUI'} starts"
        assert "brew install gh" in result.stderr, f"missing gh and acli are explained before {' '.join(args) or 'the TUI'} starts"
        assert "acli not found" in result.stderr, f"missing gh and acli are explained before {' '.join(args) or 'the TUI'} starts"
        assert "brew install acli" in result.stderr, f"missing gh and acli are explained before {' '.join(args) or 'the TUI'} starts"
        assert "Traceback" not in result.stderr, f"missing gh and acli are explained before {' '.join(args) or 'the TUI'} starts"
