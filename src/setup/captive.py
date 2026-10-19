from __future__ import annotations

from flask import Response, redirect, request

from setup.state import AP_ADDRESS


CAPTIVE_PATHS = {
    "/hotspot-detect.html",
    "/library/test/success.html",
    "/generate_204",
    "/gen_204",
    "/connecttest.txt",
    "/ncsi.txt",
    "/redirect",
    "/success.txt",
    "/canonical.html",
    "/kindle-wifi/wifiredirect.html",
    "/kindle-wifi/wifistub.html",
}


CAPTIVE_HOSTS = {
    "captive.apple.com",
    "www.apple.com",
    "www.appleiphonecell.com",
    "connectivitycheck.gstatic.com",
    "clients3.google.com",
    "connectivitycheck.android.com",
    "www.msftconnecttest.com",
    "ipv6.msftconnecttest.com",
    "www.msftncsi.com",
    "detectportal.firefox.com",
}


def is_captive_probe() -> bool:
    path = request.path.rstrip("/") or "/"
    host = (request.host or "").split(":")[0].lower()
    if path in CAPTIVE_PATHS:
        return True
    if host in CAPTIVE_HOSTS:
        return True
    if host.endswith(".apple.com") and "hotspot-detect" in path:
        return True
    return False


def captive_portal_url() -> str:
    return f"http://{AP_ADDRESS}/setup/wifi"


def captive_portal_response():
    target = captive_portal_url()
    if request.path in {"/generate_204", "/gen_204"}:
        html = (
            "<html><head>"
            f'<meta http-equiv="refresh" content="0;url={target}">'
            f'<title>GameLine</title></head><body>'
            f'<a href="{target}">Continue setup</a></body></html>'
        )
        return Response(html, status=200, mimetype="text/html")

    return redirect(target, code=302)
