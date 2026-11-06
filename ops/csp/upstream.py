"""Synthetic upstream for the isolated CI proxy check; never runs in production."""

from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/v1/broken":
            self.close_connection = True
            return
        code = int(self.path.rsplit("/", 1)[-1])
        self.send_response(code)
        self.send_header("Content-Security-Policy", "default-src *")
        self.end_headers()
        self.wfile.write(b'{"synthetic":true}')

    def log_message(self, *args):
        pass


HTTPServer(("0.0.0.0", 8000), Handler).serve_forever()
