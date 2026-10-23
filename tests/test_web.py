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


@pytest.mark.parametrize("path,content_type", [
    ("/manifest.webmanifest", "application/manifest+json"),
    ("/sw.js", "text/javascript"), ("/pwa.mjs", "text/javascript"),
    ("/icons/icon-180.png", "image/png"),
    ("/icons/icon-192.png", "image/png"),
    ("/icons/icon-512.png", "image/png"),
])
def test_pwa_assets_are_public_and_revalidated(service, path, content_type):
    _, client = service
    with urlopen(client.server + path, timeout=2) as response:
        assert response.headers.get_content_type() == content_type
        assert response.headers["Cache-Control"] == "no-cache"
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.read()


def test_manifest_and_icons_are_installable(service):
    import json
    import struct
    from urllib.parse import urljoin

    _, client = service
    with urlopen(client.server + "/manifest.webmanifest", timeout=2) as response:
        manifest = json.load(response)
    assert manifest["name"] == "Process Aquarium"
    assert manifest["display"] == "standalone"
    assert manifest["id"] == manifest["start_url"] == manifest["scope"] == "./"
    assert {icon["sizes"] for icon in manifest["icons"]} == {"192x192", "512x512"}
    for icon in manifest["icons"]:
        with urlopen(urljoin(client.server + "/", icon["src"]), timeout=2) as response:
            data = response.read()
        assert data[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", data[16:24])
        assert icon["sizes"] == f"{width}x{height}"
    with urlopen(client.server, timeout=2) as response:
        html = response.read().decode()
    assert 'rel="manifest" href="./manifest.webmanifest"' in html
    assert 'rel="apple-touch-icon"' in html
    assert 'src="./pwa.mjs"' in html


@pytest.mark.parametrize("path", [
    "/api/v1/hosts", "/api/v1/snapshot?host=a", "/api/v1/flows",
    "/api/v1/transfers",
])
def test_unauthorized_telemetry_is_never_cacheable(service, path):
    _, client = service
    with pytest.raises(HTTPError) as exc:
        urlopen(client.server + path, timeout=2)
    assert exc.value.code == 401
    assert exc.value.headers["Cache-Control"] == "no-store"
