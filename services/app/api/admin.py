"""
Title: admin.py — Django admin configuration for the API app
Description:
    Django admin site configuration for the API module. Currently minimal with
    no model admin customizations.

Changelog:
    2026-05-08: Added file header to meet documentation standards
    2026-05-13 (#52): Register WorkerLogUpload via api.log_admin.
"""

# Importing this module triggers the @admin.register decorator and is
# the supported way to wire model admins from a sibling file.
from . import log_admin  # noqa: F401
