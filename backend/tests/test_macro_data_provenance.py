import asyncio

from app.agents.macro_analyst import MACRO_DATA_REGISTRY, macro_analyst


def test_macro_data_registry_provenance():
    """Verify macro data registry explicit metadata and absence of unverified values."""
    repo_meta = MACRO_DATA_REGISTRY["rbi_repo_rate"]
    assert repo_meta["status"] == "FEED_UNAVAILABLE"
    assert repo_meta["value"] is None
    assert "offline simulation" in repo_meta["limitation"]


def test_macro_analyst_explicit_provenance_disclosure():
    """Verify MacroAnalyst output never silently represents unverified data as current."""
    res = asyncio.run(macro_analyst.analyze("RELIANCE"))
    assert res["macro_data_status"] == "FEED_UNAVAILABLE"
    assert "limitation" in str(res["macro_provenance_note"]).lower() or "unverified" in str(res["macro_provenance_note"]).lower()
    
    # Assert observations include provenance disclosure
    obs_text = " ".join(res["key_observations"])
    assert "Macro Data Status: FEED_UNAVAILABLE" in obs_text
    assert "Live RBI policy feed unverified" in obs_text
