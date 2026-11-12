"""Exploratory priority score: breakdown adds up, bands, every factor explained (Gate 2)."""

from src.label_check import LABELLED, NOT_FOUND, POSSIBLY, UNAVAILABLE
from src.priority import SeriousnessCounts, band, fetch_seriousness, score
from src.openfda_client import Filters
from src.trend import INCREASING, NO_CHANGE


def test_maximum_is_ten_and_breakdown_adds_up():
    r = score(NOT_FOUND, True, SeriousnessCounts(10, 8, 1), 3, INCREASING)
    assert r.total == 10 and r.band == "Higher"
    assert sum(f.points for f in r.factors) == r.total
    assert sum(f.max_points for f in r.factors) == 10
    assert all(f.evidence and f.rationale for f in r.factors)


def test_labelled_common_event_scores_low():
    r = score(LABELLED, False, SeriousnessCounts(100, 20, 0), 3, NO_CHANGE)
    assert r.total == 2 and r.band == "Lower"


def test_possibly_labelled_and_two_rules():
    r = score(POSSIBLY, False, SeriousnessCounts(10, 6, 0), 2, NO_CHANGE)
    # +1 possibly labelled, +1 >50% serious, +1 two rules
    assert r.total == 3


def test_seriousness_threshold_is_more_than_half():
    assert score(LABELLED, False, SeriousnessCounts(10, 5, 0), 0, None).total == 0   # exactly 50%
    assert score(LABELLED, False, SeriousnessCounts(10, 6, 0), 0, None).total == 1


def test_unavailable_label_gets_no_points_but_says_check_manually():
    r = score(UNAVAILABLE, False, SeriousnessCounts(0, 0, 0), 0, None)
    assert r.total == 0
    assert "check manually" in r.factors[0].evidence
    assert "not computable" in r.factors[3].evidence


def test_bands():
    assert [band(n) for n in (0, 3, 4, 6, 7, 10)] == ["Lower", "Lower", "Medium", "Medium", "Higher", "Higher"]


def test_fetch_seriousness_queries():
    class C:
        def __init__(self): self.calls = []
        def total(self, search):
            self.calls.append(search)
            if "seriousnessdeath:1" in search: return 2
            if "serious:1" in search: return 30
            return 50
    c = C()
    s = fetch_seriousness(c, "atorvastatin", "RHABDOMYOLYSIS", Filters(sex="Female"))
    assert (s.reports, s.serious, s.fatal) == (50, 30, 2)
    assert all("patient.patientsex:2" in q for q in c.calls)       # same filters as the screen
