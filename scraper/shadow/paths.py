"""Paths for the isolated Scrapling shadow pilot. Never points at write-paths for production data."""
from __future__ import annotations

import os

SHADOW_ROOT = os.path.dirname(os.path.abspath(__file__))
SCRAPER_ROOT = os.path.dirname(SHADOW_ROOT)
REPO_ROOT = os.path.dirname(SCRAPER_ROOT)

PRODUCTION_FIXTURES = os.path.join(SCRAPER_ROOT, "fixtures")
SHADOW_FIXTURES = os.path.join(SHADOW_ROOT, "fixtures")
ADAPTIVE_STATE_DIR = os.path.join(SHADOW_ROOT, "adaptive_state")
ARTIFACTS_DIR = os.path.join(SHADOW_ROOT, "artifacts")
SHADOW_REPORT = os.path.join(ARTIFACTS_DIR, "scrapling-shadow.json")

# Production catalog files — shadow code must never write these.
PRODUCTION_EVENTS = os.path.join(REPO_ROOT, "events.json")
PRODUCTION_HEALTH = os.path.join(REPO_ROOT, "source_health.json")

PRODUCTION_CIC = os.path.join(PRODUCTION_FIXTURES, "cic", "events.html")
PRODUCTION_HKIE = os.path.join(PRODUCTION_FIXTURES, "hkie_cpd", "calendar.html")
PRODUCTION_HKGBC = os.path.join(PRODUCTION_FIXTURES, "hkgbc", "events_listing.html")
PRODUCTION_HKGBC_DETAIL = os.path.join(PRODUCTION_FIXTURES, "hkgbc", "events_detail.html")
PRODUCTION_HKGBC_OG = os.path.join(PRODUCTION_FIXTURES, "hkgbc", "events_detail_og.html")

CIC_DRIFT = os.path.join(SHADOW_FIXTURES, "cic_listing_drift.html")
CIC_DECOY = os.path.join(SHADOW_FIXTURES, "cic_listing_decoy.html")
HKIE_DRIFT = os.path.join(SHADOW_FIXTURES, "hkie_cpd_listing_drift.html")
HKIE_DECOY = os.path.join(SHADOW_FIXTURES, "hkie_cpd_listing_decoy.html")
HKGBC_DRIFT = os.path.join(SHADOW_FIXTURES, "hkgbc_listing_drift.html")
HKGBC_DECOY = os.path.join(SHADOW_FIXTURES, "hkgbc_listing_decoy.html")

STATE_CIC = os.path.join(ADAPTIVE_STATE_DIR, "cic.json")
STATE_HKIE = os.path.join(ADAPTIVE_STATE_DIR, "hkie_cpd.json")
STATE_HKGBC = os.path.join(ADAPTIVE_STATE_DIR, "hkgbc.json")

CIC_URL = "https://www.cic.hk/en/events"
HKIE_URL = "https://hkie.org.hk/professional-development/continuing-professional-development/cpd-calendar/"
HKGBC_URL = "https://www.hkgbc.org.hk/eng/news-events/events-trainings/events"

# Identifiers for Scrapling adaptive fingerprints (stable, source-specific).
IDENT_CIC_CARD = "cic_event_card"
IDENT_HKIE_CARD = "hkie_cpd_course_card"
IDENT_HKGBC_CARD = "hkgbc_event_card"

# CSS used to establish the baseline element (must fail after the drift rename).
CSS_CIC_CARD = "article.event-card"
CSS_HKIE_CARD = ".e-loop-item"
CSS_HKGBC_CARD = ".event-card, .eventpost"
