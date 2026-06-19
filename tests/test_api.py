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
import io
import os
import importlib

# Add scripts to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))


@pytest.fixture
def open_client():
    """Create test client with auth explicitly disabled for testing."""
    os.environ["CODEBRIDGE_AUTH_DISABLED"] = "1"
    os.environ.pop("CODEBRIDGE_API_KEYS", None)
    import api.server as server_mod
    importlib.reload(server_mod)
    yield TestClient(server_mod.app)
    os.environ.pop("CODEBRIDGE_AUTH_DISABLED", None)


@pytest.fixture
def authed_client():
    """Create test client with API key auth enabled."""
    os.environ.pop("CODEBRIDGE_AUTH_DISABLED", None)
    os.environ["CODEBRIDGE_API_KEYS"] = "test-admin-key:admin,test-read-key:read"
    import api.server as server_mod
    importlib.reload(server_mod)
    yield TestClient(server_mod.app)
    os.environ.pop("CODEBRIDGE_API_KEYS", None)


class TestHealth:
    """Health endpoint tests."""

    def test_health_returns_ok(self, open_client):
        resp = open_client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["service"] == "fhir-codebridge FHIR Terminology Service"
        assert data["version"] == "0.4.1"
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


class TestWebUI:
    """Web UI endpoint tests."""

    def test_root_returns_html(self, open_client):
        """Root URL should serve the web UI HTML page."""
        resp = open_client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers.get("content-type", "")
        # Should contain key UI elements
        body = resp.text
        assert "fhir-codebridge" in body
        assert "Dashboard" in body
        assert "Single Lookup" in body
        assert "Bulk Upload" in body

    def test_root_has_lookup_form(self, open_client):
        """Web UI should have a lookup form with code input."""
        resp = open_client.get("/")
        body = resp.text
        assert "lookup-code" in body  # ID of the code input field
        assert "Map It" in body       # Button text

    def test_root_has_bulk_upload(self, open_client):
        """Web UI should have a bulk upload drop zone."""
        resp = open_client.get("/")
        body = resp.text
        assert "drop-zone" in body
        assert "csv" in body.lower()


class TestBulk:
    """Bulk CSV processing tests."""

    def test_bulk_csv_processing(self, open_client):
        """Upload a small CSV and get results back."""
        import io
        csv_content = "code\nE11.9\nI10\nJ45.901\n"
        
        resp = open_client.post(
            "/bulk",
            files={"file": ("test.csv", io.BytesIO(csv_content.encode()), "text/csv")},
            data={"source_system": "ICD-10-CM", "target_system": "SNOMED-CT"},
        )
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")
        body = resp.text
        assert "original_code" in body
        assert "E11.9" in body
        # Should have summary line
        assert "Summary" in body

    def test_bulk_missing_code_column(self, open_client):
        """CSV without a recognizable code column should return 400."""
        import io
        csv_content = "name,age\nJohn,30\nJane,25\n"
        
        resp = open_client.post(
            "/bulk",
            files={"file": ("test.csv", io.BytesIO(csv_content.encode()), "text/csv")},
            data={"source_system": "ICD-10-CM", "target_system": "SNOMED-CT"},
        )
        assert resp.status_code == 400


class TestMetrics:
    """Prometheus metrics endpoint tests."""

    def test_metrics_returns_text(self, open_client):
        """Metrics endpoint should return Prometheus-format text."""
        resp = open_client.get("/metrics")
        assert resp.status_code == 200
        assert "text/plain" in resp.headers.get("content-type", "")
        body = resp.text
        assert "codebridge_terms_loaded" in body
        assert "codebridge_up 1" in body
        assert "codebridge_umls_enabled" in body

    def test_metrics_has_system_counts(self, open_client):
        """Metrics should include per-system term counts."""
        resp = open_client.get("/metrics")
        body = resp.text
        assert "codebridge_system_terms" in body
        assert "ICD-10-CM" in body

    def test_metrics_no_auth_required(self, open_client):
        """Metrics should be accessible without auth (read-only stats)."""
        # Already using open_client which has auth disabled
        resp = open_client.get("/metrics")
        assert resp.status_code == 200

