"""URL patterns for the analysis module views."""
from django.urls import path
from . import views

app_name = "analysis"

urlpatterns = [
    path("analysis-status/", views.status, name="status"),
]
