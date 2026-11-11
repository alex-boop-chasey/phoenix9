"""Tests for the typed repair op that raises a run's max tries."""
import pytest
from test_repair_ops_skip import applied, make

from phoenix9.ops import common, repair as ops


def test_raise_max_tries_applies_and_records_who(tmp_path):
    r = make(tmp_path)
    out = ops.raise_max_tries(r["run"], 5, who="agent")
    assert not out.get("rolled_back"), out
    assert applied()[-1]["who"] == "agent" and applied()[-1]["steps"] == ["set max_tries=5 for this run"]


@pytest.mark.parametrize("tries", [1, 3, 11, 99])
def test_not_higher_or_too_high_refused(tmp_path, tries):
    r = make(tmp_path)
    with pytest.raises(common.Conflict):
        ops.raise_max_tries(r["run"], tries)
    assert not applied()


@pytest.mark.parametrize("tries", [True, "5", 4.5, None])
def test_not_a_number_refused(tmp_path, tries):
    r = make(tmp_path)
    with pytest.raises(common.OpsError):
        ops.raise_max_tries(r["run"], tries)
