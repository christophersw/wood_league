"""
Title: log_admin.py — Django-admin integration for WorkerLogUpload
Description:
    Registers :class:`WorkerLogUpload` in the Django admin with a
    per-row "Download" action that 302-redirects to a short-lived
    presigned URL on the configured bucket, and a list-page
    "Bulk download zip" action that streams a gzip-tar archive of
    the selected logs back to the browser.

Changelog:
    2026-05-13 (#52): Initial creation.
"""
from __future__ import annotations

import io
import tarfile
from typing import Any

from django.contrib import admin, messages
from django.http import HttpRequest, HttpResponse, HttpResponseRedirect
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from api.log_storage import fetch_object, presigned_get_url
from api.models import WorkerLogUpload


def _first_note_line(note: str) -> str:
    """Return the first line of ``note`` (empty string if note is blank).

    Args:
        note: Free-form note text.

    Returns:
        First line of the note, stripped of trailing whitespace.
    """
    if not note:
        return ''
    return note.splitlines()[0].strip()


@admin.register(WorkerLogUpload)
class WorkerLogUploadAdmin(admin.ModelAdmin):
    """Admin integration for the per-session worker log uploads."""

    list_display = (
        'worker_name',
        'uploaded_at',
        'size_kb',
        'reason',
        'note_preview',
        'download_link',
    )
    list_filter = ('reason', 'uploaded_at')
    search_fields = ('worker__worker_name', 'bucket_key', 'note')
    readonly_fields = (
        'worker', 'uploaded_at', 'bucket_key', 'size_bytes',
        'note', 'reason', 'worker_version', 'host_summary',
    )
    actions = ('bulk_download_zip',)

    @admin.display(description='Worker', ordering='worker__worker_name')
    def worker_name(self, obj: WorkerLogUpload) -> str:
        """Render the human-readable worker name for the changelist."""
        return obj.worker.worker_name

    @admin.display(description='Size (KB)', ordering='size_bytes')
    def size_kb(self, obj: WorkerLogUpload) -> str:
        """Render the upload size as a kilobyte-rounded string."""
        return f'{obj.size_bytes / 1024:.1f}'

    @admin.display(description='Note')
    def note_preview(self, obj: WorkerLogUpload) -> str:
        """Render the first line of the note for the changelist."""
        return _first_note_line(obj.note)

    @admin.display(description='Download')
    def download_link(self, obj: WorkerLogUpload) -> str:
        """Render an inline "Download" link to the per-row redirect view."""
        url = reverse('admin:api_workerlogupload_download', args=[obj.pk])
        return format_html('<a href="{}">Download</a>', url)

    def get_urls(self) -> list[Any]:
        """Append the per-row download view to the admin URLconf."""
        urls = super().get_urls()
        custom = [
            path(
                '<int:object_id>/download/',
                self.admin_site.admin_view(self.download_view),
                name='api_workerlogupload_download',
            ),
        ]
        return custom + urls

    def download_view(
        self, request: HttpRequest, object_id: int
    ) -> HttpResponseRedirect:
        """Redirect to a short-lived presigned URL for ``object_id``.

        Args:
            request: The HTTP request (must be authenticated as staff).
            object_id: Primary key of the :class:`WorkerLogUpload` row.

        Returns:
            302 redirect to the presigned URL.
        """
        upload = WorkerLogUpload.objects.get(pk=object_id)
        url = presigned_get_url(upload.bucket_key, ttl_seconds=None)
        return HttpResponseRedirect(url)

    @admin.action(description='Bulk download zip of selected logs')
    def bulk_download_zip(
        self, request: HttpRequest, queryset: Any
    ) -> HttpResponse:
        """Stream a gzip-tar archive of the selected uploads.

        Args:
            request: The admin request.
            queryset: Selected :class:`WorkerLogUpload` rows.

        Returns:
            ``HttpResponse`` whose body is the in-memory tarball, or a
            redirect back to the changelist when fetching fails.
        """
        buffer = io.BytesIO()
        try:
            with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
                for upload in queryset:
                    body = fetch_object(upload.bucket_key)
                    info = tarfile.TarInfo(name=upload.bucket_key)
                    info.size = len(body)
                    archive.addfile(info, io.BytesIO(body))
        except Exception as exc:  # noqa: BLE001
            self.message_user(
                request, f'Bulk download failed: {exc}', level=messages.ERROR
            )
            return HttpResponseRedirect(request.get_full_path())

        buffer.seek(0)
        stamp = timezone.now().strftime('%Y%m%dT%H%M%SZ')
        response = HttpResponse(buffer.getvalue(), content_type='application/gzip')
        response['Content-Disposition'] = (
            f'attachment; filename="worker-logs-{stamp}.tar.gz"'
        )
        return response


__all__ = ['WorkerLogUploadAdmin']
