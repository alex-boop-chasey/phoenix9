"""Checks `proj list --json` against the real projects (read-only)."""
import json
import os
import subprocess
import unittest

PROJ = os.environ.get("PROJ_BIN", "/usr/local/bin/proj")


class ProjListJson(unittest.TestCase):
    def test_list_json(self):
        out = subprocess.run([PROJ, "list", "--json"], capture_output=True, text=True, check=True).stdout
        data = json.loads(out)
        self.assertEqual(data["home"], "home")
        names = [p["name"] for p in data["projects"]]
        self.assertIn("home", names)
        for p in data["projects"]:
            self.assertTrue(os.path.isfile(f"/srv/projects/{p['name']}/CLAUDE.md"))
            self.assertIn(p["state"], ("on", "off"))
            self.assertIsInstance(p["chats"], int)
            self.assertIsInstance(p["last_used"], str)
            if p["state"] == "off":
                self.assertEqual(p["chats"], 0)
        home = next(p for p in data["projects"] if p["name"] == "home")
        self.assertEqual(home["state"], "on")


if __name__ == "__main__":
    unittest.main()
