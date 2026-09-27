import threading

import requests


CA_BUNDLE = "/etc/ssl/certs/ca-certificates.crt"

_thread_local = threading.local()


def session():
    """Return this thread's HTTP session.

    Each thread keeps its own connection pool. The sports refresh runs
    one sport per thread, and the alert watcher is its own thread, so
    those pools stay separate and are reused for the next request.
    """
    client = getattr(_thread_local, "session", None)

    if client is None:
        client = requests.Session()
        client.headers.update({
            "Accept": "application/json",
            "User-Agent": "ScoreCast/1.0",
        })
        _thread_local.session = client

    return client


def failure_text(exc):
    response = getattr(exc, "response", None)

    if response is not None:
        text = (response.text or "").strip()

        if text:
            return text

    text = str(exc).strip()
    return text or "No response body"


def get_body(url, timeout, headers=None):
    """GET a URL and return the response body.

    Redirects are followed. HTTP status 400 and above raises
    requests.HTTPError with the response attached, which is the
    same failure curl reported with --fail-with-body.
    """
    response = session().get(
        url,
        timeout=timeout,
        verify=CA_BUNDLE,
        headers=headers,
        allow_redirects=True,
    )

    if response.status_code >= 400:
        raise requests.HTTPError(
            response.text,
            response=response,
        )

    return response.text
