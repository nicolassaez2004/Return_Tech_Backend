import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    from app.jobs import start_background_jobs
    debug = os.getenv("FLASK_DEBUG", "1") == "1"
    if not debug or os.getenv("WERKZEUG_RUN_MAIN") == "true":
        start_background_jobs(app)
    app.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "5000")),
        debug=debug,
    )

