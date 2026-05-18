"""
Title: forms.py — Analysis forms
Description:
    Django forms for the analysis module. Provides form classes for
    filtering and managing game analysis data.

Changelog:
    2026-05-08: Added file header to meet documentation standards
    2026-05-18: Add RecurringAnalysisScheduleForm (#155 B).
"""
from django import forms

from .models import RecurringAnalysisSchedule


class RecurringAnalysisScheduleForm(forms.ModelForm):
    """Create/edit form for a recurring analysis rule.

    Field-level validation is delegated to the model's ``clean()`` via
    ``ModelForm`` (``_post_clean`` calls ``instance.full_clean``), so an
    invalid crontab/timezone surfaces as a bound field error.
    """

    class Meta:
        model = RecurringAnalysisSchedule
        fields = ["name", "crontab", "timezone", "max_jobs", "note",
                  "enabled"]
        widgets = {
            "note": forms.Textarea(attrs={"rows": 2}),
        }
