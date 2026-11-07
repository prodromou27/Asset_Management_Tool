"""Exercise the synthetic callback fixture without Docker or an identity provider."""

import http.client
import threading
import unittest
from http.server import HTTPServer

from upstream import Handler


class UpstreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def request(self, path):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        self.addCleanup(connection.close)
        connection.request("GET", path)
        return connection.getresponse()

    def test_callback_query_returns_fixture_response_without_crashing(self):
        response = self.request("/api/v1/auth/entra/callback/?code=fixture&state=fixture")
        self.assertEqual(response.status, 404)
        self.assertEqual(response.getheader("Content-Security-Policy"), "default-src *")
        self.assertEqual(response.read(), b'{"synthetic":true}')

    def test_status_fixture_still_supplies_requested_code(self):
        for code in (200, 401, 403, 404, 500):
            response = self.request(f"/api/v1/status/{code}")
            self.assertEqual(response.status, code)
            response.read()

    def test_broken_fixture_still_closes_upstream_connection(self):
        with self.assertRaises(http.client.RemoteDisconnected):
            self.request("/api/v1/broken")
