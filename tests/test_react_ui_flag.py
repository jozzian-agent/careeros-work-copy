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
    assert client.get('/api/jobs?view=board').status_code == 200


def test_flag_on_without_build_falls_back_to_jinja(tmp_path, monkeypatch):
    monkeypatch.setenv('CAREEROS_REACT_UI', '1')
    monkeypatch.setenv('CAREEROS_REACT_DIST', str(tmp_path / 'missing-dist'))
    app = server.create_app(tmp_path / 'vault')
    assert '<div id="root">' not in _jobs_body(app)


# JOZ-280: the detail pages (Job, Experience, Company) have no Jinja
# coexistence, unlike /jobs above -- they exist only behind the flag, with
# no Jinja fallback when it is off. B6 retired the Company Classification
# page; its route is gone under the flag too (see
# test_company_taxonomy_route_is_gone below).
def test_flag_on_serves_react_for_every_detail_route(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path

    monkeypatch.setenv('CAREEROS_REACT_UI', '1')
    monkeypatch.setenv('CAREEROS_REACT_DIST', str(_fake_dist(tmp_path)))
    vault_root = tmp_path / 'vault'
    shutil.copytree(Path(__file__).resolve().parents[1] / 'sample/vault', vault_root)
    app = server.create_app(vault_root)
    client = app.test_client()
    for path in ('/jobs/JOB-001', '/experiences/EXP-001', '/companies/CO-001'):
        response = client.get(path)
        assert response.status_code == 200
        assert '<div id="root">' in response.get_data(as_text=True)


# 2026-11-01: Add position is the React page that replaced the Jinja
# add/edit form, so /experiences/new follows the same no-coexist rule --
# it exists only behind the flag, and the static segment beats the detail
# page's own <identifier> rule rather than being read as a record id.
def test_flag_decides_whether_add_position_exists(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path

    monkeypatch.setenv('CAREEROS_REACT_DIST', str(_fake_dist(tmp_path)))
    vault_root = tmp_path / 'vault'
    shutil.copytree(Path(__file__).resolve().parents[1] / 'sample/vault', vault_root)

    monkeypatch.setenv('CAREEROS_REACT_UI', '1')
    app = server.create_app(vault_root)
    client = app.test_client()
    assert '<div id="root">' in client.get('/experiences/new').get_data(as_text=True)
    assert app.url_map.bind('localhost').match('/experiences/new')[0] == 'react_experience_new'
    # Its data endpoint is a JSON API like every other one, so the flag
    # does not decide whether it answers.
    assert client.get('/api/experiences/new').status_code == 200

    monkeypatch.delenv('CAREEROS_REACT_UI')
    flagged_off = server.create_app(vault_root).test_client()
    assert flagged_off.get('/experiences/new').status_code == 404
    assert flagged_off.get('/api/experiences/new').status_code == 200


def test_the_jinja_experience_form_is_gone(tmp_path, monkeypatch):
    """The add form's own URL now serves the SPA, and the edit form's URL
    -- which nothing in the React app ever linked to -- answers 404. The
    JSON context behind both stays: `GET /api/experiences/<id>/edit` is
    what the Edit position popup reads."""
    import shutil
    from pathlib import Path

    monkeypatch.setenv('CAREEROS_REACT_UI', '1')
    monkeypatch.setenv('CAREEROS_REACT_DIST', str(_fake_dist(tmp_path)))
    vault_root = tmp_path / 'vault'
    shutil.copytree(Path(__file__).resolve().parents[1] / 'sample/vault', vault_root)
    client = server.create_app(vault_root).test_client()
    assert client.get('/experiences/EXP-001/edit').status_code == 404
    assert client.get('/api/experiences/EXP-001/edit').status_code == 200
    body = client.get('/experiences/new').get_data(as_text=True)
    assert '<h1>Add position</h1>' not in body
    assert '<div id="root">' in body


def test_taxonomy_pages_are_gone_and_their_endpoints_stay(tmp_path, monkeypatch):
    """B6 and 2026-11-01: neither standalone classification page exists any
    more, flag on or off. The Edit classification popup on the React
    detail pages replaces both, and the JSON endpoint it reads stays."""
    import shutil
    from pathlib import Path

    monkeypatch.setenv('CAREEROS_REACT_UI', '1')
    monkeypatch.setenv('CAREEROS_REACT_DIST', str(_fake_dist(tmp_path)))
    vault_root = tmp_path / 'vault'
    shutil.copytree(Path(__file__).resolve().parents[1] / 'sample/vault', vault_root)
    client = server.create_app(vault_root).test_client()
    assert client.get('/companies/CO-001/taxonomy').status_code == 404
    assert client.get('/api/companies/CO-001/taxonomy').status_code == 404
    assert client.get('/jobs/JOB-001/taxonomy').status_code == 404
    assert client.get('/api/jobs/JOB-001/taxonomy').status_code == 200


def test_flag_off_detail_routes_404_with_no_jinja_fallback(tmp_path, monkeypatch):
    import shutil
    from pathlib import Path

    monkeypatch.delenv('CAREEROS_REACT_UI', raising=False)
    monkeypatch.setenv('CAREEROS_REACT_DIST', str(_fake_dist(tmp_path)))
    vault_root = tmp_path / 'vault'
    shutil.copytree(Path(__file__).resolve().parents[1] / 'sample/vault', vault_root)
    app = server.create_app(vault_root)
    client = app.test_client()
    for path in ('/jobs/JOB-001', '/experiences/EXP-001', '/companies/CO-001'):
        assert client.get(path).status_code == 404
    # The job classification sub-page was the last Jinja page that still
    # answered with the flag off. It is gone (2026-11-01), so with no
    # React build the app serves /jobs and the sign-in pages and nothing
    # else.
    assert client.get('/jobs/JOB-001/taxonomy').status_code == 404
    assert client.get('/jobs').status_code == 200


# JOZ-283: Search (home), Experiences list and Companies list have the same
# no-coexist routing as the JOZ-280 detail pages above. They exist only
# behind the flag, with no Jinja fallback when it is off. The redundant
# "/search" URL the Jinja template also answered to is retired, not
# carried over: the Search page's only URL is "/".
def test_flag_on_serves_react_for_search_experiences_and_companies_lists(tmp_path, monkeypatch):
    monkeypatch.setenv('CAREEROS_REACT_UI', '1')
    monkeypatch.setenv('CAREEROS_REACT_DIST', str(_fake_dist(tmp_path)))
    app = server.create_app(tmp_path / 'vault')
    client = app.test_client()
    for path in ('/', '/experiences', '/companies'):
        response = client.get(path)
        assert response.status_code == 200
        assert '<div id="root">' in response.get_data(as_text=True)


# Owner round: Notes is the first page added since the cutover. React-only
# like /taxonomy, so it follows the same no-Jinja-fallback rule.
def test_flag_decides_whether_the_notes_page_exists(tmp_path, monkeypatch):
    monkeypatch.setenv('CAREEROS_REACT_DIST', str(_fake_dist(tmp_path)))
    monkeypatch.setenv('CAREEROS_REACT_UI', '1')
    client = server.create_app(tmp_path / 'vault').test_client()
    assert '<div id="root">' in client.get('/notes').get_data(as_text=True)
    # The page's data endpoint answers whatever the flag says, since it is
    # a JSON API like every other one.
    assert client.get('/api/notes').status_code == 200

    monkeypatch.delenv('CAREEROS_REACT_UI')
    flagged_off = server.create_app(tmp_path / 'vault').test_client()
    assert flagged_off.get('/notes').status_code == 404
    assert flagged_off.get('/api/notes').status_code == 200


def test_flag_off_search_experiences_and_companies_lists_404_with_no_jinja_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv('CAREEROS_REACT_UI', raising=False)
    monkeypatch.setenv('CAREEROS_REACT_DIST', str(_fake_dist(tmp_path)))
    app = server.create_app(tmp_path / 'vault')
    client = app.test_client()
    for path in ('/', '/experiences', '/companies', '/search'):
        assert client.get(path).status_code == 404
    # /jobs is unaffected: it keeps its own JOZ-273 dual-mode fallback.
    assert client.get('/jobs').status_code == 200


# 2026-11-01: there is no Jinja page left that the flag has to spare.
# /jobs keeps its own JOZ-273 dual-mode fallback and the sign-in set is
# rendered in Python rather than from a template, so every remaining
# template belongs to /jobs.
def test_only_the_jobs_templates_are_left(tmp_path, monkeypatch):
    from pathlib import Path

    monkeypatch.setenv('CAREEROS_REACT_UI', '1')
    monkeypatch.setenv('CAREEROS_REACT_DIST', str(_fake_dist(tmp_path)))
    app = server.create_app(tmp_path / 'vault')
    templates = Path(app.root_path) / 'templates'
    assert sorted(path.name for path in templates.glob('*.html')) == [
        'job_cards.html', 'jobs.html']
    # The one Jinja page the flag still has to spare is none: with the
    # flag on, /jobs is the SPA too.
    assert '<div id="root">' in _jobs_body(app)
