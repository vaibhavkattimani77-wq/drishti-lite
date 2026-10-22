"""Checks the cache and answer tracking without touching the internet."""

from src import openfda_client
from src.openfda_client import OpenFDAClient


class FakeResponse:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


def test_cache_and_tracking(tmp_path, monkeypatch):
    calls = []

    def fake_get(url, timeout):
        calls.append(url)
        return FakeResponse({"meta": {"results": {"total": 42}}})

    monkeypatch.setattr(openfda_client.requests, "get", fake_get)
    monkeypatch.setattr(openfda_client.config, "SECONDS_BETWEEN_CALLS", 0)
    client = OpenFDAClient(cache_path=str(tmp_path / "cache.sqlite"), api_key="")

    assert client.total(["serious:1"]) == 42     # live
    assert client.total(["serious:1"]) == 42     # same question: from cache
    assert len(calls) == 1
    assert client.answers_used == 2 and client.answers_from_cache == 1
    assert client.oldest_answer_at is not None

    client.reset_tracking()
    assert client.answers_used == 0 and client.oldest_answer_at is None


def test_404_means_zero_results(tmp_path, monkeypatch):
    class NotFound(FakeResponse):
        status_code = 404

    monkeypatch.setattr(openfda_client.requests, "get", lambda url, timeout: NotFound({}))
    monkeypatch.setattr(openfda_client.config, "SECONDS_BETWEEN_CALLS", 0)
    client = OpenFDAClient(cache_path=str(tmp_path / "cache.sqlite"), api_key="")
    assert client.total(['patient.drug.openfda.generic_name:"NO SUCH DRUG"']) == 0
