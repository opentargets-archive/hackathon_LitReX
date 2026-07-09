import requests

from litrex.data_sources.gwas.abstracts import fetch_abstract_europepmc


class FakeResp:
    def __init__(self, status, json_data=None, text=""):
        self.status_code = status
        self._json = json_data
        self.text = text

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


class FakeSession:
    def __init__(self, resp):
        self._resp = resp

    def get(self, url, **kw):
        return self._resp


def test_europepmc_parses_abstract():
    payload = {"resultList": {"result": [{"abstractText": "TCF7L2 is linked to type 2 diabetes."}]}}
    s = FakeSession(FakeResp(200, payload))
    assert fetch_abstract_europepmc("222", "http://e", s) == "TCF7L2 is linked to type 2 diabetes."


def test_europepmc_missing_returns_none():
    s = FakeSession(FakeResp(200, {"resultList": {"result": []}}))
    assert fetch_abstract_europepmc("999", "http://e", s) is None
