"""
Title: admin_views.py — Admin UI for API key management
Description:
    Staff-gated views for creating and revoking API keys. Uses Django session
    auth (not DRF). Responds to both full-page and HTMX partial requests.

Changelog:
    2026-05-06 (#15): Created admin UI for API key lifecycle management
"""
from django.contrib.auth.decorators import login_required, user_passes_test
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import WorkerAPIKey

_staff_required = user_passes_test(lambda u: u.is_staff, login_url='/auth/login/')


@login_required
@_staff_required
def api_keys_list(request):
    """
    Display list of API keys for staff users.
    Responds to both full-page requests and HTMX partial requests.
    """
    keys = WorkerAPIKey.objects.select_related('created_by').order_by('-created')
    context = {'keys': keys}
    if request.htmx:
        return render(request, '_partials/admin/api_keys/list.html', context)
    return render(request, 'admin/api_keys/index.html', context)


@login_required
@_staff_required
def api_keys_issue(request):
    """
    Issue a new API key to a worker.
    GET: Show the form in a modal.
    POST: Create the key and show the raw key (shown exactly once).
    """
    if request.method == 'GET':
        return render(request, '_partials/admin/api_keys/issue_form.html')
    
    # POST: Create the key
    worker_name = request.POST.get('worker_name', '').strip()
    notes       = request.POST.get('notes', '').strip()

    if not worker_name:
        return render(
            request,
            '_partials/admin/api_keys/issue_form.html',
            {'error': 'Worker name is required.'},
        )

    api_key, raw_key = WorkerAPIKey.objects.create_key(
        name=worker_name,
        worker_name=worker_name,
        created_by=request.user,
        notes=notes,
    )

    context = {
        'raw_key': raw_key,
        'key': api_key,
    }
    return render(request, '_partials/admin/api_keys/key_created.html', context)


@login_required
@_staff_required
@require_POST
def api_keys_revoke(request, key_id):
    """
    Revoke an API key. Returns updated table row for HTMX out-of-band swap.
    """
    key = get_object_or_404(WorkerAPIKey, pk=key_id)
    key.revoked = True
    key.save(update_fields=['revoked'])
    return render(request, '_partials/admin/api_keys/table_row.html', {'key': key})
