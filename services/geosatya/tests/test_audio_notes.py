"""Optional voice notes on an SOS and on a task completion: private storage, real audio only,
owner / assigned worker / workspace supervisor access, never required, never changes GeoSatya."""

import pytest
from fastapi.testclient import TestClient

from geosatya.main import create_app
from tests.conftest import CITIZEN, CITIZEN2, SPOT, SUPERVISOR, WORKER15, complete, fix, make_settings, reported_task, start

W = "/api/v1/women"
WEBM = b"\x1aE\xdf\xa3" + b"\x00" * 600          # an EBML (WebM) header and some body
MP4 = b"\x00\x00\x00\x18ftypM4A " + b"\x00" * 600   # an MP4 / M4A container


@pytest.fixture
def c(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as client:
        yield client


def ally_and_sos(c):
    c.post(f"{W}/allies", json={"name": "Asha Rao", "phone": "+91 98765 43210", "relationship": "PARENT", "consent": True}, headers=CITIZEN)
    r = c.post(f"{W}/sos", json={"method": "LONG_PRESS", "device_location": fix((23.2599, 77.4126), accuracy=7.0)}, headers=CITIZEN)
    assert r.status_code == 201, r.text
    return r.json()


def send(c, path, data=WEBM, headers=CITIZEN, expect=201, **form):
    r = c.post(path, files={"audio": ("note.webm", data, "audio/webm")}, data={k: str(v) for k, v in form.items()}, headers=headers)
    assert r.status_code == expect, r.text
    return r.json()


# ------------------------------------------------------------------ SOS
def test_citizen_adds_a_voice_note_to_an_active_sos_and_plays_it_back(c):
    s = ally_and_sos(c)
    out = send(c, f"{W}/sos/{s['sos_id']}/audio-notes", duration_s=12.4)
    note = out["note"]
    assert note["kind"] == "SOS" and note["duration_s"] == 12.4 and note["mime_type"] == "audio/webm"
    again = c.get(f"{W}/sos/{s['sos_id']}", headers=CITIZEN).json()
    assert [n["note_id"] for n in again["audio_notes"]] == [note["note_id"]]
    assert any(e["event"] == "VOICE_NOTE" for e in again["history"])
    played = c.get(note["url"].replace("/api/v1", "/api/v1"), headers=CITIZEN)
    assert played.status_code == 200 and played.content == WEBM and played.headers["content-type"] == "audio/webm"
    assert "no-store" in played.headers["cache-control"]


def test_the_ally_link_plays_the_voice_note_only_while_the_sos_is_active(c):
    s = ally_and_sos(c)
    send(c, f"{W}/sos/{s['sos_id']}/audio-notes", duration_s=5)
    token = s["allies"][0]["share_path"].split("/")[-1]
    shared = c.get(f"{W}/share/{token}").json()
    assert len(shared["audio_notes"]) == 1
    url = shared["audio_notes"][0]["url"]
    assert c.get(url).status_code == 200                       # the private link is the credential
    c.post(f"{W}/sos/{s['sos_id']}/resolve", headers=CITIZEN)
    assert c.get(f"{W}/share/{token}").json()["audio_notes"] == []
    assert c.get(url).status_code == 404


def test_sos_voice_notes_are_private_to_the_owner(c):
    s = ally_and_sos(c)
    note = send(c, f"{W}/sos/{s['sos_id']}/audio-notes", duration_s=3)["note"]
    assert c.get(note["url"], headers=CITIZEN2).status_code == 404
    assert c.get(note["url"], headers=SUPERVISOR).status_code == 403
    send(c, f"{W}/sos/{s['sos_id']}/audio-notes", headers=CITIZEN2, expect=404)


def test_only_real_audio_within_the_limits_is_accepted(c):
    s = ally_and_sos(c)
    path = f"{W}/sos/{s['sos_id']}/audio-notes"
    assert send(c, path, data=b"<html>not audio</html>" * 20, expect=422)["code"] == "AUDIO_UNSUPPORTED"
    assert send(c, path, data=b"\x1aE\xdf\xa3", expect=422)["code"] == "AUDIO_EMPTY"
    assert send(c, path, duration_s=999, expect=422)["code"] == "AUDIO_TOO_LONG"
    r = c.post(path, headers=CITIZEN)
    assert r.status_code == 422 and r.json()["code"] == "AUDIO_REQUIRED"
    assert send(c, path, data=MP4)["note"]["mime_type"] == "audio/mp4"     # iPhone recordings


def test_no_voice_note_after_the_sos_has_ended(c):
    s = ally_and_sos(c)
    c.post(f"{W}/sos/{s['sos_id']}/cancel", headers=CITIZEN)
    assert send(c, f"{W}/sos/{s['sos_id']}/audio-notes", expect=409)["code"] == "SOS_ENDED"


# ------------------------------------------------------------------ task completion
def test_worker_adds_a_voice_note_to_a_completion_and_the_supervisor_hears_it(c):
    inc, task, wh = reported_task(c)
    start(c, task["task_id"], wh)
    done = complete(c, task["task_id"], wh, device=fix(SPOT))
    cid = done["completion"]["completion_id"]
    out = send(c, f"/api/v1/tasks/{task['task_id']}/audio-notes", headers=wh, duration_s=20, completion_id=cid)
    note = out["note"]
    assert note["kind"] == "COMPLETION" and note["completion_id"] == cid
    detail = c.get(f"/api/v1/completions/{cid}", headers=SUPERVISOR).json()
    assert [n["note_id"] for n in detail["audio_notes"]] == [note["note_id"]]
    assert detail["outcome"] == done["completion"]["outcome"]          # the note never changes the GeoSatya result
    assert c.get(note["url"], headers=SUPERVISOR).status_code == 200
    assert c.get(note["url"], headers=wh).status_code == 200
    audit = c.get(f"/api/v1/incidents/{inc['incident_id']}/audit", headers=SUPERVISOR)
    if audit.status_code == 200:
        assert any(e.get("action") == "VOICE_NOTE_ADDED" for e in audit.json())


def test_completion_works_without_a_voice_note(c):
    inc, task, wh = reported_task(c)
    start(c, task["task_id"], wh)
    done = complete(c, task["task_id"], wh, device=fix(SPOT))
    detail = c.get(f"/api/v1/completions/{done['completion']['completion_id']}", headers=SUPERVISOR).json()
    assert detail["audio_notes"] == []


def test_only_the_assigned_worker_can_add_a_task_voice_note(c):
    inc, task, wh = reported_task(c)
    start(c, task["task_id"], wh)
    other = WORKER15 if wh != WORKER15 else {"X-GeoSatya-Demo-User": "W-DEMO-12"}
    send(c, f"/api/v1/tasks/{task['task_id']}/audio-notes", headers=other, expect=404)
    send(c, f"/api/v1/tasks/{task['task_id']}/audio-notes", headers=SUPERVISOR, expect=403)
    send(c, f"/api/v1/tasks/{task['task_id']}/audio-notes", headers=CITIZEN, expect=403)


def test_a_task_voice_note_needs_the_task_to_be_started(c):
    inc, task, wh = reported_task(c)
    assert send(c, f"/api/v1/tasks/{task['task_id']}/audio-notes", headers=wh, expect=409)["code"] == "TASK_NOT_ACTIVE"


# ------------------------------------------------------------------ worker search (read-only)
def test_worker_search_ranks_with_the_dispatch_rules_and_changes_nothing(c):
    inc, task, wh = reported_task(c)
    before = c.get(f"/api/v1/incidents/{inc['incident_id']}", headers=SUPERVISOR).json()
    r = c.get(f"/api/v1/incidents/{inc['incident_id']}/dispatch/candidates", headers=SUPERVISOR)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["total"] >= 1 and out["current_worker_id"] == task["worker_id"]
    ranks = [w["rank"] for w in out["workers"] if w["eligible"]]
    assert ranks == sorted(ranks) and all(w["distance_km"] is not None for w in out["workers"] if w["eligible"])
    assert all(w["reasons"] for w in out["workers"] if not w["eligible"])
    assert any(w["is_current"] for w in out["workers"])
    after = c.get(f"/api/v1/incidents/{inc['incident_id']}", headers=SUPERVISOR).json()
    assert after["task"] == before["task"] and after["status"] == before["status"]


def test_worker_search_is_for_supervisors_only(c):
    inc, task, wh = reported_task(c)
    assert c.get(f"/api/v1/incidents/{inc['incident_id']}/dispatch/candidates", headers=wh).status_code == 403
    assert c.get(f"/api/v1/incidents/{inc['incident_id']}/dispatch/candidates", headers=CITIZEN).status_code == 403
