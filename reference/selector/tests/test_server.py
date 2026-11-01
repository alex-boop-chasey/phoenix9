"""Tests for selector/server.py, run against tests/fake_proj (never the real proj)."""
import json
import os
import re
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "selector"))
import server  # noqa: E402

FAKE = os.path.join(HERE, "fake_proj")
ORIGIN = "https://test.example"

LIST = {
    "projects": [
        {"name": "grunt", "state": "on", "chats": 2, "last_used": "5m ago"},
        {"name": "home", "state": "on", "chats": 1, "last_used": "2m ago"},
        {"name": "phoenix", "state": "off", "chats": 0, "last_used": "10h ago"},
        {"name": "tiny", "state": "on", "chats": 0, "last_used": "1h ago"},
    ],
    "home": "home",
}

ENV_KEYS = ("PROJ_BIN", "SELECTOR_ORIGIN", "SELECTOR_TIMEOUT",
            "FAKE_PROJ_LIST", "FAKE_PROJ_LOG", "FAKE_PROJ_EXIT", "FAKE_PROJ_SLEEP")


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.saved_env = {k: os.environ.get(k) for k in ENV_KEYS}
        self.tmp = tempfile.TemporaryDirectory()
        self.list_file = os.path.join(self.tmp.name, "list.json")
        self.log_file = os.path.join(self.tmp.name, "log")
        with open(self.list_file, "w") as f:
            json.dump(LIST, f)
        os.environ.update({
            "PROJ_BIN": FAKE,
            "SELECTOR_ORIGIN": ORIGIN,
            "FAKE_PROJ_LIST": self.list_file,
            "FAKE_PROJ_LOG": self.log_file,
        })
        for k in ("SELECTOR_TIMEOUT", "FAKE_PROJ_EXIT", "FAKE_PROJ_SLEEP"):
            os.environ.pop(k, None)

        server.Handler.log_message = lambda *a: None  # keep test output quiet
        self.httpd = server.make_server(0)  # port 0 = any free port
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05},
                         daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.tmp.cleanup()
        for k, v in self.saved_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    # ---- helpers ----
    def request(self, method, path, body=None, headers=None, raw=None):
        if headers is None:
            headers = {"X-Selector": "1", "Origin": ORIGIN, "Content-Type": "application/json"}
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode(), r.headers.get("Content-Type", "")
        except urllib.error.HTTPError as e:
            with e:
                return e.code, e.read().decode(), e.headers.get("Content-Type", "")

    def post(self, path, body=None, **kw):
        status, text, _ = self.request("POST", path, body, **kw)
        return status, json.loads(text)

    def calls(self):
        """Every argv the fake was started with, in order (list calls included)."""
        if not os.path.exists(self.log_file):
            return []
        with open(self.log_file) as f:
            return [json.loads(line[4:]) for line in f if line.startswith("run ")]

    def actions(self):
        return [c for c in self.calls() if c[:1] != ["list"]]

    # ---- reading ----
    def test_list_passthrough(self):
        status, text, ctype = self.request("GET", "/api/projects")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ctype)
        self.assertEqual(json.loads(text), LIST)
        self.assertEqual(self.calls(), [["list", "--json"]])

    def test_list_failure_is_502(self):
        os.environ["FAKE_PROJ_LIST"] = os.path.join(self.tmp.name, "missing.json")
        status, text, _ = self.request("GET", "/api/projects")
        self.assertEqual(status, 502)
        body = json.loads(text)
        self.assertFalse(body["ok"])
        self.assertTrue(body["message"])

    def test_list_junk_is_502(self):
        with open(self.list_file, "w") as f:
            f.write("this is not json")
        status, text, _ = self.request("GET", "/api/projects")
        self.assertEqual(status, 502)
        self.assertFalse(json.loads(text)["ok"])

    def test_index_page(self):
        status, text, ctype = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        self.assertIn("<title>", text)
        # served under /proxy/8090/, so no absolute /api URLs
        self.assertNotRegex(text, r"""["'`(]/api""")
        self.assertIn("api/projects", text)
        self.assertIn("X-Selector", text)
        self.assertIn("https://files.rebirthwebdesign.com.au/?folder=/srv/projects/", text)

    def test_unknown_path_404(self):
        status, _, _ = self.request("GET", "/nope")
        self.assertEqual(status, 404)

    # ---- open ----
    def test_open(self):
        status, body = self.post("/api/open", {"name": "phoenix"})
        self.assertEqual(status, 200)
        self.assertTrue(body["ok"])
        self.assertIn("phoenix is on", body["message"])
        self.assertEqual(self.actions(), [["open", "phoenix"]])

    def test_open_unknown_project(self):
        status, body = self.post("/api/open", {"name": "ghost"})
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertIn("no project 'ghost'", body["message"])
        self.assertEqual(self.actions(), [])

    def test_open_bad_name_never_runs_proj(self):
        for name in ["../etc", "Phoenix", "a b", "-rf", "", 5, None]:
            status, body = self.post("/api/open", {"name": name})
            self.assertEqual(status, 400, name)
            self.assertFalse(body["ok"])
        self.assertEqual(self.calls(), [])

    def test_proj_failure_passes_message(self):
        os.environ["FAKE_PROJ_EXIT"] = "1"
        status, body = self.post("/api/open", {"name": "phoenix"})
        self.assertEqual(status, 200)
        self.assertFalse(body["ok"])
        self.assertIn("proj: fake failure", body["message"])

    # ---- close: gone (projects are always on) ----
    def test_close_is_not_an_action(self):
        status, body = self.post("/api/close", {"name": "tiny"})
        self.assertEqual(status, 404)
        self.assertEqual(self.calls(), [])

    # ---- new ----
    def test_new_without_repo(self):
        status, body = self.post("/api/new", {"name": "shop-site"})
        self.assertTrue(body["ok"])
        self.assertIn("created", body["message"])
        self.assertEqual(self.actions(), [["new", "shop-site"]])

    def test_new_with_repo(self):
        status, body = self.post("/api/new", {"name": "shop", "repo": "rebirth-wd/shop.site_1"})
        self.assertTrue(body["ok"])
        self.assertEqual(self.actions(), [["new", "shop", "--repo", "rebirth-wd/shop.site_1"]])

    def test_new_empty_repo_means_none(self):
        self.post("/api/new", {"name": "shop", "repo": ""})
        self.assertEqual(self.actions(), [["new", "shop"]])

    def test_new_bad_name_or_repo(self):
        bad = [
            {"name": "Bad"}, {"name": "-x"}, {"name": "a" * 42}, {"name": "x;rm"}, {},
            {"name": "ok", "repo": "noslash"}, {"name": "ok", "repo": "a/b/c"},
            {"name": "ok", "repo": "--upload-pack=x/y z"}, {"name": "ok", "repo": 7},
        ]
        for b in bad:
            status, body = self.post("/api/new", b)
            self.assertEqual(status, 400, b)
            self.assertFalse(body["ok"])
        self.assertEqual(self.calls(), [])

    def test_timeout(self):
        os.environ["SELECTOR_TIMEOUT"] = "0.5"
        os.environ["FAKE_PROJ_SLEEP"] = "5"
        start = time.monotonic()
        status, body = self.post("/api/new", {"name": "slow"})
        self.assertLess(time.monotonic() - start, 4)
        self.assertFalse(body["ok"])
        self.assertIn("timed out", body["message"])

    # ---- request checks ----
    def test_missing_header_403(self):
        status, body = self.post("/api/open", {"name": "phoenix"},
                                 headers={"Origin": ORIGIN, "Content-Type": "application/json"})
        self.assertEqual(status, 403)
        self.assertFalse(body["ok"])
        self.assertEqual(self.calls(), [])

    def test_foreign_origin_403(self):
        for origin in ("https://evil.example", None):
            headers = {"X-Selector": "1", "Content-Type": "application/json"}
            if origin:
                headers["Origin"] = origin
            status, body = self.post("/api/open", {"name": "phoenix"}, headers=headers)
            self.assertEqual(status, 403)
        self.assertEqual(self.calls(), [])

    def test_not_json_400(self):
        status, body = self.post("/api/open", raw=b"name=phoenix")
        self.assertEqual(status, 400)
        self.assertFalse(body["ok"])
        self.assertNotIn("Traceback", body["message"])

    def test_json_not_object_400(self):
        status, body = self.post("/api/open", raw=b'["phoenix"]')
        self.assertEqual(status, 400)

    def test_huge_body_400(self):
        raw = json.dumps({"name": "phoenix", "pad": "x" * 11000}).encode()
        status, body = self.post("/api/open", raw=raw)
        self.assertEqual(status, 400)
        self.assertEqual(self.calls(), [])

    def test_get_on_action_does_nothing(self):
        status, _, _ = self.request("GET", "/api/open?name=phoenix")
        self.assertEqual(status, 404)
        self.assertEqual(self.calls(), [])

    def test_two_actions_run_one_at_a_time(self):
        os.environ["FAKE_PROJ_SLEEP"] = "0.4"
        results = []
        threads = [threading.Thread(target=lambda n=n: results.append(self.post("/api/open", {"name": n})))
                   for n in ("phoenix", "tiny")]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(results), 2)
        self.assertTrue(all(body["ok"] for _, body in results))
        # each action must finish ("end") before the next one starts ("run")
        with open(self.log_file) as f:
            lines = [l.split(" ", 1) for l in f.read().splitlines()]
        opens = [(kind, json.loads(argv)) for kind, argv in lines if json.loads(argv)[0] == "open"]
        self.assertEqual([k for k, _ in opens], ["run", "end", "run", "end"])
        self.assertEqual(opens[0][1], opens[1][1])
        self.assertEqual(opens[2][1], opens[3][1])
        self.assertEqual({tuple(opens[0][1]), tuple(opens[2][1])},
                         {("open", "phoenix"), ("open", "tiny")})


class NoShellTest(unittest.TestCase):
    def test_no_shell_true(self):
        with open(os.path.join(HERE, "..", "selector", "server.py")) as f:
            self.assertIsNone(re.search(r"shell\s*=\s*True", f.read()))


if __name__ == "__main__":
    unittest.main()
