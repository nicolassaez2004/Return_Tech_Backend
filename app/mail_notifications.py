"""Durable event delivery for transactional e-mails, one recipient per message."""
import hashlib
import os
import smtplib
import ssl
from datetime import timedelta
from email.headerregistry import Address
from email.message import EmailMessage
from email.utils import format_datetime
from html import escape
from uuid import uuid4

from flask import current_app
from pymongo import ASCENDING, ReturnDocument

from .extensions import mongo
from .utils import now


def env_bool(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def configure_mail(app):
    app.config.update(
        MAIL_ENABLED=env_bool("MAIL_ENABLED"),
        MAIL_SERVER=os.getenv("MAIL_SERVER", "smtp.gmail.com"),
        MAIL_PORT=int(os.getenv("MAIL_PORT", "587")),
        MAIL_USE_TLS=env_bool("MAIL_USE_TLS", True),
        MAIL_USE_SSL=env_bool("MAIL_USE_SSL"),
        MAIL_USERNAME=os.getenv("MAIL_USERNAME", "").strip(),
        MAIL_PASSWORD=os.getenv("MAIL_PASSWORD", ""),
        MAIL_FROM=os.getenv("MAIL_FROM", os.getenv("MAIL_USERNAME", "")).strip(),
        MAIL_FROM_NAME=os.getenv("MAIL_FROM_NAME", "Return Tech"),
        MAIL_APP_URL=os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/"),
        MAIL_TIMEOUT_SECONDS=15,
        MAIL_BATCH_SIZE=20,
        MAIL_MAX_ATTEMPTS=5,
        MAIL_LEASE_SECONDS=300,
    )


def mail_event(kind, challenge, recipient_id=None):
    # Embedded in the same atomic write as the action; the worker can recover it
    # even if the server stops immediately after confirming that action.
    return {
        "id": uuid4().hex, "kind": kind, "created_at": now(), "queued": False,
        "recipient_id": recipient_id,
        "challenge": {key: challenge.get(key) for key in ("_id", "owner_id", "title", "deadline")},
    }


def valid_address(value):
    if not isinstance(value, str) or "\r" in value or "\n" in value:
        return False
    try:
        address = Address(addr_spec=value)
        return bool(address.username and address.domain)
    except (ValueError, TypeError):
        return False


def mail_configuration():
    config = current_app.config
    missing = [name for name in ("MAIL_SERVER", "MAIL_USERNAME", "MAIL_PASSWORD", "MAIL_FROM") if not config.get(name)]
    if config.get("MAIL_FROM") and not valid_address(config["MAIL_FROM"]):
        missing.append("MAIL_FROM_INVALID")
    if config.get("MAIL_USE_TLS", True) and config.get("MAIL_USE_SSL", False):
        missing.append("MAIL_TLS_SSL_CONFLICT")
    if not config.get("MAIL_USE_TLS", True) and not config.get("MAIL_USE_SSL", False):
        missing.append("MAIL_TLS_REQUIRED")
    return {"enabled": bool(config.get("MAIL_ENABLED")), "configured": not missing, "missing": missing}


def event_recipients(event):
    challenge = event["challenge"]
    fields = {"email": 1, "name": 1, "organization_name": 1}
    if event["kind"] == "challenge_joined":
        person = mongo.db.users.find_one({"_id": event["recipient_id"]}, fields)
        return [(person, "joined")] if person else []
    if event["kind"] == "review_requested":
        return [(person, "review_requested") for person in mongo.db.users.find({"role": "admin"}, fields)]
    owner = mongo.db.users.find_one({"_id": challenge["owner_id"]}, fields)
    if event["kind"] == "challenge_published":
        return [(owner, "published")] if owner else []
    if event["kind"] == "challenge_closed":
        recipients = [(owner, "company_closed")] if owner else []
        talent_ids = mongo.db.participations.distinct("talent_id", {"challenge_id": challenge["_id"]})
        recipients.extend((person, "talent_closed") for person in mongo.db.users.find({"_id": {"$in": talent_ids}}, fields))
        return recipients
    raise ValueError("Unknown e-mail event")


def render_notice(event, person, notice_kind):
    challenge = event["challenge"]
    title = " ".join(str(challenge.get("title") or "Desafio").splitlines())
    name = str(person.get("name") or "participante")
    owner = mongo.db.users.find_one({"_id": challenge["owner_id"]}, {"name": 1, "organization_name": 1}) or {}
    company = owner.get("organization_name") or owner.get("name") or "Uma empresa"
    subjects = {
        "joined": "Inscrição confirmada", "published": "Seu desafio foi aprovado e publicado",
        "talent_closed": "O desafio em que você se inscreveu foi encerrado",
        "company_closed": "Seu desafio foi encerrado", "review_requested": "Novo desafio aguardando aprovação",
    }
    explanations = {
        "joined": "Sua inscrição foi confirmada. Você já pode acessar o enunciado e preparar sua solução.",
        "published": "A administração aprovou a publicação do seu desafio. Ele já está disponível para os talentos.",
        "talent_closed": "O desafio em que você se inscreveu foi encerrado e não recebe novas entregas. Suas participações e soluções continuam disponíveis na plataforma.",
        "company_closed": "Seu desafio foi encerrado e não recebe novas entregas. Acesse a plataforma para acompanhar e avaliar as soluções recebidas.",
        "review_requested": f"{company} enviou um desafio para aprovação. Revise o enunciado e os entregáveis antes de aprovar a publicação ou solicitar ajustes.",
    }
    subject = f"{subjects[notice_kind]} — {title}"
    url = f"{current_app.config.get('MAIL_APP_URL', 'http://localhost:5173')}/#/desafios/{challenge['_id']}"
    deadline = str(challenge.get("deadline") or "")
    if len(deadline) == 10:
        deadline = f"{deadline[8:10]}/{deadline[5:7]}/{deadline[:4]}"
    explanation = explanations[notice_kind]
    text = f"Olá, {name}!\n\n{explanation}\n\nDesafio: {title}\nPrazo informado: {deadline}\n\nAcessar desafio: {url}\n\nEquipe Return Tech\n"
    html = (
        '<!doctype html><html lang="pt-BR"><body style="margin:0;background:#f3f6f8;font-family:Arial,sans-serif;color:#102131">'
        '<main style="max-width:600px;margin:24px auto;background:#fff;padding:28px;border-top:5px solid #c8ff32">'
        '<div style="font-weight:700;letter-spacing:2px;color:#07111c">RETURN_TECH</div>'
        f'<h1 style="font-size:23px;line-height:1.35">{escape(subject)}</h1>'
        f'<p>Olá, {escape(name)}!</p><p style="line-height:1.7">{escape(explanation)}</p>'
        f'<p><strong>Desafio:</strong> {escape(title)}<br><strong>Prazo informado:</strong> {escape(deadline)}</p>'
        f'<p style="margin:28px 0"><a href="{escape(url, quote=True)}" style="background:#c8ff32;color:#07111c;padding:14px 20px;text-decoration:none;font-weight:700">Acessar desafio</a></p>'
        '<p style="font-size:13px;color:#546b7a">Equipe Return Tech</p></main></body></html>'
    )
    return subject, text, html


def queue_event(event):
    queued = 0
    for person, notice_kind in event_recipients(event):
        recipient = str(person.get("email") or "").strip()
        if not valid_address(recipient):
            current_app.logger.warning("E-mail ignorado: destinatário inválido no evento %s", event["id"])
            continue
        key = hashlib.sha256(f"{event['id']}:{notice_kind}:{person['_id']}".encode()).hexdigest()
        subject, text, html = render_notice(event, person, notice_kind)
        result = mongo.db.email_outbox.update_one({"_id": key}, {"$setOnInsert": {
            "event_id": event["id"], "kind": notice_kind, "recipient_id": person["_id"],
            "recipient": recipient, "subject": subject, "text": text, "html": html,
            "status": "pending", "attempts": 0, "created_at": event["created_at"],
            "next_attempt_at": now(),
        }}, upsert=True)
        queued += int(result.upserted_id is not None)
    return queued


def materialize_events(limit=100):
    queued = 0
    handled = 0
    for collection in (mongo.db.participations, mongo.db.challenges):
        for document in collection.find({"mail_events.queued": False}, {"mail_events": 1}).limit(limit):
            for event in document.get("mail_events", []):
                if event.get("queued"):
                    continue
                queued += queue_event(event)
                collection.update_one({"_id": document["_id"], "mail_events.id": event["id"]},
                                      {"$set": {"mail_events.$.queued": True}})
                handled += 1
                if handled >= limit:
                    return queued
    return queued


def deliver_message(item):
    config = current_app.config
    sender = config["MAIL_FROM"]
    message = EmailMessage()
    message["From"] = Address(display_name=config.get("MAIL_FROM_NAME", "Return Tech"), addr_spec=sender)
    message["To"] = Address(addr_spec=item["recipient"])
    message["Subject"] = item["subject"]
    message["Date"] = format_datetime(item["created_at"])
    message["Message-ID"] = f"<returntech.{item['_id']}@{sender.rsplit('@', 1)[1]}>"
    message.set_content(item["text"])
    message.add_alternative(item["html"], subtype="html")
    context = ssl.create_default_context()
    timeout = config.get("MAIL_TIMEOUT_SECONDS", 15)
    if config.get("MAIL_USE_SSL"):
        connection = smtplib.SMTP_SSL(config["MAIL_SERVER"], config["MAIL_PORT"], timeout=timeout, context=context)
    else:
        connection = smtplib.SMTP(config["MAIL_SERVER"], config["MAIL_PORT"], timeout=timeout)
    with connection as smtp:
        smtp.ehlo()
        if config.get("MAIL_USE_TLS", True):
            smtp.starttls(context=context)
            smtp.ehlo()
        password = config["MAIL_PASSWORD"]
        if config["MAIL_SERVER"] == "smtp.gmail.com":
            password = password.replace(" ", "")
        smtp.login(config["MAIL_USERNAME"], password)
        refused = smtp.send_message(message, from_addr=sender, to_addrs=[item["recipient"]])
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)


