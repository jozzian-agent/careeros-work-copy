"""Full Chunk 4 verification. Run with .venv/bin/python scripts/verify.py."""
from pathlib import Path
import json
import socket
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from playwright.sync_api import sync_playwright
from careeros.web.screenshot import CHROMIUM_PATH

OUTPUT = Path('/tmp/careeros-chunk4')
BASE = 'http://127.0.0.1:8788'

def curl(route, method='GET', data=None, expected=200):
    args = ['curl', '--silent', '--show-error', '--max-time', '25', '-X', method,
            '--write-out', '\n%{http_code}', BASE+route]
    if data is not None:
        args += ['-H', 'Content-Type: application/json', '--data-binary', json.dumps(data)]
    result = subprocess.run(args, check=True, capture_output=True, text=True)
    body, code = result.stdout.rsplit('\n', 1)
    assert int(code) == expected, (method, route, code, body)
    print(f'{method} {route}: {code}', flush=True)
    return json.loads(body) if route.startswith('/api/') else body

def browser_checks():
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=CHROMIUM_PATH)
        try:
            page = browser.new_page(viewport={'width':1200, 'height':900}, device_scale_factor=2)
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            # Fail if a page tries to load any external dependency.
            external = []
            page.on('request', lambda request: external.append(request.url) if not request.url.startswith(BASE) else None)
            def visit(route, filename):
                page.goto(BASE+route, wait_until='networkidle')
                page.screenshot(path=str(OUTPUT/filename), full_page=True)
            visit('/search', 'search-view.png')
            page.get_by_role('button', name='Edit roles', exact=True).click()
            page.screenshot(path=str(OUTPUT/'search-edit.png'), full_page=True)
            page.get_by_role('textbox', name='New roles item', exact=True).fill('Synthetic verification role')
            page.locator('[data-section="roles"]').get_by_role('button', name='Add', exact=True).click()
            page.wait_for_function("document.getElementById('toast').textContent === 'Criteria saved'")
            page.reload(wait_until='networkidle')
            assert page.locator('[data-section="roles"] .items').inner_text().find('Synthetic verification role') >= 0
            page.get_by_role('button', name='Edit roles', exact=True).click()
            page.get_by_role('button', name='Remove Synthetic verification role', exact=True).click()
            page.wait_for_function("document.getElementById('toast').textContent === 'Criteria saved'")
            visit('/experiences', 'experiences-list.png')
            visit('/experiences/EXP-001', 'experience-detail.png')
            assert page.locator('strong').count() > 0
            visit('/experiences/new', 'experience-new.png')
            page.get_by_label('Company', exact=True).fill('Testwillow Fictional Lab')
            page.get_by_label('Title', exact=True).fill('Test Builder')
            page.get_by_label('Start (YYYY-MM)', exact=True).fill('2025-01')
            page.get_by_label('End (YYYY-MM or present)', exact=True).fill('present')
            page.get_by_role('button', name='Add custom field').click()
            page.get_by_label('Custom field key', exact=True).fill('Synthetic key')
            page.get_by_label('Custom field value', exact=True).fill('Synthetic value')
            page.get_by_role('button', name='Save position').click()
            page.wait_for_url('**/experiences/EXP-*')
            assert 'Synthetic key' in page.locator('main').inner_text()
            page.get_by_role('link', name='Edit position').click()
            page.get_by_label('Title', exact=True).fill('Updated Builder')
            page.get_by_role('button', name='Save position').click()
            page.wait_for_url('**/experiences/EXP-*')
            assert page.locator('h1').inner_text() == 'Updated Builder'
            page.get_by_role('button', name='Delete', exact=True).click()
            assert page.locator('dialog').is_visible()
            page.get_by_role('button', name='Keep position').click()
            page.get_by_role('button', name='Delete', exact=True).click()
            page.get_by_role('button', name='Delete position', exact=True).click()
            page.wait_for_url(BASE+'/experiences')
            visit('/jobs', 'jobs-board.png')
            assert page.locator('.kanban-column').count() == 8
            page.get_by_role('button', name='List', exact=True).click()
            assert page.locator('.jobs-table').is_visible()
            assert page.locator('.jobs-table thead').is_visible()
            assert not page.locator('#job-sort').is_visible()
            page.get_by_role('button', name='Title', exact=True).click()
            page.reload(wait_until='networkidle')
            assert page.locator('.jobs-table').is_visible()
            page.get_by_role('button', name='Board', exact=True).click()
            # Browser-only stubs test affordances without fetching sample ATS URLs.
            def enrich_response(route):
                route.fulfill(status=200, content_type='application/json', body='{"enriched":true}')
            page.route('**/api/jobs/*/enrich', enrich_response)
            page.get_by_role('button', name='Enrich pending', exact=True).click()
            page.wait_for_function("document.getElementById('toast').textContent.includes('updated, 0 failed')")
            page.get_by_role('button', name='Interested', exact=True).click()
            assert page.locator('.job-card:visible').count() == 1
            visit('/jobs/JOB-001', 'job-detail.png')
            assert page.locator('#job-history').is_visible()
            page.get_by_role('button', name='Check posting', exact=True).click()
            page.wait_for_function("document.getElementById('watch-result').textContent.startsWith('Error:')")
            page.get_by_role('button', name='Enrich', exact=True).click()
            page.wait_for_function("document.getElementById('toast').textContent === 'Job enriched'")
            page.unroute('**/api/jobs/*/enrich', enrich_response)
            page.locator('#status').select_option('interested')
            page.locator('#notes').fill('**Host verified** notes')
            page.get_by_role('button', name='Save job', exact=True).click()
            page.wait_for_function("document.getElementById('toast').textContent === 'Job saved'")
            assert page.locator('strong').inner_text() == 'Host verified'
            visit('/companies', 'companies-list.png')
            visit('/companies/CO-001', 'company-detail.png')
            page.locator('input[name="sectors"][value="J"]').check()
            page.get_by_role('button', name='Save profile', exact=True).click()
            page.wait_for_function("document.getElementById('toast').textContent === 'Profile saved'")
            assert page.locator('input[name="sectors"][value="J"]').is_checked()
            # Real delete UI: cancel, linked guard, then job and company removal.
            disposable = curl('/api/jobs/intake', 'POST', {'url':'https://browser-disposable.example/job'}, 201)
            jid, cid = disposable['job']['id'], disposable['company']['id']
            page.goto(BASE+'/companies/'+cid)
            page.once('dialog', lambda dialog: dialog.accept())
            page.get_by_role('button', name='Delete company', exact=True).click()
            page.wait_for_function("document.getElementById('toast').textContent === 'Still linked to 1 jobs'")
            page.goto(BASE+'/jobs/'+jid)
            page.once('dialog', lambda dialog: dialog.dismiss())
            page.get_by_role('button', name='Delete job', exact=True).click()
            assert curl('/api/jobs/'+jid)['id'] == jid
            page.once('dialog', lambda dialog: dialog.accept())
            page.get_by_role('button', name='Delete job', exact=True).click()
            page.wait_for_url(BASE+'/jobs')
            curl('/api/jobs/'+jid, expected=404)
            page.goto(BASE+'/companies/'+cid)
            page.once('dialog', lambda dialog: dialog.accept())
            page.get_by_role('button', name='Delete company', exact=True).click()
            page.wait_for_url(BASE+'/companies')
            curl('/api/companies/'+cid, expected=404)
            page.set_viewport_size({'width':390,'height':844})
            visit('/jobs', 'jobs-mobile.png')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.get_by_role('button', name='List', exact=True).click()
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not page.locator('.jobs-table thead').is_visible()
            assert page.get_by_label('Sort by').is_visible()
            for direction in ('asc', 'desc'):
                page.get_by_label('Sort by').select_option('0:'+direction)
                titles = page.locator('.job-row td:first-child').all_text_contents()
                assert titles == sorted(titles, reverse=direction == 'desc')
            page.screenshot(path=str(OUTPUT/'jobs-list-mobile.png'), full_page=True)
            page.goto(BASE+'/search', wait_until='networkidle')
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            page.screenshot(path=str(OUTPUT/'search-mobile.png'), full_page=True)
            assert not errors, errors
            assert not external, external
        finally:
            browser.close()

