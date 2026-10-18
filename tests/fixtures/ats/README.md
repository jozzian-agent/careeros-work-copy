# Recorded ATS feed fixtures

Real responses from five providers' public job APIs, **recorded live on
2026-10-17** for CAREER-54 and trimmed to a few postings each. The
adapters' tests run entirely offline against these; nothing in `tests/`
ever opens a socket (`tests/conftest.py`'s `offline` fixture blocks
`urllib.request.build_opener` and DNS for the whole suite).

The Personio fixtures from CAREER-53 are next door in
`tests/fixtures/personio/`, with their own README. Same convention, one
directory per provider.

## Why recorded and not written by hand

The brief says to verify each provider's documented endpoint against the
live API before coding, and a fixture someone typed would encode what
the parser expects instead of what the provider sends. That is not a
hypothetical: recording these five found four things no documentation
page said.

* **SmartRecruiters' list endpoint states the language and the
  visibility**, not only the structured fields. Only the description
  needs the second request. The adapter's docstring said otherwise until
  the fixture contradicted it.
* **A Lever company slug is instance-scoped.** `leverdemo` exists on
  both `api.lever.co` and `api.eu.lever.co` and they are different
  boards: 10 postings on one, 324 on the other.
* **Greenhouse's `content` is entity-escaped HTML**
  (`&lt;div class=&quot;...`), so it has to be unescaped before it is
  read as HTML.
* **Ashby's `secondaryLocations` carry a full postal address each**,
  including the country, which is the best location evidence of any of
  the six providers.

## How they were trimmed

JSON, unlike Personio's XML, cannot be cut on a line boundary. So each
file is the real response **parsed, sliced to the first one or two
postings, and re-serialised** with `json.dumps(..., ensure_ascii=False,
indent=1)`. Field names, values, nesting and types are exactly what the
server sent; what differs from the wire is the whitespace and the number
of postings. The paging block of the SmartRecruiters list
(`offset`, `limit`, `totalFound: 492`) is kept as served, because the
paging walk is tested against it.

## What each file is for

| File | Tenant | What makes it worth keeping |
|---|---|---|
| `greenhouse/figma_jobs_trimmed.json` | `figma` | `?content=true` with entity-escaped `content`, an `offices` list whose name is `US`, and a `location.name` of three places joined with a bullet -- the "every office is tried on its own" case. |
| `lever/leverdemo_postings_trimmed.json` | `leverdemo` | The whole posting shape: `categories` (commitment, department, team, allLocations), `country`, `workplaceType`, `salaryRange`, `lists[]`, `createdAt` as epoch milliseconds. The commitment is `Regular Full Time (Salary)`, which is why that field is read as a workload and not as a contract. |
| `lever/lever_empty_postings.json` | `lever` | An **empty board** (`[]`, two bytes). A tenant with no open postings stays valid; it just has no jobs. |
| `ashby/ashby_job_board_trimmed.json` | `ashby` | `?includeCompensation=true`, `descriptionPlain`, `employmentType: FullTime` (which names a workload, not a contract) and `secondaryLocations` with a postal address per location -- one of them in Switzerland, with no municipality, which is exactly the geocode review case. |
| `recruitee/accso_offers_trimmed.json` | `accso` | The richest payload of the six: `employment_type_code: fulltime_permanent` (compound), `experience_code: experienced` (a span, not a step), the three `remote`/`hybrid`/`on_site` booleans, `salary`, `translations`, and a `mailbox_email` this repository deliberately never stores. |
| `smartrecruiters/averydennison_postings_trimmed.json` | `AveryDennison` | A list page with `totalFound: 492`, so the paging walk is tested against a real number, plus `location` with a postal code and an ISO country, `typeOfEmployment`, `experienceLevel`, `function`, `industry` and the employer's own `customField` list. |
| `smartrecruiters/averydennison_posting_detail.json` | `AveryDennison` | The second request: `jobAd.sections` (companyDescription, jobDescription, qualifications, additionalInformation, videos), `postingUrl`, and a `creator` block this repository never stores. |
| `smartrecruiters/smartrecruiters_empty_postings.json` | `smartrecruiters` | `totalFound: 0`: a company with no open postings. |

## ETags at recording time

