import json
import threading
import time

from flyspeare.room import Room, RoomConfig, read_status, set_control

VERSE = ("to be or not to be " * 3).strip()


def room(tmp_path, **kw):
    text = tmp_path / "verse.txt"
    text.write_text(VERSE)
    cfg = RoomConfig(**{"flies": 3, "workers": 1, "speed": "max", "status_secs": 0.1, **kw})
    return Room(text, tmp_path / "room", cfg)


def test_every_fly_types_everything_with_its_own_brain(tmp_path):
    r = room(tmp_path)
    r.run()
    st = read_status(tmp_path / "room")
    assert len(st["flies"]) == 3
    assert all(f["done"] and f["word"] == 18 for f in st["flies"])
    assert len({f["presses"] for f in st["flies"]}) > 1  # different wiring, different luck
    assert st["winner"] is not None


def test_real_speed_paces_each_fly(tmp_path):
    r = room(tmp_path, speed="real", press_seconds=0.05)
    t = threading.Thread(target=r.run)
    t.start()
    time.sleep(1.0)
    r.stop()
    t.join()
    for f in read_status(tmp_path / "room")["flies"]:
        # 1 s at 0.05 s/press is ~20 presses, plus at most one attempt of overrun
        assert 5 <= f["presses"] <= 20 + 3


def test_control_pause_and_speed_switch_live(tmp_path):
    r = room(tmp_path, speed="real", press_seconds=0.05)
    set_control(tmp_path / "room", paused=True)
    t = threading.Thread(target=r.run)
    t.start()
    time.sleep(0.6)
    paused = sum(f["presses"] for f in read_status(tmp_path / "room")["flies"])
    set_control(tmp_path / "room", paused=False, speed="max")
    t.join(timeout=30)
    st = read_status(tmp_path / "room")
    assert paused == 0
    assert all(f["done"] for f in st["flies"]) and st["speed"] == "max"


def test_resume_carries_on(tmp_path):
    r = room(tmp_path, speed="real", press_seconds=0.02)
    t = threading.Thread(target=r.run)
    t.start()
    time.sleep(0.5)
    r.stop()
    t.join()
    before = {f["id"]: f["presses"] for f in read_status(tmp_path / "room")["flies"]}
    r2 = room(tmp_path, speed="max", resume=True)
    r2.run()
    after = {f["id"]: f for f in read_status(tmp_path / "room")["flies"]}
    assert all(after[i]["presses"] >= before[i] and after[i]["done"] for i in before)


def test_watched_fly_streams_a_live_feed(tmp_path):
    set_control(tmp_path / "room", watch=[1])
    r = room(tmp_path, speed="real", press_seconds=0.02, live_secs=0.05)
    t = threading.Thread(target=r.run)
    t.start()
    time.sleep(0.8)
    r.stop()
    t.join()
    live = json.loads((tmp_path / "room" / "fly-0001" / "live.json").read_text())
    assert live["items"] and {"typed", "kcs", "pns", "dopamine", "seq"} <= set(live["items"][-1])
    assert not (tmp_path / "room" / "fly-0000" / "live.json").exists()


def test_save_now_checkpoints_every_fly(tmp_path):
    r = room(tmp_path, speed="real", press_seconds=0.02)
    t = threading.Thread(target=r.run)
    t.start()
    time.sleep(0.4)
    set_control(tmp_path / "room", save=True)
    time.sleep(0.6)
    saved = [(tmp_path / "room" / f"fly-{i:04d}" / "state.json").exists() for i in range(3)]
    r.stop()
    t.join()
    assert all(saved)


def test_room_remembers_its_settings_for_loading(tmp_path):
    from dataclasses import replace
    from flyspeare.brain import SHORT_TERM, LONG_TERM, BrainConfig
    from flyspeare.room import load_room_config
    from flyspeare.rules import Rewards
    brain = BrainConfig(ctx_len=4, tau=0.2, length_cue=False,
                        compartments=(replace(SHORT_TERM, eta=0.09), LONG_TERM))
    r = room(tmp_path, brain=brain, rewards=Rewards(slip=0.1))
    r.run()
    cfg = load_room_config(tmp_path / "room")
    assert cfg.brain == brain and cfg.rewards == Rewards(slip=0.1) and cfg.flies == 3


def test_running_time_counts_only_unpaused_time_and_survives_resume(tmp_path):
    r = room(tmp_path, speed="real", press_seconds=0.05)
    t = threading.Thread(target=r.run); t.start()
    time.sleep(1.2)
    set_control(tmp_path / "room", paused=True)
    time.sleep(1.2)
    r.stop(); t.join()
    first = read_status(tmp_path / "room")["run_seconds"]
    assert 0.8 < first < 1.9          # the paused second does not count
    r2 = room(tmp_path, speed="real", press_seconds=0.05, resume=True)
    set_control(tmp_path / "room", paused=False)
    t = threading.Thread(target=r2.run); t.start()
    time.sleep(1.0)
    r2.stop(); t.join()
    assert read_status(tmp_path / "room")["run_seconds"] > first + 0.6
