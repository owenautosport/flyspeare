import json
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from flyspeare.room import Room, RoomConfig, set_control
from flyspeare.view import Handler


@pytest.fixture
def server(tmp_path):
    text = tmp_path / "verse.txt"
    text.write_text("To be, or not to be: that is the question.")
    runs = tmp_path / "runs"
    set_control(runs / "r1", watch=[0])
    Room(text, runs / "r1", RoomConfig(flies=2, workers=1, speed="max", status_secs=0.05, live_secs=0.01)).run()
    Handler.runs = runs
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def get(url):
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())


def post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_lists_rooms_with_progress(server):
    rooms = get(server + "/api/rooms")
    assert rooms[0]["name"] == "r1" and rooms[0]["flies"] == 2
    assert rooms[0]["best_word"] == rooms[0]["n_words"] == 10 and not rooms[0]["running"]


def test_paper_shows_the_original_text_typed_so_far(server):
    paper = get(server + "/api/rooms/r1/fly/0/paper")
    assert paper["text"].endswith("that is the question") and paper["word"] == 10


def test_live_feed_and_control(server):
    live = get(server + "/api/rooms/r1/fly/0/live")
    assert live["items"][-1]["correct"]
    ctl = post(server + "/api/rooms/r1/control", {"speed": "real", "watch": [1], "save": True})
    assert ctl["speed"] == "real" and ctl["watch"] == [1] and ctl["save"] == 1


def test_rejects_bad_room_names(server):
    with pytest.raises(urllib.error.HTTPError) as e:
        get(server + "/api/rooms/..%2F..%2Fetc/status")
    assert e.value.code == 400


def delete(url):
    req = urllib.request.Request(url, method="DELETE")
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())


def test_delete_a_stopped_room_removes_its_saves(server, tmp_path):
    assert (tmp_path / "runs" / "r1").exists()
    assert delete(server + "/api/rooms/r1") == {"deleted": "r1"}
    assert not (tmp_path / "runs" / "r1").exists()
    assert get(server + "/api/rooms") == []


def test_cannot_delete_a_running_room(server, tmp_path):
    import os
    (tmp_path / "runs" / "r1" / "room.pid").write_text(str(os.getpid()))  # "running": this process
    with pytest.raises(urllib.error.HTTPError) as e:
        delete(server + "/api/rooms/r1")
    assert e.value.code == 409 and (tmp_path / "runs" / "r1").exists()


def test_paper_pages_back_to_the_beginning(server):
    tail = get(server + "/api/rooms/r1/fly/0/paper?size=12")
    assert tail["text"] == "the question" and tail["start"] == tail["end"] - 12
    older = get(server + f"/api/rooms/r1/fly/0/paper?before={tail['start']}&size=1000")
    assert older["start"] == 0 and older["text"] + tail["text"] == "To be, or not to be: that is the question"


def test_feelings_endpoint_reads_the_watched_fly(server):
    f = get(server + "/api/rooms/r1/fly/0/feelings")
    assert {"summary", "gauges", "disclaimer"} <= set(f) and "mood" in f["gauges"]


def test_control_of_a_missing_room_is_refused_and_creates_nothing(server, tmp_path):
    with pytest.raises(urllib.error.HTTPError) as e:
        post(server + "/api/rooms/nope/control", {"watch": [0]})
    assert e.value.code == 404 and not (tmp_path / "runs" / "nope").exists()
