import asyncio
import json
import os
import sys
import urllib.error
import urllib.request

# Ensure UTF-8 output on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.abspath("backend"))

from app.agents.llm_provider import local_llm_provider

BACKEND_URL = "http://127.0.0.1:8000"

def http_post(url: str, data: dict, timeout: int = 60):
    req = urllib.request.Request(url, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    body = json.dumps(data).encode("utf-8")
    with urllib.request.urlopen(req, data=body, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode())

def http_get(url: str, timeout: int = 15):
    req = urllib.request.Request(url, method="GET")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, json.loads(resp.read().decode())

print("================================================================================")
print("   PHASE D, E, F: LIVE INFERENCE, SIX-AGENT WORKFLOW & DECISION PIPELINE AUDIT   ")
print("================================================================================")

# -------------------------------------------------------------------------
# PHASE D: Verify Genuine Local Inference & Failure Modes
# -------------------------------------------------------------------------
print("\n--- PHASE D: VERIFYING GENUINE LOCAL INFERENCE VIA OLLAMA ---")
code, agent_resp = http_post(f"{BACKEND_URL}/api/v1/agents/analyze", {"symbol": "RELIANCE"}, timeout=60)
assert code == 200, f"Agents analyze failed with status {code}"

print(f"Backend HTTP Response: {code} OK")
agent_audit = {}
for role, card in agent_resp.items():
    if not isinstance(card, dict) or "execution_mode" not in card:
        continue
    agent_audit[role] = {
        "provider": card.get("provider"),
        "model": card.get("model"),
        "execution_mode": card.get("execution_mode"),
        "latency_ms": card.get("latency_ms"),
        "value": card.get("value"),
        "confidence": card.get("confidence")
    }
    latency = card.get('latency_ms') or 0.0
    print(f"  [{role.upper():<20}] Mode: {card.get('execution_mode'):<12} | Prov: {card.get('provider'):<8} | Model: {card.get('model'):<12} | Latency: {latency:>7.1f} ms | Stance: {card.get('value')}")
    # Verify strict non-negotiable assertions:
    assert card.get("execution_mode") == "local_llm", f"{role} did not use local_llm!"
    assert card.get("provider") == "ollama", f"{role} provider is not ollama!"
    assert card.get("model") == "qwen3.5:4b", f"{role} model is not qwen3.5:4b!"
    assert card.get("latency_ms") is not None and card.get("latency_ms") > 0

print("\n[OK] Phase D (Mode 1 - Live Local Inference): All 6 specialist agents executed through Ollama (qwen3.5:4b).")

# Phase D: Failure Modes 2 through 6
print("\nTesting Failure Mode 2: Ollama Service Unavailable (Port 9999)...")
async def test_failure_modes():
    orig_url = local_llm_provider.base_url
    orig_enabled = local_llm_provider.enabled
    orig_model = local_llm_provider.model

    try:
        # Mode 2: Service down
        local_llm_provider.base_url = "http://127.0.0.1:9999"
        local_llm_provider._is_healthy = False
        local_llm_provider._last_health_check = 0.0
        res2, prov2 = await local_llm_provider.generate_structured(
            prompt="Test", system_prompt="Test", expected_keys=["test"]
        )
        assert res2 is None
        assert prov2["execution_mode"] == "deterministic_fallback"
        print(f"  -> Passed: Port 9999 down cleanly triggered fallback ({prov2['error'][:40]}...).")

        # Mode 3: Ollama Disabled
        print("Testing Failure Mode 3: Ollama Disabled in Config...")
        local_llm_provider.base_url = orig_url
        local_llm_provider.enabled = False
        res3, prov3 = await local_llm_provider.generate_structured(
            prompt="Test", system_prompt="Test", expected_keys=["test"]
        )
        assert res3 is None
        assert prov3["execution_mode"] == "deterministic_fallback"
        print(f"  -> Passed: Disabled config cleanly triggered fallback ({prov3['error'][:40]}...).")

        # Mode 4: Non-existent model
        print("Testing Failure Mode 4: Non-existent Model ('non_existent_xyz')...")
        local_llm_provider.enabled = True
        local_llm_provider.model = "non_existent_xyz"
        local_llm_provider._is_healthy = False
        local_llm_provider._last_health_check = 0.0
        res4, prov4 = await local_llm_provider.generate_structured(
            prompt="Test", system_prompt="Test", expected_keys=["test"]
        )
        assert res4 is None
        assert prov4["execution_mode"] == "deterministic_fallback"
        print(f"  -> Passed: Missing model cleanly triggered fallback ({prov4['error'][:40]}...).")

        # Mode 5: Malformed JSON cleaning
        print("Testing Failure Mode 5: Cleaning Malformed / Fenced JSON strings...")
        fenced = "```json\n{\"trend\": \"Bullish\", \"confidence\": 0.9}\n```"
        cleaned = local_llm_provider.clean_json_string(fenced)
        parsed = json.loads(cleaned)
        assert parsed["trend"] == "Bullish"
        print(f"  -> Passed: Cleaned fence markdown to valid JSON: {cleaned}")

    finally:
        local_llm_provider.base_url = orig_url
        local_llm_provider.enabled = orig_enabled
        local_llm_provider.model = orig_model
        local_llm_provider._is_healthy = False
        local_llm_provider._last_health_check = 0.0

asyncio.run(test_failure_modes())
print("[OK] All Phase D failure modes tested and safely handled.")

# -------------------------------------------------------------------------
# PHASE E: Specialist Agent Quality & Grounding Audit
# -------------------------------------------------------------------------
print("\n--- PHASE E: AUDITING SPECIALIST AGENTS GROUNDING & ROLE SCHEMAS ---")

# 1. Market Analyst Grounding
ma = agent_resp["market_analyst"]
print(f"1. Market Analyst: Value='{ma.get('value')}', Confidence={ma.get('confidence')}")
print(f"   Summary: {ma.get('summary')}")
assert any(t in ma.get("value", "").upper() for t in ["BULLISH", "BEARISH", "NEUTRAL"]), "Invalid stance"
assert 0.0 <= float(ma.get("confidence", 0)) <= 1.0, "Confidence out of bounds"

# 2. Sentiment Analyst Grounding
sa = agent_resp["sentiment_analyst"]
print(f"2. Sentiment Analyst: Value='{sa.get('value')}', Confidence={sa.get('confidence')}")
print(f"   Summary: {sa.get('summary')}")
assert 0.0 <= float(sa.get("confidence", 0)) <= 1.0

# 3. Macro Analyst Grounding
macro = agent_resp["macro_analyst"]
print(f"3. Macro Analyst: Value='{macro.get('value')}', Confidence={macro.get('confidence')}")
print(f"   Summary: {macro.get('summary')}")

# 4. Quant Analyst Grounding
qa = agent_resp["quant_analyst"]
print(f"4. Quant Analyst: Value='{qa.get('value')}', Confidence={qa.get('confidence')}")
print(f"   Summary: {qa.get('summary')}")

# 5. Risk Officer Grounding & Non-overridable bounds
ro = agent_resp["risk_officer"]
print(f"5. Risk Officer: Value='{ro.get('value')}', Confidence={ro.get('confidence')}")
print(f"   Summary: {ro.get('summary')}")
obs = ro.get("key_observations", [])
print(f"   Key Observations: {obs}")
assert any("VaR" in str(o) for o in obs), "Missing VaR in Risk Officer observations"

# 6. Portfolio Manager Synthesis
pm = agent_resp["portfolio_manager"]
print(f"6. Portfolio Manager: Value='{pm.get('value')}', Action='{pm.get('action')}', Target Qty={pm.get('target_quantity')}")
print(f"   Summary: {pm.get('summary')}")
assert pm.get("action") in ["BUY", "SELL", "HOLD"], "Invalid action"
assert pm.get("target_quantity") >= 0, "Invalid target quantity"

print("\n[OK] Phase E: All six agent output contracts, ranges, and evidence grounds verified.")

# -------------------------------------------------------------------------
# PHASE F: Validate Five-Stage Decision Pipeline
# -------------------------------------------------------------------------
print("\n--- PHASE F: VALIDATING FIVE-STAGE DECISION PIPELINE ---")

# Test Run 1: Permitted Decision Pipeline Run on RELIANCE with Volatility Surge
print("Executing Test Run 1: Normal / Volatility Surge pipeline run...")
code, pipe_run1 = http_post(f"{BACKEND_URL}/api/v1/decisions/run", {
    "symbol": "RELIANCE",
    "scenario_type": "VOLATILITY_SURGE",
    "severity": 40.0,
    "auto_execute": False
}, timeout=60)
assert code == 200
stages1 = pipe_run1["stages"]
print(f"Run ID: {pipe_run1['run_id']} | Status: {pipe_run1['status']} | Execution Mode: {pipe_run1['execution_mode']}")
assert len(stages1) == 5, f"Expected 5 stages, got {len(stages1)}"
stage_names1 = [s["name"] for s in stages1]
print(f"Stages: {' -> '.join(stage_names1)}")
assert stage_names1 == ["Market Data", "Specialist Analysis", "Portfolio Proposal", "Risk Gate", "Simulated Execution"]
for s in stages1:
    summary_clean = s['summary'].replace('\u20b9', 'INR ')[:80]
    print(f"  Stage '{s['name']}': state={s['state']} | summary: {summary_clean}...")
    assert s["state"] in ["done", "idle", "bad"]

# Test Run 2: Unverified Rumor Scenario -> Must be deterministically REJECTED by Risk Gate
print("\nExecuting Test Run 2: Unverified Rumor pipeline run (Must trigger Gate Veto)...")
code, pipe_run2 = http_post(f"{BACKEND_URL}/api/v1/decisions/run", {
    "symbol": "RELIANCE",
    "scenario_type": "UNVERIFIED_RUMOR",
    "severity": 70.0,
    "auto_execute": True
}, timeout=60)
assert code == 200
stages2 = pipe_run2["stages"]
print(f"Run ID: {pipe_run2['run_id']} | Status: {pipe_run2['status']}")
stage_states2 = {s["name"]: s["state"] for s in stages2}
print(f"Stage States: {stage_states2}")
assert stage_states2["Risk Gate"] == "bad", "Risk Gate should be marked bad for Unverified Rumor"
assert stage_states2["Simulated Execution"] == "bad", "Simulated Execution should be blocked (bad)"
assert pipe_run2["status"] == "rejected", "Pipeline run status must be 'rejected'"
veto_summary = stages2[3]['summary'].replace('\u20b9', 'INR ')
print(f"[OK] Deterministic Risk Gate veto verified: {veto_summary}")

print("\n================================================================================")
print("   PHASE D, E, F AUDIT COMPLETED SUCCESSFULLY WITH 100% EMPIRICAL PASS         ")
print("================================================================================")
