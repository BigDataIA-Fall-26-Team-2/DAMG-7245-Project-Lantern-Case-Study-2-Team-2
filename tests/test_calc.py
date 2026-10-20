"""Unit tests for the CS2 Part 6 calculators (src/calc/).

The brief requires tests for LTM, EV and a sign-convention case; we also test
the n.m. rules, calc_id determinism and weakest-tier inheritance, because the
comps table and every cited answer depend on them.
"""
import sys
from pathlib import Path

import pytest

# Repo root on the path so `src.calc` imports resolve (same pattern as the other tests)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.calc.core import FactRef, make_calc
from src.calc.metrics import ebitda, growth, ltm, margin
from src.calc.valuation import enterprise_value, market_cap, multiple, net_debt


def F(fid, value, tier=1, unit="USD"):
    return FactRef(fid, value, tier, unit)


# ---- LTM -----------------------------------------------------------------
def test_ltm_latest_fy_plus_ytd_minus_prior_ytd():
    assert ltm(F("fy", 100), F("ytd", 60), F("pytd", 50)).value == 110


def test_ltm_sign_convention_prior_ytd_loss_adds_back():
    # Subtracting a prior-year loss must INCREASE LTM: 100 + 60 - (-20) = 180
    assert ltm(F("fy", 100), F("ytd", 60), F("pytd", -20)).value == 180


# ---- EBITDA / growth / margin ---------------------------------------------
def test_ebitda_sign_convention_negative_d_and_a_still_adds():
    assert ebitda(F("oi", 30), F("da", -5)).value == 35


def test_growth_basic():
    assert growth(F("c", 110), F("p", 100)).value == pytest.approx(0.10)


def test_growth_from_zero_is_nm():
    g = growth(F("c", 110), F("p", 0))
    assert g.value is None and "n.m." in g.note


def test_growth_from_negative_base_uses_abs():
    # -50 -> -25 is an improvement, so growth must be positive (+50%)
    assert growth(F("c", -25), F("p", -50)).value == pytest.approx(0.50)


def test_margin_nonpositive_revenue_is_nm():
    assert margin(F("e", 20), F("r", 0), "ebitda").value is None
    assert margin(F("e", 20), F("r", -10), "ebitda").value is None


# ---- EV ------------------------------------------------------------------
def _ev(debt_value=300, sti=None):
    mc = market_cap(F("price", 10, unit="USD/share"), F("shares", 100, unit="shares"))
    nd = net_debt([F("debt", debt_value)], F("cash", 100), sti)
    return mc, nd, enterprise_value(mc, nd)


def test_ev_market_cap_plus_net_debt_with_trace():
    mc, nd, ev = _ev()
    assert (mc.value, nd.value, ev.value) == (1000, 200, 1200)
    assert dict(ev.inputs) == {"market_cap": mc.calc_id, "net_debt": nd.calc_id}
    assert dict(mc.inputs) == {"price": "price", "shares": "shares"}


def test_ev_sign_convention_negative_debt_still_increases_ev():
    assert _ev(debt_value=-300)[2].value == 1200


def test_ev_policy_subtracts_short_term_investments():
    assert _ev(sti=F("sti", 50))[2].value == 1150


def test_multiple_negative_ebitda_is_nm_not_negative():
    ev = _ev()[2]
    assert multiple(ev, F("ebitda", 100), "ebitda").value == pytest.approx(12.0)
    assert multiple(ev, F("ebitda", -50), "ebitda").value is None


# ---- receipts: calc_id and tier --------------------------------------------
def test_calc_id_is_deterministic_and_input_sensitive():
    a = make_calc("m", 1.0, "x", {"n": F("f1", 1)}, "n")
    b = make_calc("m", 1.0, "x", {"n": F("f1", 1)}, "n")
    c = make_calc("m", 1.0, "x", {"n": F("f2", 1)}, "n")
    assert a.calc_id == b.calc_id != c.calc_id


def test_derived_tier_inherits_weakest_input():
    assert margin(F("e", 20, tier=4), F("r", 100, tier=1), "ebitda").tier == 4


# ---- safety ----------------------------------------------------------------
def test_mixed_units_are_refused():
    with pytest.raises(ValueError):
        ltm(F("fy", 100), F("ytd", 60, unit="EUR"), F("pytd", 50))
    with pytest.raises(ValueError):
        market_cap(F("price", 10, unit="USD"), F("shares", 100, unit="shares"))
