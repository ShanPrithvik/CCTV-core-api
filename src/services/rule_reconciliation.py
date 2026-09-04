"""Reconcile stored rule state with what Celery is actually running.

A detection rule's Celery task runs for as long as the rule is enabled, so it
never completes on its own. Restarting the worker therefore orphans every rule
at once: the row still reads 'Active', but no task publishes frames and the
live view sits empty with nothing to explain why.

Reconciling flips those orphaned rules back to 'Inactive' so the UI shows the
truth and the rule can be started again.
"""
import logging
import os

from src.celery_worker import celery
from src.models.ruleConfig import db, RuleConfig

logger = logging.getLogger("cctv.rule.reconcile")

# Celery's inspect always waits out the full timeout collecting replies, and
# this runs during app startup, so keep it short.
INSPECT_TIMEOUT = float(os.getenv("RULE_RECONCILE_TIMEOUT", "1.0"))


def _live_task_ids():
    """Task IDs Celery currently holds as active, reserved or scheduled.

    Returns None when no worker answers. That is indistinguishable from "every
    task died", so callers must not reconcile on a None result - doing so would
    deactivate every rule whenever the API happens to boot before the worker.
    """
    inspector = celery.control.inspect(timeout=INSPECT_TIMEOUT)

    try:
        # Probed first and on its own: when no worker is up this is the call
        # that burns the full timeout, and there is no point paying it twice
        # more for reserved/scheduled.
        active = inspector.active()
        if not active:
            return None

        replies = [active]
        for probe in (inspector.reserved, inspector.scheduled):
            reply = probe()
            if reply:
                replies.append(reply)
    except Exception:
        logger.warning("Celery inspect failed; skipping rule reconciliation")
        return None

    task_ids = set()
    for reply in replies:
        for entries in reply.values():
            for entry in entries or []:
                # active/reserved report the id at the top level; scheduled
                # nests the real task under "request".
                task_id = entry.get("id") or (entry.get("request") or {}).get("id")
                if task_id:
                    task_ids.add(task_id)
    return task_ids


def reconcile_rule_tasks():
    """Mark 'Active' rules whose Celery task is gone as 'Inactive'.

    Returns a summary dict; never raises, so it is safe to call during startup.
    """
    try:
        live = _live_task_ids()
        if live is None:
            logger.info("No Celery worker responded; leaving rule status untouched")
            return {"skipped": True, "deactivated": 0}

        stale = [
            rule
            for rule in RuleConfig.query.filter_by(status="Active").all()
            if not rule.task_id or rule.task_id not in live
        ]

        for rule in stale:
            logger.warning(
                "Rule id=%s camera=%s deactivated: task %s is no longer running",
                rule.id,
                rule.camera_id,
                rule.task_id or "<none>",
            )
            rule.status = "Inactive"
            rule.task_id = None

        if stale:
            db.session.commit()

        return {"skipped": False, "deactivated": len(stale)}
    except Exception:
        logger.exception("Rule reconciliation failed")
        db.session.rollback()
        return {"skipped": True, "deactivated": 0}
