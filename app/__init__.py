"""
Tasklings application factory.
"""
from quart import Quart, jsonify, request as quart_request

from app.config import Config


def create_app(config: Config | None = None) -> Quart:
    """Create and configure the Quart application."""
    app = Quart(
        __name__,
        template_folder="templates",
        static_folder="static",
    )

    # Load config
    cfg = config or Config.from_env()
    app.config.from_mapping(
        SECRET_KEY=cfg.SECRET_KEY,
        DATABASE_PATH=cfg.DATABASE_PATH,
        SESSION_LIFETIME_HOURS=cfg.SESSION_LIFETIME_HOURS,
        HOUSEHOLD_TIMEZONE=cfg.HOUSEHOLD_TIMEZONE,
        BCRYPT_ROUNDS=cfg.BCRYPT_ROUNDS,
        TESTING=cfg.TESTING,
        SMTP_HOST=cfg.SMTP_HOST,
        SMTP_PORT=cfg.SMTP_PORT,
        SMTP_USERNAME=cfg.SMTP_USERNAME,
        SMTP_PASSWORD=cfg.SMTP_PASSWORD,
        SMTP_FROM=cfg.SMTP_FROM,
    )

    # -----------------------------------------------------------------------
    # DB lifecycle hooks
    # -----------------------------------------------------------------------
    from app.models.db import init_db, close_db

    @app.before_serving
    async def startup():
        await init_db(app)

    app.teardown_request(close_db)

    # -----------------------------------------------------------------------
    # Auth middleware -- resolve current_user on every request
    # -----------------------------------------------------------------------
    from app.middleware.auth import resolve_user, inject_current_user

    app.before_request(resolve_user)
    app.context_processor(inject_current_user)

    # -----------------------------------------------------------------------
    # UUID path-parameter validation
    # API routes use UUIDs as path params; malformed values must 404, not 500.
    # -----------------------------------------------------------------------
    from app.middleware.validation import is_valid_uuid

    @app.before_request
    async def validate_uuid_path_params():
        """
        For API routes, validate every path segment that Quart matched as a
        named parameter whose name ends with '_id'. Returns 404 JSON for any
        segment that is not a well-formed UUID.

        This prevents SQLite from receiving junk strings and prevents 500s.
        """
        if not quart_request.path.startswith("/api/"):
            return None
        view_args = quart_request.view_args or {}
        for key, value in view_args.items():
            if key.endswith("_id") and not is_valid_uuid(str(value)):
                return (
                    jsonify({"error": "Not found.", "code": "NOT_FOUND"}),
                    404,
                )
        return None

    # -----------------------------------------------------------------------
    # Security headers -- after_request hook
    # -----------------------------------------------------------------------
    @app.after_request
    async def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        # CSP: allow HTMX CDN, same-origin scripts/styles, no inline eval.
        csp = (
            "default-src 'self'; "
            "script-src 'self' https://unpkg.com 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self'; "
            "font-src 'self'; "
            "frame-ancestors 'none';"
        )
        response.headers["Content-Security-Policy"] = csp
        return response

    # -----------------------------------------------------------------------
    # Blueprints -- views
    # -----------------------------------------------------------------------
    from app.routes.views.admin import admin_views
    from app.routes.views.auth import auth_views_bp
    from app.routes.views.profile import profile_views
    from app.routes.views.quests import quests_views
    from app.routes.views.runlist import runlist_views
    from app.routes.views.store import store_views

    app.register_blueprint(auth_views_bp)
    app.register_blueprint(runlist_views)
    app.register_blueprint(store_views)
    app.register_blueprint(quests_views)
    app.register_blueprint(profile_views)
    app.register_blueprint(admin_views)

    # -----------------------------------------------------------------------
    # Blueprints -- API
    # -----------------------------------------------------------------------
    from app.routes.api.admin import admin_api_bp
    from app.routes.api.assignments import assignments_api
    from app.routes.api.auth import auth_api_bp
    from app.routes.api.chores import chores_api
    from app.routes.api.group_quests import group_quests_api
    from app.routes.api.members import members_api
    from app.routes.api.quests import quests_api
    from app.routes.api.store import store_api
    from app.routes.api.sync import sync_api
    from app.routes.api.tokens import tokens_api_bp
    from app.routes.api.transactions import transactions_api

    app.register_blueprint(auth_api_bp)
    app.register_blueprint(tokens_api_bp)
    app.register_blueprint(admin_api_bp)
    app.register_blueprint(assignments_api)
    app.register_blueprint(chores_api)
    app.register_blueprint(members_api)
    app.register_blueprint(quests_api)
    app.register_blueprint(group_quests_api)
    app.register_blueprint(store_api)
    app.register_blueprint(transactions_api)
    app.register_blueprint(sync_api)

    return app
