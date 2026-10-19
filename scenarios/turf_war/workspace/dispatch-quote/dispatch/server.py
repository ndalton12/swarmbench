import argparse
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .catalogue import load, zones
from .pricing import BadQuote, quote

CATALOGUE = load()
ZONES = zones()
MAX_BODY = 65536


class Handler(BaseHTTPRequestHandler):
    server_version = "DispatchHTTP/1.8"

    def reply(self, status, body):
        data = json.dumps(body, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == "/healthz":
            return self.reply(200, {"status": "ok", "service": "dispatch-quote",
                                    "implementation": "python", "api_version": 1})
        if url.path == "/v1/zones":
            return self.reply(200, {"zones": ZONES})
        if url.path == "/v1/catalogue":
            params = parse_qs(url.query, keep_blank_values=True)
            query = params.get("q", [""])[0].lower()
            try:
                raw_limit = params.get("limit", ["50"])[0]
                if not raw_limit.isascii() or not raw_limit.isdecimal():
                    raise ValueError
                limit = int(raw_limit)
                if not 1 <= limit <= 100:
                    raise ValueError
            except ValueError:
                return self.reply(400, {"error": "invalid_limit"})
            rows = [{"sku": sku, **item} for sku, item in sorted(CATALOGUE.items())
                    if item["active"] and query in (sku + " " + item["name"]).lower()]
            return self.reply(200, {"items": rows[:limit], "total": len(rows)})
        if url.path.startswith("/v1/catalogue/"):
            sku = url.path[len("/v1/catalogue/"):]
            if sku in CATALOGUE:
                return self.reply(200, {"sku": sku, **CATALOGUE[sku]})
        self.reply(404, {"error": "not_found"})

    def do_POST(self):
        if urlsplit(self.path).path != "/v1/quote":
            return self.reply(404, {"error": "not_found"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.reply(400, {"error": "invalid_json"})
        if length < 0:
            return self.reply(400, {"error": "invalid_json"})
        if length > MAX_BODY:
            return self.reply(413, {"error": "body_too_large"})
        try:
            body = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError):
            return self.reply(400, {"error": "invalid_json"})
        try:
            result = quote(body, CATALOGUE, ZONES)
        except BadQuote as e:
            return self.reply(400, {"error": e.code})
        self.reply(200, result)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8080")))
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("dispatch-quote listening on 127.0.0.1:%d" % server.server_port, flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
