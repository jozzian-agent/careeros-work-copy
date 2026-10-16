"""Protects the D7 board data: one status vocabulary, the open and ended
split, the closed-posting flag with its week-old review list, the "Your
search so far" counts, and the words history gives a move and its reason.

`board_context` is pure, so most of these are record snapshots rather
than vaults.
"""
from datetime import date

import pytest

from careeros import history, vault, watcher
from careeros.server import create_app
from careeros.web.pages import jobs

TODAY = date(2026, 10, 15)
URL = 'https://fiction.example/job'


def job(identifier='JOB-001', **fields):
    return {'id': identifier, 'title': 'Builder', 'status': 'new'} | fields


def context(entries, today=TODAY):
    return jobs.board_context(list(entries), [], {}, today=today)


def moved(*pairs):
    """A history of status moves, in the shape the vault records them."""
    return [{'ts': f'2026-10-0{index + 1}T09:00:00+00:00', 'event': 'status_changed',
             'detail': f'{old} -> {new}'}
            for index, (old, new) in enumerate(pairs)]


# --- the vocabulary -------------------------------------------------------

def test_the_statuses_are_the_owner_list_in_order():
    """Decision D7: eight statuses, in the order a job moves through them,
    and the ended three are the last three."""
    assert vault.STATUSES == ('new', 'interested', 'applied', 'interviewing',
                              'offer', 'won', 'rejected', 'stopped')
    assert vault.ENDED_STATUSES == ('won', 'rejected', 'stopped')
    assert vault.OPEN_STATUSES == ('new', 'interested', 'applied', 'interviewing', 'offer')


def test_closed_and_withdrawn_are_not_statuses():
    """Closed is a flag about the posting and Stopped replaced Withdrawn,
    so neither word is a status any more, and the vault refuses one."""
    assert 'closed' not in vault.STATUSES
    assert 'withdrawn' not in vault.STATUSES


@pytest.mark.parametrize('status', ['closed', 'withdrawn'])
def test_the_vault_refuses_a_retired_status(tmp_path, status):
    saved = vault.save_job(tmp_path, {'title': 'Builder', 'url': URL})
    with pytest.raises(ValueError):
        vault.save_job(tmp_path, {'status': status}, saved['id'])


def test_every_status_has_one_owner_facing_word():
    assert list(vault.STATUS_LABELS) == list(vault.STATUSES)
    assert list(vault.STATUS_LABELS.values()) == [
        'New', 'Interested', 'Applied', 'Interviewing', 'Offer', 'Won', 'Rejected', 'Stopped']


def test_the_board_payload_carries_the_vocabulary_and_the_words():
    result = context([job()])
    assert result['statuses'] == vault.STATUSES
    assert result['ended_statuses'] == vault.ENDED_STATUSES
    assert result['status_labels'] == vault.STATUS_LABELS
    assert result['end_reasons'] == {'stopped': list(vault.STOPPED_REASONS),
                                      'rejected': list(vault.REJECTED_REASONS)}
    assert result['end_note_title'] == vault.END_NOTE_TITLE


def test_the_job_page_shows_the_same_list_as_the_board():
    """Two surfaces expose the status list; one vocabulary feeds both."""
    page = jobs.job_context(job(), None, {})
    assert page['statuses'] == context([job()])['statuses']


def test_the_ending_suggestions_are_the_owner_words():
    assert vault.STOPPED_REASONS == ('Not interested anymore', 'Salary or conditions',
                                     'Location or commute', 'Took another offer',
                                     'Withdrew application', 'Posting closed', 'No response')
    assert vault.REJECTED_REASONS == ('No reason given', 'After interview',
                                      'Experience did not match', 'Position filled')
    assert set(vault.END_REASONS) == {'stopped', 'rejected'}


def test_a_reason_outside_the_suggestions_is_refused(tmp_path):
    saved = vault.save_job(tmp_path, {'title': 'Builder', 'url': URL})
    with pytest.raises(ValueError):
        vault.save_job(tmp_path, {'end_reason': 'Because'}, saved['id'])
    kept = vault.save_job(tmp_path, {'status': 'stopped', 'end_reason': 'No response'}, saved['id'])
    assert kept['end_reason'] == 'No response'


# --- the open and ended split --------------------------------------------

def test_the_split_counts_the_two_ends_of_the_board():
    entries = [job(f'JOB-{index}', status=status) for index, status in enumerate(vault.STATUSES)]
    assert context(entries)['counts'] == {'open': 5, 'ended': 3}


def test_a_job_with_no_status_counts_as_open():
    assert context([{'id': 'JOB-001', 'title': 'Builder'}])['counts'] == {'open': 1, 'ended': 0}


