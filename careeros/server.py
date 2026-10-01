"""Flask entry point for the CareerOS shell."""

import argparse
import os
from threading import RLock
from pathlib import Path

from flask import Flask, request, jsonify
from careeros import vault as storage

from careeros.web.pages import companies, experiences, interviews, jobs, search
from careeros.web.theme import page_shell

DEFAULT_VAULT = Path('/root/career-os')


def create_app(vault: str | Path | None = None) -> Flask:
    """Build the app with an explicit, environment, or default vault path."""
    app = Flask(__name__)
    app.config['VAULT_PATH'] = Path(vault if vault is not None else os.environ.get('CAREEROS_VAULT', DEFAULT_VAULT)).expanduser()
    app.add_url_rule('/', 'index', search.build_page)
    for module in (search, experiences, jobs, companies, interviews):
        slug = module.__name__.rsplit('.', 1)[-1]
        app.add_url_rule(f'/{slug}', slug, module.build_page)

    app.add_url_rule('/experiences/new', 'experience_new', experiences.form)
    app.add_url_rule('/experiences/<identifier>', 'experience_detail', experiences.detail)
    app.add_url_rule('/experiences/<identifier>/edit', 'experience_edit', experiences.form)
    write_lock = RLock()

    @app.route('/api/search', methods=['GET', 'POST'])
    def search_api():
        root = app.config['VAULT_PATH']
        if request.method == 'GET':
            return jsonify(storage.load_search(root))
        with write_lock:
            return jsonify(storage.save_search(root, request.get_json()))

    @app.route('/api/experiences', methods=['GET', 'POST'])
    def experience_collection():
        root = app.config['VAULT_PATH']
        if request.method == 'GET':
            return jsonify(storage.list_experiences(root))
        with write_lock:
            return jsonify(storage.save_experience(root, request.get_json())), 201

    @app.route('/api/experiences/<identifier>', methods=['GET', 'PUT', 'POST', 'DELETE'])
    def experience_api(identifier):
        root = app.config['VAULT_PATH']
        with write_lock:
            data = storage.load_experience(root, identifier)
            if data is None:
                return jsonify(error='Position not found.'), 404
            if request.method == 'GET':
                return jsonify(data)
            if request.method == 'DELETE':
                storage.delete_experience(root, identifier)
                return jsonify(deleted=identifier)
            return jsonify(storage.save_experience(root, request.get_json(), identifier))

    @app.errorhandler(ValueError)
    def invalid_data(error):
        return jsonify(error=str(error)), 400

    @app.errorhandler(400)
    @app.errorhandler(415)
    def bad_request(error):
        return jsonify(error='Provide a valid JSON object.'), error.code

    @app.errorhandler(OSError)
    def storage_error(error):
        app.logger.exception('Vault operation failed')
        return jsonify(error='Unable to access the vault. Please try again.'), 500

    @app.errorhandler(404)
    def not_found(error):
        return page_shell(
            'Page not found', '',
            "<section class='card empty-state'><h1>Page not found</h1>"
            "<p class='muted'>This page does not exist. <a href='/search'>Return to Search</a>.</p></section>",
        ), 404

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8788)
    parser.add_argument('--vault', type=Path, default=None)
    args = parser.parse_args()
    create_app(args.vault).run(host=args.host, port=args.port, debug=False)


if __name__ == '__main__':
    main()
