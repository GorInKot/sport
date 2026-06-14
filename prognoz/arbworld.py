"""Парсер arbworld.net — прогрузы (dropping odds) по футболу, рынок 1X2.

Страница серверная, данные в HTML-таблице. Структура строки:
  tr.fade-in
    td.col-event[data-league,data-home,data-away,data-date]
    td (исход 1)  div.do-cell > span.do-arrow{up|down} + div.do-odds > span.open + span.current
    td (исход X)  ...
    td (исход 2)  ...
    td.col-vl     объём ставок (£)
"""

from __future__ import annotations

from typing import Optional

import requests
from bs4 import BeautifulSoup

from .models import ArbRow, DropSignal

URL = "https://arbworld.net/dropping-odds/football/1x2"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
    ),
}


def _to_float(text: str) -> Optional[float]:
    try:
        return float(text.strip())
    except (TypeError, ValueError):
        return None


def _parse_cell(td) -> DropSignal:
    """Из ячейки исхода достаёт коэффициенты открытия и текущий."""
    if td is None:
        return DropSignal()
    open_el = td.select_one("span.open")
    cur_el = td.select_one("span.current")
    return DropSignal(
        opening=_to_float(open_el.get_text()) if open_el else None,
        current=_to_float(cur_el.get_text()) if cur_el else None,
    )


def fetch_drops(timeout: int = 25) -> list[ArbRow]:
    """Возвращает прогрузы по всем доступным футбольным матчам."""
    resp = requests.get(URL, headers=HEADERS, timeout=timeout)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    rows: list[ArbRow] = []
    for tr in soup.select("tr.fade-in"):
        tds = tr.find_all("td", recursive=False)
        if len(tds) < 4:
            continue
        event = tds[0]
        home = event.get("data-home") or ""
        away = event.get("data-away") or ""
        if not (home and away):
            continue

        # Колонки исходов: вторая, третья, четвёртая ячейки (1 / X / 2).
        # Последняя ячейка (col-vl) — объём; берём её отдельно.
        vol_td = tr.select_one("td.col-vl")
        volume = vol_td.get_text(strip=True) if vol_td else None
        outcome_tds = [td for td in tds[1:] if "col-vl" not in (td.get("class") or [])]

        one = _parse_cell(outcome_tds[0]) if len(outcome_tds) > 0 else DropSignal()
        draw = _parse_cell(outcome_tds[1]) if len(outcome_tds) > 1 else DropSignal()
        two = _parse_cell(outcome_tds[2]) if len(outcome_tds) > 2 else DropSignal()

        rows.append(
            ArbRow(
                league=event.get("data-league") or "",
                home=home,
                away=away,
                date_text=event.get("data-date") or "",
                one=one,
                draw=draw,
                two=two,
                volume=volume,
            )
        )
    return rows
