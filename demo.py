"""
FormulaForge Demo Runner
========================
Run with --mock to test locally without AWS credentials.
Run without --mock to use real AI models via Amazon Bedrock (Nova).

Usage:
    python demo.py --mock                     # Mock mode, default query
    python demo.py --mock "vitamin C serum"   # Mock mode, custom query
    python demo.py "anti-aging night cream"   # Real AI, custom query
    FORGE_IMAGE=label.jpg python demo.py      # With product label image
"""

import json
import os
import sys
import time
import random

# ── Mock Client (for demos without API credentials) ─────────────────────

MOCK_INGREDIENTS_DB = {
    "default": [
        {"name": "hyaluronic acid", "min_pct": 0.5, "max_pct": 5.0, "cost_per_pct": 0.45, "efficacy_score": 9.0, "category": "active"},
        {"name": "niacinamide", "min_pct": 2.0, "max_pct": 10.0, "cost_per_pct": 0.20, "efficacy_score": 8.5, "category": "active"},
        {"name": "vitamin c (ascorbic acid)", "min_pct": 5.0, "max_pct": 20.0, "cost_per_pct": 0.35, "efficacy_score": 9.0, "category": "active"},
        {"name": "vitamin e (tocopherol)", "min_pct": 0.5, "max_pct": 5.0, "cost_per_pct": 0.15, "efficacy_score": 7.0, "category": "active"},
        {"name": "aloe vera gel", "min_pct": 5.0, "max_pct": 40.0, "cost_per_pct": 0.05, "efficacy_score": 6.0, "category": "base"},
        {"name": "glycerin", "min_pct": 3.0, "max_pct": 15.0, "cost_per_pct": 0.03, "efficacy_score": 6.5, "category": "base"},
        {"name": "purified water", "min_pct": 20.0, "max_pct": 75.0, "cost_per_pct": 0.01, "efficacy_score": 3.0, "category": "base"},
        {"name": "cetyl alcohol", "min_pct": 1.0, "max_pct": 8.0, "cost_per_pct": 0.08, "efficacy_score": 4.0, "category": "base"},
        {"name": "phenoxyethanol", "min_pct": 0.5, "max_pct": 1.0, "cost_per_pct": 0.12, "efficacy_score": 3.0, "category": "preservative"},
        {"name": "citric acid", "min_pct": 0.1, "max_pct": 1.0, "cost_per_pct": 0.04, "efficacy_score": 2.5, "category": "preservative"},
    ],
    "retinol": [
        {"name": "retinol", "min_pct": 0.1, "max_pct": 1.0, "cost_per_pct": 1.20, "efficacy_score": 9.5, "category": "active"},
        {"name": "peptide complex", "min_pct": 1.0, "max_pct": 8.0, "cost_per_pct": 0.80, "efficacy_score": 8.0, "category": "active"},
        {"name": "squalane", "min_pct": 5.0, "max_pct": 25.0, "cost_per_pct": 0.18, "efficacy_score": 7.5, "category": "active"},
        {"name": "ceramides", "min_pct": 1.0, "max_pct": 5.0, "cost_per_pct": 0.55, "efficacy_score": 8.0, "category": "active"},
        {"name": "shea butter", "min_pct": 2.0, "max_pct": 15.0, "cost_per_pct": 0.10, "efficacy_score": 6.0, "category": "base"},
        {"name": "jojoba oil", "min_pct": 3.0, "max_pct": 20.0, "cost_per_pct": 0.12, "efficacy_score": 6.5, "category": "base"},
        {"name": "purified water", "min_pct": 20.0, "max_pct": 60.0, "cost_per_pct": 0.01, "efficacy_score": 3.0, "category": "base"},
        {"name": "emulsifying wax", "min_pct": 2.0, "max_pct": 8.0, "cost_per_pct": 0.06, "efficacy_score": 3.0, "category": "base"},
        {"name": "phenoxyethanol", "min_pct": 0.5, "max_pct": 1.0, "cost_per_pct": 0.12, "efficacy_score": 3.0, "category": "preservative"},
        {"name": "tocopheryl acetate", "min_pct": 0.5, "max_pct": 2.0, "cost_per_pct": 0.15, "efficacy_score": 5.0, "category": "preservative"},
    ],
}

MOCK_EXPLANATIONS = [
    (
        "This formula is designed for maximum efficacy while maintaining skin safety and stability. "
        "The active ingredients work through complementary mechanisms: hydrating the skin via humectant "
        "pathways (hyaluronic acid binds up to 1000x its weight in water), protecting against oxidative "
        "stress (vitamin C neutralizes free radicals via electron donation), and strengthening the skin "
        "barrier (niacinamide stimulates ceramide synthesis).\n\n"
        "The base system uses purified water as the primary solvent with glycerin as a co-humectant that "
        "prevents transepidermal water loss (TEWL). Aloe vera provides additional soothing polysaccharides "
        "and serves as a natural thickening agent. Cetyl alcohol acts as an emollient and co-emulsifier, "
        "giving the formula its smooth, spreadable texture.\n\n"
        "Phenoxyethanol at 0.8-1.0% provides broad-spectrum antimicrobial preservation within EU regulatory "
        "limits. Citric acid serves dual purpose as a pH adjuster (targeting pH 3.5-4.0 for optimal vitamin C "
        "stability) and mild exfoliant. The formula is suitable for normal to dry skin types and should be "
        "applied in the morning under SPF protection, as vitamin C can increase photosensitivity."
    ),
    (
        "This retinol-based night treatment formula combines gold-standard anti-aging actives with a rich, "
        "barrier-supportive base. Retinol (vitamin A) works by binding to nuclear retinoic acid receptors "
        "(RARs), accelerating cell turnover and stimulating collagen I and III synthesis in the dermis. "
        "The concentration is optimized below 1% to balance efficacy with tolerability.\n\n"
        "The peptide complex supports retinol's action by signaling fibroblasts to increase extracellular "
        "matrix production. Squalane, a biomimetic lipid, provides non-comedogenic moisturization and "
        "enhances retinol penetration through the stratum corneum. Ceramides restore the lamellar lipid "
        "structure of the skin barrier, which retinol can temporarily disrupt.\n\n"
        "The emulsion base uses a water-in-oil approach with shea butter and jojoba oil providing occlusivity, "
        "while emulsifying wax creates a stable system. Tocopheryl acetate (vitamin E) serves as both an "
        "antioxidant stabilizer for the retinol molecule and a skin-conditioning agent. This formula should "
        "be used at night only, with mandatory SPF 30+ use during the day."
    ),
]

