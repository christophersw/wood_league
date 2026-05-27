"""
Title: 0004_drop_network_calibration.py — Drop NetworkCalibration (#214)
Description:
    Removes the per-network draw-rate calibration table. The worker now ships
    a hard-coded LC0_DRAW_RATE_REFERENCE = 0.62 paired with the BT4 network
    config; the app no longer pre-flights calibration on lc0 checkouts.

Changelog:
    2026-05-27 (#214): Initial migration — DeleteModel(NetworkCalibration).
"""
from django.db import migrations


class Migration(migrations.Migration):
    """Drop the NetworkCalibration table."""

    dependencies = [
        ("analysis", "0003_drop_arrow_score"),
    ]

    operations = [
        migrations.DeleteModel(name="NetworkCalibration"),
    ]
