import json
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from pathlib import Path

try:
    from server import make_server
except ImportError:
    make_server = None


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(make_server, "HTTP implementation required")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / "main.json"
        self.source.write_text(json.dumps({"records": [{"recordId": "T-1", "action": "<img src=x onerror=alert(1)>", "status": "待判断"}]}))
        self.http = make_server(self.root / "test.db", self.source, port=0)
        self.port = self.http.server_port
        self.base = "http://127.0.0.1:" + str(self.port)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)

    def request(self, path, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_host_and_cross_origin_rejected(self):
        self.assertEqual(self.request("/api/bootstrap", headers={"Host": "evil.example"})[0], 403)
        status, raw = self.request("/api/bootstrap")
        token = json.loads(raw)["csrfToken"]
        self.assertEqual(self.request("/api/refresh", {}, {"Origin": "https://evil.example", "Content-Type": "application/json", "X-CSRF-Token": token})[0], 403)
        self.assertEqual(self.request("/api/refresh", {}, {"Origin": self.base, "Content-Type": "application/json"})[0], 403)

    def test_paths_private_and_body_limited(self):
        for path in ["/../store.py", "/%2e%2e/server.py", "/state.sqlite3", "/api/tasks/T-1/sources/99"]:
            self.assertEqual(self.request(path)[0], 404)
        status, raw = self.request("/api/bootstrap")
        h = {"Origin": self.base, "Content-Type": "application/json", "X-CSRF-Token": json.loads(raw)["csrfToken"]}
        self.assertEqual(self.request("/api/refresh", {"x": "a" * 17000}, h)[0], 413)
        self.assertEqual(self.request("/api/refresh", {"unknown": True}, h)[0], 400)

    def test_confirm_roundtrip_and_safe_error(self):
        status, raw = self.request("/api/bootstrap")
        data = json.loads(raw)
        self.assertEqual(len(data["tasks"]), 1)
        h = {"Origin": self.base, "Content-Type": "application/json", "X-CSRF-Token": data["csrfToken"]}
        payload = dict(state="等对方", note="本地记录", expectedRevision=0, reminder=None)
        status, raw = self.request("/api/tasks/T-1/confirm", payload, h)
        self.assertEqual(status, 200, raw)
        t = json.loads(raw)["task"]
        self.assertTrue(t["confirmed"])
        self.assertEqual(t["selectedState"], "等对方")
        self.assertEqual(self.request("/api/tasks/T-1/confirm", payload, h)[0], 409)
        self.assertEqual(self.request("/api/refresh", {}, h)[0], 200)
        data = json.loads(self.request("/api/bootstrap")[1])
        self.assertEqual(data["tasks"][0]["note"], "本地记录")


if __name__ == "__main__":
    unittest.main()

