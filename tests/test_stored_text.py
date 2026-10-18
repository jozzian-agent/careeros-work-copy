"""The storage boundary for extracted text (brief 2026-10-18, section 6):
that markup and entity escapes never reach a stored field, that an
employer's internal site code never reaches a company name, and that a
careers page's own heading is never stored as a job title."""
import pytest

from careeros import ingest, intake
from careeros.feeds import base, greenhouse
from careeros.web.pages.jobs import needs_attention


# --- plain_text -----------------------------------------------------------

@pytest.mark.parametrize('raw, expected', [
    # The vault's own JOB-047, which is what sent the owner looking.
    ('Lead Business &amp; Technology Engineering (w/m/d),<br/>80-100% Zürich / hybrid',
     'Lead Business & Technology Engineering (w/m/d), 80-100% Zürich / hybrid'),
    ('<p class="x">Product Owner</p>', 'Product Owner'),
    ('Head of <strong>Digital</strong>', 'Head of Digital'),
    ('Smith &amp; Co', 'Smith & Co'),
    ('Zug&nbsp;&amp;&nbsp;Zurich', 'Zug & Zurich'),
    # An escaped tag is still not text a record should hold.
    ('One&lt;br&gt;Two', 'One Two'),
    # Posting prose that only looks like markup survives.
    ('Salary < 100k', 'Salary < 100k'),
    ('a > b', 'a > b'),
    ('I <3 this role', 'I <3 this role'),
    # A description's own lines survive; the spaces between words do not
    # multiply.
    ('First line\nSecond   line', 'First line\nSecond line'),
    ('Para one\n\n\n\nPara two', 'Para one\n\nPara two'),
    ('  padded  ', 'padded'),
    ('', ''),
])
def test_plain_text(raw, expected):
    assert ingest.plain_text(raw) == expected


def test_plain_text_is_idempotent():
    once = ingest.plain_text('A &amp; B<br/>C')
    assert ingest.plain_text(once) == once


def test_strip_markup_reaches_nested_values():
    payload = {'title': 'A<br/>B', 'skills': ['x &amp; y'], 'count': 3, 'flag': True,
               'nested': {'summary': '<p>text</p>'}}
    assert ingest.strip_markup(payload) == {
        'title': 'A B', 'skills': ['x & y'], 'count': 3, 'flag': True,
        'nested': {'summary': 'text'},
    }


def test_clean_extracted_still_redacts():
    dropped = []
    assert ingest.clean_extracted('<b>10.1.2.3</b>', dropped, 'title') == ''
    assert dropped == ['title']


# --- the scrape boundary --------------------------------------------------

def schema_html(title='Product Owner', company='Northwind Systems'):
    return ('<html><head><script type="application/ld+json">'
            '{"@type": "JobPosting", "title": "' + title + '",'
            ' "description": "A role.",'
            ' "hiringOrganization": {"@type": "Organization", "name": "' + company + '"}}'
            '</script></head><body><p>A role.</p></body></html>')


def test_a_scraped_title_is_stored_as_plain_text():
    data = intake.extract('https://example.test/jobs/1',
                          schema_html(title='Lead Engineering (w/m/d),<br/>80-100%'))
    assert data['title'] == 'Lead Engineering (w/m/d), 80-100%'


def test_a_scraped_employer_name_loses_a_leading_site_code():
    data = intake.extract('https://thomsonreuters.wd5.myworkdayjobs.com/en-US/x/details/A_JREQ1',
                          schema_html(company='CHE003 Thomson Reuters Enterprise Centre GmbH'))
    assert data['company'] == 'Thomson Reuters Enterprise Centre GmbH'
    assert data['employer_named_in_posting'] == 'Thomson Reuters Enterprise Centre GmbH'


@pytest.mark.parametrize('name', [
    'BMW 320 Service AG',       # an abbreviation and a number, space between
    'ABC12 Holdings',           # too few digits
    'ABCD123 Holdings',         # too many letters
    'abc123 Holdings',          # lower case
])
def test_a_real_company_name_keeps_every_word(name):
    assert ingest.company_name_text(name) == name


