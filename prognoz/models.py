"""Модели данных, общие для всех модулей сервиса."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class Odds1x2:
    """Коэффициенты на исход 1X2 (победа хозяев / ничья / победа гостей)."""

    w1: Optional[float] = None
    x: Optional[float] = None
    w2: Optional[float] = None

    def complete(self) -> bool:
        return all(v and v > 1 for v in (self.w1, self.x, self.w2))


@dataclass
class DropSignal:
    """Прогруз по одному исходу с arbworld: открытие, текущий коэф, направление.

    drop > 0  — коэффициент упал (на исход заходят деньги, «прогруз»).
    drop < 0  — коэффициент вырос (от исхода уходят).
    """

    opening: Optional[float] = None
    current: Optional[float] = None

    @property
    def drop(self) -> float:
        """Относительное движение линии: (открытие − текущий) / открытие."""
        if not self.opening or not self.current:
            return 0.0
        return (self.opening - self.current) / self.opening


@dataclass
class ArbRow:
    """Строка прогрузов с arbworld по матчу (исходы 1 / X / 2 + объём)."""

    league: str
    home: str
    away: str
    date_text: str
    one: DropSignal = field(default_factory=DropSignal)
    draw: DropSignal = field(default_factory=DropSignal)
    two: DropSignal = field(default_factory=DropSignal)
    volume: Optional[str] = None


@dataclass
class Match:
    """Предстоящий матч со stavka.tv плюс приложенный прогруз (если найден)."""

    slug: str
    sport: str
    league: str
    league_country: Optional[str]
    home: str
    away: str
    home_en: str           # английский слаг команды — для матчинга с arbworld
    away_en: str
    kickoff: Optional[datetime]
    odds: Odds1x2
    predictions_total: int = 0          # сколько прогнозов оставило сообщество
    has_expert: bool = False
    summary_html: Optional[str] = None  # текстовый разбор от редакции stavka.tv
    arb: Optional[ArbRow] = None        # прогруз, привязанный matcher'ом


@dataclass
class ScorePred:
    """Один вариант точного счёта с вероятностью."""

    home_goals: int
    away_goals: int
    prob: float

    @property
    def label(self) -> str:
        return f"{self.home_goals}:{self.away_goals}"


@dataclass
class Prediction:
    """Результат работы движка прогнозов по одному матчу."""

    match: Match
    # де-маржинальные вероятности 1X2 (после учёта прогрузов)
    p_home: float
    p_draw: float
    p_away: float
    # ожидаемые голы модели Пуассона
    lambda_home: float
    lambda_away: float
    top_scores: list[ScorePred]
    p_over_25: float
    p_btts: float          # обе забьют
    best_pick: str         # текстовая рекомендация
    confidence: float      # 0..1 — уверенность в основном исходе
    notes: list[str] = field(default_factory=list)  # пояснения (прогрузы и т.п.)

    @property
    def double_chance(self) -> dict[str, float]:
        return {
            "1X": self.p_home + self.p_draw,
            "12": self.p_home + self.p_away,
            "X2": self.p_draw + self.p_away,
        }
