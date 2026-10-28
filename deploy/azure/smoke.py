"""Public, content-free smoke. Full signed-in/provider smoke remains a release gate."""

import http.client
import json
import sys
from urllib.parse import urlsplit

origin = urlsplit(sys.argv[1])
if (
    origin.scheme != "https"
    or not origin.hostname
    or origin.username
    or origin.password
    or origin.path not in ("", "/")
    or origin.query
    or origin.fragment
):
    raise SystemExit("A canonical HTTPS origin is required")
connection = http.client.HTTPSConnection(origin.hostname, origin.port or 443, timeout=30)
try:
    for path in ("/", "/readyz"):
        connection.request("GET", path)
        response = connection.getresponse()
        response.read()
        if response.status != 200:
            raise SystemExit("public readiness failed")
    connection.request("GET", "/healthz")
    response = connection.getresponse()
    health = json.loads(response.read())
    if response.status != 200 or health.get("ner") != "ready":
        raise SystemExit("required NER is not ready")
    connection.request(
        "POST",
        "/v1/analyze",
        body=json.dumps({"text": "Synthetic specimen.", "language": "en"}),
        headers={"Content-Type": "application/json"},
    )
    response = connection.getresponse()
    response.read()
    if response.status not in (401, 403):
        raise SystemExit("anonymous protected API was accepted or returned an unexpected status")
finally:
    connection.close()
print("Landing, readiness and anonymous API refusal passed; provider smoke still required.")
