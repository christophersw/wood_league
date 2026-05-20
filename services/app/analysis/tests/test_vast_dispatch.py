"""
Title: test_vast_dispatch.py — thin vast.ai REST client
Description:
    Offer filtering/sort + price ceiling, create env-merge payload,
    destroy idempotency on 404, list parsing, key-never-logged, and
    NoVastOfferError when nothing qualifies. httpx is mocked.
Changelog:
    2026-05-18: Initial — issue #155 Sub-project A.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
from django.test import TestCase

from analysis.services import vast_dispatch


class SearchOffersTests(TestCase):
    """search_cheapest_offer filters by price and picks the cheapest."""

    def _resp(self, payload, status=200):
        return MagicMock(status_code=status, json=MagicMock(return_value=payload))

    def test_picks_cheapest_under_ceiling(self):
        """Cheapest offer at/under the ceiling is chosen."""
        payload = {"offers": [
            {"id": 11, "gpu_name": "L40S", "dph_total": 1.20},
            {"id": 22, "gpu_name": "L40S", "dph_total": 0.90},
            {"id": 33, "gpu_name": "L40S", "dph_total": 2.50},
        ]}
        with patch("analysis.services.vast_dispatch.httpx.post",
                   return_value=self._resp(payload)):
            offer = vast_dispatch.search_cheapest_offer(
                api_key="k", gpu_name="L40S", max_dph=1.50)
        self.assertEqual(offer["id"], 22)
        self.assertEqual(offer["dph_total"], 0.90)

    def test_raises_when_none_under_ceiling(self):
        """All offers above the ceiling → NoVastOfferError."""
        payload = {"offers": [{"id": 1, "gpu_name": "L40S", "dph_total": 9.0}]}
        with patch("analysis.services.vast_dispatch.httpx.post",
                   return_value=self._resp(payload)):
            with self.assertRaises(vast_dispatch.NoVastOfferError):
                vast_dispatch.search_cheapest_offer(
                    api_key="k", gpu_name="L40S", max_dph=1.50)

    def test_raises_on_empty(self):
        """Empty offer list → NoVastOfferError."""
        with patch("analysis.services.vast_dispatch.httpx.post",
                   return_value=self._resp({"offers": []})):
            with self.assertRaises(vast_dispatch.NoVastOfferError):
                vast_dispatch.search_cheapest_offer(
                    api_key="k", gpu_name="L40S", max_dph=1.50)

    def test_default_search_omits_verified_filter(self):
        """Without ``verified_only`` the body has no ``verified`` key."""
        payload = {"offers": [{"id": 1, "gpu_name": "L40S", "dph_total": 1.0}]}
        with patch("analysis.services.vast_dispatch.httpx.post",
                   return_value=self._resp(payload)) as post:
            vast_dispatch.search_cheapest_offer(
                api_key="k", gpu_name="L40S", max_dph=1.50)
        self.assertNotIn("verified", post.call_args.kwargs["json"])

    def test_verified_only_adds_verified_filter(self):
        """``verified_only=True`` sends ``verified={"eq": True}``."""
        payload = {"offers": [{"id": 1, "gpu_name": "L40S", "dph_total": 1.0}]}
        with patch("analysis.services.vast_dispatch.httpx.post",
                   return_value=self._resp(payload)) as post:
            vast_dispatch.search_cheapest_offer(
                api_key="k", gpu_name="L40S", max_dph=1.50,
                verified_only=True)
        self.assertEqual(
            post.call_args.kwargs["json"]["verified"], {"eq": True})


class CreateInstanceTests(TestCase):
    """create_instance sends template_hash_id, label and merged env."""

    def test_create_payload_and_returns_contract_id(self):
        """Body carries template/label/env; returns new_contract as str."""
        resp = MagicMock(status_code=200,
                          json=MagicMock(return_value={"new_contract": 98765}))
        with patch("analysis.services.vast_dispatch.httpx.put",
                   return_value=resp) as mock_put:
            result = vast_dispatch.create_instance(
                api_key="k", offer_id=22, template_hash="HASH",
                label="wl-sched-7",
                env={"WL_CAMPAIGN_ID": "c1", "WLW_MAX_JOBS": "100",
                     "WL_SCHEDULE_ID": "7"})
        self.assertEqual(result["ok"], True)
        self.assertEqual(result["vast_instance_id"], "98765")
        _, kwargs = mock_put.call_args
        self.assertEqual(kwargs["json"]["template_hash_id"], "HASH")
        self.assertEqual(kwargs["json"]["label"], "wl-sched-7")
        self.assertEqual(kwargs["json"]["env"]["WL_SCHEDULE_ID"], "7")
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer k")

    def test_create_non_2xx_returns_not_ok(self):
        """A non-2xx create response yields ok=False, no raise."""
        resp = MagicMock(status_code=400, text="bad offer",
                         json=MagicMock(return_value={}))
        with patch("analysis.services.vast_dispatch.httpx.put", return_value=resp):
            result = vast_dispatch.create_instance(
                api_key="k", offer_id=1, template_hash="H",
                label="l", env={})
        self.assertFalse(result["ok"])
        self.assertIsNone(result["vast_instance_id"])


class DestroyInstanceTests(TestCase):
    """destroy_instance is idempotent and never raises."""

    def test_2xx_success(self):
        resp = MagicMock(status_code=200,
                         json=MagicMock(return_value={"success": True}))
        with patch("analysis.services.vast_dispatch.httpx.delete",
                   return_value=resp):
            result = vast_dispatch.destroy_instance(api_key="k",
                                                    vast_instance_id="123")
        self.assertTrue(result["ok"])

    def test_404_treated_as_success(self):
        """A 404 (already gone) is idempotent success."""
        resp = MagicMock(status_code=404, text="not found",
                         json=MagicMock(return_value={}))
        with patch("analysis.services.vast_dispatch.httpx.delete",
                   return_value=resp):
            result = vast_dispatch.destroy_instance(api_key="k",
                                                    vast_instance_id="123")
        self.assertTrue(result["ok"])

    def test_network_error_not_ok_no_raise(self):
        with patch("analysis.services.vast_dispatch.httpx.delete",
                   side_effect=httpx.ConnectError("boom")):
            result = vast_dispatch.destroy_instance(api_key="k",
                                                    vast_instance_id="123")
        self.assertFalse(result["ok"])

    def test_api_key_never_logged(self):
        """The api key must never appear in log output."""
        with self.assertLogs("analysis.services.vast_dispatch",
                              level="WARNING") as cm:
            with patch("analysis.services.vast_dispatch.httpx.delete",
                       side_effect=httpx.ConnectError("boom")):
                vast_dispatch.destroy_instance(api_key="SECRETKEY",
                                               vast_instance_id="123")
        self.assertNotIn("SECRETKEY", "\n".join(cm.output))


class ListInstancesTests(TestCase):
    """list_instances returns the parsed instances array."""

    def test_returns_instances(self):
        resp = MagicMock(status_code=200, json=MagicMock(
            return_value={"instances": [
                {"id": 1, "label": "wl-sched-7", "actual_status": "running"}]}))
        with patch("analysis.services.vast_dispatch.httpx.get",
                   return_value=resp):
            out = vast_dispatch.list_instances(api_key="k")
        self.assertEqual(out[0]["label"], "wl-sched-7")

    def test_non_2xx_returns_empty(self):
        """A non-2xx list response yields []."""
        resp = MagicMock(status_code=500, text="err",
                         json=MagicMock(return_value={}))
        with patch("analysis.services.vast_dispatch.httpx.get",
                   return_value=resp):
            self.assertEqual(vast_dispatch.list_instances(api_key="k"), [])

    def test_network_error_returns_empty(self):
        """A network error yields [] (never raises)."""
        with patch("analysis.services.vast_dispatch.httpx.get",
                   side_effect=httpx.ConnectError("boom")):
            self.assertEqual(vast_dispatch.list_instances(api_key="k"), [])
