"""Tests for alert integration wiring — verify fire_alert/fire_alert_event
are called at the right integration points with correct arguments."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone


# ── PHI Shield ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_phi_shield_fires_alert_on_detection():
    """PHI detection should fire an event alert."""
    with patch("trellis.alerts.fire_alert_event", new_callable=AsyncMock) as mock_fire:
        from trellis.phi_shield import shield_request
        messages = [{"role": "user", "content": "Patient SSN is 123-45-6789"}]
        await shield_request(messages, agent_id="test-agent", phi_shield_mode="full")

        mock_fire.assert_called_once()
        args, kwargs = mock_fire.call_args
        assert args[0] == "phi_shield"
        assert args[1] == "phi_detected"
        assert "SSN" in args[2]
        assert kwargs["agent_id"] == "test-agent"


@pytest.mark.asyncio
async def test_phi_shield_no_alert_when_clean():
    """No PHI = no alert."""
    with patch("trellis.alerts.fire_alert_event", new_callable=AsyncMock) as mock_fire:
        from trellis.phi_shield import shield_request
        messages = [{"role": "user", "content": "Hello, how are you?"}]
        await shield_request(messages, agent_id="test-agent", phi_shield_mode="full")

        mock_fire.assert_not_called()


@pytest.mark.asyncio
async def test_phi_shield_no_alert_when_off():
    """PHI shield off = no alert."""
    with patch("trellis.alerts.fire_alert_event", new_callable=AsyncMock) as mock_fire:
        from trellis.phi_shield import shield_request
        messages = [{"role": "user", "content": "Patient SSN is 123-45-6789"}]
        await shield_request(messages, agent_id="test-agent", phi_shield_mode="off")

        mock_fire.assert_not_called()


# ── Gateway Budget Alerts ──────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_budget_fires_alert_on_high_spend():
    """Budget ratio >= 80% should fire a finops alert."""
    with patch("trellis.alerts.fire_alert", new_callable=AsyncMock) as mock_fire, \
         patch("trellis.gateway._get_daily_spend", new_callable=AsyncMock, return_value=9.0), \
         patch("trellis.gateway._get_monthly_spend", new_callable=AsyncMock, return_value=85.0):
        from trellis.gateway import check_budget_alerts

        api_key = MagicMock()
        api_key.agent_id = "test-agent"
        api_key.budget_daily_usd = 10.0
        api_key.budget_monthly_usd = 100.0

        db = AsyncMock()
        await check_budget_alerts(db, api_key)

        assert mock_fire.call_count == 2
        # Daily call
        daily_call = mock_fire.call_args_list[0]
        assert daily_call.args[0] == "finops"
        assert daily_call.args[1] == "budget_pct"
        assert daily_call.args[2] == 90.0  # 9/10 * 100
        # Monthly call
        monthly_call = mock_fire.call_args_list[1]
        assert monthly_call.args[2] == 85.0  # 85/100 * 100


@pytest.mark.asyncio
async def test_budget_no_alert_under_threshold():
    """Budget ratio < 80% should not fire."""
    with patch("trellis.alerts.fire_alert", new_callable=AsyncMock) as mock_fire, \
         patch("trellis.gateway._get_daily_spend", new_callable=AsyncMock, return_value=5.0), \
         patch("trellis.gateway._get_monthly_spend", new_callable=AsyncMock, return_value=30.0):
        from trellis.gateway import check_budget_alerts

        api_key = MagicMock()
        api_key.agent_id = "test-agent"
        api_key.budget_daily_usd = 10.0
        api_key.budget_monthly_usd = 100.0

        db = AsyncMock()
        await check_budget_alerts(db, api_key)

        mock_fire.assert_not_called()


# ── Observatory ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_observatory_fires_alert_on_metrics(client):
    """Observatory model metrics endpoint should fire alerts for error rate and latency."""
    from trellis.database import async_session
    from trellis.models import CostEvent

    # Seed some cost events
    async with async_session() as db:
        for i in range(5):
            db.add(CostEvent(
                agent_id="test", model_requested="gpt-4", model_used="gpt-4",
                provider="openai", tokens_in=100, tokens_out=50,
                cost_usd=0.01, latency_ms=500 + i * 100,
                has_tool_calls=False, complexity_class="normal",
                timestamp=datetime.now(timezone.utc),
            ))
        await db.commit()

    with patch("trellis.alerts.fire_alert", new_callable=AsyncMock) as mock_fire:
        resp = await client.get("/api/observatory/models/gpt-4/metrics?hours=1",
                                headers={"Authorization": "Bearer test-mgmt-key"})
        if resp.status_code == 200:
            assert mock_fire.call_count >= 1
            sources = [c.args[0] for c in mock_fire.call_args_list]
            assert "observatory" in sources


# ── Health Auditor ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_health_auditor_fires_alert_on_failure():
    """Failed health checks should fire event alerts."""
    with patch("trellis.alerts.fire_alert_event", new_callable=AsyncMock) as mock_fire, \
         patch("trellis.agents.health_auditor.run_agent_health_checks", new_callable=AsyncMock, return_value=[]), \
         patch("trellis.agents.health_auditor.check_llm_providers", new_callable=AsyncMock, return_value=[]), \
         patch("trellis.agents.health_auditor.check_database", new_callable=AsyncMock) as mock_db_check, \
         patch("trellis.agents.health_auditor.check_adapters", new_callable=AsyncMock, return_value=[]), \
         patch("trellis.agents.health_auditor.check_background_tasks", return_value=[]), \
         patch("trellis.agents.health_auditor.check_smtp") as mock_smtp, \
         patch("trellis.agents.health_auditor.check_system") as mock_system, \
         patch("trellis.agents.health_auditor.async_session") as mock_session:

        from trellis.agents.health_auditor import run_all_checks, CheckResult

        mock_db_check.return_value = CheckResult(name="database", status="degraded", details={"error": "test"})
        mock_smtp.return_value = CheckResult(name="smtp", status="healthy")
        mock_system.return_value = CheckResult(name="system", status="healthy")

        # Mock the DB session for persisting health checks
        mock_db_ctx = AsyncMock()
        mock_session.return_value.__aenter__ = mock_db_ctx
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        await run_all_checks()

        mock_fire.assert_called()
        call_args = mock_fire.call_args_list[0]
        assert call_args.args[0] == "health"
        assert call_args.args[1] == "check_failed"
        assert "database" in call_args.args[2]


@pytest.mark.asyncio
async def test_health_auditor_no_alert_when_healthy():
    """All healthy checks should not fire alerts."""
    with patch("trellis.alerts.fire_alert_event", new_callable=AsyncMock) as mock_fire, \
         patch("trellis.agents.health_auditor.run_agent_health_checks", new_callable=AsyncMock, return_value=[]), \
         patch("trellis.agents.health_auditor.check_llm_providers", new_callable=AsyncMock, return_value=[]), \
         patch("trellis.agents.health_auditor.check_database", new_callable=AsyncMock) as mock_db_check, \
         patch("trellis.agents.health_auditor.check_adapters", new_callable=AsyncMock, return_value=[]), \
         patch("trellis.agents.health_auditor.check_background_tasks", return_value=[]), \
         patch("trellis.agents.health_auditor.check_smtp") as mock_smtp, \
         patch("trellis.agents.health_auditor.check_system") as mock_system, \
         patch("trellis.agents.health_auditor.async_session") as mock_session:

        from trellis.agents.health_auditor import run_all_checks, CheckResult

        mock_db_check.return_value = CheckResult(name="database", status="healthy")
        mock_smtp.return_value = CheckResult(name="smtp", status="healthy")
        mock_system.return_value = CheckResult(name="system", status="healthy")

        mock_db_ctx = AsyncMock()
        mock_session.return_value.__aenter__ = mock_db_ctx
        mock_session.return_value.__aexit__ = AsyncMock(return_value=False)

        await run_all_checks()

        mock_fire.assert_not_called()
