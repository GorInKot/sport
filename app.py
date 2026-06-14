"""Веб-сервис прогнозов на футбол.

Запуск:
    pip install -r requirements.txt
    python app.py
    -> http://127.0.0.1:5000
"""

from __future__ import annotations

import time
from threading import Lock

from flask import Flask, abort, render_template

from prognoz import arbworld, stavka
from prognoz.matcher import attach_drops
from prognoz.predictor import predict

app = Flask(__name__)

CACHE_TTL = 120  # секунд: щадим сайты-источники и ускоряем повторные заходы
_cache: dict[str, object] = {}
_lock = Lock()


def _load_matches():
    """Тянет матчи + прогрузы, связывает их. Результат кэшируется на CACHE_TTL."""
    now = time.time()
    with _lock:
        cached = _cache.get("matches")
        if cached and now - cached[0] < CACHE_TTL:
            return cached[1], cached[2]

    matches = stavka.fetch_upcoming(limit=80)
    matched = 0
    try:
        drops = arbworld.fetch_drops()
        matched = attach_drops(matches, drops)
    except Exception as exc:  # arbworld недоступен — работаем на данных stavka
        app.logger.warning("arbworld недоступен: %s", exc)

    matches.sort(key=lambda m: (m.kickoff is None, m.kickoff))
    with _lock:
        _cache["matches"] = (now, matches, matched)
    return matches, matched


@app.route("/")
def index():
    try:
        matches, matched = _load_matches()
    except Exception as exc:
        return render_template("error.html", error=str(exc)), 502

    cards = []
    for m in matches:
        p = predict(m)
        if p:
            cards.append(p)
    return render_template(
        "index.html",
        predictions=cards,
        total=len(cards),
        matched=matched,
    )


@app.route("/match/<path:slug>")
def match_detail(slug: str):
    matches, _ = _load_matches()
    match = next((m for m in matches if m.slug == slug), None)
    if match is None:
        abort(404)
    prediction = predict(match)
    if prediction is None:
        abort(404)
    summary = stavka.fetch_summary(slug)
    return render_template("match.html", p=prediction, summary=summary)


@app.template_filter("pct")
def pct(value: float) -> str:
    return f"{value * 100:.0f}%"


@app.template_filter("kickoff")
def kickoff(dt) -> str:
    return dt.strftime("%d.%m %H:%M") if dt else "—"


if __name__ == "__main__":
    app.run(debug=True, port=5000)