Five of the six providers serve one, so conditional requests work; the
tags are headers and not part of a body, so they are listed here rather
than in the files.

    greenhouse      figma           W/"dfd20445fb6a17bf67fb14e6cad325df"
    lever           leverdemo       W/"14643-3EYmNGbOeLolfx664boSRCYE2t0"
    lever           lever (empty)   W/"2-l9Fw4VUO7kr8CvBlt4zaMCqXZ0w"
    ashby           ashby           W/"job-board:a9332f8b6cde0252cec7b13..."
    recruitee       accso           (none served)
    smartrecruiters AveryDennison   W/"298bb-KfCjpF0J9TC+k2wM7lZT8fCwIWc"
    smartrecruiters detail          W/"1921-kII0FthUh9xtXcl10I5DzOZPlt8"

## Terms and robots observation

Each adapter module carries its own source check; this is the short
version, all read 2026-10-17.

| Provider | Documented as public? | robots.txt of the API host |
|---|---|---|
| Greenhouse | Yes, and "authentication is not required for any GET endpoints" | `User-agent: * / Disallow: /embed/` -- the API path is not `/embed/`, so allowed |
| Lever | Yes, in Lever's own `postings-api` repository | `Allow: / / Crawl-delay: 1`, and one request a second is what the shared limiter does |
| Ashby | Yes, no authentication documented | the host answers **401** for `/robots.txt`; a 4xx means no rules published |
| Recruitee | Yes: "The public API doesn't require any authentication" | `Disallow: /v/` on a careers site; the API path is not `/v/` |
| SmartRecruiters | Yes, "For public postings only, no authentication is needed" | **`User-agent: * / Disallow: /`, with `Allow: /v1/companies/` for LinkedInBot only.** The one robots tension; see `careeros/feeds/smartrecruiters.py` and question 1 of `data/ats/TRIAL_REPORT.md` |

* **Politeness as recorded.** Every request above went through
  `scripts/polite_http`: the user agent `CareerOS/0.x (+contact: owner)`
  and at least one second between requests.
* **Whose content this is.** The posting text belongs to the employers
  that published it. It is kept here as a test fixture of each API's
  SHAPE, trimmed to one or two postings, and no posting text is
  republished anywhere by this repository. If the owner would rather not
  keep real posting text in the repository at all, the alternative is to
  blank every description value, which costs the description tests their
  only real input; that is an owner call and is flagged in
  `data/ats/TRIAL_REPORT.md` (it was flagged for Personio too).

## Re-recording them

    .venv/bin/python - <<'PY'
    import sys, json; sys.path.insert(0, 'scripts')
    import polite_http
    from pathlib import Path

    base = Path('tests/fixtures/ats')
    limiter = polite_http.RateLimiter()

    def save(path, data):
        (base / path).parent.mkdir(parents=True, exist_ok=True)
        (base / path).write_text(json.dumps(data, ensure_ascii=False, indent=1) + '\n')

    def get(url):
        return json.loads(polite_http.request_text(
            url, limiter=limiter, max_body=32_000_000, timeout=90)['text'])

    data = get('https://boards-api.greenhouse.io/v1/boards/figma/jobs?content=true')
    save('greenhouse/figma_jobs_trimmed.json', {'jobs': data['jobs'][:2]})
    save('lever/leverdemo_postings_trimmed.json',
         get('https://api.lever.co/v0/postings/leverdemo?mode=json')[:2])
    save('lever/lever_empty_postings.json',
         get('https://api.lever.co/v0/postings/lever?mode=json'))
    data = get('https://api.ashbyhq.com/posting-api/job-board/ashby?includeCompensation=true')
    save('ashby/ashby_job_board_trimmed.json',
         {'jobs': data['jobs'][:2], 'apiVersion': data.get('apiVersion')})
    data = get('https://accso.recruitee.com/api/offers/')
    save('recruitee/accso_offers_trimmed.json', {'offers': data['offers'][:2]})
    data = get('https://api.smartrecruiters.com/v1/companies/AveryDennison/postings'
               '?limit=100&offset=0')
    save('smartrecruiters/averydennison_postings_trimmed.json',
         {**{key: data[key] for key in ('offset', 'limit', 'totalFound')},
          'content': data['content'][:2]})
    save('smartrecruiters/averydennison_posting_detail.json',
         get('https://api.smartrecruiters.com/v1/companies/AveryDennison/postings/'
             + data['content'][0]['id']))
    save('smartrecruiters/smartrecruiters_empty_postings.json',
         get('https://api.smartrecruiters.com/v1/companies/smartrecruiters/postings'
             '?limit=100&offset=0'))
    PY

A re-recording will differ: these boards open and close postings. The
tests assert on the SHAPE and on specific recorded postings, so a
re-record means updating the handful of asserts that name an id, a title
or a `totalFound`. That is the cost of testing against real feeds and it
is the cost the brief asks for.