def process_outbox(limit=None):
    settings = mail_configuration()
    if not settings["enabled"] or not settings["configured"]:
        return 0
    config = current_app.config
    sent = 0
    for _ in range(limit or config.get("MAIL_BATCH_SIZE", 20)):
        timestamp = now()
        lease = uuid4().hex
        item = mongo.db.email_outbox.find_one_and_update({"$or": [
            {"status": "pending", "next_attempt_at": {"$lte": timestamp}},
            {"status": "sending", "lease_until": {"$lte": timestamp}},
        ]}, {"$set": {"status": "sending", "lease": lease,
                      "lease_until": timestamp + timedelta(seconds=config.get("MAIL_LEASE_SECONDS", 300))},
             "$inc": {"attempts": 1}}, sort=[("created_at", ASCENDING)], return_document=ReturnDocument.AFTER)
        if not item:
            break
        query = {"_id": item["_id"], "lease": lease, "status": "sending"}
        try:
            deliver_message(item)
        except Exception as error:
            failed = item["attempts"] >= config.get("MAIL_MAX_ATTEMPTS", 5)
            mongo.db.email_outbox.update_one(query, {"$set": {
                "status": "failed" if failed else "pending",
                "next_attempt_at": now() + timedelta(seconds=min(3600, 30 * 2 ** (item["attempts"] - 1))),
                "last_error": type(error).__name__,
            }, "$unset": {"lease": "", "lease_until": ""}})
            current_app.logger.warning("Falha ao enviar evento %s: %s", item["event_id"], type(error).__name__)
        else:
            mongo.db.email_outbox.update_one(query, {"$set": {"status": "sent", "sent_at": now()},
                                                   "$unset": {"lease": "", "lease_until": "", "last_error": ""}})
            sent += 1
    return sent
