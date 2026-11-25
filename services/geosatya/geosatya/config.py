from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent

# The geofence is a business rule, not a promise of GPS precision. It can be
# changed (Settings page or GEOFENCE_RADIUS_M) within this range only.
GEOFENCE_MIN_M, GEOFENCE_MAX_M = 10.0, 20.0
ACCURACY_MIN_M, ACCURACY_MAX_M = 10.0, 100.0


def parse_token_pairs(raw: str) -> dict[str, str]:
    """Parse "token:user_id,token2:user_id2" into {token: user_id}."""
    pairs: dict[str, str] = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        token, sep, user_id = chunk.partition(":")
        token, user_id = token.strip(), user_id.strip()
        if not sep or len(token) < 16 or not user_id:
            raise ValueError("AUTH_TOKENS entries must look like <token of 16+ chars>:<user id>")
        pairs[token] = user_id
    return pairs


class Settings(BaseSettings):
    app_name: str = "GeoSatya"
    app_version: str = "0.3.0"
    api_prefix: str = "/api/v1"
    app_env: Literal["development", "test", "production"] = "development"

    # jwt:   real sign-in (citizen sign-up/login, worker access code + registration,
    #        supervisor credentials + access code). FastAPI issues a JWT access token.
    # demo:  development only: the UI may also pick a seeded demo identity (refused in production).
    #        JWT sign-in works in demo mode too.
    # token: fixed bearer tokens mapped to users (for scripts and tests).
    auth_mode: Literal["jwt", "demo", "token"] = "jwt"
    auth_tokens: SecretStr = SecretStr("")
    # Signs the access tokens. Empty = a random secret per server start (everyone signs in again after a restart).
    # Production needs a fixed secret of 32+ characters. Never commit it.
    jwt_secret: SecretStr = SecretStr("")
    jwt_ttl_hours: float = Field(default=12.0, gt=0, le=24 * 30)
    # Predefined access codes, held only by the server (environment variables). Empty = that door is closed.
    worker_access_code: SecretStr = SecretStr("")       # needed to register as a field worker
    supervisor_access_code: SecretStr = SecretStr("")   # needed, with credentials, for supervisor sign-in
    admin_access_code: SecretStr = SecretStr("")        # needed, with credentials, for platform admin sign-in
    # Sign-in / registration attempts per client address and per account per minute.
    login_rate_limit_per_min: int = Field(default=8, ge=0)

    database_url: str = f"sqlite:///{(BASE_DIR / 'data' / 'geosatya_v3.db').as_posix()}"
    storage_dir: Path = BASE_DIR / "private_uploads"
    max_image_size_bytes: int = Field(default=8 * 1024 * 1024, gt=0)
    max_image_pixels: int = Field(default=50_000_000, gt=0)

    # Starting values; a supervisor can change them later on the Settings page.
    geofence_radius_m: float = Field(default=15.0, ge=GEOFENCE_MIN_M, le=GEOFENCE_MAX_M)
    max_accuracy_m: float = Field(default=25.0, ge=ACCURACY_MIN_M, le=ACCURACY_MAX_M)
    # Photo GPS further than this from the device/incident counts as a conflict.
    exif_tolerance_m: float = Field(default=50.0, gt=0)
    # A browser fix older than this at photo time is refreshed first.
    location_freshness_s: int = Field(default=30, ge=1)
    # None = allowed only in development. Production always refuses simulation.
    simulated_can_pass: bool | None = None

    min_completion_chars: int = Field(default=10, ge=0)
    seed_demo_data: bool = True
    # Team live demo: only the ten team members, and a sign-in screen that accepts any password (demo mode only).
    team_demo: bool = False
    cors_origins: str = ""

    # Browser key for the Maps JavaScript API. It is visible to visitors by
    # design: restrict it to your HTTP referrers and that API in Google Cloud.
    # Leave empty to use Leaflet + OpenStreetMap.
    google_maps_browser_key: str | None = None
    google_maps_map_id: str | None = None

    # --- Incident Intelligence agent (separate service, incident-intelligence-agent branch).
    # Empty = not configured: reports are still accepted and marked "analysis not configured".
    intelligence_url: str = ""
    intelligence_timeout_s: float = Field(default=8.0, gt=0, le=60)
    # Team agents after Incident Intelligence (each optional; empty = not configured).
    # Their results are advisory: they are stored and shown, never block a report.
    duplicate_detection_url: str = ""     # Duplicate Detection agent (Yash), consolidation API
    supervisor_agent_url: str = ""        # Supervisor agent (Karanveer)
    sanitation_agent_url: str = ""        # Sanitation Planning agent (Namrata)
    agents_timeout_s: float = Field(default=6.0, gt=0, le=60)
    # Verification agent (MrBadDrip), run in-process on each completion photo.
    # off | mock (OpenCV quality/alignment + GPS; no AI vision) | gemini (needs GEMINI_API_KEY + GEMINI_MODEL)
    verification_agent: str = "mock"
    # Women's safety (Trusted Allies + SOS). No SMS / WhatsApp / push provider is connected:
    # until one is, allies get a private link the user sends from their own phone.
    sos_max_active_hours: float = Field(default=6.0, gt=0, le=48)    # an SOS left open is closed after this long
    sos_max_allies: int = Field(default=8, ge=1, le=20)
    sos_location_max_age_s: int = Field(default=900, ge=30)          # an older fix is not shared as "current"

    # --- Dispatch (ranking reused from the dispatch-work branch).
    dispatch_max_radius_km: float = Field(default=2.0, gt=0, le=50)
    dispatch_location_max_age_s: int = Field(default=900, ge=60)  # dispatch-work's 15-minute freshness rule
    # When no worker passes the dispatch rules only because nobody has shared a
    # location: "workload" assigns the least-loaded qualified worker (labelled),
    # "escalate" leaves the incident unassigned for a supervisor.
    dispatch_fallback: Literal["workload", "escalate"] = "workload"

    # --- Live tracking and ETA (approximate; no routing provider is configured).
    tracking_min_interval_s: int = Field(default=10, ge=0)
    tracking_stale_s: int = Field(default=120, ge=10)
    tracking_history_keep: int = Field(default=20, ge=2, le=500)
    arrival_radius_m: float = Field(default=50.0, ge=10, le=500)
    # Arrival needs this many consecutive good readings inside the arrival radius, so one stray fix can't claim it.
    arrival_confirm_readings: int = Field(default=2, ge=1, le=10)
    # An assignment not accepted within this time is shown as overdue; a supervisor can re-dispatch it.
    acceptance_timeout_min: int = Field(default=15, ge=1)
    # No movement toward the incident for this long (while not arrived) marks the worker as stationary.
    stationary_after_s: int = Field(default=180, ge=60)
    eta_assumed_speed_kmh: float = Field(default=20.0, gt=1, le=120)
    eta_route_factor: float = Field(default=1.4, ge=1.0, le=3.0)  # straight line -> typical road distance

    # --- Road routing (optional). "none" = straight-line estimates only.
    # "osrm" needs ROUTING_URL, e.g. a self-hosted OSRM server. The public demo
    # server (https://router.project-osrm.org) is for light testing only: its
    # usage policy does not allow production traffic.
    routing_provider: Literal["none", "osrm"] = "none"
    routing_url: str = ""
    routing_profile: str = "driving"
    routing_timeout_s: float = Field(default=4.0, gt=0, le=30)
    routing_cache_s: int = Field(default=120, ge=0)
    # Dispatch compares road travel time for this many top-ranked eligible workers.
    dispatch_route_candidates: int = Field(default=3, ge=1, le=10)
    # A worker location less accurate than this is not used for dispatch distance.
    dispatch_max_location_accuracy_m: float = Field(default=200.0, gt=0)
    # Development link gate: when set, every page and API call needs this code first (except /health).
    # Use it whenever the app is reachable beyond this computer (tunnel, Wi-Fi). Never commit a real code.
    access_code: SecretStr = SecretStr("")
    access_cookie_hours: int = Field(default=12, ge=1, le=720)
    # Citizen report submissions per user per minute (0 = off).
    report_rate_limit_per_min: int = Field(default=10, ge=0)

    # --- Resolution estimate (ETR) baseline, used until history exists.
    etr_default_travel_min: int = Field(default=30, ge=1)
    etr_review_buffer_min: int = Field(default=30, ge=0)
    etr_history_min_samples: int = Field(default=3, ge=1)

    model_config = SettingsConfigDict(env_file=BASE_DIR / ".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def simulation_allowed(self) -> bool:
        return self.app_env != "production"

    @property
    def simulated_may_pass(self) -> bool:
        if not self.simulation_allowed:
            return False
        return self.app_env == "development" if self.simulated_can_pass is None else self.simulated_can_pass

    def token_map(self) -> dict[str, str]:
        return parse_token_pairs(self.auth_tokens.get_secret_value())

    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
