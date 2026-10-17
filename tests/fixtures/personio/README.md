# Recorded Personio feed fixtures

Real responses from Personio's public job XML feeds, **recorded live on
2026-10-17** for CAREER-53 and trimmed to a few positions each. The
adapter's tests run entirely offline against these; nothing in
`tests/` ever opens a socket (`tests/conftest.py`'s `offline` fixture
blocks `urllib.request.build_opener` and DNS for the whole suite).

## Why recorded and not written by hand

The spec says the documentation is old and tells the builder to verify
the field list against real feeds before writing the parser. A fixture
someone typed would encode what the parser expects instead of what
Personio sends, which is exactly the bug the spec is guarding against.
These are byte-for-byte what the server returned, minus the positions
that were cut.

## How they were trimmed

The first N `<position>` blocks are kept **verbatim**, with the XML
declaration, the `<workzag-jobs>` root and every element inside each
kept position untouched. Nothing was edited inside a position: the
German text, the CDATA HTML, the inline styles, the absent fields and the
odd office spellings are all the tenants' own. The trimming rule is in
the command below.

## What each file is for

| File | Tenant | What makes it worth keeping |
|---|---|---|
| `isolutions_de_trimmed.xml` | `isolutions` | A Swiss employer with Zurich offices. `office` is a bare city name (`Zürich`) with `additionalOffices` for Basel and Bern -- the "in scope because one office is in canton Zurich" case. |
| `bring_labs_de_trimmed.xml` | `bring-labs` | German feed, `office` written `CH - Zürich`, with a `DE - Berlin` posting beside it and one posting with `additionalOffices`, no `subcompany` and no `jobDescriptions` text. The whole field list in one file. |
| `bring_labs_en_trimmed.xml` | `bring-labs` | The same tenant's **English** feed: the spec asks for a fixture with English postings. Same ids, different `name` and `jobDescriptions`. |
| `bring_labs_com_de_trimmed.xml` | `bring-labs` | Fetched from **`jobs.personio.com`**, which the spec asks for a fixture of. See the finding below. |
| `bring_labs_fr_unsupported.xml` | `bring-labs` | A language the tenant does **not** publish. The server answers **200**, not 404, with every structural field intact and `<jobDescriptions></jobDescriptions>` empty. This is why `personio.has_descriptions` exists. |
| `mapegy_de_empty.xml` | `mapegy` | An **empty feed** (72 bytes, `<workzag-jobs>` with no positions). The spec: "a tenant with an empty feed stays valid; it just has no open jobs." |
| `knott_de_trimmed.xml` | `knott` | A German manufacturer whose offices read `Eggstätt (EGG)` and `Natzing (NAT)`. This is the feed that caught a geocoder defect during the trial -- splitting on the parenthesis made `EGG` match the Zurich municipality **Egg** and filed eleven German postings in canton Zurich. It is a fixture so that cannot come back. |

## Findings recorded with the fixtures

* **`/xml` is the only endpoint.** `https://{tenant}.jobs.personio.de/xml?language=de`
  answers 200; `.../de/xml` answers **404**. The language is a query
  parameter, not a path segment.
* **`.de` and `.com` are the same career site.** `bring-labs` returned a
  byte-identical body on both hosts, down to the same
  `ETag: "9075d1f9af4b9246c2f6c8b117c2183a"`. The adapter still tries
  `.de` first and records which host answered, because the spec asks for
  it, but no tenant tried was reachable only on `.com`.
* **The feed serves an `ETag`**, so conditional requests work. The tags
  as recorded are listed below; they are not stored in the fixture files
  themselves, because a fixture is a body and an ETag is a header.
* **Fields beyond the spec's mapping table are real and useful**:
  `recruitingCategory`, `keywords`, `occupation` and
  `occupationCategory`. The last two are Personio's own machine-readable
  occupation ids (`product_management` inside `marketing_and_product`),
  which is what the golden-set export stratifies on.

ETags at recording time, for the conditional-request test:

    isolutions      de   "af96ed26ba470c065596965a8060ea47"
    bring-labs      de   "9075d1f9af4b9246c2f6c8b117c2183a"
    bring-labs      en   "f8b31a97d138f2ddbf28a72118f6094f"
    bring-labs .com de   "9075d1f9af4b9246c2f6c8b117c2183a"
    bring-labs      fr   "2c33a9d618895f28b18efa7aa08f7c36"
    mapegy          de   "679e30294f297eac3cd813895d0a31d4"
    knott           de   "3d53f77800dbb63c8a6691d1debe0f95"

## Terms and robots observation

* **The feed is published for machine consumption.** Personio documents
  `https://{company}.jobs.personio.de/xml` as the way to put a career
  site's jobs on another website, needs no credentials for it, and lists
  the language parameter values
  (https://developer.personio.de/v1.0/reference/get_xml).
* **robots.txt allows it.** `https://bring-labs.jobs.personio.de/robots.txt`,
  checked 2026-10-17, is:

      User-agent: *
      Allow: /

  So there is no robots tension for the feeds at all -- unlike the
  Common Crawl index, whose own `Disallow: /` and the reasoning applied
  to it are recorded in `careeros/feeds/discovery.py`.
* **Politeness as recorded.** Every request above went through
  `scripts/polite_http`: the user agent
  `CareerOS/0.x (+contact: owner)` and at least one second between
  requests.
* **Whose content this is.** The posting text belongs to the employers
  that published it. It is kept here as a test fixture of the feed's
  SHAPE, trimmed to a few positions, and no posting text is republished
  anywhere by this repository. If the owner would rather not keep real
  posting text in the repository at all, the alternative is to keep only
  the structural elements and blank every `jobDescription` value, which
  costs the description-concatenation test its only real input; that is
  an owner call and is flagged in `data/personio/TRIAL_REPORT.md`.

## Re-recording them

    .venv/bin/python - <<'PY'
    import sys; sys.path.insert(0, 'scripts')
    import polite_http
    from pathlib import Path

    def trim(xml, keep):
        head, _, rest = xml.partition('<position>')
        blocks = ('<position>' + rest).split('</position>')
        kept = '</position>'.join(blocks[:keep]) + ('</position>\n' if keep else '')
        return head + kept + '\n</workzag-jobs>\n'

    limiter = polite_http.RateLimiter()
    for name, url, keep in [
        ('isolutions_de_trimmed.xml', 'https://isolutions.jobs.personio.de/xml?language=de', 3),
        ('bring_labs_de_trimmed.xml', 'https://bring-labs.jobs.personio.de/xml?language=de', 3),
        ('bring_labs_en_trimmed.xml', 'https://bring-labs.jobs.personio.de/xml?language=en', 2),
        ('bring_labs_com_de_trimmed.xml', 'https://bring-labs.jobs.personio.com/xml?language=de', 1),
        ('bring_labs_fr_unsupported.xml', 'https://bring-labs.jobs.personio.de/xml?language=fr', 3),
        ('mapegy_de_empty.xml', 'https://mapegy.jobs.personio.de/xml?language=de', 0),
        ('knott_de_trimmed.xml', 'https://knott.jobs.personio.de/xml?language=de', 2),
    ]:
        result = polite_http.request_text(url, limiter=limiter, max_body=32_000_000)
        body = trim(result['text'], keep) if keep else result['text']
        Path('tests/fixtures/personio', name).write_text(body)
    PY

A re-recording will differ: these tenants' postings open and close. The
tests assert on the SHAPE and on specific recorded postings, so a
re-record means updating the handful of asserts that name an id or a
title. That is the cost of testing against real feeds and it is the cost
the spec asks for.