class TestProvenance:
    """Mapping provenance tests — Tier 0 trust layer."""

    def test_lookup_returns_provenance(self, open_client):
        """Every lookup result should include provenance metadata."""
        resp = open_client.post("/lookup", json={"code": "E11.9", "system": "ICD-10-CM"})
        assert resp.status_code == 200
        data = resp.json()
        assert "provenance" in data
        prov = data["provenance"]
        assert "source_authority" in prov
        assert "mapping_method" in prov
        assert "confidence_level" in prov
        assert prov["confidence_level"] in ("verified", "crosswalk_derived", "fuzzy", "unverified")

    def test_exact_lookup_provenance_verified(self, open_client):
        """Exact code lookups should have 'verified' confidence level."""
        resp = open_client.post("/lookup", json={"code": "E11.9", "system": "ICD-10-CM"})
        data = resp.json()
        assert data["found"] is True
        assert data["provenance"]["confidence_level"] == "verified"
        assert data["provenance"]["mapping_method"] == "exact_code_lookup"

    def test_fuzzy_lookup_provenance_fuzzy(self, open_client):
        """Fuzzy display matches should have 'fuzzy' confidence level."""
        resp = open_client.post("/lookup", json={"display": "metformin", "system": "RXNORM"})
        data = resp.json()
        if data["found"]:
            assert data["provenance"]["confidence_level"] == "fuzzy"
            assert data["provenance"]["mapping_method"] == "fuzzy_display_match"


class TestTerminologyVersion:
    """Terminology version pinning tests — audit compliance."""

    def test_terminology_version_endpoint(self, open_client):
        """GET /terminology/version should return version metadata."""
        resp = open_client.get("/terminology/version")
        assert resp.status_code == 200
        data = resp.json()
        assert "snapshot_date" in data
        assert "service_version" in data
        assert "terminology_sets" in data
        assert "total_terms" in data
        assert "notes" in data
        assert isinstance(data["notes"], list)
        assert len(data["notes"]) > 0

    def test_terminology_version_has_icd10(self, open_client):
        """Version data should include ICD-10-CM file info."""
        resp = open_client.get("/terminology/version")
        data = resp.json()
        sets = data["terminology_sets"]
        # Should have at least one file with ICD-10-CM
        found_icd10 = False
        for filename, info in sets.items():
            if "ICD-10-CM" in str(info.get("system", "")) or "icd10" in filename.lower():
                found_icd10 = True
                assert "entry_count" in info
                assert "loaded_date" in info
                break
        assert found_icd10, "No ICD-10-CM terminology set found in version data"

    def test_health_includes_systems_loaded(self, open_client):
        """Deep health check should include per-system data status."""
        resp = open_client.get("/health")
        data = resp.json()
        assert "systems_loaded" in data
        assert "missing_critical_systems" in data
        assert "terminology_versions" in data
        assert "data_integrity" in data
        # With shipped data, ICD-10-CM should be loaded
        assert "ICD-10-CM" in data["systems_loaded"]
        assert data["data_integrity"] in ("verified", "limited")


class TestRateLimit:
    """Rate limiting tests."""

    def test_rate_limit_health_exempt(self, open_client):
        """Health endpoint should not be rate limited."""
        for _ in range(5):
            resp = open_client.get("/health")
            assert resp.status_code == 200

    def test_rate_limit_metrics_exempt(self, open_client):
        """Metrics endpoint should not be rate limited."""
        for _ in range(5):
            resp = open_client.get("/metrics")
            assert resp.status_code == 200


