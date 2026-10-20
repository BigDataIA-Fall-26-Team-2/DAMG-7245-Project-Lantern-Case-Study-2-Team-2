"""Valuation calculators: market cap, net debt, EV and multiples (CS2 Part 6).

Policies we commit to (the brief asks us to state them):
  - Market cap = price (from the instructor price snapshot) x shares
    (dei:EntityCommonStockSharesOutstanding). The price is a FactRef with its
    own id and citation, so the EV trace never ends at an unsourced number.
  - Net debt = total debt - cash - short-term investments.
    Short-term investments (current marketable securities) are subtracted
    because they convert to cash within a year; long-term marketable
    securities are NOT subtracted. Callers pass short_term_investments=None
    to switch this off (the switch lives in params.yaml, comps.ev.*).
  - EV = market cap + net debt + preferred stock + non-controlling interest.
  - Sign convention: debt, cash, investments, preferred and NCI are balance
    sheet magnitudes, so we use their absolute values. A filer that stores
    debt as a negative number must still make EV larger, never smaller.
  - Multiples: EV / denominator; denominator <= 0 -> n.m. (value=None).
"""
from __future__ import annotations

from .core import Calc, FactRef, Operand, make_calc

PRICE_UNIT = "USD/share"
SHARES_UNIT = "shares"


def market_cap(price: FactRef, shares: FactRef) -> Calc:
    if price.unit != PRICE_UNIT or shares.unit != SHARES_UNIT:
        raise ValueError(f"market_cap needs {PRICE_UNIT} x {SHARES_UNIT}, "
                         f"got {price.unit} x {shares.unit}")
    return make_calc("market_cap", price.value * shares.value, "USD",
                     {"price": price, "shares": shares}, "price * shares")


def net_debt(debts: list[Operand], cash: Operand,
             short_term_investments: Operand | None = None) -> Calc:
    if not debts:
        raise ValueError("net_debt needs at least one debt line (use a zero fact if none)")
    inputs: dict[str, Operand] = {f"debt_{i}": d for i, d in enumerate(debts, 1)}
    inputs["cash"] = cash
    value = sum(abs(d.value) for d in debts) - abs(cash.value)
    formula = "sum(|debt_i|) - |cash|"
    if short_term_investments is not None:
        inputs["short_term_investments"] = short_term_investments
        value -= abs(short_term_investments.value)
        formula += " - |short_term_investments|"
    return make_calc("net_debt", value, "USD", inputs, formula)


def enterprise_value(mcap: Calc, ndebt: Calc,
                     preferred: Operand | None = None,
                     nci: Operand | None = None) -> Calc:
    inputs: dict[str, Operand] = {"market_cap": mcap, "net_debt": ndebt}
    value = mcap.value + ndebt.value
    formula = "market_cap + net_debt"
    for role, op in (("preferred", preferred), ("nci", nci)):
        if op is not None:
            inputs[role] = op
            value += abs(op.value)
            formula += f" + |{role}|"
    return make_calc("enterprise_value", value, "USD", inputs, formula)


def multiple(ev: Calc, denominator: Operand, name: str) -> Calc:
    inputs = {"ev": ev, "denominator": denominator}
    formula = "ev / denominator"
    if denominator.value is None or denominator.value <= 0:
        return make_calc(f"ev_{name}", None, "x", inputs, formula,
                         note=f"n.m.: {name} is zero, negative or n.m.")
    return make_calc(f"ev_{name}", ev.value / denominator.value, "x",
                     inputs, formula)
