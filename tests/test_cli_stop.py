"""Stopping a room with SIGTERM (what the viewer's Stop button sends) must save every fly."""
import json
import signal
import subprocess
import sys
import time

import pytest


@pytest.mark.parametrize("flies,workers", [(1, 1), (4, 2)])
def test_sigterm_saves_every_fly_up_to_the_moment_it_stopped(tmp_path, flies, workers):
    text = tmp_path / "t.txt"
    text.write_text("To be, or not to be, that is the question: whether tis nobler in the mind " * 50)
    room = tmp_path / "room"
    p = subprocess.Popen([sys.executable, "-m", "flyspeare.cli", "room", str(room), "--flies", str(flies),
                          "--workers", str(workers), "--speed", "max", "--text", str(text)],
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    deadline = time.time() + 30
    while not (room / "room.json").exists() and time.time() < deadline:
        time.sleep(0.2)
    time.sleep(3)
    p.send_signal(signal.SIGTERM)
    assert p.wait(timeout=60) == 0, p.stderr.read().decode()
    status = json.loads((room / "room.json").read_text())
    for f in status["flies"]:
        state = json.loads((room / f"fly-{f['id']:04d}" / "state.json").read_text())
        # the save happens at the stop, so it is at least as far along as the last status
        assert state["totals"]["presses"] >= f["presses"] > 0
