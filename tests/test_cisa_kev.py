"""Tests for the CISA KEV lookup tool."""

from unittest.mock import patch, MagicMock
import time

import httpx
import pytest

import trellis.agents.tools as tools

# Sample KEV catalog payload for mocking
_FAKE_CATALOG = {
    "title": "CISA KEV Catalog",
    "catalogVersion": "2024.01.01",
    "vulnerabilities": [
        {
            "cveID": "CVE-2021-44228",
            "vendorProject": "Apache",
            "product": "Log4j",
            "dateAdded": "2021-12-10",
            "shortDescription": "Apache Log4j2 JNDI features do not protect against attacker-controlled LDAP and other JNDI related endpoints.",
            "requiredAction": "For all affected software assets, apply patches or remove Log4j.",
            "dueDate": "2021-12-24",
        },
        {
            "cveID": "CVE-2023-12345",
            "vendorProject": "TestVendor",
            "product": "TestProduct",
            "dateAdded": "2023-06-01",
            "shortDescription": "Test vulnerability.",
            "requiredAction": "Apply patch.",
            "dueDate": "2023-06-15",
        },
    ],
}


def _reset_cache():
    """Clear module-level cache between tests."""
    tools._cisa_kev_cache = None
    tools._cisa_kev_cache_ts = 0.0


@pytest.fixture(autouse=True)
def clear_cache():
    _reset_cache()
    yield
    _reset_cache()


def _mock_response():
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = _FAKE_CATALOG
    resp.raise_for_status = MagicMock()
    return resp


class TestCheckCisaKev:
    """Tests for check_cisa_kev function."""

    @patch("trellis.agents.tools.httpx.get")
    def test_found_cve(self, mock_get):
        mock_get.return_value = _mock_response()
        result = tools.check_cisa_kev("CVE-2021-44228")

        assert result["found"] is True
        assert result["vulnerability"] is not None
        vuln = result["vulnerability"]
        assert vuln["cveID"] == "CVE-2021-44228"
        assert vuln["vendorProject"] == "Apache"
        assert vuln["product"] == "Log4j"
        assert vuln["dateAdded"] == "2021-12-10"
        assert vuln["shortDescription"] is not None
        assert vuln["requiredAction"] is not None
        assert vuln["dueDate"] == "2021-12-24"

    @patch("trellis.agents.tools.httpx.get")
    def test_not_found_cve(self, mock_get):
        mock_get.return_value = _mock_response()
        result = tools.check_cisa_kev("CVE-9999-99999")

        assert result["found"] is False
        assert result["vulnerability"] is None
        assert "error" not in result

    @patch("trellis.agents.tools.httpx.get")
    def test_case_insensitive_lookup(self, mock_get):
        mock_get.return_value = _mock_response()
        result = tools.check_cisa_kev("cve-2021-44228")

        assert result["found"] is True
        assert result["vulnerability"]["cveID"] == "CVE-2021-44228"

    @patch("trellis.agents.tools.httpx.get")
    def test_whitespace_stripped(self, mock_get):
        mock_get.return_value = _mock_response()
        result = tools.check_cisa_kev("  CVE-2021-44228  ")

        assert result["found"] is True

    @patch("trellis.agents.tools.httpx.get")
    def test_cache_prevents_refetch(self, mock_get):
        mock_get.return_value = _mock_response()

        tools.check_cisa_kev("CVE-2021-44228")
        tools.check_cisa_kev("CVE-2021-44228")

        assert mock_get.call_count == 1

    @patch("trellis.agents.tools.httpx.get")
    @patch("trellis.agents.tools.time")
    def test_cache_ttl_expired(self, mock_time, mock_get):
        mock_get.return_value = _mock_response()
        # First call at t=1000
        mock_time.time.return_value = 1000.0
        tools.check_cisa_kev("CVE-2021-44228")
        assert mock_get.call_count == 1

        # Second call within TTL — no refetch
        mock_time.time.return_value = 1000.0 + 3599
        tools.check_cisa_kev("CVE-2021-44228")
        assert mock_get.call_count == 1

        # Third call after TTL — refetch
        mock_time.time.return_value = 1000.0 + 3601
        tools.check_cisa_kev("CVE-2021-44228")
        assert mock_get.call_count == 2

    @patch("trellis.agents.tools.httpx.get")
    def test_network_error(self, mock_get):
        mock_get.side_effect = httpx.ConnectError("Connection refused")
        result = tools.check_cisa_kev("CVE-2021-44228")

        assert result["found"] is False
        assert result["vulnerability"] is None
        assert "error" in result
        assert "Connection refused" in result["error"]

    @patch("trellis.agents.tools.httpx.get")
    def test_http_error_status(self, mock_get):
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 503
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "503 Service Unavailable", request=MagicMock(), response=resp
        )
        mock_get.return_value = resp
        result = tools.check_cisa_kev("CVE-2021-44228")

        assert result["found"] is False
        assert "error" in result

    @patch("trellis.agents.tools.httpx.get")
    def test_timeout_error(self, mock_get):
        mock_get.side_effect = httpx.TimeoutException("Timed out")
        result = tools.check_cisa_kev("CVE-2021-44228")

        assert result["found"] is False
        assert "error" in result


class TestCisaKevSchema:
    """Tests for the CISA_KEV_SCHEMA constant."""

    def test_schema_structure(self):
        assert tools.CISA_KEV_SCHEMA["type"] == "function"
        func = tools.CISA_KEV_SCHEMA["function"]
        assert func["name"] == "check_cisa_kev"
        assert "cve_id" in func["parameters"]["properties"]
        assert func["parameters"]["required"] == ["cve_id"]
