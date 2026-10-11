#!/usr/bin/env python3
"""Local backend for the agentic-tool config editor.

Serves the static web UI and exposes /api/browse, /api/open and /api/save so
the editor can look up a config file on disk, copy it into a temp folder for
editing, and write it back to a chosen folder. Standard library only.
"""

import argparse
import atexit
import codecs
import http.cookiejar
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

WEB_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_DIR.parent
DEFAULT_PORT = 8765
TMP_DIR = Path(tempfile.gettempdir()) / "agentic-tool-editor"

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
}


CONNECTORS = [
    {
        "id": "console_mcp",
        "module": "mcp_connectors.console_mcp",
        "port": 9999,
        "label": "Console MCP",
        "description": "Console command execution server",
    },
    {
        "id": "playwright_mcp",
        "module": "mcp_connectors.playwright_mcp",
        "port": 8934,
        "label": "Playwright MCP",
        "description": "Browser automation server (needs: playwright install chromium)",
    },
]

_connector_lock = threading.Lock()
_connector_state = {
    c["id"]: {"proc": None, "log": deque(maxlen=60), "startedAt": None}
    for c in CONNECTORS
}


def _connector_by_id(conn_id: str) -> dict:
    for c in CONNECTORS:
        if c["id"] == conn_id:
            return c
    raise ValueError(f"Unknown connector: {conn_id}")


def _connector_python() -> str:
    venv = PROJECT_ROOT / ".venv" / ("Scripts" if os.name == "nt" else "bin") / (
        "python.exe" if os.name == "nt" else "python"
    )
    return str(venv) if venv.is_file() else sys.executable


def _port_open(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.3):
            return True
    except OSError:
        return False


def _pump_output(proc: subprocess.Popen, log: deque):
    try:
        for line in proc.stdout:
            log.append(line.rstrip("\n"))
    except Exception:
        pass


def _connector_status(conn: dict) -> dict:
    entry = _connector_state[conn["id"]]
    proc = entry["proc"]
    running = proc is not None and proc.poll() is None
    if proc is not None and not running:
        status = "stopped"
    elif running:
        status = "running"
    elif _port_open(conn["port"]):
        status = "external"
    else:
        status = "stopped"
    result = {
        "id": conn["id"],
        "label": conn["label"],
        "description": conn["description"],
        "port": conn["port"],
        "endpoint": f"http://127.0.0.1:{conn['port']}/mcp",
        "status": status,
        "pid": proc.pid if running else None,
        "startedAt": entry["startedAt"] if running else None,
        "log": list(entry["log"])[-15:],
    }
    if proc is not None and not running and entry["startedAt"]:
        result["exitCode"] = proc.poll()
    return result


def connector_states() -> dict:
    with _connector_lock:
        return {"connectors": [_connector_status(c) for c in CONNECTORS]}


