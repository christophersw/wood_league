"""
Title: admin_urls.py — URL routing for API key management admin interface
Description:
    Provides admin endpoints for managing worker API keys, including listing keys,
    issuing new keys, and revoking existing keys.

Changelog:
    2026-05-08: Added file header to meet documentation standards
"""
from django.urls import path
from . import admin_views

urlpatterns = [
    path('', admin_views.api_keys_list, name='api-keys-list'),
    path('issue/', admin_views.api_keys_issue, name='api-keys-issue'),
    path('<str:key_id>/revoke/', admin_views.api_keys_revoke, name='api-keys-revoke'),
    path('list/', admin_views.api_keys_list, name='api-keys-list-partial'),
]
