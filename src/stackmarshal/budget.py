from __future__ import annotations

from dataclasses import dataclass

from .models import BudgetState


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    allowed: bool
    counter: str
    used: int
    limit: int


def consume(budget: BudgetState, counter: str, amount: int = 1) -> BudgetDecision:
    if amount < 0:
        raise ValueError("Budget counters cannot decrease")
    if counter not in budget.limits:
        raise KeyError(f"Unknown budget counter: {counter}")
    current = budget.used.get(counter, 0)
    proposed = current + amount
    limit = budget.limits[counter]
    if proposed > limit:
        return BudgetDecision(False, counter, current, limit)
    budget.used[counter] = proposed
    return BudgetDecision(True, counter, proposed, limit)


def check(budget: BudgetState) -> list[BudgetDecision]:
    return [
        BudgetDecision(budget.used.get(key, 0) <= limit, key, budget.used.get(key, 0), limit)
        for key, limit in budget.limits.items()
    ]