# --- the closed posting and its review -----------------------------------

def closed(identifier='JOB-001', status='interested', days=8, **fields):
    """A job whose posting was found gone `days` ago."""
    gone = date.fromordinal(TODAY.toordinal() - days)
    return job(identifier, status=status, closed=True, closed_at=gone.isoformat(), **fields)


def test_a_week_old_closed_posting_on_an_unapplied_job_is_asked_about():
    result = context([closed(days=8)])
    assert result['closed_review'] == [{'id': 'JOB-001', 'closed_at': '2026-10-07', 'days_closed': 8}]


@pytest.mark.parametrize('days', [0, 1, 7])
def test_a_closed_posting_inside_the_week_is_not_asked_about(days):
    assert context([closed(days=days)])['closed_review'] == []


@pytest.mark.parametrize('status', ['applied', 'interviewing', 'offer', 'won', 'rejected', 'stopped'])
def test_a_job_the_owner_applied_to_is_never_asked_about(status):
    """A closed posting does not end an application, so only the statuses
    before Applied raise the question."""
    assert context([closed(status=status)])['closed_review'] == []


def test_a_job_the_owner_kept_is_not_asked_about_again():
    """The Keep action stamps closed_reviewed_at, and that is the whole
    mechanism: the job keeps its flag and leaves the list."""
    kept = closed(closed_reviewed_at='2026-10-14')
    assert context([kept])['closed_review'] == []


def test_a_closed_posting_with_no_date_is_not_asked_about():
    """Without a date there is no week to measure, so the banner says
    nothing rather than claiming what the record does not."""
    assert context([job(closed=True, status='interested')])['closed_review'] == []


def test_an_open_posting_is_not_asked_about():
    assert context([job(status='interested', closed_at='2026-01-01')])['closed_review'] == []


def test_the_keep_marker_goes_through_the_generic_job_put(tmp_path):
    saved = vault.save_job(tmp_path, {'title': 'Builder', 'url': URL, 'status': 'interested',
                                       'closed': True, 'closed_at': '2026-01-01'})
    client = create_app(tmp_path).test_client()
    board = client.get('/api/jobs?view=board').get_json()
    assert [row['id'] for row in board['closed_review']] == [saved['id']]
    kept = client.put(f"/api/jobs/{saved['id']}", json={'closed_reviewed_at': date.today().isoformat()})
    assert kept.status_code == 200
    assert kept.get_json()['closed'] is True
    assert client.get('/api/jobs?view=board').get_json()['closed_review'] == []


def test_a_gone_posting_sets_the_flag_and_leaves_the_status_alone(tmp_path):
    """The watcher records a fact about the posting. Ending the job is
    the owner's decision, and this is not it."""
    from urllib.error import HTTPError

    saved = vault.save_job(tmp_path, {'title': 'Builder', 'url': 'https://fiction.example/job',
                                       'status': 'interested'})

    def gone(url):
        raise HTTPError(url, 404, 'failure', {}, None)

    events = watcher.scan(tmp_path, fetch=gone)
    assert [event['event'] for event in events] == ['posting_gone']
    stored = vault.load_job(tmp_path, saved['id'])
    assert stored['closed'] is True
    assert stored['closed_at'] == date.today().isoformat()
    assert stored['status'] == 'interested'


def test_a_posting_found_gone_again_keeps_the_day_it_went(tmp_path):
    """closed_at is the day the posting was first missed, which is the day
    the week is counted from."""
    from urllib.error import HTTPError

    saved = vault.save_job(tmp_path, {'title': 'Builder', 'url': 'https://fiction.example/job',
                                       'closed': True, 'closed_at': '2026-09-01'})

    def gone(url):
        raise HTTPError(url, 404, 'failure', {}, None)

    watcher.scan(tmp_path, fetch=gone)
    assert vault.load_job(tmp_path, saved['id'])['closed_at'] == '2026-09-01'


# --- your search so far --------------------------------------------------

def test_the_counts_read_history_including_ended_jobs():
    entries = [
        job('JOB-001', status='stopped', history=moved(('new', 'applied'), ('applied', 'stopped'))),
        job('JOB-002', status='rejected', history=moved(('applied', 'interviewing'),
                                                        ('interviewing', 'rejected'))),
        job('JOB-003', status='offer', history=moved(('interviewing', 'offer'))),
        job('JOB-004', status='interested'),
    ]
    assert context(entries)['search_so_far'] == {'applied_to': 3, 'interviews': 2, 'offers': 1}


def test_a_job_written_straight_into_a_status_counts_without_history():
    assert context([job(status='applied')])['search_so_far']['applied_to'] == 1


