"""Synthetic upstream for the isolated CI proxy check; never runs in production."""

from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/api/v1/broken":
            self.close_connection = True
            return
        code = 404 if path == "/api/v1/auth/entra/callback/" else int(path.rsplit("/", 1)[-1])
        self.send_response(code)
        self.send_header("Content-Security-Policy", "default-src *")
        self.end_headers()
        self.wfile.write(b'{"synthetic":true}')

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
