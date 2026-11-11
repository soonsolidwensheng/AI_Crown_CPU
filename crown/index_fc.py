#!/usr/bin/env python3

"""Alibaba Cloud Function Compute adapter for crownJsonProcessor.

The module keeps the existing JSON contract and can be used in two ways:

* ``handler(event, context)`` for direct function-style invocation.
* A small HTTP server for an FC custom-container image.

The native crown processor is deliberately protected by one process-wide lock.
Individual requests may contain several large meshes, so allowing concurrent
native calls would create avoidable memory spikes.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import crown

try:
    import requests
except ImportError:  # pragma: no cover - Dockerfile installs requests.
    requests = None


LOGGER = logging.getLogger("crown_fc")
PROCESS_LOCK = threading.Lock()
DEFAULT_PORT = 9000
DEFAULT_URL_TIMEOUT_SECONDS = 120


def _status_response(
    status: str,
    error_code: int,
    error_message: str,
    job_id: str | None = None,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "status": status,
        "errorCode": error_code,
        "errorMsg": error_message,
    }
    if job_id:
        state["job_id"] = job_id
    return {"crown": {"state": state}}


def _error_response(error_message: str) -> dict[str, Any]:
    return {
        "crown": {
            "result": None,
            "state": {
                "status": "failed",
                "errorCode": 215,
                "errorMsg": error_message,
            },
        }
    }


def _url_timeout_seconds() -> float:
    value = os.getenv("CROWN_URL_TIMEOUT_SECONDS")
    if not value:
        return DEFAULT_URL_TIMEOUT_SECONDS
    try:
        timeout = float(value)
    except ValueError:
        return DEFAULT_URL_TIMEOUT_SECONDS
    return timeout if timeout > 0 else DEFAULT_URL_TIMEOUT_SECONDS


def _process_json(input_json: str) -> str:
    with PROCESS_LOCK:
        return crown.process_crown_json(input_json)


def _process_direct_event(event: dict[str, Any]) -> dict[str, Any]:
    try:
        output_json = _process_json(
            json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        )
        return json.loads(output_json)
    except Exception as exception:
        LOGGER.exception("Crown processing failed")
        return _error_response(str(exception))


def _process_url_event(event: dict[str, Any]) -> dict[str, Any]:
    job_id = event.get("job_id") or None
    source_url = event.get("source_url")
    target_url = event.get("target_url")

    if not source_url or not target_url:
        return _status_response(
            "failed",
            215,
            "source_url and target_url must be provided together.",
            job_id,
        )

    if requests is None:
        return _status_response(
            "failed",
            211,
            "The requests package is required.",
            job_id,
        )

    timeout = _url_timeout_seconds()

    try:
        response = requests.get(source_url, timeout=timeout)
        response.raise_for_status()
        input_json = json.dumps(
            response.json(), ensure_ascii=False, separators=(",", ":")
        )
    except Exception as exception:
        error_message = f"Failed to read from source_url: {exception}"
        LOGGER.warning("Crown URL input failed job_id=%s error=%s", job_id, exception)
        return _status_response("failed", 211, error_message, job_id)

    try:
        output_json = _process_json(input_json)
        result = json.loads(output_json)
    except Exception as exception:
        error_message = (
            f"Processing failed: {exception}\n{traceback.format_exc()}"
        )
        LOGGER.exception("Crown URL processing failed job_id=%s", job_id)
        return _status_response("failed", 212, error_message, job_id)

    try:
        parsed_url = urlparse(target_url)
        query_params = parse_qs(parsed_url.query)
        content_type = query_params.get("Content-Type", ["application/json"])[0]
        response = requests.put(
            target_url,
            json=result,
            headers={"Content-Type": content_type},
            timeout=timeout,
        )
        response.raise_for_status()
    except Exception as exception:
        error_message = f"Failed to write to target_url: {exception}"
        LOGGER.warning("Crown URL output failed job_id=%s error=%s", job_id, exception)
        return _status_response("failed", 213, error_message, job_id)

    result_state = result.get("crown", {}).get("state", {})
    error_code = result_state.get("errorCode", 500)
    error_message = result_state.get("errorMsg", "Unknown error")
    status = "success" if error_code == 200 else "failed"
    return _status_response(status, error_code, error_message, job_id)


def _decode_http_body(event: dict[str, Any]) -> dict[str, Any]:
    body = event.get("body")
    if event.get("isBase64Encoded"):
        if not isinstance(body, str):
            raise ValueError("base64 HTTP body must be a string")
        try:
            body = base64.b64decode(body, validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError) as exception:
            raise ValueError("invalid base64 HTTP body") from exception

    if isinstance(body, dict):
        return body
    if not isinstance(body, str):
        raise ValueError("HTTP body must contain a JSON object")

    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise ValueError("HTTP body must contain a JSON object")
    return payload


def handler(event: Any, context: Any = None) -> dict[str, Any]:
    """Process one direct FC event or an FC HTTP event."""

    del context

    try:
        if not isinstance(event, dict):
            return _error_response("event must be a JSON object.")

        if "body" in event:
            payload = _decode_http_body(event)
        else:
            payload = event

        has_source_url = bool(payload.get("source_url"))
        has_target_url = bool(payload.get("target_url"))
        if has_source_url or has_target_url:
            if not (has_source_url and has_target_url):
                return _error_response(
                    "source_url and target_url must be provided together."
                )
            return _process_url_event(payload)

        if "crownInput" not in payload:
            return _error_response(
                "source_url and target_url must be provided together, "
                "or crownInput must be provided."
            )

        return _process_direct_event(payload)
    except Exception as exception:
        LOGGER.exception("Unhandled Crown FC request failure")
        return _error_response(str(exception))


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


class _CrownRequestHandler(BaseHTTPRequestHandler):
    server_version = "CrownFC/1.0"

    def _write_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = _json_bytes(payload)
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        if urlparse(self.path).path == "/health":
            self._write_json(200, {"status": "ok"})
            return
        self._write_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API.
        path = urlparse(self.path).path
        if path not in ("/", "/crown"):
            self._write_json(404, {"error": "not found"})
            return

        try:
            content_length = int(self.headers.get("Content-Length", "-1"))
        except ValueError:
            content_length = -1

        if content_length < 0:
            self._write_json(400, _error_response("Content-Length is required."))
            return

        raw_body = self.rfile.read(content_length)
        started = time.monotonic()
        try:
            body = raw_body.decode("utf-8")
            payload = json.loads(body)
            if not isinstance(payload, dict):
                raise ValueError("request body must contain a JSON object")
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exception:
            self._write_json(400, _error_response(str(exception)))
            return

        result = handler(payload, None)
        state = result.get("crown", {}).get("state", {})
        elapsed_ms = int((time.monotonic() - started) * 1000)
        LOGGER.info(
            "POST %s body_bytes=%d error_code=%s elapsed_ms=%d job_id=%s",
            path,
            len(raw_body),
            state.get("errorCode"),
            elapsed_ms,
            state.get("job_id", ""),
        )
        self._write_json(200, result)

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.info("HTTP " + format, *args)


class _CrownHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _listen_port() -> int:
    for name in ("FC_SERVER_PORT", "PORT", "CROWN_FC_PORT"):
        value = os.getenv(name)
        if not value:
            continue
        try:
            port = int(value)
        except ValueError:
            continue
        if 1 <= port <= 65535:
            return port
    return DEFAULT_PORT


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    port = _listen_port()
    server = _CrownHTTPServer(("0.0.0.0", port), _CrownRequestHandler)
    LOGGER.info("Crown FC adapter listening on 0.0.0.0:%d", port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("Crown FC adapter stopping")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
