import atexit
import threading

import click
from flask.cli import with_appcontext

from .challenge_lifecycle import close_expired_challenges
from .extensions import mongo
from .mail_notifications import mail_configuration, materialize_events, process_outbox
from .utils import now


def maintenance_tick():
    closed = close_expired_challenges()
    queued = materialize_events()
    sent = process_outbox()
    return {"closed": closed, "queued": queued, "sent": sent}


def worker_loop(app, stop):
    interval = max(1, int(app.config.get("JOBS_INTERVAL_SECONDS", 30)))
    while not stop.is_set():
        try:
            with app.app_context():
                maintenance_tick()
        except Exception as error:
            app.logger.error("Falha no processamento de avisos automáticos: %s", type(error).__name__)
        stop.wait(interval)


def start_background_jobs(app):
    if not app.config.get("BACKGROUND_JOBS_ENABLED", True):
        return
    if app.extensions.get("return_tech_jobs"):
        return
    stop = threading.Event()
    thread = threading.Thread(target=worker_loop, args=(app, stop), daemon=True, name="return-tech-notifications")
    app.extensions["return_tech_jobs"] = {"thread": thread, "stop": stop}
    atexit.register(stop.set)
    thread.start()


@click.command("worker")
@click.option("--once", is_flag=True, help="Processa uma rodada e encerra.")
@with_appcontext
def worker_command(once):
    """Processar prazos e e-mails fora do servidor web."""
    if once:
        click.echo(maintenance_tick())
        return
    from flask import current_app
    worker_loop(current_app._get_current_object(), threading.Event())


@click.command("mail-status")
@with_appcontext
def mail_status():
    """Mostrar o estado do envio sem expor credenciais ou destinatários."""
    state = mail_configuration()
    click.echo(f"Envio ativado: {state['enabled']}; configuração completa: {state['configured']}")
    if state["missing"]:
        click.echo("Campos pendentes: " + ", ".join(state["missing"]))
    for status in ("pending", "sending", "sent", "failed"):
        click.echo(f"{status}: {mongo.db.email_outbox.count_documents({'status': status})}")


@click.command("retry-failed-emails")
@with_appcontext
def retry_failed_emails():
    """Recolocar os avisos que falharam na fila após corrigir a configuração."""
    result = mongo.db.email_outbox.update_many({"status": "failed"},
        {"$set": {"status": "pending", "attempts": 0, "next_attempt_at": now()}, "$unset": {"last_error": ""}})
    click.echo(f"Avisos recolocados na fila: {result.modified_count}")
