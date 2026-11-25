"""Road routing behind a small replaceable interface.

`make_router(settings)` returns None when routing is off, so every caller
falls back to straight-line estimates. Only OSRM is implemented; another
provider needs one class with the same `route()` method.

Failures (timeout, HTTP error, no route) return None and are logged; they
never break tracking, dispatch or reporting. Results are cached briefly by
rounded coordinates so polling viewers don't multiply requests.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field

import httpx

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Route:
    distance_m: float
    duration_s: float
    provider: str
    geometry: list = field(default_factory=list)  # [[lat, lon], ...]


class OsrmRouter:
    name = "osrm"

    def __init__(self, base_url: str, profile: str = "driving", timeout_s: float = 4.0,
                 transport: httpx.BaseTransport | None = None) -> None:
        self.base_url, self.profile, self.timeout_s, self._transport = base_url.rstrip("/"), profile, timeout_s, transport

    def route(self, origin: tuple[float, float], dest: tuple[float, float]) -> Route | None:
        coords = f"{origin[1]:.6f},{origin[0]:.6f};{dest[1]:.6f},{dest[0]:.6f}"  # OSRM wants lon,lat
        url = f"{self.base_url}/route/v1/{self.profile}/{coords}"
        try:
            with httpx.Client(timeout=self.timeout_s, transport=self._transport) as client:
                r = client.get(url, params={"overview": "simplified", "geometries": "geojson"})
            data = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.warning("routing_failed provider=osrm error=%s", type(exc).__name__)
            return None
        if r.status_code != 200 or data.get("code") != "Ok" or not data.get("routes"):
            log.warning("routing_no_route provider=osrm status=%s code=%s", r.status_code, data.get("code"))
            return None
        best = data["routes"][0]
        geometry = [[lat, lon] for lon, lat in (best.get("geometry") or {}).get("coordinates", [])]
        return Route(float(best["distance"]), float(best["duration"]), "OSRM", geometry)


class CachedRouter:
    """Short-lived cache keyed by coordinates rounded to ~10 m."""

    def __init__(self, inner, ttl_s: int, size: int = 512) -> None:
        self.inner, self.ttl_s, self.size = inner, ttl_s, size
        self.name = inner.name
        self._items: OrderedDict = OrderedDict()
        self._lock = threading.Lock()

    def route(self, origin, dest):
        key = (round(origin[0], 4), round(origin[1], 4), round(dest[0], 4), round(dest[1], 4))
        now = time.monotonic()
        with self._lock:
            hit = self._items.get(key)
            if hit and now - hit[0] <= self.ttl_s:
                return hit[1]
        result = self.inner.route(origin, dest)
        with self._lock:
            self._items[key] = (now, result)
            self._items.move_to_end(key)
            while len(self._items) > self.size:
                self._items.popitem(last=False)
        return result


def make_router(settings):
    if settings.routing_provider == "osrm":
        if not settings.routing_url:
            raise RuntimeError("ROUTING_PROVIDER=osrm needs ROUTING_URL.")
        inner = OsrmRouter(settings.routing_url, settings.routing_profile, settings.routing_timeout_s)
        return CachedRouter(inner, settings.routing_cache_s) if settings.routing_cache_s else inner
    return None
