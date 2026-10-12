"""CAREEROS_REACT_UI flag: /jobs is served by the built React SPA or Jinja.

M0 migration (JOZ-273). The flag is opt-in and degrades to the Jinja page
whenever the build output is missing, so a fresh clone never serves a
broken /jobs.
"""

from pathlib import Path

from careeros import server


def _fake_dist(tmp_path: Path) -> Path:
    dist = tmp_path / 'dist'
    (dist / 'assets').mkdir(parents=True)
    (dist / 'index.html').write_text('<html><body><div id="root"></div>'
                                     '<script src="/assets/app.js"></script></body></html>')
    (dist / 'assets' / 'app.js').write_text('// bundle')
    return dist


def _jobs_body(app, path='/jobs'):
    return app.test_client().get(path).get_data(as_text=True)


def test_flag_off_serves_jinja_page(tmp_path, monkeypatch):
    monkeypatch.delenv('CAREEROS_REACT_UI', raising=False)
    monkeypatch.setenv('CAREEROS_REACT_DIST', str(_fake_dist(tmp_path)))
    app = server.create_app(tmp_path / 'vault')
    assert '<div id="root">' not in _jobs_body(app)


def test_flag_on_serves_react_index_and_assets(tmp_path, monkeypatch):
    monkeypatch.setenv('CAREEROS_REACT_UI', '1')
    monkeypatch.setenv('CAREEROS_REACT_DIST', str(_fake_dist(tmp_path)))
    app = server.create_app(tmp_path / 'vault')
    client = app.test_client()
    assert '<div id="root">' in client.get('/jobs').get_data(as_text=True)
    assert client.get('/assets/app.js').status_code == 200
    # Other pages keep their Jinja handlers.
    assert client.get('/search').status_code == 200
    assert client.get('/api/jobs?view=board').status_code == 200


def test_flag_on_without_build_falls_back_to_jinja(tmp_path, monkeypatch):
    monkeypatch.setenv('CAREEROS_REACT_UI', '1')
    monkeypatch.setenv('CAREEROS_REACT_DIST', str(tmp_path / 'missing-dist'))
    app = server.create_app(tmp_path / 'vault')
    assert '<div id="root">' not in _jobs_body(app)


# JOZ-280: the detail pages (Job, Experience, Company, Company
# Classification) have no Jinja coexistence, unlike /jobs above -- they
# exist only behind the flag, with no Jinja fallback when it is off.
def test_flag_on_serves_react_for_every_detail_route(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path

    monkeypatch.setenv('CAREEROS_REACT_UI', '1')
    monkeypatch.setenv('CAREEROS_REACT_DIST', str(_fake_dist(tmp_path)))
    vault_root = tmp_path / 'vault'
    shutil.copytree(Path(__file__).resolve().parents[1] / 'sample/vault', vault_root)
    app = server.create_app(vault_root)
    client = app.test_client()
    for path in ('/jobs/JOB-001', '/experiences/EXP-001', '/companies/CO-001', '/companies/CO-001/taxonomy'):
        response = client.get(path)
        assert response.status_code == 200
        assert '<div id="root">' in response.get_data(as_text=True)


def test_flag_off_detail_routes_404_with_no_jinja_fallback(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path

    monkeypatch.delenv('CAREEROS_REACT_UI', raising=False)
    monkeypatch.setenv('CAREEROS_REACT_DIST', str(_fake_dist(tmp_path)))
    vault_root = tmp_path / 'vault'
    shutil.copytree(Path(__file__).resolve().parents[1] / 'sample/vault', vault_root)
    app = server.create_app(vault_root)
    client = app.test_client()
    for path in ('/jobs/JOB-001', '/experiences/EXP-001', '/companies/CO-001', '/companies/CO-001/taxonomy'):
        assert client.get(path).status_code == 404
    # The job classification sub-page is not part of this cutover (the
    # React Job detail page edits it via a popup instead); it stays Jinja
    # regardless of the flag.
    assert client.get('/jobs/JOB-001/taxonomy').status_code == 200
