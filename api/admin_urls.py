"""URL routing for API key management admin views."""
from django.urls import path
from . import admin_views

urlpatterns = [
    path('', admin_views.api_keys_list, name='api-keys-list'),
    path('issue/', admin_views.api_keys_issue, name='api-keys-issue'),
    path('<str:key_id>/revoke/', admin_views.api_keys_revoke, name='api-keys-revoke'),
    path('list/', admin_views.api_keys_list, name='api-keys-list-partial'),
]
