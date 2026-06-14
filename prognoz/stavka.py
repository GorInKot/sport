"""Парсер stavka.tv — предматчевые данные через публичный API Nuxt-приложения.

API обнаружен в JS-бандлах сайта:
  base = https://stavka.tv/api/v2
  GET /matches/center?sport=soccer&limit=N  — лента матч-центра
  GET /matches/{slug}                        — карточка матча (текстовый разбор)
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

import requests

from .models import Match, Odds1x2

API_BASE = "https://stavka.tv/api/v2"
HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
    ),
}

# Статусы матча в API: 0 — не начался, 6/7/80 — лайв, 100 — завершён.
STATUS_UPCOMING = 0

# В слаге матча даты и имена команд уже на английском: "13-06-2026-usa-paraguay".
_SLUG_DATE_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{4})-(.+)$")


def _parse_kickoff(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _en_names_from_slug(slug: str) -> tuple[str, str]:
    """Достаёт английские имена команд из слага матча.

    "13-06-2026-usa-paraguay" -> ("usa", "paraguay").
    Команды в слаге разделены последним участком после даты; разделитель — дефис,
    но имена тоже могут содержать дефисы, поэтому берём team.slug как приоритет,
    а это — запасной разбор по центру.
    """
    m = _SLUG_DATE_RE.match(slug or "")
    if not m:
        return "", ""
    tail = m.group(4)
    parts = tail.split("-")
    mid = len(parts) // 2
    return "-".join(parts[:mid]), "-".join(parts[mid:])


def _odds_from(match: dict) -> Odds1x2:
    block = ((match.get("odds") or {}).get("one_x_two")) or {}

    def val(key: str) -> Optional[float]:
        cell = block.get(key) or {}
        v = cell.get("value")
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    return Odds1x2(w1=val("w1"), x=val("x"), w2=val("w2"))


def _team_en(team: dict, fallback: str) -> str:
    """Английский идентификатор команды для матчинга: slug или country.slug."""
    country = team.get("country") or {}
    slug = team.get("slug") or country.get("slug") or ""
    # У национальных сборных slug вида "usa-3" — отрезаем числовой суффикс.
    slug = re.sub(r"-\d+$", "", slug)
    return slug or fallback


def fetch_upcoming(sport: str = "soccer", limit: int = 80,
                   timeout: int = 20) -> list[Match]:
    """Возвращает предстоящие матчи с коэффициентами 1X2."""
    resp = requests.get(
        f"{API_BASE}/matches/center",
        params={"sport": sport, "limit": limit},
        headers=HEADERS,
        timeout=timeout,
    )
    resp.raise_for_status()
    payload = resp.json()

    matches: list[Match] = []
    for league in payload.get("data", []):
        country = (league.get("country") or {}).get("name")
        for raw in league.get("matches", []):
            if raw.get("status") != STATUS_UPCOMING:
                continue
            odds = _odds_from(raw)
            if not odds.complete():
                continue  # без полной линии 1X2 прогноз не строим

            teams = raw.get("teams") or {}
            home, away = teams.get("home") or {}, teams.get("away") or {}
            slug = raw.get("slug") or ""
            home_en, away_en = _team_en(home, ""), _team_en(away, "")
            if not (home_en and away_en):
                home_en, away_en = _en_names_from_slug(slug)

            stats = raw.get("predictionStats") or {}
            matches.append(
                Match(
                    slug=slug,
                    sport=raw.get("sportSlug") or sport,
                    league=league.get("name") or "",
                    league_country=country,
                    home=home.get("name") or home.get("shortName") or "?",
                    away=away.get("name") or away.get("shortName") or "?",
                    home_en=home_en,
                    away_en=away_en,
                    kickoff=_parse_kickoff(raw.get("matchDate")),
                    odds=odds,
                    predictions_total=int(stats.get("total") or 0),
                    has_expert=bool(stats.get("haveExpertPredictions")),
                )
            )
    return matches


def fetch_summary(slug: str, timeout: int = 20) -> Optional[str]:
    """Текстовый предматчевый разбор от редакции stavka.tv (HTML), если есть."""
    try:
        resp = requests.get(
            f"{API_BASE}/matches/{slug}", headers=HEADERS, timeout=timeout
        )
        resp.raise_for_status()
        data = resp.json().get("data") or resp.json()
        return data.get("predictionSummary")
    except (requests.RequestException, ValueError):
        return None
