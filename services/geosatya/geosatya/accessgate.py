"""Optional access code for development links (e.g. a Cloudflare tunnel).

Set ACCESS_CODE and every request needs it first, except /health. Browsers get
a small code-entry page; the right code sets a cookie (HttpOnly, SameSite=Lax,
Secure on https) for ACCESS_COOKIE_HOURS. API calls without it get 401.
Wrong codes are rate-limited per client. Changing ACCESS_CODE invalidates
every cookie. This is a gate in front of the demo, not user authentication:
demo roles still apply behind it.
"""

from __future__ import annotations

import hashlib
import hmac
import html

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from geosatya.ratelimit import SlidingWindowLimiter

COOKIE = "geosatya_access"
OPEN_PATHS = {"/health", "/access"}


def _token(code: str) -> str:
    return hmac.new(code.encode(), b"geosatya-access-v1", hashlib.sha256).hexdigest()


def _is_https(request: Request) -> bool:
    # Behind a tunnel or proxy the original scheme arrives in X-Forwarded-Proto.
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"


def _client(request: Request) -> str:
    # Cloudflare passes the real visitor address; fall back to the socket address.
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")


def _page(message: str = "", status: int = 401) -> HTMLResponse:
    note = f'<p class="err">{html.escape(message)}</p>' if message else ""
    body = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>GeoSatya · access code</title>
<style>
 body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#F2F5FB;font:16px system-ui,sans-serif;color:#0E1A33}}
 form{{background:#fff;padding:28px 24px;border-radius:16px;box-shadow:0 6px 24px rgba(14,26,51,.1);width:min(340px,88vw);display:grid;gap:14px}}
 h1{{margin:0;font-size:20px}} p{{margin:0;color:#4A5872;font-size:14px;line-height:1.45}}
 input{{font:inherit;padding:12px;border:1px solid #C9D3E6;border-radius:10px}}
 button{{font:600 16px system-ui,sans-serif;padding:12px;border:0;border-radius:10px;background:#2F6BFF;color:#fff}}
 .err{{color:#B91C1C}}
</style></head><body>
<form method="post" action="/access">
 <h1>GeoSatya</h1><p>This is a private development link. Enter the access code you were given.</p>{note}
 <input name="code" type="password" autocomplete="current-password" required autofocus aria-label="Access code">
 <button type="submit">Continue</button>
</form></body></html>"""
    return HTMLResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


def install(app, code: str, cookie_hours: int, attempts_per_min: int = 5) -> None:
    token = _token(code)
    limiter = SlidingWindowLimiter(attempts_per_min)

    @app.middleware("http")
    async def access_gate(request: Request, call_next):
        path = request.url.path
        if path == "/access" and request.method == "POST":
            if not limiter.allow(_client(request)):
                return _page("Too many attempts. Wait a minute and try again.", 429)
            form = await request.form()
            if not hmac.compare_digest(str(form.get("code", "")).strip().encode(), code.encode()):
                return _page("That code is not right.")
            response = RedirectResponse("/", status_code=303)
            response.set_cookie(COOKIE, token, max_age=cookie_hours * 3600, httponly=True, samesite="lax",
                                secure=_is_https(request), path="/")
            return response
        if path in OPEN_PATHS:
            return await call_next(request)
        if hmac.compare_digest(request.cookies.get(COOKIE, "").encode(), token.encode()):
            return await call_next(request)
        if path.startswith("/api/"):
            return JSONResponse({"detail": "Access code required.", "code": "ACCESS_CODE_REQUIRED"}, status_code=401)
        return _page()
