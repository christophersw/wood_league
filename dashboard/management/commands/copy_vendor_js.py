"""Copy vendored JS files (htmx, plotly) from installed packages into static/js/."""

from __future__ import annotations

import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand


def _package_path(import_path: str) -> Path:
    """Return the directory of an installed package."""
    import importlib
    mod = importlib.import_module(import_path)
    return Path(mod.__file__).parent


VENDORS = [
    (
        "django_htmx",
        "static/django_htmx/htmx.min.js",
        "js/htmx.min.js",
    ),
    (
        "plotly",
        "package_data/plotly.min.js",
        "js/plotly.min.js",
    ),
]


class Command(BaseCommand):
    help = "Copy htmx.min.js and plotly.min.js from installed packages into static/js/."

    def handle(self, *args, **options):
        static_dir = Path(settings.STATICFILES_DIRS[0])
        static_dir.mkdir(parents=True, exist_ok=True)

        for package, rel_src, rel_dst in VENDORS:
            src = _package_path(package) / rel_src
            dst = static_dir / rel_dst
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            self.stdout.write(self.style.SUCCESS(f"Copied {src.name} → {dst}"))
