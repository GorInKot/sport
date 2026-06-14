"""Сопоставление прогрузов arbworld со матчами stavka.tv.

stavka даёт английский слаг команды (usa, switzerland, atletico-goianiense),
arbworld — английское имя (USA, Switzerland, Zamora). Сводим оба к нормальному
виду и сопоставляем по обеим командам; при наличии — сверяем день/месяц.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

from .models import ArbRow, Match

# Алиасы для расхождений в написании названий между источниками.
_ALIASES = {
    "usa": "unitedstates",
    "unitedstatesofamerica": "unitedstates",
    "southkorea": "korearepublic",
    "korea": "korearepublic",
    "ivorycoast": "cotedivoire",
    "czechia": "czechrepublic",
}


def _norm(text: str) -> str:
    """Нормализует имя: транслит-нейтрально, только латинские буквы в нижнем."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = re.sub(r"[^a-zA-Z]", "", text).lower()
    return _ALIASES.get(text, text)


def _names_match(a: str, b: str) -> bool:
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    if a == b:
        return True
    # одно имя — префикс/вхождение другого (Switzerland vs Swiss и т.п.)
    shorter, longer = sorted((a, b), key=len)
    return len(shorter) >= 4 and shorter in longer


def _date_compatible(match: Match, arb: ArbRow) -> bool:
    """Если у матча известна дата, отбрасываем прогрузы другого дня."""
    if not match.kickoff or not arb.date_text:
        return True
    # arb.date_text вида "Jun 13, 19:00" — сверяем номер дня.
    m = re.search(r"\b(\d{1,2})\b", arb.date_text)
    if not m:
        return True
    return int(m.group(1)) == match.kickoff.day


def attach_drops(matches: list[Match], drops: list[ArbRow]) -> int:
    """Привязывает к каждому матчу подходящий прогруз. Возвращает число совпадений."""
    matched = 0
    used: set[int] = set()
    for match in matches:
        best: Optional[int] = None
        for i, arb in enumerate(drops):
            if i in used or not _date_compatible(match, arb):
                continue
            home_ok = _names_match(match.home_en, arb.home) or _names_match(match.home, arb.home)
            away_ok = _names_match(match.away_en, arb.away) or _names_match(match.away, arb.away)
            if home_ok and away_ok:
                best = i
                break
        if best is not None:
            match.arb = drops[best]
            used.add(best)
            matched += 1
    return matched
