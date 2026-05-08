"""URL patterns for the players app."""

from django.urls import path
from . import views

app_name = "players"

urlpatterns = [
    path("members/", views.members_list, name="members"),
]
