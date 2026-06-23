"""API 蓝图注册中心。"""
from __future__ import annotations
from flask import Flask

def register_blueprints(app: Flask) -> None:
    from web.api.dashboard import bp as dashboard_bp
    from web.api.queue import bp as queue_bp
    from web.api.data import bp as data_bp
    from web.api.proxy import bp as proxy_bp
    from web.api.captcha import bp as captcha_bp
    from web.api.config_api import bp as config_bp
    from web.api.parsers import bp as parsers_bp
    from web.api.logs import bp as logs_bp
    from web.api.crawler_control import bp as crawler_bp
    from web.api.images import bp as images_bp

    app.register_blueprint(dashboard_bp, url_prefix='/api/dashboard')
    app.register_blueprint(queue_bp, url_prefix='/api/queue')
    app.register_blueprint(data_bp, url_prefix='/api/data')
    app.register_blueprint(proxy_bp, url_prefix='/api/proxy')
    app.register_blueprint(captcha_bp, url_prefix='/api/captcha')
    app.register_blueprint(config_bp, url_prefix='/api/config')
    app.register_blueprint(parsers_bp, url_prefix='/api/parsers')
    app.register_blueprint(logs_bp, url_prefix='/api/logs')
    app.register_blueprint(crawler_bp, url_prefix='/api/crawler')
    app.register_blueprint(images_bp, url_prefix='/api/images')

    from web.api.cookie_presets import bp as cookie_presets_bp
    app.register_blueprint(cookie_presets_bp, url_prefix='/api/cookie-presets')
