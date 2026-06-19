#!/usr/bin/env python3
"""
fhir-codebridge API Integration Tests
=====================================
Tests the FastAPI terminology service endpoints.
Run: pytest tests/ -v
"""

import pytest
from fastapi.testclient import TestClient
import sys
import os
import importlib

# Add scripts to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))


@pytest.fixture
def open_client():
    """Create test client with auth explicitly disabled for testing."""
    os.environ["LISA_AUTH_DISABLED"] = "1"
    os.environ.pop("LISA_API_KEYS", None)
    import api.server as server_mod
    importlib.reload(server_mod)
    yield TestClient(server_mod.app)
    os.environ.pop("LISA_AUTH_DISABLED", None)


@pytest.fixture
def authed_client():
    """Create test client with API key auth enabled."""
    os.environ.pop("LISA_AUTH_DISABLED", None)
    os.environ["LISA_API_KEYS"] = "test-admin-key:admin,test-read-key:read"
    import api.server as server_mod
    importlib.reload(server_mod)
    yield TestClient(server_mod.app)
    os.environ.pop("LISA_API_KEYS", None)


class TestHealth:
    """Health endpoint tests."""

    def test_health_returns_ok(self, open_client):
        resp = open_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "fhir-codebridge FHIR Terminology Service"
        assert data["version"] == "0.2.0"
        assert "terms_loaded" in data
        assert "auth_enabled" in data

    def test_health_no_auth_required(self, open_client):
        """Health endpoint should work without API key."""
        resp = open_client.get("/health")
        assert resp.status_code == 200


class TestStats:
    """Stats endpoint tests."""

    def test_stats_returns_systems(self, open_client):
        resp = open_client.get("/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_terms" in data
        assert "by_system" in data
        assert data["total_terms"] > 0

    def test_stats_has_icd10(self, open_client):
        """ICD-10-CM should be loaded (74K+ terms from CMS)."""
        resp = open_client.get("/stats")
        data = resp.json()
        assert "ICD-10-CM" in data["by_system"]
        assert data["by_system"]["ICD-10-CM"] > 70000


class TestSystems:
    """Systems endpoint tests."""

    def test_systems_list(self, open_client):
        resp = open_client.get("/systems")
        assert resp.status_code == 200
        data = resp.json()
        assert "systems" in data
        assert len(data["systems"]) > 0
        for s in data["systems"]:
            assert "name" in s
            assert "count" in s


class TestLookup:
    """Lookup endpoint tests."""

    def test_lookup_icd10_exact(self, open_client):
        """Exact code lookup for ICD-10-CM E11.9 (Type 2 DM)."""
        resp = open_client.post("/lookup", json={
            "code": "E11.9",
            "system": "ICD-10-CM"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is True
        # CMS stores codes without dots (E119); lookup normalizes both formats
        assert data["source"]["code"] in ("E11.9", "E119")
        assert "diabetes" in data["source"]["display"].lower()

    def test_lookup_icd10_nondot(self, open_client):
        """ICD-10-CM lookup with non-dotted format (E119)."""
        resp = open_client.post("/lookup", json={
            "code": "E119",
            "system": "ICD-10-CM"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is True

    def test_lookup_rxnorm(self, open_client):
        """RxNorm lookup for metformin."""
        resp = open_client.post("/lookup", json={
            "code": "6809",
            "system": "RXNORM"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is True
        assert "metformin" in data["source"]["display"].lower()

    def test_lookup_cdt(self, open_client):
        """CDT lookup for D0120 (periodic oral evaluation)."""
        resp = open_client.post("/lookup", json={
            "code": "D0120",
            "system": "CDT"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is True

    def test_lookup_not_found(self, open_client):
        """Non-existent code should return found=False, not crash."""
        resp = open_client.post("/lookup", json={
            "code": "ZZZZZZ",
            "system": "ICD-10-CM"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is False

    def test_lookup_fhir_uri(self, open_client):
        """Lookup using FHIR URI instead of plain system name."""
        resp = open_client.post("/lookup", json={
            "code": "E11.9",
            "system": "http://hl7.org/fhir/sid/icd-10-cm"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["found"] is True


class TestTranslate:
    """FHIR $translate endpoint tests."""

    def test_translate_icd10_to_snomed(self, open_client):
        """$translate from ICD-10-CM to SNOMED-CT."""
        resp = open_client.post("/$translate", json={
            "code": "E11.9",
            "system": "http://hl7.org/fhir/sid/icd-10-cm",
            "target_system": "http://snomed.info/sct"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["resourceType"] == "Parameters"
        params = data["parameter"]
        result_param = [p for p in params if p.get("name") == "result"]
        assert len(result_param) > 0
        assert result_param[0]["valueBoolean"] is True

    def test_translate_no_target(self, open_client):
        """$translate without target_system should still find the source code."""
        resp = open_client.post("/$translate", json={
            "code": "E11.9",
            "system": "ICD-10-CM"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["resourceType"] == "Parameters"

    def test_translate_not_found(self, open_client):
        """$translate for non-existent code should return result=False."""
        resp = open_client.post("/$translate", json={
            "code": "ZZZZZZ",
            "system": "ICD-10-CM"
        })
        assert resp.status_code == 200
        data = resp.json()
        params = data["parameter"]
        result_param = [p for p in params if p.get("name") == "result"]
        assert result_param[0]["valueBoolean"] is False


class TestAuth:
    """Authentication and RBAC tests."""

    def test_no_key_returns_401(self, authed_client):
        """Without auth disabled, missing API key should return 401."""
        resp = authed_client.get("/stats")
        assert resp.status_code == 401

    def test_wrong_key_returns_401(self, authed_client):
        """Invalid API key should return 401."""
        resp = authed_client.get("/stats", headers={"X-API-Key": "wrong-key"})
        assert resp.status_code == 401

    def test_readonly_key_blocked_from_audit(self, authed_client):
        """Read-only key should get 403 on admin endpoints."""
        resp = authed_client.get("/audit", headers={"X-API-Key": "test-read-key"})
        assert resp.status_code == 403

    def test_admin_key_can_access_audit(self, authed_client):
        """Admin key should access audit endpoint."""
        resp = authed_client.get("/audit", headers={"X-API-Key": "test-admin-key"})
        assert resp.status_code == 200

    def test_readonly_key_can_lookup(self, authed_client):
        """Read-only key should be able to use lookup."""
        resp = authed_client.post("/lookup", json={
            "code": "E11.9",
            "system": "ICD-10-CM"
        }, headers={"X-API-Key": "test-read-key"})
        assert resp.status_code == 200


class TestAuditLog:
    """Audit logging tests."""

    def test_audit_logs_lookup(self, open_client):
        """Lookup requests should be audit logged."""
        open_client.post("/lookup", json={"code": "E11.9", "system": "ICD-10-CM"})
        
        resp = open_client.get("/audit", params={"limit": 5, "action": "lookup"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0
        latest = data["entries"][-1]
        assert latest["action"] == "lookup"
        assert latest["detail"]["code"] == "E11.9"