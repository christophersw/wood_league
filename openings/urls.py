"""URL patterns for the openings app."""

from django.urls import path
from . import views

app_name = "openings"

urlpatterns = [
    path("<int:opening_id>/", views.detail, name="detail"),
]
