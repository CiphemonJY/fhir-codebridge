"""Tests for the codebridge client SDK."""
import os
import sys
import json
import io
import csv

# Ensure the package is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from codebridge import CodeBridge


def test_client_initialization():
    """Client should initialize with URL and optional API key."""
    cb = CodeBridge("http://localhost:8000/", api_key="test-key")
    assert cb.base_url == "http://localhost:8000"  # trailing slash stripped
    assert cb.api_key == "test-key"


def test_client_reads_env_key():
    """Client should read API key from CODEBRIDGE_API_KEY env var."""
    os.environ["CODEBRIDGE_API_KEY"] = "env-key-123"
    cb = CodeBridge()
    assert cb.api_key == "env-key-123"
    del os.environ["CODEBRIDGE_API_KEY"]


def test_client_lookup_method_exists():
    """Client should have all expected methods."""
    cb = CodeBridge()
    assert hasattr(cb, "lookup")
    assert hasattr(cb, "translate")
    assert hasattr(cb, "bulk_map")
    assert hasattr(cb, "health")
    assert hasattr(cb, "stats")
    assert hasattr(cb, "systems")
    assert hasattr(cb, "metrics")
    assert hasattr(cb, "audit")