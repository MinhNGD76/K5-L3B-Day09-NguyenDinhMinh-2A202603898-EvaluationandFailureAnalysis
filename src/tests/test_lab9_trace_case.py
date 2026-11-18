"""Regression test for docs/trace_case.md: C-002@11, ticket trusted over the DB (FM-03)."""
import pytest

pytestmark = pytest.mark.student


def _kinds(shape):
    from lab9.trace_case import investigate

    t = investigate(shape, "C-002", 11)["trial"]
    return t, [e["kind"] for e in t["events"]]


def test_c002_ticket_override_is_first_wrong_step():
    bad, kinds = _kinds("seeded_regression")
    assert kinds.index("model_override") == 2          # event 3, right after the order lookup
    assert bad["snapshot"]["refund_vnd"] == 20000 and not bad["lab8_pass"]


def test_c002_fixed_keeps_db_fact():
    good, kinds = _kinds("fixed")
    assert "model_override" not in kinds
    assert good["snapshot"]["refund_vnd"] == 0 and good["lab8_pass"]
