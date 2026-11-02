import smtplib
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from bson import ObjectId

from app.challenge_lifecycle import close_expired_challenges, deadline_end
from app.jobs import maintenance_tick, retry_failed_emails
from app.mail_notifications import (
    mail_configuration, mail_event, materialize_events, process_outbox, queue_event,
)
from app.utils import now
import test_ctfs as ctf_fixtures


class MailTests(unittest.TestCase):
    create = ctf_fixtures.CTFTests.create
    status = ctf_fixtures.CTFTests.status
    approve = ctf_fixtures.CTFTests.approve

    def setUp(self):
        ctf_fixtures.CTFTests.setUp(self)
        self.fields["deadline"] = "2026-12-10"
        self.clock_patch = patch("app.challenge_lifecycle.now", return_value=datetime(2026, 11, 2, 12, tzinfo=timezone.utc))
        self.clock_patch.start()
        self.addCleanup(self.clock_patch.stop)
        self.app.config.update(
            MAIL_ENABLED=True, MAIL_SERVER="smtp.gmail.com", MAIL_PORT=587,
            MAIL_USE_TLS=True, MAIL_USE_SSL=False, MAIL_USERNAME="sender@example.test",
            MAIL_PASSWORD="fake-app-password", MAIL_FROM="sender@example.test",
            MAIL_FROM_NAME="Return Tech", MAIL_APP_URL="http://localhost:5173",
            MAIL_MAX_ATTEMPTS=5, CHALLENGE_TIMEZONE="America/Sao_Paulo",
        )
        self.context = self.app.app_context()
        self.context.push()
        self.addCleanup(self.context.pop)
        self.smtp_patch = patch("app.mail_notifications.smtplib.SMTP")
        self.smtp_factory = self.smtp_patch.start()
        self.addCleanup(self.smtp_patch.stop)
        self.smtp = self.smtp_factory.return_value.__enter__.return_value
        self.smtp.send_message.return_value = {}

    def queue_single(self):
        challenge = {**self.fields, "_id": ObjectId(), "owner_id": self.users["company"]}
        event = mail_event("challenge_joined", challenge, self.users["talent"])
        self.assertEqual(queue_event(event), 1)
        return event

    def test_join_confirmation_is_sent_once_and_never_inside_request(self):
        challenge_id = self.create()
        self.approve(challenge_id)
        materialize_events()
        process_outbox()
        self.smtp.reset_mock()
        for _ in range(2):
            response = self.client.post(f"/api/challenges/{challenge_id}/join", headers=self.headers["talent"])
            self.assertEqual(response.status_code, 200)
        self.smtp.send_message.assert_not_called()
        self.assertEqual(materialize_events(), 1)
        self.assertEqual(process_outbox(), 1)
        self.assertEqual(materialize_events(), 0)
        self.assertEqual(process_outbox(), 0)
        self.smtp.send_message.assert_called_once()
        message = self.smtp.send_message.call_args.args[0]
        self.assertEqual(str(message["To"]), "talent@example.test")
        self.assertIn("Inscrição confirmada", str(message["Subject"]))
        self.assertIn(challenge_id, message.get_body(preferencelist=("plain",)).get_content())

    def test_all_admins_receive_review_request_individually(self):
        self.db.users.insert_one({"role": "admin", "name": "Equipe", "email": "admin2@example.test"})
        challenge_id = self.create()
        self.assertEqual(materialize_events(), 0)
        self.status(challenge_id, "submit_review")
        self.assertEqual(self.status(challenge_id, "submit_review").status_code, 409)
        self.assertEqual(materialize_events(), 2)
        self.assertEqual(process_outbox(), 2)
        recipients = {call.kwargs["to_addrs"][0] for call in self.smtp.send_message.call_args_list}
        self.assertEqual(recipients, {"admin@example.test", "admin2@example.test"})
        for call in self.smtp.send_message.call_args_list:
            self.assertEqual(len(call.kwargs["to_addrs"]), 1)
            self.assertIsNone(call.args[0]["Cc"])
            self.assertIsNone(call.args[0]["Bcc"])

    def test_company_receives_publication_confirmation_only_after_approval(self):
        challenge_id = self.create()
        self.status(challenge_id, "publish")
        materialize_events()
        self.assertEqual(self.db.email_outbox.count_documents({"kind": "published"}), 0)
        self.status(challenge_id, "approve", "admin")
        materialize_events()
        company_mail = self.db.email_outbox.find_one({"kind": "published"})
        self.assertEqual(company_mail["recipient"], "company@example.test")
        self.assertIn("aprovado e publicado", company_mail["subject"])
        self.assertEqual(self.db.email_outbox.count_documents({"recipient": "talent@example.test"}), 0)

    def test_manual_closure_notifies_company_and_all_participants_once(self):
        challenge_id = self.create()
        self.approve(challenge_id)
        self.client.post(f"/api/challenges/{challenge_id}/join", headers=self.headers["talent"])
        self.db.participations.insert_one({"challenge_id": ObjectId(challenge_id), "talent_id": self.users["outsider"], "status": "rejected"})
        self.assertEqual(self.status(challenge_id, "close", "admin").status_code, 200)
        self.assertEqual(self.status(challenge_id, "close", "admin").status_code, 409)
        materialize_events()
        closed = list(self.db.email_outbox.find({"kind": {"$in": ["company_closed", "talent_closed"]}}))
        self.assertEqual({item["recipient"] for item in closed}, {"company@example.test", "talent@example.test", "outsider@example.test"})
        self.assertEqual(len(closed), 3)
        self.assertEqual(materialize_events(), 0)

    def test_deadline_uses_end_of_day_in_sao_paulo(self):
        challenge_id = self.create()
        self.approve(challenge_id)
        self.client.post(f"/api/challenges/{challenge_id}/join", headers=self.headers["talent"])
        self.assertEqual(deadline_end("2026-12-10"), datetime(2026, 12, 11, 3, tzinfo=timezone.utc))
        with patch("app.challenge_lifecycle.now", return_value=datetime(2026, 12, 11, 2, 59, 59, tzinfo=timezone.utc)):
            self.assertEqual(close_expired_challenges(), 0)
        with patch("app.challenge_lifecycle.now", return_value=datetime(2026, 12, 11, 3, tzinfo=timezone.utc)):
            self.assertEqual(close_expired_challenges(), 1)
            self.assertEqual(close_expired_challenges(), 0)
        challenge = self.db.challenges.find_one({"_id": ObjectId(challenge_id)})
        self.assertEqual(challenge["closed_reason"], "deadline")
        materialize_events()
        self.assertEqual(self.db.email_outbox.count_documents({"kind": "company_closed"}), 1)
        self.assertEqual(self.db.email_outbox.count_documents({"kind": "talent_closed"}), 1)

    def test_existing_published_records_also_expire(self):
        challenge_id = self.create()
        self.approve(challenge_id)
        self.db.challenges.update_one({"_id": ObjectId(challenge_id)}, {"$unset": {"ends_at": ""}})
        self.assertEqual(close_expired_challenges(), 0)
        self.assertIn("ends_at", self.db.challenges.find_one({"_id": ObjectId(challenge_id)}))
        with patch("app.challenge_lifecycle.now", return_value=datetime(2026, 12, 11, 3, tzinfo=timezone.utc)):
            self.assertEqual(close_expired_challenges(), 1)

    def test_no_late_joins_or_submissions_between_worker_ticks(self):
        challenge_id = self.create()
        self.approve(challenge_id)
        self.client.post(f"/api/challenges/{challenge_id}/join", headers=self.headers["talent"])
        with patch("app.challenge_lifecycle.now", return_value=datetime(2026, 12, 11, 3, tzinfo=timezone.utc)):
            self.assertEqual(self.client.post(f"/api/challenges/{challenge_id}/submissions", data={"summary": "Fora do prazo"}, headers=self.headers["talent"]).status_code, 409)
            self.assertIn(self.client.post(f"/api/challenges/{challenge_id}/join", headers=self.headers["outsider"]).status_code, (404, 409))
        self.assertEqual(self.db.submissions.count_documents({}), 0)

    def test_admin_cannot_approve_an_expired_deadline(self):
        challenge_id = self.create()
        self.status(challenge_id, "submit_review")
        with patch("app.challenge_lifecycle.now", return_value=datetime(2026, 12, 11, 3, tzinfo=timezone.utc)):
            self.assertEqual(self.status(challenge_id, "approve", "admin").status_code, 409)
        self.assertEqual(self.db.challenges.find_one({"_id": ObjectId(challenge_id)})["status"], "pending_review")

    def test_resubmission_creates_a_new_admin_notice(self):
        challenge_id = self.create()
        self.status(challenge_id, "submit_review")
        self.status(challenge_id, "request_changes", "admin", feedback="Detalhe o escopo")
        self.client.patch(f"/api/challenges/{challenge_id}", json={**self.fields, "description": "Escopo corrigido"}, headers=self.headers["company"])
        self.status(challenge_id, "submit_review")
        materialize_events()
        self.assertEqual(self.db.email_outbox.count_documents({"kind": "review_requested"}), 2)

    def test_event_snapshot_survives_later_changes(self):
        challenge_id = self.create()
        self.approve(challenge_id)
        self.client.patch(f"/api/challenges/{challenge_id}", json={**self.fields, "title": "Outro título"}, headers=self.headers["company"])
        materialize_events()
        notice = self.db.email_outbox.find_one({"kind": "published"})
        self.assertIn(self.fields["title"], notice["subject"])
        self.assertNotIn("Outro título", notice["subject"])

    def test_reprocessing_a_persisted_event_does_not_send_twice(self):
        challenge_id = self.create()
        self.status(challenge_id, "submit_review")
        self.assertEqual(materialize_events(), 1)
        self.assertEqual(process_outbox(), 1)
        self.db.challenges.update_one({"_id": ObjectId(challenge_id)}, {"$set": {"mail_events.0.queued": False}})
        self.assertEqual(materialize_events(), 0)
        self.assertEqual(process_outbox(), 0)
        self.assertEqual(self.db.email_outbox.count_documents({}), 1)

    def test_smtp_failure_retries_without_losing_the_event(self):
        self.queue_single()
        self.smtp.send_message.side_effect = OSError("private-fake-secret")
        self.assertEqual(process_outbox(), 0)
        item = self.db.email_outbox.find_one()
        self.assertEqual(item["status"], "pending")
        self.assertEqual(item["attempts"], 1)
        self.assertEqual(item["last_error"], "OSError")
        self.assertNotIn("private-fake-secret", str(item))
        self.assertEqual(process_outbox(), 0)
        first_message_id = str(self.smtp.send_message.call_args.args[0]["Message-ID"])
        self.db.email_outbox.update_one({"_id": item["_id"]}, {"$set": {"next_attempt_at": now() - timedelta(seconds=1)}})
        self.smtp.send_message.side_effect = None
        self.assertEqual(process_outbox(), 1)
        self.assertEqual(str(self.smtp.send_message.call_args.args[0]["Message-ID"]), first_message_id)
        self.assertEqual(self.db.email_outbox.find_one()["status"], "sent")

    def test_stopped_worker_lease_can_be_recovered(self):
        self.queue_single()
        self.db.email_outbox.update_one({}, {"$set": {"status": "sending", "lease": "old", "lease_until": now() - timedelta(seconds=1), "attempts": 1}})
        self.assertEqual(process_outbox(), 1)
        self.assertEqual(self.db.email_outbox.find_one()["attempts"], 2)

    def test_another_worker_cannot_claim_an_in_progress_message(self):
        self.queue_single()
        def send_while_another_worker_checks(*args, **kwargs):
            self.assertEqual(process_outbox(limit=1), 0)
            return {}
        self.smtp.send_message.side_effect = send_while_another_worker_checks
        self.assertEqual(process_outbox(), 1)
        self.smtp.send_message.assert_called_once()

    def test_disabled_or_incomplete_configuration_keeps_queue_unsent(self):
        self.queue_single()
        self.app.config["MAIL_ENABLED"] = False
        self.assertEqual(process_outbox(), 0)
        self.app.config.update(MAIL_ENABLED=True, MAIL_PASSWORD="")
        self.assertFalse(mail_configuration()["configured"])
        self.assertEqual(process_outbox(), 0)
        self.smtp_factory.assert_not_called()
        self.assertEqual(self.db.email_outbox.find_one()["attempts"], 0)

    def test_transport_uses_tls_and_private_multipart_message(self):
        self.queue_single()
        self.assertEqual(process_outbox(), 1)
        self.smtp.starttls.assert_called_once()
        self.smtp.login.assert_called_once_with("sender@example.test", "fake-app-password")
        call = self.smtp.send_message.call_args
        self.assertEqual(call.kwargs["from_addr"], "sender@example.test")
        self.assertEqual(call.kwargs["to_addrs"], ["talent@example.test"])
        self.assertIsNotNone(call.args[0].get_body(preferencelist=("plain",)))
        self.assertIsNotNone(call.args[0].get_body(preferencelist=("html",)))

    def test_untrusted_text_is_escaped_and_cannot_add_headers(self):
        self.db.users.update_one({"_id": self.users["talent"]}, {"$set": {"name": "<script>name</script>"}})
        challenge = {**self.fields, "_id": ObjectId(), "owner_id": self.users["company"], "title": "<b>CTF</b>\nBcc: injected@example.test"}
        queue_event(mail_event("challenge_joined", challenge, self.users["talent"]))
        process_outbox()
        message = self.smtp.send_message.call_args.args[0]
        self.assertIsNone(message["Bcc"])
        html = message.get_body(preferencelist=("html",)).get_content()
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)

    def test_exhausted_attempts_can_be_requeued_after_fixing_credentials(self):
        self.queue_single()
        self.app.config["MAIL_MAX_ATTEMPTS"] = 2
        self.smtp.send_message.side_effect = smtplib.SMTPAuthenticationError(535, b"Denied")
        process_outbox()
        self.db.email_outbox.update_one({}, {"$set": {"next_attempt_at": now() - timedelta(seconds=1)}})
        process_outbox()
        self.assertEqual(self.db.email_outbox.find_one()["status"], "failed")
        self.assertEqual(process_outbox(), 0)
        self.app.cli.add_command(retry_failed_emails)
        result = self.app.test_cli_runner().invoke(args=["retry-failed-emails"])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(self.db.email_outbox.find_one()["status"], "pending")
        self.smtp.send_message.side_effect = None
        self.assertEqual(process_outbox(), 1)

    def test_maintenance_queues_notices_even_when_delivery_is_disabled(self):
        self.app.config["MAIL_ENABLED"] = False
        challenge_id = self.create()
        self.status(challenge_id, "submit_review")
        result = maintenance_tick()
        self.assertEqual(result, {"closed": 0, "queued": 1, "sent": 0})
        self.smtp_factory.assert_not_called()

    def test_delivery_events_are_kept_private_in_api_responses(self):
        challenge_id = self.create()
        self.approve(challenge_id)
        self.client.post(f"/api/challenges/{challenge_id}/join", headers=self.headers["talent"])
        self.assertIn("mail_events", self.db.challenges.find_one({"_id": ObjectId(challenge_id)}))
        for role in ("company", "talent"):
            response = self.client.get("/api/dashboard", headers=self.headers[role])
            self.assertNotIn("mail_events", str(response.json))
        response = self.client.get("/api/admin/challenges", headers=self.headers["admin"])
        self.assertNotIn("mail_events", str(response.json))


if __name__ == "__main__":
    unittest.main()
