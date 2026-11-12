"""URL building and extraction-record provenance (no network)."""

from src.openfda_client import ExtractionRecord, Filters, OpenFDAClient, build_url, drug_clause


def test_url_building():
    url = build_url([drug_clause("atorvastatin")] + Filters(serious_only=True, year_from=2020).clauses())
    assert 'patient.drug.openfda.generic_name:"ATORVASTATIN"+AND+serious:1' in url
    assert "receivedate:[20200101+TO+21001231]" in url
    assert url.endswith("limit=1")


def test_age_filter_requires_years_unit():
    clauses = Filters(age_group="Older adult (65+)").clauses()
    assert "patient.patientonsetage:[65+TO+120]" in clauses
    assert "patient.patientonsetageunit:801" in clauses


def test_cache_and_mixed_versions_flagged(tmp_path):
    client = OpenFDAClient(cache_path=str(tmp_path / "c.sqlite"))
    client._save("u1", {"meta": {"last_updated": "2026-10-01"}}, 1.8e9)
    client._save("u2", {"meta": {"last_updated": "2026-10-28"}}, 1.8e9)
    import time
    client.db.execute("UPDATE cache SET fetched_at=?", (time.time(),))
    client.get("u1")
    client.get("u2")
    prov = client.provenance()
    assert prov["queries"] == 2 and prov["from_cache"] == 2
    assert prov["mixed_data_versions"]
    rec = ExtractionRecord.create(client, {"x": 1}, "dme v")
    assert rec.openfda_last_updated.startswith("MIXED")


def test_record_saved_as_json(tmp_path):
    client = OpenFDAClient(cache_path=str(tmp_path / "c.sqlite"))
    rec = ExtractionRecord.create(client, {"x": 1}, "dme v")
    path = rec.save(str(tmp_path / "ext"))
    assert path.exists() and rec.extraction_id in path.name
