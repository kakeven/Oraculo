"""Interface HTTP local para ler e aprovar itens do catálogo."""

from __future__ import annotations

import argparse
import json
import re
import secrets
import threading
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .pipeline import choose_pdf
from .review_store import current_rows, decisions, fingerprint, set_decision, set_text, state


WEB_DIR = Path(__file__).parent / "web"
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def make_handler(system_dir: Path, port: int, token: str):
    write_lock = threading.Lock()
    origin = f"http://127.0.0.1:{port}"

    class Handler(BaseHTTPRequestHandler):
        def _headers(self, status: int, content_type: str, length: int) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(length))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; script-src 'self'; style-src 'self'; "
                             "connect-src 'self'; frame-src 'self'; img-src 'self' data:; "
                             "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            self.end_headers()

        def _send(self, status: int, data: bytes, content_type: str) -> None:
            self._headers(status, content_type, len(data))
            self.wfile.write(data)

        def _json(self, status: int, value: object) -> None:
            self._send(status, json.dumps(value, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _valid_host(self) -> bool:
            return self.headers.get("Host") == f"127.0.0.1:{port}"

        def _valid_token(self) -> bool:
            supplied = self.headers.get("X-Oraculo-Token", "")
            return bool(supplied) and secrets.compare_digest(supplied, token)

        def do_GET(self) -> None:
            if not self._valid_host():
                self._json(HTTPStatus.FORBIDDEN, {"error": "Host inválido."})
                return
            route = urllib.parse.urlsplit(self.path).path
            if route == "/":
                page = (WEB_DIR / "review.html").read_text(encoding="utf-8")
                self._send(HTTPStatus.OK, page.replace("__SESSION_TOKEN__", token).encode("utf-8"),
                           "text/html; charset=utf-8")
            elif route in {"/review.css", "/review.js"}:
                kind = "text/css" if route.endswith(".css") else "text/javascript"
                self._send(HTTPStatus.OK, (WEB_DIR / route.lstrip("/")).read_bytes(),
                           f"{kind}; charset=utf-8")
            elif route == "/api/catalog":
                if not self._valid_token():
                    self._json(HTTPStatus.FORBIDDEN, {"error": "Sessão inválida."})
                    return
                try:
                    rows = current_rows(system_dir)
                    latest = decisions(system_dir)
                    self._json(HTTPStatus.OK, [{
                        "id": row["id"], "type": row["type"], "name": row["name"],
                        "page_start": row["page_start"], "page_end": row["page_end"],
                        "state": state(row, latest), "fingerprint": fingerprint(row),
                        "edited": row["edited"],
                    } for row in rows])
                except (OSError, ValueError) as exc:
                    self._json(HTTPStatus.CONFLICT, {"error": str(exc)})
            elif route.startswith("/api/items/"):
                if not self._valid_token():
                    self._json(HTTPStatus.FORBIDDEN, {"error": "Sessão inválida."})
                    return
                row_id = urllib.parse.unquote(route[len("/api/items/"):])
                try:
                    row = next((item for item in current_rows(system_dir) if item["id"] == row_id), None)
                    if row is None:
                        self._json(HTTPStatus.NOT_FOUND, {"error": "Item não encontrado."})
                        return
                    self._json(HTTPStatus.OK, {**row, "state": state(row, decisions(system_dir)),
                                               "fingerprint": fingerprint(row)})
                except (OSError, ValueError) as exc:
                    self._json(HTTPStatus.CONFLICT, {"error": str(exc)})
            elif route == "/source.pdf":
                try:
                    source = choose_pdf(system_dir / "source")
                    size = source.stat().st_size
                    self._headers(HTTPStatus.OK, "application/pdf", size)
                    with source.open("rb") as stream:
                        while block := stream.read(1024 * 1024):
                            self.wfile.write(block)
                except (OSError, ValueError, BrokenPipeError):
                    return
            else:
                self._json(HTTPStatus.NOT_FOUND, {"error": "Página não encontrada."})

        def _mutation(self) -> None:
            if not self._valid_host() or self.headers.get("Origin") != origin or not self._valid_token():
                self._json(HTTPStatus.FORBIDDEN, {"error": "Solicitação não autorizada."})
                return
            route = urllib.parse.urlsplit(self.path).path
            is_review = self.command == "POST" and route.endswith("/review")
            is_text = self.command == "PUT" and route.endswith("/text")
            if not route.startswith("/api/items/") or not (is_review or is_text):
                self._json(HTTPStatus.NOT_FOUND, {"error": "Ação não encontrada."})
                return
            size_header = self.headers.get("Content-Length", "")
            limit = 4096 if is_review else 400_000
            if not size_header.isdigit() or not 0 < int(size_header) <= limit:
                self._json(HTTPStatus.BAD_REQUEST, {"error": "Corpo inválido."})
                return
            if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
                self._json(HTTPStatus.UNSUPPORTED_MEDIA_TYPE, {"error": "Use JSON."})
                return
            try:
                body = json.loads(self.rfile.read(int(size_header)))
                fields = {"decision", "fingerprint"} if is_review else {"text", "fingerprint"}
                if not isinstance(body, dict) or set(body) != fields:
                    raise ValueError("Campos inválidos.")
                if not isinstance(body["fingerprint"], str):
                    raise ValueError("Versão inválida.")
                suffix = "/review" if is_review else "/text"
                row_id = urllib.parse.unquote(route[len("/api/items/"):-len(suffix)])
                with write_lock:
                    result = (set_decision(system_dir, row_id, body["decision"], body["fingerprint"])
                              if is_review else set_text(system_dir, row_id, body["text"], body["fingerprint"]))
                self._json(HTTPStatus.OK, result)
            except (ValueError, json.JSONDecodeError) as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
            except KeyError as exc:
                self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
            except RuntimeError as exc:
                self._json(HTTPStatus.CONFLICT, {"error": str(exc)})

        def do_POST(self) -> None:
            self._mutation()

        def do_PUT(self) -> None:
            self._mutation()

        def log_message(self, format: str, *args: object) -> None:
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(prog="oraculo-review")
    parser.add_argument("system", help="Slug do sistema, por exemplo mutantes-malfeitores")
    parser.add_argument("--data-dir", type=Path, default=Path.cwd() / "data" / "systems")
    parser.add_argument("--port", type=int, default=0, help="Porta local; 0 escolhe uma disponível")
    parser.add_argument("--no-browser", action="store_true", help="Não abrir o navegador automaticamente")
    args = parser.parse_args()
    if not SLUG_RE.fullmatch(args.system):
        parser.error("Slug de sistema inválido.")
    system_dir = args.data_dir / args.system
    try:
        current_rows(system_dir)
        server = ThreadingHTTPServer(("127.0.0.1", args.port),
                                     lambda *handler_args, **kwargs: None)
        token = secrets.token_urlsafe(32)
        server.RequestHandlerClass = make_handler(system_dir, server.server_port, token)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"Erro: {exc}\n")
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Revisão local: {url}", flush=True)
    print("Pressione Ctrl+C para encerrar.", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
