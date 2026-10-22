from pathlib import Path

import pytest

from backend import create_app


@pytest.fixture
def app(tmp_path):
    app = create_app()
    app.config["TESTING"] = True
    app.static_folder = str(tmp_path)
    return app


@pytest.mark.parametrize(
    ("url", "target"),
    [
        ("/", "http://localhost:5173/"),
        ("/graph?search=visa", "http://localhost:5173/graph?search=visa"),
        ("/graph?search=visa?", "http://localhost:5173/graph?search=visa?"),
    ],
)
def test_debug_pages_redirect_to_vite(app, url, target):
    app.debug = True

    response = app.test_client().get(url)

    assert response.status_code == 302
    assert response.headers["Location"] == target


@pytest.mark.parametrize("debug", [False, True])
def test_api_stays_on_flask(app, debug):
    app.debug = debug
    client = app.test_client()

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json == {"status": "ok"}
    assert client.get("/api/missing").status_code == 404
    assert client.get("/api").status_code == 404


def test_missing_build_explains_setup(app):
    response = app.test_client().get("/")

    assert response.status_code == 503
    assert b"npm run build --prefix frontend" in response.data


@pytest.mark.parametrize("url", ["/", "/graph"])
def test_production_serves_built_index(app, url):
    html = '<html><script src="/static/assets/app.js"></script></html>'
    (Path(app.static_folder) / "index.html").write_text(html)
    assets = Path(app.static_folder) / "assets"
    assets.mkdir()
    (assets / "app.js").write_text("console.log('frontend')")
    client = app.test_client()

    response = client.get(url)

    assert response.status_code == 200
    assert response.get_data(as_text=True) == html
    assert client.get("/static/assets/app.js").status_code == 200
    assert client.get("/static/assets/missing.js").status_code == 404
