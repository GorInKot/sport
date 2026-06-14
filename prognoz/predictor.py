"""Движок прогнозов.

Идея:
  1. Коэффициенты 1X2 -> вероятности с вычетом маржи букмекера.
  2. Подгоняем модель Пуассона (ожидаемые голы λ хозяев и гостей) так, чтобы она
     воспроизводила эти вероятности 1X2.
  3. Корректируем λ прогрузами с arbworld: куда падает линия и заходят деньги —
     туда смещаем перевес.
  4. Из итоговой модели Пуассона считаем варианты результатов: 1X2, точные счёта,
     тотал 2.5, обе забьют (ОЗ), двойной шанс.
"""

from __future__ import annotations

import math
from typing import Optional

from .models import Match, Prediction, ScorePred

MAX_GOALS = 10            # потолок голов в модели Пуассона
LAMBDA_GRID = [round(0.15 + 0.1 * i, 2) for i in range(40)]  # 0.15 .. 4.05
DROP_K = 1.2             # сила влияния прогруза на перевес
DROP_CLAMP = (0.72, 1.45)  # границы множителя λ


def implied_probabilities(o1: float, ox: float, o2: float) -> tuple[float, float, float]:
    """Коэффициенты -> вероятности 1X2 с нормализацией (вычет маржи)."""
    raw = [1.0 / o1, 1.0 / ox, 1.0 / o2]
    s = sum(raw)
    return raw[0] / s, raw[1] / s, raw[2] / s


def _poisson_pmf(lam: float, n: int = MAX_GOALS) -> list[float]:
    """Распределение числа голов 0..n при ожидании lam."""
    pmf = []
    for k in range(n + 1):
        pmf.append(math.exp(-lam) * lam ** k / math.factorial(k))
    # хвост (>n) добавляем к последнему значению, чтобы сумма была ~1
    pmf[-1] += max(0.0, 1.0 - sum(pmf))
    return pmf


def _outcome_probs(lh: float, la: float) -> tuple[float, float, float]:
    """Из λ хозяев/гостей -> P(победа1), P(ничья), P(победа2)."""
    home, away = _poisson_pmf(lh), _poisson_pmf(la)
    p1 = pd = p2 = 0.0
    for i, ph in enumerate(home):
        for j, pa in enumerate(away):
            joint = ph * pa
            if i > j:
                p1 += joint
            elif i == j:
                pd += joint
            else:
                p2 += joint
    return p1, pd, p2


def fit_lambdas(p1: float, pd: float, p2: float) -> tuple[float, float]:
    """Подбирает λ хозяев и гостей, наилучше воспроизводящие вероятности 1X2."""
    best = (1.3, 1.1)
    best_err = float("inf")
    pmf_cache = {lam: _poisson_pmf(lam) for lam in LAMBDA_GRID}
    for lh in LAMBDA_GRID:
        home = pmf_cache[lh]
        for la in LAMBDA_GRID:
            away = pmf_cache[la]
            a = d = b = 0.0
            for i, ph in enumerate(home):
                for j, pa in enumerate(away):
                    joint = ph * pa
                    if i > j:
                        a += joint
                    elif i == j:
                        d += joint
                    else:
                        b += joint
            err = (a - p1) ** 2 + (d - pd) ** 2 + (b - p2) ** 2
            if err < best_err:
                best_err, best = err, (lh, la)
    return best


def _apply_drop(match: Match, lh: float, la: float) -> tuple[float, float, list[str]]:
    """Смещает λ в сторону исхода, на который заходят деньги (прогруз)."""
    notes: list[str] = []
    arb = match.arb
    if arb is None:
        return lh, la, notes

    d1, d2 = arb.one.drop, arb.two.drop  # >0 => коэф упал => деньги на исход
    net = d1 - d2                        # перевес сигнала в сторону хозяев
    if abs(net) < 0.01 and abs(arb.draw.drop) < 0.01:
        return lh, la, notes

    fh = min(DROP_CLAMP[1], max(DROP_CLAMP[0], 1 + DROP_K * net))
    fa = min(DROP_CLAMP[1], max(DROP_CLAMP[0], 1 - DROP_K * net))
    lh, la = lh * fh, la * fa

    def pct(x: float) -> str:
        return f"{x * 100:+.1f}%"

    if d1 > 0.02:
        notes.append(f"Прогруз на П1 ({match.home}): коэф {arb.one.opening}→{arb.one.current} ({pct(d1)})")
    if d2 > 0.02:
        notes.append(f"Прогруз на П2 ({match.away}): коэф {arb.two.opening}→{arb.two.current} ({pct(d2)})")
    if arb.draw.drop > 0.02:
        notes.append(f"Прогруз на ничью: коэф {arb.draw.opening}→{arb.draw.current} ({pct(arb.draw.drop)})")
    if arb.volume:
        notes.append(f"Объём ставок: {arb.volume}")
    return lh, la, notes


def _top_scores(lh: float, la: float, k: int = 6) -> list[ScorePred]:
    home, away = _poisson_pmf(lh), _poisson_pmf(la)
    scores = [
        ScorePred(i, j, home[i] * away[j])
        for i in range(min(6, MAX_GOALS) + 1)
        for j in range(min(6, MAX_GOALS) + 1)
    ]
    scores.sort(key=lambda s: s.prob, reverse=True)
    return scores[:k]


def _over_25(lh: float, la: float) -> float:
    home, away = _poisson_pmf(lh), _poisson_pmf(la)
    under = sum(
        home[i] * away[j]
        for i in range(MAX_GOALS + 1)
        for j in range(MAX_GOALS + 1)
        if i + j <= 2
    )
    return 1.0 - under


def _btts(lh: float, la: float) -> float:
    home, away = _poisson_pmf(lh), _poisson_pmf(la)
    return (1.0 - home[0]) * (1.0 - away[0])


def _verdict(match: Match, p1: float, pd: float, p2: float) -> tuple[str, float]:
    """Текстовая рекомендация и уровень уверенности (0..1)."""
    options = [("П1 — победа " + match.home, p1), ("Ничья", pd), ("П2 — победа " + match.away, p2)]
    options.sort(key=lambda x: x[1], reverse=True)
    (top_name, top_p), (_, second_p) = options[0], options[1]
    # уверенность: насколько лидер оторвался + абсолютная вероятность
    confidence = min(1.0, (top_p - second_p) * 1.5 + top_p * 0.5)
    return top_name, confidence


def predict(match: Match) -> Optional[Prediction]:
    """Строит прогноз по матчу. None — если линия 1X2 неполная."""
    o = match.odds
    if not o.complete():
        return None

    p1, pd, p2 = implied_probabilities(o.w1, o.x, o.w2)
    lh, la = fit_lambdas(p1, pd, p2)
    lh, la, notes = _apply_drop(match, lh, la)

    # после корректировки прогрузом пересчитываем вероятности из модели
    ap1, apd, ap2 = _outcome_probs(lh, la)
    best_pick, confidence = _verdict(match, ap1, apd, ap2)

    return Prediction(
        match=match,
        p_home=ap1,
        p_draw=apd,
        p_away=ap2,
        lambda_home=lh,
        lambda_away=la,
        top_scores=_top_scores(lh, la),
        p_over_25=_over_25(lh, la),
        p_btts=_btts(lh, la),
        best_pick=best_pick,
        confidence=confidence,
        notes=notes,
    )
