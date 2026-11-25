"""Women's safety: Trusted Allies and SOS. Privacy first: allies, SOS history and locations belong to
one user; only a private per-ally link shows anything, and only while the SOS is active."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from geosatya.main import create_app
from tests.conftest import CITIZEN, CITIZEN2, SUPERVISOR, WORKER12, fix, make_settings

W = "/api/v1/women"
ORG_ADMIN = {"X-GeoSatya-Demo-User": "ORG-DEMO-01"}
PLATFORM_ADMIN = {"X-GeoSatya-Demo-User": "PA-DEMO-01"}
PHONE_FIX = (23.2599, 77.4126)


@pytest.fixture
def c(tmp_path):
    with TestClient(create_app(make_settings(tmp_path))) as client:
        yield client


def ally(c, name="Asha Rao", phone="+91 98765 43210", rel="PARENT", consent=True, headers=CITIZEN, expect=201):
    r = c.post(f"{W}/allies", json={"name": name, "phone": phone, "relationship": rel, "consent": consent}, headers=headers)
    assert r.status_code == expect, r.text
    return r.json()


def real_fix(**over):
    f = fix(PHONE_FIX, accuracy=7.0)
    f.update(over)
    return f


def sos(c, location="default", headers=CITIZEN, expect=201, **extra):
    body = {"method": "LONG_PRESS", **extra}
    if location == "default":
        body["device_location"] = real_fix()
    elif location is not None:
        body["device_location"] = location
    r = c.post(f"{W}/sos", json=body, headers=headers)
    assert r.status_code == expect, r.text
    return r.json()


# ------------------------------------------------------------ trusted allies
def test_add_update_list_and_remove_trusted_allies(c):
    a = ally(c)
    assert a["phone"] == "+919876543210" and a["relationship_label"] == "Parent" and a["consent_at"]
    b = ally(c, name="Ravi Rao", phone="9000011111", rel="SIBLING")
    ov = c.get(f"{W}/overview", headers=CITIZEN).json()
    assert [x["name"] for x in ov["allies"]] == ["Asha Rao", "Ravi Rao"] and ov["max_allies"] == 8
    assert "live location" in ov["who_gets_it"]
    up = c.patch(f"{W}/allies/{b['ally_id']}", json={"name": "Ravi R.", "relationship": "FRIEND"}, headers=CITIZEN).json()
    assert up["name"] == "Ravi R." and up["relationship"] == "FRIEND"
    assert c.delete(f"{W}/allies/{a['ally_id']}", headers=CITIZEN).json() == {"removed": True}
    assert [x["name"] for x in c.get(f"{W}/overview", headers=CITIZEN).json()["allies"]] == ["Ravi R."]


def test_consent_is_required_and_input_is_validated(c):
    assert ally(c, consent=False, expect=422)["code"] == "CONSENT_REQUIRED"
    assert ally(c, phone="abcdefgh", expect=422)["code"] == "INVALID_PHONE"
    assert ally(c, rel="BOSS", expect=422)["code"] == "INVALID_REQUEST"
    ally(c)
    assert ally(c, name="Someone Else", phone="+919876543210", expect=409)["code"] == "DUPLICATE_ALLY"


def test_ally_limit(c):
    for i in range(8):
        ally(c, name=f"Person {i}", phone=f"90000000{i:02d}")
    assert ally(c, name="Too many", phone="9111111111", expect=409)["code"] == "LIMIT_REACHED"


def test_allies_are_private_to_their_owner(c):
    a = ally(c)
    assert c.get(f"{W}/overview", headers=CITIZEN2).json()["allies"] == []
    assert c.patch(f"{W}/allies/{a['ally_id']}", json={"name": "Hacked"}, headers=CITIZEN2).status_code == 404
    assert c.delete(f"{W}/allies/{a['ally_id']}", headers=CITIZEN2).status_code == 404
    for who in (SUPERVISOR, WORKER12, ORG_ADMIN, PLATFORM_ADMIN):
        assert c.get(f"{W}/overview", headers=who).status_code == 403
        assert c.post(f"{W}/sos", json={"method": "BUTTON"}, headers=who).status_code == 403


# ----------------------------------------------------------------- SOS trigger
def test_sos_records_time_location_and_notifies_allies_honestly(c):
    ally(c)
    ally(c, name="Ravi Rao", phone="9000011111", rel="SIBLING")
    before = datetime.now(timezone.utc)
    s = sos(c)
    assert s["status"] == "ACTIVE" and before - timedelta(seconds=5) <= datetime.fromisoformat(s["triggered_at"]) <= datetime.now(timezone.utc) + timedelta(seconds=5)
    assert s["location_status"] == "SHARING" and s["location"]["latitude"] == pytest.approx(PHONE_FIX[0]) and s["location"]["mode"] == "LIVE"
    assert [a["name"] for a in s["allies"]] == ["Asha Rao", "Ravi Rao"]
    for a in s["allies"]:
        assert a["status"] == "PENDING_INTEGRATION" and a["status"] != "SENT"      # never claims delivery
        assert "not connected" in a["status_text"].lower() or "not sent" in a["status_text"].lower()
        assert a["share_path"].startswith("#/sos/")
    assert "Nothing is shown as delivered" in s["delivery_note"]
    assert [e["event"] for e in s["history"]][:2] == ["TRIGGERED", "LOCATION"]


def test_sos_without_gps_is_created_but_never_pretends_location_is_shared(c):
    ally(c)
    s = sos(c, location=None, device_location_error="PERMISSION_DENIED")
    assert s["status"] == "ACTIVE" and s["location"] is None and s["location_status"] == "WAITING_FOR_GPS"
    assert "permission" in s["location_text"].lower() and s["location_text"].startswith("No location is being shared")
    token = s["allies"][0]["share_path"].split("/")[-1]
    shared = c.get(f"{W}/share/{token}").json()
    assert shared["location"] is None and shared["location_note"].startswith("No location is being shared")


def test_manual_location_is_a_labelled_fallback_not_gps(c):
    ally(c)
    s = sos(c, location=None, device_location_error="TIMEOUT")
    m = c.post(f"{W}/sos/{s['sos_id']}/manual-location", json={"latitude": 23.25, "longitude": 77.40}, headers=CITIZEN).json()
    assert m["location_status"] == "MANUAL" and m["location"]["mode"] == "MANUAL" and "not GPS" in m["location_text"]
    # real GPS taking over replaces it
    live = c.post(f"{W}/sos/{s['sos_id']}/location", json={"device_location": real_fix()}, headers=CITIZEN).json()
    assert live["location_status"] == "SHARING" and live["location"]["mode"] == "LIVE"


def test_simulated_or_stale_locations_are_never_shared(c):
    ally(c)
    assert sos(c, location=real_fix(mode="SIMULATED"), expect=422)["code"] == "SIMULATED_NOT_ALLOWED"
    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    s = sos(c, location=real_fix(observed_at=old))
    assert s["location"] is None and s["location_error"] == "LOCATION_TOO_OLD"
    sim = c.post(f"{W}/sos/{s['sos_id']}/location", json={"device_location": real_fix(mode="SIMULATED")}, headers=CITIZEN)
    assert sim.status_code == 422


def test_pressing_sos_twice_does_not_create_a_second_sos(c):
    ally(c)
    first, second = sos(c), sos(c)
    assert first["sos_id"] == second["sos_id"]
    assert len(c.get(f"{W}/overview", headers=CITIZEN).json()["history"]) == 1


def test_sos_with_no_allies_still_works_and_says_nobody_was_alerted(c):
    s = sos(c)
    assert s["no_allies"] is True and s["allies"] == []
    assert {n["number"] for n in s["emergency"]} == {"100", "108", "112"}


# ------------------------------------------------------- live updates and ending
def test_live_location_updates_only_while_active_and_ignore_older_fixes(c):
    ally(c)
    s = sos(c)
    newer = (datetime.now(timezone.utc) + timedelta(seconds=1)).isoformat()
    u = c.post(f"{W}/sos/{s['sos_id']}/location", json={"device_location": real_fix(latitude=23.2610, observed_at=newer)}, headers=CITIZEN).json()
    assert u["location"]["latitude"] == pytest.approx(23.2610) and u["updates"] == 2
    older = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()
    ig = c.post(f"{W}/sos/{s['sos_id']}/location", json={"device_location": real_fix(latitude=23.0, observed_at=older)}, headers=CITIZEN).json()
    assert ig["update_ignored"] == "OUT_OF_ORDER" and ig["location"]["latitude"] == pytest.approx(23.2610)


def test_cancel_records_time_stops_sharing_and_queues_ally_notice(c):
    ally(c)
    s = sos(c)
    token = s["allies"][0]["share_path"].split("/")[-1]
    assert c.get(f"{W}/share/{token}").json()["location"] is not None
    x = c.post(f"{W}/sos/{s['sos_id']}/cancel", headers=CITIZEN).json()
    assert x["status"] == "CANCELLED" and x["ended_at"] and x["ended_reason"] == "USER_CANCELLED"
    assert x["allies"][0]["followup"] == "CANCELLED" and x["allies"][0]["share_path"] is None
    gone = c.get(f"{W}/share/{token}").json()
    assert gone["location"] is None and gone["status"] == "CANCELLED" and "no longer shared" in gone["location_note"]
    late = c.post(f"{W}/sos/{s['sos_id']}/location", json={"device_location": real_fix()}, headers=CITIZEN)
    assert late.status_code == 409 and late.json()["code"] == "SOS_ENDED"
    assert c.post(f"{W}/sos/{s['sos_id']}/cancel", headers=CITIZEN).status_code == 409
    hist = c.get(f"{W}/overview", headers=CITIZEN).json()
    assert hist["active"] is None and hist["history"][0]["status"] == "CANCELLED"        # history preserved


def test_i_am_safe_resolves_and_a_new_sos_can_start(c):
    ally(c)
    s = sos(c)
    r = c.post(f"{W}/sos/{s['sos_id']}/resolve", headers=CITIZEN).json()
    assert r["status"] == "RESOLVED" and r["ended_reason"] == "USER_SAFE"
    assert sos(c)["sos_id"] != s["sos_id"]


def test_an_sos_left_open_is_closed_automatically(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, sos_max_active_hours=1))) as c2:
        ally(c2)
        s = sos(c2)
        from geosatya.platform_models import SosRow
        with c2.app.state.session_factory() as db:
            db.get(SosRow, s["sos_id"]).triggered_at = datetime.now(timezone.utc) - timedelta(hours=2)
            db.commit()
        assert c2.get(f"{W}/sos/{s['sos_id']}", headers=CITIZEN).json()["status"] == "EXPIRED"


# -------------------------------------------------------- ally link and privacy
def test_ally_link_shows_only_name_time_and_live_location(c):
    ally(c)
    ally(c, name="Ravi Rao", phone="9000011111", rel="SIBLING")
    s = sos(c)
    token = s["allies"][0]["share_path"].split("/")[-1]
    shared = c.get(f"{W}/share/{token}").json()               # no sign-in: the private link is the credential
    assert shared["person"] == "Aarav" and shared["ally"] == "Asha Rao" and shared["status"] == "ACTIVE" and shared["triggered_at"]
    assert shared["location"]["latitude"] == pytest.approx(PHONE_FIX[0]) and shared["location"]["age_s"] is not None
    assert {n["number"] for n in shared["emergency"]} == {"100", "108", "112"} and "does not replace" in shared["disclaimer"]
    text = str(shared)
    # nothing that identifies the account, and nothing about the other allies
    assert "CIT-DEMO-01" not in text and "9876543210" not in text and "9000011111" not in text and "Ravi" not in text
    assert c.get(f"{W}/share/not-a-real-token").status_code == 404


def test_each_ally_has_their_own_private_link_and_open_time_is_recorded(c):
    ally(c)
    ally(c, name="Ravi Rao", phone="9000011111", rel="SIBLING")
    s = sos(c)
    t1, t2 = (a["share_path"].split("/")[-1] for a in s["allies"])
    assert t1 != t2 and len(t1) >= 20
    c.get(f"{W}/share/{t1}")
    opened = c.get(f"{W}/sos/{s['sos_id']}", headers=CITIZEN).json()["allies"]
    assert opened[0]["opened_at"] and opened[1]["opened_at"] is None


def test_sos_is_private_and_not_in_audit_or_public_data(c):
    ally(c)
    s = sos(c)
    assert c.get(f"{W}/sos/{s['sos_id']}", headers=CITIZEN2).status_code == 404
    assert c.post(f"{W}/sos/{s['sos_id']}/cancel", headers=CITIZEN2).status_code == 404
    for who in (SUPERVISOR, ORG_ADMIN, PLATFORM_ADMIN):
        assert c.get(f"{W}/sos/{s['sos_id']}", headers=who).status_code == 403
    audit = c.get("/api/v1/evidence-history", headers=SUPERVISOR).json()
    assert s["sos_id"] not in str(audit) and "SOS" not in {e["action"] for e in audit["events"]}
    assert s["sos_id"] not in str(c.get("/api/v1/kavach/public/stats").json())
    assert s["sos_id"] not in str(c.get("/api/v1/kavach/admin/overview", headers=PLATFORM_ADMIN).json())


def test_removing_an_ally_keeps_history_but_drops_their_contact_details(c):
    a = ally(c)
    s = sos(c)
    c.delete(f"{W}/allies/{a['ally_id']}", headers=CITIZEN)
    from geosatya.platform_models import TrustedAllyRow
    with c.app.state.session_factory() as db:
        assert db.get(TrustedAllyRow, a["ally_id"]) is None
    assert c.get(f"{W}/sos/{s['sos_id']}", headers=CITIZEN).json()["allies"][0]["name"] == "Asha Rao"


def test_emergency_dialer_links_and_disclaimer(c):
    ov = c.get(f"{W}/overview", headers=CITIZEN).json()
    assert [(e["number"], e["tel"]) for e in ov["emergency"]] == [("100", "tel:100"), ("108", "tel:108"), ("112", "tel:112")]
    assert "does not replace" in ov["disclaimer"]


def test_sos_is_never_blocked_while_one_is_active_but_new_ones_are_rate_limited(c):
    ally(c)
    first = sos(c)
    assert all(sos(c)["sos_id"] == first["sos_id"] for _ in range(10))           # mashing the button is safe
    codes = []
    for _ in range(8):                                                           # abuse: start and end SOS over and over
        s = c.post(f"{W}/sos", json={"method": "BUTTON", "device_location": real_fix()}, headers=CITIZEN)
        codes.append(s.status_code)
        if s.status_code == 201:
            c.post(f"{W}/sos/{s.json()['sos_id']}/cancel", headers=CITIZEN)
    assert 429 in codes