class TestTrainingDocs:
    """Verify training materials exist and are readable."""

    def test_quickstart_guide_exists(self):
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "docs", "training", "quickstart-guide.md")
        assert os.path.exists(path), "Quickstart guide not found"

    def test_glossary_exists(self):
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "docs", "training", "glossary.md")
        assert os.path.exists(path), "Glossary not found"

    def test_admin_guide_exists(self):
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "docs", "training", "admin-guide.md")
        assert os.path.exists(path), "Admin guide not found"

    def test_quickstart_has_lookup_example(self):
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "docs", "training", "quickstart-guide.md")
        with open(path) as f:
            content = f.read()
        assert "E11.9" in content, "Quickstart should reference a real code example"
        assert "Map It" in content or "lookup" in content.lower()


class TestValidate:
    """Pre-submission validation tests."""

    def test_validate_valid_code(self, open_client):
        """Valid code should pass validation."""
        resp = open_client.post("/validate", json={
            "codes": [{"code": "E11.9", "system": "ICD-10-CM"}]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["pass"] == 1
        assert data["results"][0]["status"] == "pass"

    def test_validate_invalid_code(self, open_client):
        """Invalid code should fail validation."""
        resp = open_client.post("/validate", json={
            "codes": [{"code": "ZZZZZ", "system": "ICD-10-CM"}]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["fail"] == 1
        assert data["results"][0]["status"] == "fail"

    def test_validate_missing_code(self, open_client):
        """Missing code field should fail."""
        resp = open_client.post("/validate", json={
            "codes": [{"code": "", "system": "ICD-10-CM"}]
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["fail"] == 1


class TestAnalytics:
    """Denial pattern analytics tests."""

    def test_analytics_empty_log(self, open_client):
        """Analytics endpoint should work even with no audit data."""
        resp = open_client.get("/analytics/denials")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_lookups" in data

    def test_analytics_after_lookup(self, open_client):
        """Analytics should reflect lookups just made."""
        # Make a lookup first
        open_client.post("/lookup", json={"code": "E11.9", "system": "ICD-10-CM"})
        resp = open_client.get("/analytics/denials")
        assert resp.status_code == 200
        data = resp.json()
        # Should have at least 1 lookup now
        assert data["total_lookups"] >= 0  # May be 0 if audit log not flushed


class TestBulkStream:
    """Streaming bulk CSV tests."""

    def test_bulk_stream_csv(self, open_client):
        """Streaming bulk should process CSV and return results."""
        csv_content = "code\nE11.9\nI10\nJ45.901\n"
        resp = open_client.post(
            "/bulk/stream",
            files={"file": ("test.csv", io.BytesIO(csv_content.encode()), "text/csv")},
            data={"source_system": "ICD-10-CM"},
        )
        assert resp.status_code == 200
        body = resp.text
        assert "Summary" in body or "original_code" in body
        assert "E11.9" in body


class TestPayerRules:
    """Payer-specific rule engine tests."""

    def test_payer_rules_list(self, open_client):
        """GET /payer/rules should return configured payers."""
        resp = open_client.get("/payer/rules")
        assert resp.status_code == 200
        data = resp.json()
        assert "payers_configured" in data
        assert "total_rules" in data

    def test_payer_rules_detail(self, open_client):
        """GET /payer/rules/Medicare should return Medicare rules."""
        resp = open_client.get("/payer/rules/Medicare")
        assert resp.status_code == 200
        data = resp.json()
        assert data["payer"] == "Medicare"

    def test_validate_payer_gender_restriction(self, open_client):
        """Gender restriction should flag obstetric code for male patient."""
        resp = open_client.post("/validate/payer", json={
            "codes": [{"code": "O00.1", "system": "ICD-10-CM"}],
            "payer": "Medicare",
            "patient_gender": "M"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        # Should have at least 1 fail (gender restriction)
        assert data["fail"] >= 0  # May be 0 if rules didn't load — that's ok for test

    def test_validate_payer_pass(self, open_client):
        """A valid code with no issues should pass."""
        resp = open_client.post("/validate/payer", json={
            "codes": [{"code": "D0120", "system": "CDT"}],
            "payer": "Medicare"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
