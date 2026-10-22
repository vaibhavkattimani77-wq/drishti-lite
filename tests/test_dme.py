"""Checks the EMA DME list file and matching."""

from src.dme import dme_list_version, dme_terms, is_dme


def test_list_has_62_unique_terms():
    assert len(dme_terms()) == 62


def test_matching_is_case_insensitive():
    assert is_dme("RHABDOMYOLYSIS")            # FAERS style
    assert is_dme("Stevens-Johnson syndrome")  # EMA style
    assert is_dme("REYE'S SYNDROME")
    assert not is_dme("NAUSEA")
    assert not is_dme("RHABDO")                # exact match only


def test_version_string():
    assert dme_list_version() == "EMA DME list, EMA/326038/2020, dated 15 June 2020"
