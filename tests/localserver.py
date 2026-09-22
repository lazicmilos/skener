"""Lažni sajt na `localhost` za integracione testove.

Fetcher i browser sloj se ne mogu testirati nad pravim sajtovima: test nad
`mensa.rs` zavisi od toga da li je Mensa jutros online (§2.1). Ovde je sajt koji
je namerno pokvaren na tačno određene načine, pa su testovi offline i
deterministički.
"""

from __future__ import annotations

import gzip
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@dataclass
class Response:
    body: bytes = b""
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0.0


def html(title: str, *, body: str = "", head: str = "") -> bytes:
    return (
        f"<!doctype html><html lang='sr'><head><title>{title}</title>{head}</head>"
        f"<body><h1>{title}</h1><p>Sadržaj stranice o uslugama i cenama, sa dijakriticima "
        f"čćšžđ, dovoljno dug da jezička heuristika bude pouzdana. {'Tekst. ' * 60}</p>"
        f"{body}</body></html>"
    ).encode()


SITEMAP_INDEX = (
    b'<?xml version="1.0"?><sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    b"<sitemap><loc>{base}/sitemap-1.xml</loc></sitemap></sitemapindex>"
)
SITEMAP_URLS = (
    b'<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
    b"<url><loc>{base}/usluge</loc></url>"
    b"<url><loc>{base}/o-nama</loc></url>"
    b"<url><loc>{base}/kontakt</loc></url>"
    b"<url><loc>{base}/blog/prvi</loc></url>"
    b"<url><loc>{base}/blog/drugi</loc></url>"
    b"<url><loc>{base}/tajno/nesto</loc></url>"
    b"</urlset>"
)

ROBOTS = b"""User-agent: *
Disallow: /tajno
Sitemap: {base}/sitemap.xml
"""


class FakeSite:
    """Servira unapred pripremljene odgovore i broji šta je traženo."""

    def __init__(
        self,
        *,
        soft404: bool = False,
        extra: dict[str, Response | Callable[[], Response]] | None = None,
    ) -> None:
        self.soft404 = soft404
        self.extra = extra or {}
        self.requests: list[str] = []
        self.concurrent_peak = 0
        self._in_flight = 0
        self._lock = threading.Lock()
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    # ------------------------------------------------------------------ server
    @property
    def base_url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def __enter__(self) -> FakeSite:
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)

    def paths(self) -> list[str]:
        return list(self.requests)

    # ----------------------------------------------------------------- content
    def route(self, path: str) -> Response:
        base = self.base_url.encode()
        routes: dict[str, Response] = {
            "/": Response(
                html(
                    "Početna",
                    head=(
                        f"<link rel='canonical' href='{self.base_url}/'>"
                        "<meta name='description' content='Opis početne strane.'>"
                        "<meta property='og:title' content='OG naslov'>"
                        "<meta property='og:description' content='OG opis'>"
                        "<meta property='og:image' content='/slika.jpg'>"
                    ),
                    body="<a href='/usluge'>usluge</a><a href='/o-nama'>o nama</a>",
                )
            ),
            "/robots.txt": Response(ROBOTS.replace(b"{base}", base), headers={"content-type": "text/plain"}),
            "/sitemap.xml": Response(
                SITEMAP_INDEX.replace(b"{base}", base), headers={"content-type": "application/xml"}
            ),
            "/sitemap-1.xml": Response(
                SITEMAP_URLS.replace(b"{base}", base), headers={"content-type": "application/xml"}
            ),
            "/usluge": Response(html("Usluge")),
            "/o-nama": Response(html("O nama")),
            "/kontakt": Response(html("Kontakt")),
            "/blog/prvi": Response(html("Prvi tekst")),
            "/blog/drugi": Response(html("Drugi tekst")),
            "/tajno/nesto": Response(html("Tajna strana")),
        }
        routes.update(self.extra)

        if path in routes:
            found = routes[path]
            return found() if callable(found) else found
        if self.soft404:
            # Sajt koji na nepostojeću adresu vraća početnu — tačno §5.2.
            return routes["/"]
        return Response(b"<html><h1>404</h1></html>", status=404)

    # ----------------------------------------------------------------- handler
    def _handler(self):
        site = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self) -> None:  # noqa: N802 — ime traži biblioteka
                with site._lock:
                    site.requests.append(self.path)
                    site._in_flight += 1
                    site.concurrent_peak = max(site.concurrent_peak, site._in_flight)
                try:
                    response = site.route(self.path)
                    if response.delay:
                        time.sleep(response.delay)
                    body = response.body
                    headers = dict(response.headers)
                    if headers.get("content-encoding") == "gzip":
                        body = gzip.compress(body)
                    self.send_response(response.status)
                    for key, value in headers.items():
                        self.send_header(key, value)
                    self.send_header("Content-Length", str(len(body)))
                    if "content-type" not in {k.lower() for k in headers}:
                        self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(body)
                finally:
                    with site._lock:
                        site._in_flight -= 1

            def log_message(self, *_args: object) -> None:
                """Tišina — inače testovi ispisuju pristupni log."""

        return Handler
