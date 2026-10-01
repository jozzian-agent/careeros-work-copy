"""Experience library, detail and shared add/edit form."""
from flask import abort, current_app
from markupsafe import Markup
from careeros import vault
from careeros.web.markdown import render_markdown
from careeros.web.ui import page

EMPTY_STATE = 'No positions yet — add your first one'

def root():
    return current_app.config['VAULT_PATH']

def get(identifier):
    data = vault.load_experience(root(), identifier)
    if data is None:
        abort(404)
    return data

def build_page():
    return page('Experiences', 'experiences', 'experiences.html', entries=vault.list_experiences(root()), empty=EMPTY_STATE)

def detail(identifier):
    data = get(identifier)
    return page(data['title'], 'experiences', 'detail.html', exp=data, markdown=Markup(render_markdown(data.get('detail', ''))))

def form(identifier=None):
    data = get(identifier) if identifier else {}
    return page('Edit position' if identifier else 'Add position', 'experiences', 'experience_form.html', exp=data)
