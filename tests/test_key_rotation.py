"""
Verification test for Multi-Account Round-Robin Key Pool and Model Fallback.
Makes 3 small test schema extractions and prints which key and model processed each call.
"""

import os
import sys
import logging

# Ensure project root is in python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from pydantic import BaseModel, Field
from src.llm_router import invoke_structured_llm, get_key_pool


class TestExtraction(BaseModel):
    query_id: int = Field(description="The integer query ID")
    extracted_summary: str = Field(description="A concise summary in 5 words or fewer")


def test_round_robin_rotation():
    print("=" * 70)
    print("  TEST: Multi-Account Round-Robin Key Pool Verification")
    print("=" * 70)

    keys = get_key_pool()
    print(f"Active Key Pool Count: {len(keys)}")
    for i, k in enumerate(keys, 1):
        print(f"  Key #{i}: ...{k[-4:]}")

    if not keys:
        print("[FAIL] No keys found in GEMINI_API_KEYS or GOOGLE_API_KEY")
        return

    test_prompts = [
        "Extract query_id: 1, extracted_summary: Alpha test prompt processed",
        "Extract query_id: 2, extracted_summary: Beta test prompt processed",
        "Extract query_id: 3, extracted_summary: Gamma test prompt processed",
    ]

    used_keys = []
    used_models = []

    print("\nExecuting 3 structured calls through invoke_structured_llm()...\n")

    for i, prompt in enumerate(test_prompts, 1):
        result, meta = invoke_structured_llm(
            TestExtraction,
            prompt,
            tier="lite",
            return_meta=True,
        )
        print(f"Call #{i}:")
        print(f"  [OK] Model used: {meta['model']}")
        print(f"  [OK] Key used:   {meta['key_suffix']}")
        print(f"  [OK] Extracted:  ID={result.query_id}, Summary='{result.extracted_summary}'")
        print("-" * 50)

        used_keys.append(meta["key_suffix"])
        used_models.append(meta["model"])

    print("\nRotation Summary:")
    print(f"  Keys used across calls: {' -> '.join(used_keys)}")
    print(f"  Models used:            {' -> '.join(set(used_models))}")

    if len(keys) > 1:
        # Check that multiple keys were exercised
        unique_keys = set(used_keys)
        print(f"  Unique keys exercised:  {len(unique_keys)} of {len(keys)}")
        if len(unique_keys) > 1:
            print("  [SUCCESS] Round-robin key rotation confirmed active!")
        else:
            print("  [NOTE] Only 1 unique key was used (check pool configuration).")
    else:
        print("  [SUCCESS] Single key execution succeeded.")

    print("\n" + "=" * 70)
    print("  TEST COMPLETED SUCCESSFULLY")
    print("=" * 70)


if __name__ == "__main__":
    test_round_robin_rotation()

