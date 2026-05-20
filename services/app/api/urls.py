"""
Title: urls.py — URL routing for the Analysis Worker API
Description:
    Defines REST API endpoints for workers to checkout analysis jobs, report
    completion, report failures, send heartbeats, and query queue status.
    Also includes the RunPod dispatcher submit endpoint.

Changelog:
    2026-05-08: Added file header to meet documentation standards
    2026-05-08: Added jobs/<id>/submit/ for RunPod dispatcher integration
"""
from django.urls import path
from . import views
from .log_upload_view import WorkerLogUploadView

urlpatterns = [
    path('health/', views.HealthView.as_view()),
    path('jobs/checkout/', views.JobCheckoutView.as_view()),
    path('jobs/<int:job_id>/complete/', views.JobCompleteView.as_view()),
    path('jobs/<int:job_id>/fail/', views.JobFailView.as_view()),
    path('jobs/<int:job_id>/submit/', views.JobSubmitView.as_view()),
    path('jobs/status/', views.QueueStatusView.as_view()),
    path('heartbeat/', views.HeartbeatView.as_view()),
    path('worker/logs/', WorkerLogUploadView.as_view()),
    path('network_calibrations/', views.NetworkCalibrationView.as_view()),
]
