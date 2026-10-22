from flask import Blueprint, jsonify, render_template

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/health')
def health_check():
    return jsonify({"status": "ok"})