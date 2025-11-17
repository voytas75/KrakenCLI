"""Analysis package.

Contains pattern analysis components:
- pattern_scanner: deterministic detectors and orchestration
- pattern_nl_mapper: NL-to-existing-detector mapper (rule-based + optional LLM)
- pattern_llm_client: LiteLLM client wrapper used by the mapper

Updates:
    v0.9.16 - 2025-11-17 - Added package init to support relative imports
"""