import asyncio
from unittest.mock import patch

import httpx
from app.agents.llm_provider import LocalLLMProvider
from app.agents.macro_analyst import macro_analyst
from app.agents.market_analyst import market_analyst
from app.agents.portfolio_manager import portfolio_manager
from app.agents.quant_analyst import quant_analyst
from app.agents.risk_officer import risk_officer
from app.agents.sentiment_analyst import sentiment_analyst
from app.risk.engine import risk_engine
from pydantic import BaseModel


class SampleTestSchema(BaseModel):
    trend: str
    confidence: float


def test_llm_provider_clean_json_string():
    """Verify clean_json_string strips code fences, whitespace, and extraneous text."""
    provider = LocalLLMProvider()
    
    # 1. Clean code fence
    fence_input = '```json\n{"trend": "Bullish", "score": 42}\n```'
    assert provider.clean_json_string(fence_input) == '{"trend": "Bullish", "score": 42}'
    
    # 2. Text with leading/trailing commentary
    noisy_input = 'Here is the JSON response:\n{"regime": "Expansion"}\nHope this helps!'
    assert provider.clean_json_string(noisy_input) == '{"regime": "Expansion"}'


def test_llm_provider_unavailable_handling():
    """Verify graceful handling when Ollama is disabled or port is unreachable."""
    async def _run():
        provider = LocalLLMProvider()
        provider.enabled = False
        
        res, meta = await provider.generate_structured(
            prompt="test",
            system_prompt="test",
            expected_keys=["trend"]
        )
        assert res is None
        assert meta["execution_mode"] == "deterministic_fallback"
        assert "disabled" in meta["error"].lower()

    asyncio.run(_run())


def test_llm_provider_malformed_json_fallback():
    """Verify graceful handling when model returns non-JSON or truncated text."""
    async def _run():
        provider = LocalLLMProvider()
        provider.enabled = True
        
        dummy_req = httpx.Request("POST", "http://test")
        mock_resp = httpx.Response(200, json={"message": {"content": "I am not returning JSON today!"}}, request=dummy_req)
        
        with patch("httpx.AsyncClient.post", return_value=mock_resp), \
             patch.object(provider, "is_available", return_value=True):
            res, meta = await provider.generate_structured(
                prompt="test",
                system_prompt="test",
                expected_keys=["trend"]
            )
            assert res is None
            assert meta["execution_mode"] == "deterministic_fallback"
            assert meta["validation_passed"] is False
            assert "Failed to parse JSON" in meta["error"] or "Missing required keys" in meta["error"]

    asyncio.run(_run())


def test_llm_provider_timeout_fallback():
    """Verify graceful handling when Ollama times out."""
    async def _run():
        provider = LocalLLMProvider()
        provider.enabled = True
        
        with patch("httpx.AsyncClient.post", side_effect=httpx.TimeoutException("Read timed out")), \
             patch.object(provider, "is_available", return_value=True):
            res, meta = await provider.generate_structured(
                prompt="test",
                system_prompt="test"
            )
            assert res is None
            assert meta["execution_mode"] == "deterministic_fallback"
            assert "timed out" in meta["error"].lower()

    asyncio.run(_run())


def test_llm_provider_missing_model_handling():
    """Verify is_available returns False when configured model is not in Ollama list."""
    async def _run():
        provider = LocalLLMProvider()
        provider.enabled = True
        provider.model = "non_existent_model_999"
        
        dummy_req = httpx.Request("GET", "http://test")
        mock_tags = httpx.Response(200, json={"models": [{"name": "qwen3.5:4b"}]}, request=dummy_req)
        
        with patch("httpx.AsyncClient.get", return_value=mock_tags):
            available = await provider.is_available(force_check=True)
            assert available is False

    asyncio.run(_run())