MOCK_EVALUATION = (
    "Upon critical review, this formula shows strong foundational design but has room for refinement. "
    "The active ingredient concentrations are within evidence-based ranges, and the base system provides "
    "adequate vehicle properties. However, several improvements could enhance overall performance.\n\n"
    "First, the humectant-to-occlusive ratio could be better balanced. Increasing glycerin slightly would "
    "improve moisture retention without significantly impacting cost. Second, the current formula may benefit "
    "from a small addition of panthenol (provitamin B5) for its wound-healing and anti-inflammatory properties, "
    "which would complement the existing actives. Third, some active concentrations could be fine-tuned based "
    "on the latest clinical literature."
)

MOCK_REFINEMENTS = [
    {"ingredient": "glycerin", "min_pct": 5.0, "max_pct": None, "reason": "Increase minimum to ensure adequate humectant activity"},
    {"ingredient": "purified water", "min_pct": None, "max_pct": 65.0, "reason": "Cap water to make room for more actives"},
    {"ingredient": "panthenol", "min_pct": 1.0, "max_pct": 5.0, "cost_per_pct": 0.15, "efficacy_score": 7.0, "category": "active", "reason": "Add provitamin B5 for barrier repair and anti-inflammation"},
]

MOCK_COMPARISON = (
    "Version 2 represents a meaningful improvement over the initial formulation. The most significant change "
    "is the addition of panthenol, which fills a gap in the formula's barrier repair capability. Combined with "
    "the increased glycerin minimum, the hydration architecture is now more robust.\n\n"
    "The cost increase is modest (typically under $0.50/100g) while the performance score improvement is "
    "substantial, representing better clinical efficacy per dollar spent. The reduced water percentage means "
    "a higher concentration of functional ingredients, which users will perceive as a more premium product.\n\n"
    "Version 2 is recommended for most skin types. Users with very oily skin may prefer Version 1's lighter "
    "feel due to its higher water content, while those with dry or mature skin will benefit more from Version 2's "
    "enhanced barrier support."
)


class MockNovaClient:
    """Drop-in replacement for NovaClient that returns realistic mock responses."""

    def __init__(self, *args, **kwargs):
        pass

    def invoke(self, prompt: str, system: str = "", temperature: float = 0.3,
               max_tokens: int = 4096, image_bytes=None, image_media_type="image/jpeg",
               json_mode: bool = False, _retries: int = 0) -> str:
        time.sleep(0.5)  # Simulate API latency

        prompt_lower = prompt.lower()

        # Evaluate step (check BEFORE parse since both contain "ingredient" and "json")
        if "critically evaluate" in prompt_lower or "reviewing this formula" in prompt_lower:
            refinements_json = json.dumps(MOCK_REFINEMENTS, indent=2)
            return f"{MOCK_EVALUATION}\n\n===REFINEMENTS===\n{refinements_json}"

        # Compare step
        if "compare these two" in prompt_lower:
            return MOCK_COMPARISON

        # Parse step: return ingredient JSON
        if "json array" in prompt_lower and ("ingredient" in prompt_lower or "extract" in prompt_lower):
            key = "retinol" if "retinol" in prompt_lower or "anti-aging" in prompt_lower or "night" in prompt_lower else "default"
            return json.dumps(MOCK_INGREDIENTS_DB[key], indent=2)

        # Explain step
        return random.choice(MOCK_EXPLANATIONS)

    def generate_speech(self, text: str, voice: str = "nova") -> bytes:
        return b"mock_audio_bytes"

    def transcribe_audio(self, audio_bytes: bytes, filename: str = "audio.webm") -> str:
        return "this is a mock transcription"

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    mock_mode = "--mock" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--mock"]
    query = " ".join(args) if args else "brightening vitamin C serum with hyaluronic acid for dry skin"

    if mock_mode:
        # Monkey-patch the NovaClient
        import formula_forge
        formula_forge.NovaClient = MockNovaClient
        from formula_forge import single_run, console
        console.print("[bold yellow]>>> MOCK MODE (no API calls) <<<[/bold yellow]\n")
    else:
        from formula_forge import single_run

    image_path = os.environ.get("FORGE_IMAGE")
    budget = float(os.environ.get("FORGE_BUDGET", "15.0"))

    result = single_run(query, image_path=image_path, budget=budget)
    return result


if __name__ == "__main__":
    main()
