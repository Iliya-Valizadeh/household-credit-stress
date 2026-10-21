"""A small HTTP helper with a timeout and a few retries, using only the standard library."""

from __future__ import annotations

import time
import urllib.error
import urllib.request

TIMEOUT_SECONDS = 60
RETRIES = 3


def get_bytes(url: str, body: bytes | None = None, content_type: str | None = None) -> bytes:
    """Return the response body for `url`. A `body` turns the request into a POST.

    Retries on network errors and 5xx responses, waiting a little longer each time.
    A 4xx response is raised at once, since asking again will not change it.
    """
    # Python's default User-Agent is kept on purpose. The CBA site refuses
    # custom agent strings that contain a URL, but serves the default one.
    headers: dict[str, str] = {}
    if content_type:
        headers["Content-Type"] = content_type
    last_error: Exception | None = None
    for attempt in range(RETRIES):
        request = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
                data: bytes = response.read()
                return data
        except urllib.error.HTTPError as error:
            if error.code < 500:
                raise
            last_error = error
        except urllib.error.URLError as error:
            last_error = error
        time.sleep(2**attempt)
    assert last_error is not None
    raise last_error
