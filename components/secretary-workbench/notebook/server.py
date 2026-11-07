#!/usr/bin/env python3
"""Loopback-only local task application. No external service or collector."""
import argparse
import hmac
import json
import mimetypes
import secrets
import sys
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit, quote

from store import ValidationError, ConflictError, strict_json
from notebook import Notebook, STATES

APP_ROOT = Path(__file__).resolve().parent
WEB = APP_ROOT / "web"
SOURCE_DEFAULT = Path("/home/operator/Documents/Codex/2026-10-20/personal-actions/个人事项_主表.json")
DB_DEFAULT = Path.home() / "Library/Application Support/TashanPersonalActions/actions.sqlite3"
ASSETS = {
    "/": "index.html", "/index.html": "index.html", "/app.js": "app.js", "/style.css": "style.css",
    "/fonts/HarmonyOS_Sans_SC_Regular.ttf": "fonts/HarmonyOS_Sans_SC_Regular.ttf",
    "/fonts/HarmonyOS_Sans_SC_Medium.ttf": "fonts/HarmonyOS_Sans_SC_Medium.ttf",
    "/fonts/google-sans-flex-latin.woff2": "fonts/google-sans-flex-latin.woff2",
}


def make_server(db_file=None, source_file=None, port=8876):
    if db_file is None or source_file is None:raise ValidationError('Explicit database and source required')
    store = Notebook(db_file, source_file)
    store.refresh()

    class Handler(BaseHTTPRequestHandler):
        server_version = "TashanActions/1"
        protocol_version = "HTTP/1.0"

        def setup(self):
            super().setup()
            self.connection.settimeout(10)

        def log_message(self, *_args):
            pass

        def headers_safe(self):
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
            self.send_header("Permissions-Policy", "camera=(), microphone=(), geolocation=()")

        def send(self, status, content, content_type="application/json; charset=utf-8", extra=None):
            raw = json.dumps(content, ensure_ascii=False).encode("utf-8") if isinstance(content, (dict, list)) else content
            self.send_response(status)
            self.headers_safe()
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(raw)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(raw)

        def error(self, status, message, code="request_error"):
            self.send(status, {"error": message, "code": code})

        def valid_host(self):
            return self.headers.get("Host") in {
                "127.0.0.1:" + str(self.server.server_port),
                "localhost:" + str(self.server.server_port)}

        def bootstrap(self):
            return dict(csrfToken=self.server.csrf, states=STATES, tasks=store.tasks(),
                        meta=store.meta(), notificationMode="in_app")

        def do_HEAD(self):
            self.do_GET()

        def do_GET(self):
            if not self.valid_host():
                return self.error(403, "仅允许本机访问", "host")
            path = unquote(urlsplit(self.path).path)
            try:
                if path == "/api/health":
                    return self.send(200, {"ok": True, "app": "TashanPersonalActions"})
                if path == "/api/bootstrap":
                    return self.send(200, self.bootstrap())
                if path == "/api/reminders":
                    return self.send(200, {"tasks": store.due_reminders()})
                parts = path.strip("/").split("/")
                if len(parts) == 3 and parts[:2] == ["api", "tasks"]:
                    return self.send(200, store.detail(parts[2]))
                if len(parts) == 5 and parts[:2] == ["api", "tasks"] and parts[3] == "sources" and parts[4].isdigit():
                    source = store.source(parts[2], int(parts[4]))
                    raw = source.read_bytes()
                    if source.suffix.lower() in {".md", ".txt", ".json", ".csv", ".xml", ".log"}:
                        return self.send(200, raw, "text/plain; charset=utf-8")
                    return self.send(200, raw, "application/octet-stream",
                                     {"Content-Disposition": "attachment; filename*=UTF-8''" + quote(source.name)})
                if path in ASSETS:
                    file = WEB / ASSETS[path]
                    if file.is_file():
                        mime = mimetypes.guess_type(file.name)[0] or "application/octet-stream"
                        if mime.startswith("text/") or path.endswith(".js"):
                            mime += "; charset=utf-8"
                        return self.send(200, file.read_bytes(), mime)
                return self.error(404, "未找到页面或资料", "not_found")
            except KeyError:
                return self.error(404, "未找到事项或来源", "not_found")
            except ValidationError as exc:
                return self.error(400, str(exc), "validation")
            except (BrokenPipeError, ConnectionResetError, socket.timeout):
                return
            except Exception:
                return self.error(500, "读取失败，请刷新后重试", "internal")

        def do_POST(self):
            origin = self.headers.get("Origin")
            expected = {"http://127.0.0.1:" + str(self.server.server_port),
                        "http://localhost:" + str(self.server.server_port)}
            token = self.headers.get("X-CSRF-Token", "")
            if not self.valid_host() or origin not in expected or not hmac.compare_digest(token.encode('utf-8'), self.server.csrf.encode('utf-8')):
                return self.error(403, "请求未获本机页面验证，请重新打开页面", "origin")
            if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Type", "").split(";")[0].strip() != "application/json":
                return self.error(400, "只接受JSON请求", "content_type")
            try:
                size = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self.error(400, "请求长度无效", "length")
            if size < 0 or size > 16384:
                return self.error(413, "请求内容过长", "too_large")
            try:
                raw = self.rfile.read(size)
                if len(raw) != size:
                    raise ValidationError("请求内容不完整")
                body = strict_json(raw.decode("utf-8"))
                path = unquote(urlsplit(self.path).path)
                if path == "/api/refresh":
                    if body != {}:
                        raise ValidationError("刷新请求不接受额外字段")
                    changes = store.refresh()
                    result = self.bootstrap()
                    result["changes"] = changes
                    return self.send(200, result)
                if path == "/api/tasks":
                    return self.send(200, {"task": store.create_task(body)})
                parts = path.strip("/").split("/")
                if len(parts) == 4 and parts[:2] == ["api", "tasks"]:
                    if parts[3] == "record":
                        return self.send(200, {"task": store.record(parts[2], body)})
                    if parts[3] == "confirm":
                        return self.send(200, {"task": store.confirm(parts[2], body)})
                    if parts[3] == "reminder-ack":
                        if body != {}:
                            raise ValidationError("提醒确认不接受额外字段")
                        return self.send(200, {"task": store.ack_reminder(parts[2])})
                return self.error(404, "未找到操作", "not_found")
            except (ValidationError, UnicodeDecodeError) as exc:
                return self.error(400, str(exc) if isinstance(exc, ValidationError) else "请求编码无效", "validation")
            except ConflictError as exc:
                return self.error(409, str(exc), "conflict")
            except KeyError:
                return self.error(404, "未找到事项", "not_found")
            except (BrokenPipeError, ConnectionResetError, socket.timeout):
                return
            except Exception:
                return self.error(500, "保存失败，原有记录未被覆盖，请重试", "internal")

    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    httpd.csrf = secrets.token_urlsafe(32)
    httpd.store = store
    return httpd


def main():
    parser = argparse.ArgumentParser(description="他山 · 本地个人事项（仅本机）")
    parser.add_argument("--port", type=int, default=8876)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error("端口需为1024—65535")
    if not args.source.is_file():
        parser.error("未找到事项主表，请用--source指定已有主表")
    try:
        server = make_server(args.db, args.source, args.port)
    except OSError as exc:
        parser.exit(1, "无法启动本地应用（端口占用或文件不可访问）：" + str(exc) + "\n")
    print("我的事项已启动：http://127.0.0.1:" + str(server.server_port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    if len(sys.argv)==1:print('Use local_server.py --help with an explicit workspace.')
    else:main()
