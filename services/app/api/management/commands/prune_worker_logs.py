"""
Title: prune_worker_logs.py — Retention cron for WorkerLogUpload rows
Description:
    Deletes :class:`api.models.WorkerLogUpload` rows (and their objects in
    the configured bucket) older than ``WORKER_LOG_RETENTION_DAYS``. Run
    on a Railway cron schedule; safe to invoke ad-hoc from a shell too.

Changelog:
    2026-05-13 (#52): Initial creation.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from api import log_storage
from api.models import WorkerLogUpload


class Command(BaseCommand):
    """``./manage.py prune_worker_logs [--days N]``."""

    help = 'Delete WorkerLogUpload rows + bucket objects older than N days.'

    def add_arguments(self, parser: Any) -> None:
        """Register the optional ``--days`` override.

        Args:
            parser: ``argparse`` parser the management base class supplies.
        """
        parser.add_argument(
            '--days',
            type=int,
            default=None,
            help='Override WORKER_LOG_RETENTION_DAYS for this invocation.',
        )

    def handle(self, *args: Any, **options: Any) -> None:
        """Delete every upload older than the retention threshold.

        Args:
            args: Unused positional args.
            options: Parsed CLI options; honours ``--days``.
        """
        days = options.get('days') or settings.WORKER_LOG_RETENTION_DAYS
        threshold = timezone.now() - timedelta(days=days)
        old = WorkerLogUpload.objects.filter(uploaded_at__lt=threshold)
        count = 0
        for upload in old:
            try:
                log_storage.delete_object(upload.bucket_key)
            except Exception as exc:  # noqa: BLE001
                self.stderr.write(
                    f'Failed to delete bucket object {upload.bucket_key}: {exc}'
                )
            upload.delete()
            count += 1
        self.stdout.write(f'Pruned {count} worker log upload(s) older than {days} days.')


__all__ = ['Command']
