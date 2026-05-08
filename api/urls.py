"""URL routing for the Analysis Worker API."""
from django.urls import path
from . import views

urlpatterns = [
    path('health/', views.HealthView.as_view()),
    path('jobs/checkout/', views.JobCheckoutView.as_view()),
    path('jobs/<int:job_id>/complete/', views.JobCompleteView.as_view()),
    path('jobs/<int:job_id>/fail/', views.JobFailView.as_view()),
    path('jobs/status/', views.QueueStatusView.as_view()),
    path('heartbeat/', views.HeartbeatView.as_view()),
]
