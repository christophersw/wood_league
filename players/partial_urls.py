"""HTMX partial URL patterns for member management actions."""

from django.urls import path
from . import views

urlpatterns = [
    path("members/add/", views.add_member, name="members-add"),
    path("members/<int:pk>/edit/", views.edit_member, name="members-edit"),
    path("members/<int:pk>/delete/", views.delete_member, name="members-delete"),
    path("members/<int:pk>/invite/", views.invite_member, name="members-invite"),
]
