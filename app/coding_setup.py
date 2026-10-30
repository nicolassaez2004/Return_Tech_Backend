"""Coding module startup and optional durable polling worker."""
import time

import click

from .extensions import mongo
from .services.coding import refresh_job
from .services.judge0 import Judge0Client, Judge0Error


def setup_coding(app):
    app.extensions["judge0_client"] = Judge0Client(app.config)
    from .routes.coding import coding_bp
    app.register_blueprint(coding_bp, url_prefix="/api")
    with app.app_context():
        mongo.db.coding_configs.create_index("challenge_id", unique=True)
        mongo.db.coding_scores.create_index([("challenge_id", 1), ("talent_id", 1)], unique=True)
        mongo.db.coding_jobs.create_index([("challenge_id", 1), ("talent_id", 1), ("created_at", -1)])
        mongo.db.coding_jobs.create_index(
            [("challenge_id", 1), ("talent_id", 1)], unique=True,
            partialFilterExpression={"active": True}, name="one_active_code_job",
        )
        mongo.db.coding_jobs.create_index([("status", 1), ("created_at", 1)])

    @app.cli.command("process-code-jobs")
    @click.option("--watch", is_flag=True, help="Continue consultando a fila a cada 2 segundos.")
    def process_code_jobs(watch):
        """Finalize jobs even after candidates close their browsers."""
        while True:
            count = 0
            # Poll sequentially: a second worker can safely share the database leases.
            for job in mongo.db.coding_jobs.find({"$or": [
                {"status": {"$in": ["creating", "processing"]}},
                {"status": "completed", "mode": "submit", "score_recorded": {"$ne": True}},
            ]}).limit(50):
                try:
                    updated = refresh_job(job)
                    count += updated["status"] in {"completed", "service_error"}
                except Judge0Error:
                    app.logger.warning("Executor indisponível; a tentativa permanece pendente.")
            click.echo(f"Execuções finalizadas: {count}")
            if not watch:
                return
            time.sleep(2)
