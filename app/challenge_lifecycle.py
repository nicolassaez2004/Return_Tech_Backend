from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import current_app

from .extensions import mongo
from .mail_notifications import mail_event
from .utils import now


def deadline_end(value):
    deadline = date.fromisoformat(value)
    local_end = datetime.combine(deadline + timedelta(days=1), time.min,
                                 tzinfo=ZoneInfo(current_app.config.get("CHALLENGE_TIMEZONE", "America/Sao_Paulo")))
    return local_end.astimezone(timezone.utc)


def deadline_passed(challenge, timestamp=None):
    try:
        end = deadline_end(challenge["deadline"])
    except (ValueError, KeyError, TypeError, OverflowError):
        return False
    timestamp = timestamp or now()
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return timestamp >= end


def close_if_expired(challenge, timestamp=None):
    timestamp = timestamp or now()
    if challenge["status"] != "published" or not deadline_passed(challenge, timestamp):
        return False
    result = mongo.db.challenges.update_one(
        {"_id": challenge["_id"], "status": "published", "deadline": challenge["deadline"],
         "updated_at": challenge.get("updated_at")},
        {"$set": {"status": "closed", "updated_at": timestamp, "closed_at": timestamp, "closed_reason": "deadline"},
         "$push": {"mail_events": mail_event("challenge_closed", challenge)}},
    )
    return result.modified_count == 1


def close_expired_challenges(limit=100):
    timestamp = now()
    closed = 0
    candidates = mongo.db.challenges.find({"status": "published", "$or": [
        {"ends_at": {"$lte": timestamp}}, {"ends_at": {"$exists": False}},
    ]}).sort("deadline", 1).limit(limit)
    for challenge in candidates:
        if close_if_expired(challenge, timestamp):
            closed += 1
        elif "ends_at" not in challenge:
            try:
                end = deadline_end(challenge["deadline"])
            except (ValueError, KeyError, TypeError, OverflowError):
                continue
            mongo.db.challenges.update_one({"_id": challenge["_id"], "status": "published",
                                            "deadline": challenge["deadline"]}, {"$set": {"ends_at": end}})
    return closed