def test_a_name_that_is_only_a_code_is_kept_rather_than_emptied():
    assert ingest.company_name_text('CHE003') == 'CHE003'


# --- a careers page is not a job title ------------------------------------

@pytest.mark.parametrize('heading', sorted(ingest.GENERIC_HEADINGS))
def test_every_generic_heading_is_recognised_whatever_its_case(heading):
    assert ingest.is_generic_heading(heading.upper())
    assert ingest.is_generic_heading(heading.title())


@pytest.mark.parametrize('title', ['Job Offers Manager', 'Careers Advisor', 'Head of Jobs'])
def test_a_real_title_that_contains_one_of_those_words_is_still_a_title(title):
    assert not ingest.is_generic_heading(title)


@pytest.mark.parametrize('heading', ['Job Offers', 'Careers and jobs', 'Stellenangebote'])
def test_a_generic_heading_is_never_stored_as_the_title(heading):
    data = intake.extract('https://finders.test/en/candidates/job-offers/',
                          schema_html(title=heading, company='Finders'))
    assert data['title'] == 'Finders opportunity'
    assert data['field_status_reason'] == {'title': ingest.NO_TITLE_REASON}


def test_a_job_with_no_evidenced_title_asks_the_owner_for_one():
    data = intake.extract('https://finders.test/en/candidates/job-offers/',
                          schema_html(title='Job Offers', company='Finders'))
    assert needs_attention({'field_status_reason': data['field_status_reason']}) is True


def test_a_posting_that_names_a_role_reports_no_reason():
    data = intake.extract('https://example.test/jobs/1', schema_html())
    assert 'field_status_reason' not in data
    assert needs_attention({'title': data['title']}) is False


def test_a_model_answer_that_is_a_page_heading_never_replaces_a_title():
    parser = intake.Posting()
    parser.feed(schema_html())
    schema = intake.job_schema(parser, 'https://example.test/jobs/1')
    data = intake._extract('https://example.test/jobs/1', parser, schema)
    merged = intake._merge_extracted(data, {'title': 'Careers', 'ingest_source': 'llm'},
                                     schema, parser)
    assert merged['title'] == 'Product Owner'


# --- the feed boundary ----------------------------------------------------

def greenhouse_posting(title, company):
    raw = {'id': 991, 'title': title, 'company_name': company,
           'absolute_url': 'https://boards.greenhouse.io/acme/jobs/991',
           'content': '&lt;p&gt;A role.&lt;/p&gt;',
           'location': {'name': 'Z&amp;rich'},
           'departments': [{'name': 'Product &amp; Design'}], 'offices': [],
           'first_published': '2026-10-01', 'updated_at': '2026-10-02'}
    return greenhouse.map_posting(raw, tenant='acme', variant=None, guide_version='1')


def test_a_feed_posting_is_stored_as_plain_text():
    mapped = greenhouse_posting('Senior PM &amp; Lead<br/>80-100%', 'Acme AG')
    assert mapped['title'] == 'Senior PM & Lead 80-100%'
    assert mapped['department'] == 'Product & Design'
    assert mapped['location_raw'] == 'Z&rich'


def test_a_feed_employer_name_loses_a_leading_site_code():
    mapped = greenhouse_posting('Product Owner', 'CHE003 Acme Enterprise Centre GmbH')
    assert mapped['employer_name'] == 'Acme Enterprise Centre GmbH'


def test_the_feed_content_hash_is_taken_over_what_is_stored():
    first = greenhouse_posting('Senior PM &amp; Lead', 'Acme AG')
    second = greenhouse_posting('Senior PM & Lead', 'Acme AG')
    assert first['content_hash'] == second['content_hash']


def test_the_text_fields_finalize_cleans_are_the_prose_ones_only():
    # A provider id, a tenant, a url and a posting id are data, so they
    # are deliberately absent from the list.
    assert 'provider' not in base.TEXT_FIELDS
    assert 'tenant' not in base.TEXT_FIELDS
    assert 'url' not in base.TEXT_FIELDS
    assert 'posting_id' not in base.TEXT_FIELDS
