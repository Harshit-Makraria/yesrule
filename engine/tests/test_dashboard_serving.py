from pathlib import Path

from fastapi.testclient import TestClient

from yesrule.api import create_app, mount_dashboard


def _app(tmp_path: Path) -> TestClient:
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<div id=root></div>")
    (dist / "assets" / "app.js").write_text("console.log(1)")
    (dist / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("do not serve")
    app = create_app(f"sqlite:///{tmp_path / 't.db'}")
    # replace the default mount with one pointing at the temp build
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") not in {"/assets", "/{path:path}"}]
    mount_dashboard(app, dist)
    return TestClient(app)


def test_spa_routes_fall_back_to_index(tmp_path: Path) -> None:
    c = _app(tmp_path)
    for path in ("/", "/inbox", "/rules", "/hard-lines"):
        r = c.get(path)
        assert r.status_code == 200 and "id=root" in r.text


def test_assets_and_root_files_served(tmp_path: Path) -> None:
    c = _app(tmp_path)
    assert c.get("/assets/app.js").text == "console.log(1)"
    assert c.get("/favicon.svg").text == "<svg/>"


def test_api_paths_are_not_swallowed(tmp_path: Path) -> None:
    c = _app(tmp_path)
    assert c.get("/v1/nope").status_code == 404
    assert c.get("/health").json()["status"] == "ok"
    assert isinstance(c.get("/v1/rules").json(), list)


def test_no_path_traversal(tmp_path: Path) -> None:
    c = _app(tmp_path)
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/../../secret.txt"):
        assert "do not serve" not in c.get(path).text


def test_unbuilt_dashboard_explains_how_to_build(tmp_path: Path) -> None:
    app = create_app(f"sqlite:///{tmp_path / 't.db'}")
    app.router.routes = [r for r in app.router.routes if getattr(r, "path", "") not in {"/assets", "/{path:path}"}]
    mount_dashboard(app, tmp_path / "missing")
    r = TestClient(app).get("/inbox")
    assert r.status_code == 200 and "npm run build" in r.text
