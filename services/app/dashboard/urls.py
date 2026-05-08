"""Main URL routes for the dashboard app."""

from django.urls import path
from . import views

app_name = "dashboard"

urlpatterns = [
    path("", views.index, name="index"),
]
