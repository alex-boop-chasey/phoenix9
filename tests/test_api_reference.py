"""Reference material over the API: upload round trip, size cap, bad names, links and the agent's limits."""
import base64

from phoenix9 import paths
from test_agentaccess import HEADERS, as_agent
from test_api_server import POST_HEADERS, api, dist, make_project  # noqa: F401  (fixtures)

URL = "/api/projects/alpha/reference"


def upload(api, name, data=b"a{color:red}", **extra):
    return api(URL + "/files", "POST", POST_HEADERS,
               {"filename": name, "data_base64": base64.b64encode(data).decode(), **extra})


def test_upload_round_trip(api):
    make_project("alpha")
    status, body = upload(api, "brand.css")
    assert status == 200 and body["data"]["name"] == "brand.css"
    assert (paths.projects() / "alpha" / "notes" / "reference" / "brand.css").read_bytes() == b"a{color:red}"
    listed = api(URL)[1]["data"]
    assert [f["name"] for f in listed["files"]] == ["brand.css"] and listed["links"] == []
    status, body = api(URL + "/files/brand.css", "DELETE", POST_HEADERS)
    assert status == 200 and body["data"]["removed"] is True
    assert api(URL)[1]["data"]["files"] == []


def test_big_upload_is_allowed_but_oversize_is_refused(api):
    make_project("alpha")
    assert upload(api, "big.txt", b"x" * (3 * 1024 * 1024))[0] == 200
    try:
        status, body = upload(api, "huge.txt", b"x" * (7 * 1024 * 1024))
    except OSError:   # the server hangs up without reading a body it refuses, so the sender may see a broken pipe
        return
    assert status == 400 and "too big" in body["message"]


def test_other_routes_keep_the_small_cap(api):
    make_project("alpha")
    status, body = api(URL + "/links", "POST", POST_HEADERS, {"text": "x" * (100 * 1024)})
    assert status == 400 and "too big" in body["message"]


def test_bad_name_and_bad_data_are_refused(api):
    make_project("alpha")
    assert upload(api, "evil.exe")[0] == 400
    assert upload(api, "...")[0] == 400
    assert api(URL + "/files", "POST", POST_HEADERS, {"filename": "a.css", "data_base64": "!!"})[0] == 400
    assert api(URL + "/files/..%2Fx.css", "DELETE", POST_HEADERS)[0] == 400
    assert api(URL + "/files", "POST", {"Content-Type": "application/json"}, {"filename": "a.css"})[0] == 403


def test_links_round_trip(api):
    make_project("alpha")
    status, body = api(URL + "/links", "POST", POST_HEADERS, {"text": "https://example.com/a | brand"})
    assert status == 200 and len(body["data"]["added"]) == 1
    assert api(URL)[1]["data"]["links"] == [{"url": "https://example.com/a", "note": "brand"}]
    status, _ = api(URL + "/links", "DELETE", POST_HEADERS, {"url": "https://example.com/a"})
    assert status == 200 and api(URL)[1]["data"]["links"] == []
    assert api(URL + "/links", "DELETE", POST_HEADERS, {"url": "https://example.com/a"})[0] == 400


def test_agent_may_list_and_remove_but_not_add(api):
    make_project("alpha")
    upload(api, "brand.css")
    as_agent(api)
    assert api(URL, headers=HEADERS)[0] == 200
    body = {"filename": "x.css", "data_base64": base64.b64encode(b"a{}").decode()}
    assert api(URL + "/files", "POST", HEADERS, body)[0] == 403
    assert api(URL + "/links", "POST", HEADERS, {"text": "https://example.com"})[0] == 403
    assert api(URL + "/files/remove", "POST", HEADERS, {"filename": "brand.css"})[0] == 200
