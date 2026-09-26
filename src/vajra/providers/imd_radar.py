"""IMD Doppler Weather Radar public imagery (mode=LIVE, visual reference only).

Verified 2026-09-27: IMD serves station radar products as GIF/PNG images (e.g.
mausam.imd.gov.in/Radar/caz_delhi.gif) refreshed ~10 min. There is NO public
numeric radar channel. This provider therefore returns IMAGES for visual display
only — it never pretends to be quantitative radar input to models. Numeric radar
ingestion remains BLOCKED pending institutional access (MASTER.md §5).

Security: fetch targets come exclusively from a hardcoded allowlist below. The
provider performs SSRF hardening anyway (scheme + host allowlist check, manual
same-host-only redirect following, response content-type check) so the pattern
stays safe even if the allowlist grows.
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urljoin, urlparse

import httpx

from ..config import Settings
from ..schemas import DataHealth, DataMode, Modality
from ..logsetup import get_logger, log_event

logger = get_logger("vajra.providers.imd_radar")

ALLOWED_HOST_SUFFIX = "mausam.imd.gov.in"
ALLOWED_SCHEMES = {"https"}

STATION_PRODUCT_PATHS: dict[str, str] = {
    # Public station product pages verified on mausam.imd.gov.in (CAPPI composite
    # GIF products under /Radar/). Paths only — joined onto the fixed origin.
    "delhi": "/Radar/caz_delhi.gif",
    "patna": "/Radar/caz_patna.gif",
    "kolkata": "/Radar/caz_kolkata.gif",
    "mumbai": "/Radar/caz_mumbai.gif",
    "chennai": "/Radar/caz_chennai.gif",
    "visakhapatnam": "/Radar/caz_vishakhapatnam.gif",
    "lucknow": "/Radar/caz_lucknow.gif",
    "srinagar": "/Radar/caz_srinagar.gif",
}

BASE_ORIGIN = "https://mausam.imd.gov.in"


def _validate_url(url: str) -> None:
    u = urlparse(url)
    if u.scheme not in ALLOWED_SCHEMES:
        raise ValueError(f"scheme '{u.scheme}' not allowed")
    if not (u.hostname == ALLOWED_HOST_SUFFIX or (u.hostname or "").endswith("." + ALLOWED_HOST_SUFFIX)):
        raise ValueError(f"host '{u.hostname}' outside allowed domain {ALLOWED_HOST_SUFFIX}")


class ImradarGifProvider:
    """Fetches the latest public radar product image for visual reference."""

    name = "imd_radar_gif"
    modality = Modality.RADAR
    mode = DataMode.LIVE

    def __init__(self, settings: Settings, timeout_s: float = 12.0, max_redirects: int = 2):
        self.settings = settings
        self.timeout_s = timeout_s
        self.max_redirects = max_redirects
        self._last_success: datetime | None = None
        self._last_error: str = ""

    def health(self) -> DataHealth:
        if self._last_success is not None:
            status = DataMode.LIVE
            msg = "public GIF imagery available (visual reference only; not numeric)"
        else:
            status = DataMode.UNAVAILABLE
            msg = self._last_error or "not fetched yet"
        return DataHealth(source=self.name, modality=self.modality, status=status,
                          last_success=self._last_success, message=msg)

    def fetch(self, station: str = "delhi") -> tuple[bytes, str]:
        """Returns (image_bytes, content_type). Raises on failure — callers decide."""
        path = STATION_PRODUCT_PATHS.get(station)
        if path is None:
            raise KeyError(f"unknown radar station '{station}'; known: {sorted(STATION_PRODUCT_PATHS)}")
        url = urljoin(BASE_ORIGIN, path)
        _validate_url(url)
        try:
            with httpx.Client(timeout=self.timeout_s, follow_redirects=False) as client:
                for _ in range(self.max_redirects + 1):
                    resp = client.get(url, headers={"User-Agent": "vajra-sih26072-demo/0.1 (educational)"})
                    if resp.is_redirect:
                        nxt = urljoin(url, resp.headers.get("location", ""))
                        _validate_url(nxt)  # cross-host redirects are rejected
                        url = nxt
                        continue
                    break
            resp.raise_for_status()
            ct = resp.headers.get("content-type", "image/gif")
            if not ct.startswith("image/"):
                raise ValueError(f"unexpected content-type {ct} — IMD page layout may have changed")
            self._last_success = datetime.now(timezone.utc)
            self._last_error = ""
            return resp.content, ct
        except Exception as exc:  # noqa: BLE001 — boundary: record and re-raise typed info
            self._last_error = f"{type(exc).__name__}: {exc}"
            log_event(logger, 30, "radar gif fetch failed", station=station, error=self._last_error)
            raise