def start_connector(conn_id: str) -> dict:
    conn = _connector_by_id(conn_id)
    with _connector_lock:
        entry = _connector_state[conn["id"]]
        proc = entry["proc"]
        if proc is not None and proc.poll() is None:
            raise ValueError(f"{conn['label']} is already running (pid {proc.pid})")
        if _port_open(conn["port"]):
            raise ValueError(
                f"Port {conn['port']} is already in use — a server is listening there already"
            )
        entry["log"].clear()
        entry["startedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        kwargs = {}
        if os.name == "posix":
            kwargs["start_new_session"] = True
        proc = subprocess.Popen(
            [_connector_python(), "-m", conn["module"], "--port", str(conn["port"])],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            **kwargs,
        )
        entry["proc"] = proc
        threading.Thread(target=_pump_output, args=(proc, entry["log"]), daemon=True).start()
        time.sleep(0.5)
        code = proc.poll()
        if code is not None:
            tail = " | ".join(list(entry["log"])[-5:]) or f"exit code {code}"
            entry["proc"] = None
            entry["startedAt"] = None
            raise ValueError(f"{conn['label']} failed to start ({tail})")
        return _connector_status(conn)


def stop_connector(conn_id: str) -> dict:
    conn = _connector_by_id(conn_id)
    with _connector_lock:
        entry = _connector_state[conn["id"]]
        proc = entry["proc"]
        if proc is None or proc.poll() is not None:
            raise ValueError(f"{conn['label']} is not running")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
        entry["proc"] = None
        entry["startedAt"] = None
        return _connector_status(conn)


def stop_all_connectors():
    for conn in CONNECTORS:
        try:
            entry = _connector_state[conn["id"]]
            proc = entry["proc"]
            if proc is not None and proc.poll() is None:
                proc.terminate()
        except Exception:
            pass


RUN_LOG_MAXLEN = 5000

_run_lock = threading.Lock()
_run_state = {
    "proc": None,
    "log": deque(maxlen=RUN_LOG_MAXLEN),
    "partial": "",
    "total": 0,
    "startedAt": None,
    "path": None,
    "autoConnectors": [],
}


def _pump_run_output(proc: subprocess.Popen):
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    try:
        while True:
            chunk = proc.stdout.read1(65536)
            if not chunk:
                break
            text = decoder.decode(chunk).replace("\r\n", "\n").replace("\r", "\n")
            with _run_lock:
                buf = _run_state["partial"] + text
                parts = buf.split("\n")
                _run_state["partial"] = parts.pop()
                for line in parts:
                    _run_state["log"].append(line)
                    _run_state["total"] += 1
    except Exception as exc:
        with _run_lock:
            _run_state["log"].append(f"[output pump error: {exc!r}]")
            _run_state["total"] += 1
    tail = decoder.decode(b"", final=True)
    with _run_lock:
        tail_line = _run_state["partial"] + tail
        _run_state["partial"] = ""
        if tail_line:
            _run_state["log"].append(tail_line)
            _run_state["total"] += 1
    try:
        proc.wait()
    except Exception:
        pass
    with _run_lock:
        auto = list(_run_state.get("autoConnectors") or [])
    _stop_auto_connectors(auto)


def _stop_auto_connectors(conn_ids: list):
    for conn_id in conn_ids:
        try:
            stop_connector(conn_id)
        except Exception:
            pass


def _endpoint_host_port(url: str):
    """Return (host, port) for an MCP endpoint URL, or (None, None) if unparseable."""
    try:
        parsed = urlparse(url)
    except ValueError:
        return None, None
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return None, None
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    return parsed.hostname, port


def _host_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.5):
            return True
    except OSError:
        return False


def _bundled_connector_for(endpoint: str) -> dict | None:
    host, port = _endpoint_host_port(endpoint)
    if port is None or host not in ("127.0.0.1", "localhost", "::1"):
        return None
    for conn in CONNECTORS:
        if conn["port"] == port:
            return conn
    return None


