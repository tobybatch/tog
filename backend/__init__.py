from pathlib import Path

from flask import Flask, abort, redirect, render_template, request, send_from_directory
from backend.routes.api import api_bp

def create_app():
    app = Flask(__name__, static_folder='static', template_folder='templates')

    # Register API blueprints
    app.register_blueprint(api_bp)

    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def catch_all(path):
        if path == 'api' or path.startswith('api/'):
            abort(404)
        if app.debug:
            target = request.full_path if request.query_string else request.path
            return redirect(f'http://localhost:5173{target}')
        if not (Path(app.static_folder) / 'index.html').is_file():
            return render_template('index.html'), 503
        return send_from_directory(app.static_folder, 'index.html')

    return app