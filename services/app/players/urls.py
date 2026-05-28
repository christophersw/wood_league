"""
Title: urls.py — URL routing for the players module
Description:
    Defines URL patterns for viewing the member list and admin actions such
    as sending magic-link invites to club members.

Changelog:
    2026-05-28: Add member_send_invite route (#218)
    2026-05-08: Added file header to meet documentation standards
"""

from django.urls import path
from . import views

app_name = "players"

urlpatterns = [
    path("members/", views.members_list, name="members"),
    path("members/", views.members_list, name="members_list"),
    path("members/<int:player_id>/invite/", views.member_send_invite, name="member_send_invite"),
]
