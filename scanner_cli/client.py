"""
ApiClient provides a simple HTTP client interface using httpx.

Attributes:
    _base_timeout (int): Default timeout for requests in seconds.
    _client (httpx.Client): The underlying httpx client instance.

Methods:
    __init__(timeout: int = 10):
        Initializes the ApiClient with an optional timeout.

    send():
        Sends an HTTP request using the specified method to the given endpoint.
        For POST, PUT, PATCH methods, the payload is sent as JSON.
        For other methods, the payload is sent as query parameters.
        Allows overriding timeout and adding custom headers.

    close():
        Closes the underlying httpx client.

    __enter__():
        Enables use of ApiClient as a context manager.

    __exit__(exc_type, exc, tb):
        Ensures the client is closed when exiting a context.

(c) Passlick Development 2025. All rights reserved.
"""


from __future__ import annotations

import httpx
from typing import Any, Dict


class ApiClient:
    def __init__(self, timeout: int = 10):
        self._base_timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    def send(
        self,
        method: str,
        endpoint: str,
        payload: Dict[str, Any],
        *,
        timeout: int | None = None,
        headers: Dict[str, str] | None = None,
    ) -> httpx.Response:
        method = method.upper()
        hdrs = {"Content-Type": "application/json"}
        if headers:
            hdrs.update(headers)
        request_args = {
            "url": endpoint,
            "timeout": timeout or self._base_timeout,
            "headers": hdrs,
        }
        if method in {"POST", "PUT", "PATCH"}:
            request_args["json"] = payload
        else:
            request_args["params"] = payload
        return self._client.request(method, **request_args)

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False
    