"""EMA DME list loads with its version and matches FAERS PTs case-insensitively."""

from src.dme import load_dme


def test_dme_list_loads_62_terms_with_version():
    dme = load_dme()
    assert len(dme) == 62
    assert "EMA/326038/2020" in dme.version


def test_case_insensitive_exact_match():
    dme = load_dme()
    assert dme.contains("RHABDOMYOLYSIS")
    assert dme.contains("Stevens-Johnson syndrome")
    assert not dme.contains("RHABDO")            # exact, not partial
    assert not dme.contains("NAUSEA")