def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, '-m', 'pytest', '-q'], cwd=ROOT, check=True)
    # Snapshot only synthetic fixtures; restore exact bytes even on failed checks.
    sample = ROOT/'sample/vault'
    snapshots = {path: path.read_bytes() for path in sample.rglob('*.yaml')}
    server = None
    try:
        with socket.socket() as sock:
            if sock.connect_ex(('127.0.0.1',8788)) == 0:
                raise RuntimeError('Port 8788 occupied; refusing to use another server.')
        with (OUTPUT/'server.log').open('w') as log:
            # Verification process only: deterministic public DNS and blocked fetches.
            # Production SSRF checks remain unchanged; intake exercises its fallback.
            offline_server = (
                "import socket; from careeros import intake; from careeros.server import create_app; "
                "_real_gai=socket.getaddrinfo; "
                "socket.getaddrinfo=lambda host,*a,**kw: _real_gai(host,*a,**kw) "
                "if host in ('127.0.0.1','localhost','::1',None,'') "
                "else [(2,1,6,'',('8.8.8.8' if 'disposable.example' in host else '127.0.0.1',443))]; "
                "_real_fetch=intake.fetch_url; "
                "intake.fetch_url=lambda url: (_ for _ in ()).throw(RuntimeError('Offline verification')) "
                "if 'disposable.example' in url else _real_fetch(url); "
                "create_app('sample/vault').run(host='127.0.0.1',port=8788,debug=False)"
            )
            server = subprocess.Popen([sys.executable,'-c',offline_server], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError('Server exited; see server.log')
                with socket.socket() as sock:
                    if sock.connect_ex(('127.0.0.1',8788)) == 0:
                        break
                time.sleep(.1)
            else:
                raise RuntimeError('Server boot timed out')
            for route in ['/','/search','/experiences','/experiences/new','/experiences/EXP-001','/experiences/EXP-001/edit','/jobs','/jobs/JOB-001','/companies','/companies/CO-001']:
                assert 'CareerOS' in curl(route)
            assert 'Page not found' in curl('/missing', expected=404)
            curl('/experiences/EXP-999', expected=404)
            criteria = curl('/api/search')
            criteria['notes'] += '\nSynthetic API verification.'
            curl('/api/search', 'POST', criteria)
            assert curl('/api/search')['notes'] == criteria['notes']
            entries = curl('/api/experiences')
            data = entries[0] | {'company':'Verification Fictionworks', 'title':'Test Position'}
            created = curl('/api/experiences', 'POST', data, 201)
            route = '/api/experiences/'+created['id']
            assert curl(route) == created
            created['title'] = 'Edited Test Position'
            curl(route, 'PUT', created)
            assert curl(route)['title'] == created['title']
            curl(route, 'POST', created)
            curl(route, 'DELETE')
            curl(route, expected=404)
            jobs = curl('/api/jobs')
            assert len(jobs) == 6
            curl('/api/jobs/JOB-001')
            curl('/api/jobs/JOB-001', 'PUT', {'status':'invalid'}, 400)
            curl('/api/jobs/JOB-001', 'PUT', {'status':'interested'})
            curl('/api/companies')
            curl('/api/companies/CO-001')
            curl('/api/companies/CO-001', 'PUT', {'notes':'**Host verification**'})
            # External fetching is covered by offline mocked pytest cases.
            # Exercise guarded failure without making an external request.
            curl('/api/jobs/intake', 'POST', {'url':'file:///posting'}, 400)
            created = curl('/api/jobs/intake', 'POST', {'url':'https://verification-disposable.example/job'}, 201)
            company_route = '/api/companies/'+created['company']['id']
            job_route = '/api/jobs/'+created['job']['id']
            assert curl(company_route, 'DELETE', expected=409)['count'] == 1
            curl(job_route, 'DELETE')
            assert curl(company_route, 'DELETE') == {'deleted':created['company']['id']}
            curl(company_route, expected=404)
            # Reset the sample status before browser filter checks.
            curl('/api/jobs/JOB-001', 'PUT', {'status':'new'})
            browser_checks()
    finally:
        if server:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill(); server.wait(timeout=5)
            print('Verification server stopped.', flush=True)
        for path in sample.rglob('*.yaml'):
            if path not in snapshots:
                path.unlink()
        for path, data in snapshots.items():
            path.write_bytes(data)
    print(f'Full verification passed; screenshots: {OUTPUT}', flush=True)

if __name__ == '__main__':
    OUTPUT.mkdir(parents=True, exist_ok=True)
    try:
        main()
    except Exception:
        (OUTPUT/'verification.txt').write_text(traceback.format_exc())
        raise
    else:
        (OUTPUT/'verification.txt').write_text('All tests, curl API checks, browser interactions, and screenshots passed.\n')