def _ensure_config_connectors(path: Path) -> list:
    """Make every MCP server referenced by the config reachable before a run.

    Bundled connectors that are down are started (and stopped again when the run
    ends). Any other unreachable MCP server aborts the run with an error.
    Returns the ids of connectors this call started.
    """
    try:
        data = json.loads(path.read_text())
    except ValueError as exc:
        raise ValueError(f"Invalid JSON in {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    tools = ((data.get("llm") or {}).get("mcpTools")) or []
    started = []
    for tool in tools:
        if not isinstance(tool, dict):
            continue
        name = str(tool.get("name") or "(unnamed)")
        endpoint = str(tool.get("endpoint") or "")
        conn = _bundled_connector_for(endpoint)
        if conn is not None:
            entry = _connector_state[conn["id"]]
            proc = entry["proc"]
            if (proc is not None and proc.poll() is None) or _port_open(conn["port"]):
                continue
            start_connector(conn["id"])
            started.append(conn["id"])
            deadline = time.time() + 5
            while time.time() < deadline and not _port_open(conn["port"]):
                time.sleep(0.15)
            if not _port_open(conn["port"]):
                _stop_auto_connectors(started)
                raise ValueError(f"{conn['label']} started but port {conn['port']} never opened")
        else:
            host, port = _endpoint_host_port(endpoint)
            if host is None:
                _stop_auto_connectors(started)
                raise ValueError(f"MCP server \"{name}\" has an invalid endpoint: {endpoint or '(empty)'}")
            if not _host_open(host, port):
                _stop_auto_connectors(started)
                raise ValueError(
                    f"MCP server \"{name}\" ({endpoint}) is not reachable — start it before running"
                )
    return started


def run_status(offset: int = 0) -> dict:
    with _run_lock:
        proc = _run_state["proc"]
        running = proc is not None and proc.poll() is None
        lines = list(_run_state["log"])
        base = _run_state["total"] - len(lines)
        start = max(0, offset - base)
        result = {
            "running": running,
            "path": _run_state["path"],
            "startedAt": _run_state["startedAt"],
            "offset": _run_state["total"],
            "lines": lines[start:],
            "pending": _run_state["partial"],
        }
        if offset < base:
            result["reset"] = True
        if proc is not None and not running:
            result["exitCode"] = proc.poll()
        return result


def run_start(path_raw: str) -> dict:
    path = resolve_path(path_raw)
    if path.suffix.lower() != ".json":
        raise ValueError("Only .json config files can be executed")
    if not path.is_file():
        raise ValueError(f"Config file not found: {path}")
    with _run_lock:
        proc = _run_state["proc"]
        if proc is not None and proc.poll() is None:
            raise ValueError(f"A run is already in progress (pid {proc.pid})")
        _run_state["log"].clear()
        _run_state["partial"] = ""
        _run_state["total"] = 0
        _run_state["startedAt"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _run_state["path"] = str(path)
        _run_state["autoConnectors"] = []
    auto_started = _ensure_config_connectors(path)
    with _run_lock:
        _run_state["autoConnectors"] = auto_started
        kwargs = {}
        if os.name == "posix":
            kwargs["start_new_session"] = True
        env = os.environ.copy()
        env["PYTHONUNBUFFERED"] = "1"
        try:
            proc = subprocess.Popen(
                [_connector_python(), "-u", "agentic-tool.py", "--file", str(path)],
                cwd=str(PROJECT_ROOT),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=env,
                **kwargs,
            )
        except OSError as exc:
            _run_state["autoConnectors"] = []
            _stop_auto_connectors(auto_started)
            raise ValueError(f"Cannot launch agentic-tool ({exc})") from exc
        _run_state["proc"] = proc
        threading.Thread(target=_pump_run_output, args=(proc,), daemon=True).start()
    time.sleep(0.5)
    with _run_lock:
        code = proc.poll()
        if code is not None:
            tail = " | ".join(list(_run_state["log"])[-5:]) or f"exit code {code}"
            raise ValueError(f"agentic-tool failed to start ({tail})")
    result = run_status(0)
    result["autoStarted"] = auto_started
    return result


def run_stop() -> dict:
    with _run_lock:
        proc = _run_state["proc"]
        if proc is None or proc.poll() is not None:
            raise ValueError("No run is in progress")
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                pass
    return run_status(0)


def stop_all():
    stop_all_connectors()
    try:
        proc = _run_state["proc"]
        if proc is not None and proc.poll() is None:
            proc.terminate()
    except Exception:
        pass


atexit.register(stop_all)


def resolve_path(raw: str) -> Path:
    p = Path(unquote(raw)).expanduser()
    if not p.is_absolute():
        p = PROJECT_ROOT / p
    return p.resolve()


def browse_dir(raw: str) -> dict:
    """List directories and .json files in a directory for the Open dialog."""
    target = resolve_path(raw) if raw.strip() else PROJECT_ROOT
    if not target.is_dir():
        raise ValueError(f"Not a directory: {target}")
    dirs, files = [], []
    try:
        entries = sorted(target.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        raise ValueError(f"Cannot read directory ({exc})") from exc
    for entry in entries:
        if entry.name.startswith("."):
            continue
        try:
            if entry.is_dir():
                dirs.append({"name": entry.name, "dir": True})
            elif entry.suffix.lower() == ".json" and entry.is_file():
                files.append({"name": entry.name, "dir": False, "size": entry.stat().st_size})
        except OSError:
            continue
    parent = str(target.parent) if target.parent != target else None
    return {"dir": str(target), "parent": parent, "entries": dirs + files}


def open_to_tmp(raw: str) -> dict:
    """Read a .json config, validate it, and copy it into the temp edit folder."""
    src = resolve_path(raw)
    if src.suffix.lower() != ".json":
        raise ValueError("Only .json config files can be opened")
    if not src.is_file():
        raise ValueError(f"File not found: {src}")
    try:
        data = json.loads(src.read_text())
    except ValueError as exc:
        raise ValueError(f"Invalid JSON in {src.name}: {exc}") from exc
    safe_stem = re.sub(r"[^\w.-]+", "_", src.stem).strip("._") or "config"
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    tmp = TMP_DIR / f"{safe_stem[:60]}-{uuid.uuid4().hex[:8]}.json"
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    return {"name": src.name, "tmpPath": str(tmp), "data": data}


def save_config(raw_dir: str, raw_name: str, data) -> dict:
    """Write the edited config as a .json file into the chosen directory."""
    if not isinstance(data, dict):
        raise ValueError("Config data must be a JSON object")
    name = re.sub(r"[/\\:*?\"<>|\x00-\x1f]+", "_", str(raw_name).strip()).strip(" .")
    if not name or name in (".", ".."):
        raise ValueError("File name is required")
    if not name.lower().endswith(".json"):
        name += ".json"
    target = resolve_path(raw_dir) if raw_dir.strip() else PROJECT_ROOT
    if not target.is_dir():
        raise ValueError(f"Not a directory: {target}")
    path = target / name
    try:
        path.write_text(json.dumps(data, indent=2) + "\n")
    except OSError as exc:
        raise ValueError(f"Cannot write {path} ({exc})") from exc
    return {"name": name, "path": str(path)}


def _rpc_message(raw: str) -> dict:
    """Extract the first JSON-RPC message from a plain-JSON or SSE body."""
    for line in raw.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line.startswith("{"):
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        if isinstance(msg, dict) and ("result" in msg or "error" in msg):
            return msg
    raise ValueError("No JSON-RPC response in server reply")


def mcp_check(endpoint: str, timeout: float = 10.0) -> dict:
    """Probe a Streamable HTTP MCP server: initialize, then tools/list.

    Returns {"alive": True, serverInfo, toolCount} or {"alive": False, error}.
    Standard library only so the editor needs no project dependencies.
    """
    parsed = urlparse(endpoint)
    if parsed.scheme not in ("http", "https"):
        raise ValueError("MCP endpoint must be an http(s) URL")

    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )

    def post(body: dict, session_id: str | None = None, protocol: str | None = None):
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if session_id:
            headers["Mcp-Session-Id"] = session_id
        if protocol:
            headers["MCP-Protocol-Version"] = protocol
        req = urllib.request.Request(endpoint, data=json.dumps(body).encode(), headers=headers)
        with opener.open(req, timeout=timeout) as resp:
            return resp.headers.get("Mcp-Session-Id"), resp.read().decode("utf-8", "replace")

    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "agentic-tool-config-editor", "version": "1.0"},
        },
    }
    try:
        session_id, raw = post(init)
    except urllib.error.HTTPError as exc:
        return {"alive": False, "error": f"MCP server replied HTTP {exc.code} — endpoint may not be an MCP server"}
    except (urllib.error.URLError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        text = str(reason)
        low = text.lower()
        if isinstance(reason, ConnectionRefusedError) or "connection refused" in low:
            text = "connection refused"
        elif isinstance(reason, TimeoutError) or "timed out" in low:
            text = "connection timed out"
        elif isinstance(reason, socket.gaierror) or "name or service not known" in low:
            text = "host name could not be resolved"
        return {"alive": False, "error": f"MCP server unreachable ({text})"}

    try:
        msg = _rpc_message(raw)
    except ValueError:
        return {"alive": False, "error": "MCP server replied with an unexpected response — endpoint may not be an MCP server"}
    if "error" in msg:
        err = msg["error"]
        return {"alive": False, "error": f"MCP server error: {err.get('message') or 'unknown error'}"}

    server_info = msg.get("result", {}).get("serverInfo", {})
    protocol_version = msg.get("result", {}).get("protocolVersion") or "2025-03-26"

    try:
        post({"jsonrpc": "2.0", "method": "notifications/initialized"}, session_id, protocol_version)
    except Exception:
        pass

    tools = None
    tools_error = None
    try:
        _, raw_tools = post({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, session_id, protocol_version)
        tools_msg = _rpc_message(raw_tools)
        if "result" in tools_msg:
            tools = [
                {"name": t.get("name", ""), "description": t.get("description", "")}
                for t in tools_msg["result"].get("tools", [])
            ]
        elif "error" in tools_msg:
            tools_error = tools_msg["error"].get("message") or "unknown JSON-RPC error"
    except urllib.error.HTTPError as exc:
        tools_error = f"HTTP {exc.code} {exc.reason}"
    except Exception as exc:
        tools_error = str(exc) or type(exc).__name__

    result = {
        "alive": True,
        "serverInfo": server_info,
        "protocolVersion": protocol_version,
        "endpoint": endpoint,
        "tools": tools,
    }
    if tools is not None:
        result["toolCount"] = len(tools)
    else:
        result["toolsError"] = tools_error or "tools/list returned no result"
    return result


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _json(self, code: int, payload: dict):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, url_path: str):
        rel = url_path.lstrip("/") or "index.html"
        target = (WEB_DIR / rel).resolve()
        if WEB_DIR != target.parent and WEB_DIR not in target.parents:
            self.send_error(403)
            return
        if not target.is_file():
            self.send_error(404)
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/browse":
            raw = (parse_qs(parsed.query).get("dir") or [""])[0]
            try:
                self._json(200, {"ok": True, **browse_dir(raw)})
            except Exception as exc:
                self._json(400, {"ok": False, "error": str(exc)})
            return
        if parsed.path == "/api/connectors":
            try:
                self._json(200, {"ok": True, **connector_states()})
            except Exception as exc:
                self._json(400, {"ok": False, "error": str(exc)})
            return
        if parsed.path == "/api/run/status":
            raw = (parse_qs(parsed.query).get("offset") or ["0"])[0]
            try:
                offset = max(0, int(raw))
            except ValueError:
                offset = 0
            try:
                self._json(200, {"ok": True, **run_status(offset)})
            except Exception as exc:
                self._json(400, {"ok": False, "error": str(exc)})
            return
        self._static(parsed.path if parsed.path != "/" else "index.html")

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/check":
            endpoint = ""
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                endpoint = str(payload.get("endpoint", ""))
                result = mcp_check(endpoint)
            except Exception as exc:
                result = {"alive": False, "error": str(exc)}
            result["endpoint"] = endpoint
            self._json(200, {"ok": True, **result})
            return
        if parsed.path in ("/api/connectors/start", "/api/connectors/stop"):
            conn_id = ""
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                conn_id = str(payload.get("id", ""))
                action = start_connector if parsed.path.endswith("/start") else stop_connector
                result = {"ok": True, "connector": action(conn_id)}
            except Exception as exc:
                result = {"ok": False, "error": str(exc), "id": conn_id}
            self._json(200, result)
            return
        if parsed.path in ("/api/run/start", "/api/run/stop"):
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                if parsed.path.endswith("/start"):
                    result = {"ok": True, **run_start(str(payload.get("path", "")))}
                else:
                    result = {"ok": True, **run_stop()}
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            self._json(200, result)
            return
        if parsed.path == "/api/open":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length))
                result = open_to_tmp(str(payload.get("path", "")))
                self._json(200, {"ok": True, **result})
            except Exception as exc:
                self._json(400, {"ok": False, "error": str(exc)})
            return
        if parsed.path != "/api/save":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            result = save_config(
                str(payload.get("dir", "")),
                str(payload.get("name", "")),
                payload.get("data"),
            )
            self._json(200, {"ok": True, **result})
        except Exception as exc:
            self._json(400, {"ok": False, "error": str(exc)})


def main():
    ap = argparse.ArgumentParser(description="Serve the agentic-tool config editor")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT)
    ap.add_argument("--no-browser", action="store_true", help="Do not open a browser tab")
    args = ap.parse_args()

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    url = f"http://127.0.0.1:{args.port}/"
    print(f"agentic-tool config editor: {url} (Ctrl+C to stop)")
    print(f"File browser starts at: {PROJECT_ROOT} (relative paths resolve here)")
    print(f"Opened files are copied to the temp edit folder: {TMP_DIR}")
    print("Save writes configs to the folder chosen in the Save dialog")
    if not args.no_browser:
        threading.Timer(0.7, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