def test_a_job_won_straight_off_the_interested_column_still_counts_as_applied_to():
    """Dropping a card onto the Won lane from Interested is a path the
    brief allows, and you cannot win a job you did not apply to
    (review MUST-FIX 2, 2026-10-15)."""
    entries = [job('JOB-001', status='won', history=moved(('new', 'interested'), ('interested', 'won')))]
    assert context(entries)['search_so_far']['applied_to'] == 1


def test_the_most_common_reason_to_stop_is_left_out_while_nobody_has_one():
    entries = [job('JOB-001', status='stopped'), job('JOB-002', status='rejected')]
    assert 'top_stopped_reason' not in context(entries)['search_so_far']


def test_the_most_common_reason_to_stop_comes_with_its_count():
    entries = [job('JOB-001', status='stopped', end_reason='No response'),
               job('JOB-002', status='stopped', end_reason='No response'),
               job('JOB-003', status='stopped', end_reason='Salary or conditions'),
               job('JOB-004', status='rejected', end_reason='Position filled')]
    assert context(entries)['search_so_far']['top_stopped_reason'] == {'reason': 'No response', 'count': 2}


def test_a_tie_goes_to_the_earlier_suggestion():
    """Two reasons with the same count must always report the same way, so
    the suggestion list order decides."""
    entries = [job('JOB-001', status='stopped', end_reason='No response'),
               job('JOB-002', status='stopped', end_reason='Salary or conditions')]
    assert context(entries)['search_so_far']['top_stopped_reason'] == {'reason': 'Salary or conditions',
                                                                        'count': 1}


def test_a_reason_on_a_job_that_is_no_longer_stopped_is_not_counted():
    """Dragging an ended job back to an open column keeps its reason, and
    the stat is about jobs the owner stopped."""
    entries = [job('JOB-001', status='applied', end_reason='No response')]
    assert 'top_stopped_reason' not in context(entries)['search_so_far']


# --- the words history uses ----------------------------------------------

def test_a_move_reads_as_plain_words(tmp_path):
    saved = vault.save_job(tmp_path, {'title': 'Builder', 'url': URL, 'status': 'applied'})
    client = create_app(tmp_path).test_client()
    client.put(f"/api/jobs/{saved['id']}", json={'status': 'stopped'})
    page = client.get(f"/api/jobs/{saved['id']}?view=page").get_json()
    assert 'Status changed from Applied to Stopped' in [entry['label'] for entry in page['history']]


def test_a_reason_reads_as_the_status_and_the_reason(tmp_path):
    saved = vault.save_job(tmp_path, {'title': 'Builder', 'url': URL, 'status': 'applied'})
    client = create_app(tmp_path).test_client()
    client.put(f"/api/jobs/{saved['id']}", json={'status': 'stopped'})
    client.put(f"/api/jobs/{saved['id']}", json={'end_reason': 'Salary or conditions'})
    page = client.get(f"/api/jobs/{saved['id']}?view=page").get_json()
    assert [entry['label'] for entry in page['history']] == [
        'Job added', 'Status changed from Applied to Stopped', 'Stopped: Salary or conditions']


def test_a_reason_is_recorded_once(tmp_path):
    """Saving the same reason again changes nothing, so the history does
    not fill up with one decision."""
    saved = vault.save_job(tmp_path, {'title': 'Builder', 'url': URL, 'status': 'stopped',
                                       'end_reason': 'No response'})
    again = vault.save_job(tmp_path, {'end_reason': 'No response'}, saved['id'])
    assert [event['event'] for event in again['history']].count('end_reason_set') == 1


def test_every_d7_status_moves_through_the_generic_put(tmp_path):
    saved = vault.save_job(tmp_path, {'title': 'Builder', 'url': URL})
    client = create_app(tmp_path).test_client()
    for status in vault.STATUSES:
        response = client.put(f"/api/jobs/{saved['id']}", json={'status': status})
        assert response.status_code == 200, status
        assert response.get_json()['status'] == status
    labels = [entry['label'] for entry in
              history.resolve(vault.load_job(tmp_path, saved['id'])['history'])]
    assert 'Status changed from Offer to Won' in labels


def test_winning_a_job_leaves_every_other_job_alone(tmp_path):
    """Won needs no behaviour of its own: nothing happens to other jobs."""
    first = vault.save_job(tmp_path, {'title': 'Builder', 'url': URL, 'status': 'offer'})
    second = vault.save_job(tmp_path, {'title': 'Other', 'url': URL + '-other', 'status': 'applied'})
    client = create_app(tmp_path).test_client()
    client.put(f"/api/jobs/{first['id']}", json={'status': 'won'})
    assert vault.load_job(tmp_path, second['id'])['status'] == 'applied'
