from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from test_server import service


@pytest.mark.parametrize("path,content_type", [
    ("/", "text/html"), ("/aquarium.css", "text/css"),
    ("/app.mjs", "text/javascript"), ("/world.mjs", "text/javascript"),
    ("/renderer.mjs", "text/javascript"),
    ("/fish.mjs", "text/javascript"), ("/geometry.mjs", "text/javascript"),
    ("/effects.mjs", "text/javascript"), ("/controls.mjs", "text/javascript"),
    ("/menu.mjs", "text/javascript"),
    ("/multiverse.mjs", "text/javascript"), ("/backgrounds.mjs", "text/javascript"),
    ("/tides.mjs", "text/javascript"),
    ("/intertank.mjs", "text/javascript"),
])
def test_static_client_is_available_without_exposing_telemetry(service, path, content_type):
    _, client = service
    with urlopen(client.server + path, timeout=2) as response:
        assert response.headers.get_content_type() == content_type
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
        assert response.read()


@pytest.mark.parametrize("path", ["/../pyproject.toml", "/%2e%2e/main.py", "/main.py", "/.env"])
def test_static_server_only_exposes_explicit_assets(service, path):
    _, client = service
    with pytest.raises(HTTPError) as exc:
        urlopen(client.server + path, timeout=2)
    assert exc.value.code in (401, 404)
