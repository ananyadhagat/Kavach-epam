"""Development access code in front of the app (for tunnel / Wi-Fi links)."""

import pytest
from fastapi.testclient import TestClient

from geosatya.accessgate import COOKIE
from geosatya.main import create_app
from tests.conftest import SUPERVISOR, make_settings


@pytest.fixture
def gated(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, access_code="river-7342"))) as c:
        yield c


def test_without_the_code_pages_show_the_code_form_and_the_api_refuses(gated):
    page = gated.get("/")
    assert page.status_code == 401 and "access code" in page.text.lower() and page.headers["cache-control"] == "no-store"
    assert gated.get("/js/app.js").status_code == 401                # app files too
    assert gated.get("/docs").status_code == 401
    r = gated.get("/api/v1/dashboard/live", headers=SUPERVISOR)
    assert r.status_code == 401 and r.json()["code"] == "ACCESS_CODE_REQUIRED"
    assert gated.get("/health").status_code == 200                    # health checks stay open


def test_the_right_code_sets_a_cookie_and_everything_works(gated):
    r = gated.post("/access", data={"code": "river-7342"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "secure" not in cookie   # plain http locally
    assert gated.get("/").status_code == 200 and 'id="main"' in gated.get("/").text
    assert gated.get("/api/v1/dashboard/live", headers=SUPERVISOR).status_code == 200


def test_cookie_is_secure_behind_an_https_tunnel(gated):
    r = gated.post("/access", data={"code": "river-7342"}, headers={"X-Forwarded-Proto": "https"}, follow_redirects=False)
    assert "secure" in r.headers["set-cookie"].lower()


def test_wrong_codes_are_refused_and_rate_limited(gated):
    for _ in range(5):
        r = gated.post("/access", data={"code": "guess"})
        assert r.status_code == 401 and "is not right" in r.text
    assert gated.post("/access", data={"code": "river-7342"}).status_code == 429   # even the right one, for a minute
    assert COOKIE not in gated.cookies


def test_a_forged_cookie_does_not_pass(gated):
    gated.cookies.set(COOKIE, "0" * 64)
    assert gated.get("/api/v1/me", headers=SUPERVISOR).status_code == 401


def test_changing_the_code_logs_everyone_out(tmp_path):
    with TestClient(create_app(make_settings(tmp_path, access_code="river-7342"))) as c:
        c.post("/access", data={"code": "river-7342"})
        old = c.cookies.get(COOKIE)
    with TestClient(create_app(make_settings(tmp_path, access_code="harbour-1188"))) as c:
        c.cookies.set(COOKIE, old)
        assert c.get("/api/v1/me", headers=SUPERVISOR).status_code == 401


def test_no_code_set_means_no_gate(client):
    assert client.get("/").status_code == 200


def test_a_too_short_code_is_refused_at_start(tmp_path):
    with pytest.raises(RuntimeError):
        create_app(make_settings(tmp_path, access_code="123"))
