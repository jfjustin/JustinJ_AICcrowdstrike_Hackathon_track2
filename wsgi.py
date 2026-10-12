"""Azure App Service (and any gunicorn-based host) entrypoint.

Oryx's default Linux Python startup command is `gunicorn ... app:app` — this
file gives it a top-level `app` object without needing a custom startup
command, while app/main.py's create_app() factory stays the single source
of truth for route wiring.
"""
from app.main import create_app

app = create_app()