def test_llm_schema_validation_enforcement():
    """Verify Pydantic model validation passes on compliant JSON and fails on invalid types."""
    async def _run():
        provider = LocalLLMProvider()
        provider.enabled = True
        dummy_req = httpx.Request("POST", "http://test")
        
        # Valid schema response
        mock_resp_valid = httpx.Response(200, json={"message": {"content": '{"trend": "Bullish", "confidence": 0.95}'}}, request=dummy_req)
        
        with patch("httpx.AsyncClient.post", return_value=mock_resp_valid), \
             patch.object(provider, "is_available", return_value=True):
            res, meta = await provider.generate_structured(
                prompt="test",
                system_prompt="test",
                schema_model=SampleTestSchema
            )
            assert res is not None
            assert meta["validation_passed"] is True
            assert meta["execution_mode"] == "local_llm"
            assert meta["provider"] == "ollama"

        # Invalid schema response (string instead of float confidence)
        mock_resp_invalid = httpx.Response(200, json={"message": {"content": '{"trend": "Bullish", "confidence": "INVALID_FLOAT"}'}}, request=dummy_req)
        
        with patch("httpx.AsyncClient.post", return_value=mock_resp_invalid), \
             patch.object(provider, "is_available", return_value=True):
            res, meta = await provider.generate_structured(
                prompt="test",
                system_prompt="test",
                schema_model=SampleTestSchema
            )
            assert res is None
            assert meta["validation_passed"] is False
            assert "Pydantic schema validation error" in meta["error"]

    asyncio.run(_run())


def test_all_six_agents_output_contracts():
    """Verify all 6 agents return their expected dictionary keys and provenance fields."""
    async def _run():
        sample_indicators = {
            "trend": "Bullish",
            "momentum": "Neutral",
            "rsi_14": 49.2,
            "sma_20": 1210.0,
            "ema_50": 1205.0,
            "volatility": 0.18,
            "bollinger_upper": 1250.0,
            "bollinger_lower": 1170.0,
            "macd": 2.5,
            "macd_signal": 1.8,
            "macd_hist": 0.7,
        }
        
        # 1. Market Analyst
        m_out = await market_analyst.analyze("RELIANCE", sample_indicators, 1211.70)
        assert "trend" in m_out and "summary" in m_out and "execution_mode" in m_out
        assert m_out["execution_mode"] in ("local_llm", "deterministic_fallback")
        assert "provider" in m_out
        
        # 2. Sentiment Analyst
        s_out = await sentiment_analyst.analyze("RELIANCE", headline="Reliance reports robust refining margins.")
        assert "sentiment" in s_out and "sentiment_score" in s_out and "execution_mode" in s_out
        assert "provider" in s_out
        
        # 3. Macro Strategist
        mac_out = await macro_analyst.analyze("RELIANCE")
        assert "macro_regime" in mac_out and "sector_rating" in mac_out and "execution_mode" in mac_out
        assert "provider" in mac_out
        
        # 4. Quant Analyst
        q_out = await quant_analyst.analyze("RELIANCE", sample_indicators, 1211.70)
        assert "alpha_score" in q_out and "regime" in q_out and "execution_mode" in q_out
        assert "provider" in q_out
        
        # 5. Risk Officer
        r_out = await risk_officer.analyze("RELIANCE", 1211.70, equity=1000000.0)
        assert "risk_status" in r_out and "var_95_pct" in r_out and "execution_mode" in r_out
        assert "provider" in r_out
        
        # 6. Portfolio Manager
        pm_out = await portfolio_manager.propose(
            symbol="RELIANCE",
            market_analysis=m_out,
            sentiment_analysis=s_out,
            equity=1000000.0,
            current_price=1211.70,
            quant_analysis=q_out,
            macro_analysis=mac_out,
            risk_analysis=r_out
        )
        assert "action" in pm_out and "target_quantity" in pm_out and "execution_mode" in pm_out
        assert pm_out["action"] in ("BUY", "SELL", "HOLD")
        assert "provider" in pm_out

    asyncio.run(_run())


def test_deterministic_risk_cannot_be_overridden_by_llm(db):
    """
    Verify that even if an LLM proposes a trade, the deterministic Risk Gate
    strictly halts orders violating risk rules (e.g. unverified rumor, excessive allocation).
    """
    # 1. Unverified rumor rejection
    eval_rumor = risk_engine.evaluate_order(
        db=db,
        symbol="RELIANCE",
        side="BUY",
        requested_qty=20,
        price=1211.70,
        scenario_type="UNVERIFIED_RUMOR"
    )
    assert eval_rumor["outcome"] == "REJECTED"
    assert "unverified headline" in eval_rumor["reason"].lower()

    # 2. Oversized order resizing (10% equity rule)
    eval_size = risk_engine.evaluate_order(
        db=db,
        symbol="RELIANCE",
        side="BUY",
        requested_qty=200,  # 200 * 1211.70 = 242,340 > 10% of 1,000,000 (100,000)
        price=1211.70
    )
    assert eval_size["outcome"] == "RESIZED"
    assert eval_size["approved_qty"] < 200
    assert eval_size["approved_qty"] * 1211.70 <= 101000.0
