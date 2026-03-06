"""
FormulaForge - AI-Powered Cosmetic Formulation Optimization Agent
=================================================================
An agentic pipeline that uses OpenAI GPT-4o for reasoning
and PuLP for linear programming to design optimal cosmetic formulations.

Pipeline:
  Step 1  [PARSE]      Nova parses user input (text or image) into structured ingredient JSON
  Step 2  [OPTIMIZE]   PuLP LP solver maximizes performance score under real-world constraints
  Step 3  [EXPLAIN]    Nova writes a scientific explanation of the optimized formula
  Step 4  [EVALUATE]   Nova critiques the formula and proposes constraint refinements
  Step 5  [RE-OPTIMIZE] Solver runs again with agent-suggested adjustments (true agent loop)
  Step 6  [COMPARE]    Side-by-side delta analysis of v1 vs v2 with improvement narrative

Supports up to N refinement loops (configurable), multimodal label scanning,
regulatory guardrails, and ingredient interaction/synergy modeling.

Author: Sami (FormulaForge / OraxAI)
Stack:  openai + GPT-4o  |  PuLP  |  Rich (terminal UI)
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field
from enum import Enum
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

import pulp
from openai import OpenAI, RateLimitError, APIError
from rich.columns import Columns
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text
from rich import box

# ──────────────────────────────────────────────────────────────────────────────
# Configuration & Constants
# ──────────────────────────────────────────────────────────────────────────────

MODEL_ID = "gpt-4o"
MODEL_MINI_ID = "gpt-4o-mini"
MODEL_REASONING_ID = "o3-mini"
DALLE_MODEL_ID = "dall-e-3"
TTS_MODEL_ID = "tts-1-hd"
WHISPER_MODEL_ID = "whisper-1"
MAX_REFINEMENT_LOOPS = int(os.environ.get("FORGE_MAX_LOOPS", "2"))
DEFAULT_BUDGET = 15.0          # $/100g default budget ceiling
SOLVER_TIME_LIMIT = 30         # seconds
TEMPERATURE = 0.3              # low temp for structured output reliability
SLIDES_SCRIPT = Path(__file__).parent / "generate_slides.js"

# Regulatory hard limits (simplified EU/FDA guardrails)
REGULATORY_LIMITS: dict[str, float] = {
    "retinol":            1.0,
    "salicylic acid":     2.0,
    "benzoyl peroxide":  10.0,
    "hydroquinone":       2.0,
    "alpha hydroxy acid": 10.0,
    "glycolic acid":     10.0,
    "lactic acid":       10.0,
    "vitamin c":         20.0,
    "ascorbic acid":     20.0,
    "niacinamide":       10.0,
    "zinc oxide":        25.0,
    "titanium dioxide":  25.0,
    "fragrance":          1.0,
    "essential oil":      1.0,
}

# Known synergy/conflict pairs (ingredient_a, ingredient_b, type, note)
INTERACTION_RULES: list[dict] = [
    {"a": "retinol",        "b": "vitamin c",       "type": "conflict",  "note": "pH incompatibility -- use in separate routines"},
    {"a": "retinol",        "b": "ascorbic acid",   "type": "conflict",  "note": "pH incompatibility -- use in separate routines"},
    {"a": "niacinamide",    "b": "vitamin c",       "type": "conflict",  "note": "Can cause flushing at high combined concentrations"},
    {"a": "hyaluronic acid","b": "glycerin",         "type": "synergy",   "note": "Both humectants -- layering boosts hydration"},
    {"a": "vitamin c",      "b": "vitamin e",        "type": "synergy",   "note": "Antioxidant network effect -- C regenerates E"},
    {"a": "salicylic acid", "b": "glycolic acid",    "type": "conflict",  "note": "Over-exfoliation risk when combined"},
    {"a": "ceramides",      "b": "cholesterol",      "type": "synergy",   "note": "Mimics skin lipid bilayer for barrier repair"},
    {"a": "peptides",       "b": "aha",              "type": "conflict",  "note": "Low pH degrades peptide bonds"},
]

console = Console()


# ──────────────────────────────────────────────────────────────────────────────
# Data Models
# ──────────────────────────────────────────────────────────────────────────────

class StepStatus(Enum):
    PENDING  = "pending"
    RUNNING  = "running"
    SUCCESS  = "success"
    FAILED   = "failed"
    SKIPPED  = "skipped"


@dataclass
class Ingredient:
    name: str
    min_pct: float = 0.0
    max_pct: float = 100.0
    cost_per_pct: float = 0.1        # cost per 1% in a 100g batch
    efficacy_score: float = 5.0       # 1-10 performance rating
    category: str = "active"          # active | base | preservative | fragrance
    notes: str = ""

    def __post_init__(self):
        self.name = self.name.strip().lower()
        # Apply regulatory caps automatically
        for reg_name, reg_max in REGULATORY_LIMITS.items():
            if reg_name in self.name:
                self.max_pct = min(self.max_pct, reg_max)
                self.notes += f" [Reg cap: {reg_max}%]"
                break


@dataclass
class Formula:
    ingredients: dict[str, float] = field(default_factory=dict)   # name -> optimized %
    total_cost: float = 0.0
    performance_score: float = 0.0
    solver_status: str = ""
    warnings: list[str] = field(default_factory=list)
    interactions: list[dict] = field(default_factory=list)


@dataclass
class PipelineResult:
    user_input: str
    parsed_ingredients: list[Ingredient] = field(default_factory=list)
    formula_v1: Optional[Formula] = None
    explanation_v1: str = ""
    evaluation: str = ""
    refinements: list[dict] = field(default_factory=list)
    formula_v2: Optional[Formula] = None
    explanation_v2: str = ""
    comparison: str = ""
    loop_count: int = 0
    steps: dict[str, StepStatus] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    pptx_path: str = ""
    canvas_image_path: str = ""
    brand_name: str = ""
    brand_vision: str = ""
    brand_palette: dict = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# OpenAI Client Wrapper
# ──────────────────────────────────────────────────────────────────────────────

class OpenAIClient:
    """Thin wrapper around the OpenAI Python SDK for GPT-4o / GPT-4o-mini / o3-mini."""

    def __init__(self, model_id: str = MODEL_ID):
        self.model_id = model_id
        self._client = OpenAI()  # reads OPENAI_API_KEY from env

    @property
    def client(self):
        """Expose the raw OpenAI client for direct API calls (images, audio, etc.)."""
        return self._client

    def invoke(
        self,
        prompt: str,
        system: str = "",
        temperature: float = TEMPERATURE,
        max_tokens: int = 4096,
        image_bytes: Optional[bytes] = None,
        image_media_type: str = "image/jpeg",
        json_mode: bool = False,
    ) -> str:
        """Send a message to OpenAI and return the text response."""
        messages: list[dict] = []

        if system:
            messages.append({"role": "system", "content": system})

        # Build user content (text or multimodal)
        if image_bytes:
            b64_img = base64.b64encode(image_bytes).decode("utf-8")
            data_url = f"data:{image_media_type};base64,{b64_img}"
            user_content: list[dict] = [
                {"type": "image_url", "image_url": {"url": data_url, "detail": "high"}},
                {"type": "text", "text": prompt},
            ]
            messages.append({"role": "user", "content": user_content})
        else:
            messages.append({"role": "user", "content": prompt})

        kwargs: dict[str, Any] = {
            "model": self.model_id,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "top_p": 0.9,
        }
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            resp = self._client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except RateLimitError:
            console.print("[yellow]Rate limited -- retrying in 5s...[/yellow]")
            time.sleep(5)
            return self.invoke(prompt, system, temperature, max_tokens, image_bytes, image_media_type, json_mode)
        except APIError as exc:
            raise RuntimeError(f"OpenAI API error: {exc}") from exc

    def generate_speech(self, text: str, voice: str = "nova") -> bytes:
        """Generate speech audio from text using OpenAI TTS."""
        resp = self._client.audio.speech.create(
            model=TTS_MODEL_ID,
            voice=voice,
            input=text,
            response_format="mp3",
        )
        return resp.content

    def transcribe_audio(self, audio_bytes: bytes, filename: str = "audio.webm") -> str:
        """Transcribe audio using OpenAI Whisper."""
        from io import BytesIO
        audio_file = BytesIO(audio_bytes)
        audio_file.name = filename
        transcript = self._client.audio.transcriptions.create(
            model=WHISPER_MODEL_ID,
            file=audio_file,
        )
        return transcript.text


# ──────────────────────────────────────────────────────────────────────────────
# LP Solver
# ──────────────────────────────────────────────────────────────────────────────

class FormulaSolver:
    """PuLP-based linear programming optimizer for cosmetic formulations."""

    @staticmethod
    def _sanitize_constraints(
        ingredients: list[Ingredient],
        budget: float,
    ) -> list[str]:
        """
        Pre-solve feasibility check. Automatically fixes contradictory
        constraints so the LP solver never receives an infeasible problem.

        Returns a list of warnings about adjustments that were made.
        """
        fixes: list[str] = []

        # ── Fix 1: Ensure every ingredient has min <= max ─────────────
        for ing in ingredients:
            if ing.min_pct < 0:
                ing.min_pct = 0.0
            if ing.max_pct < ing.min_pct:
                fixes.append(
                    f"[auto-fix] {ing.name}: max_pct ({ing.max_pct}) < min_pct ({ing.min_pct}), "
                    f"set max_pct = {ing.min_pct}"
                )
                ing.max_pct = ing.min_pct

        # ── Fix 2: Sum of min_pct must be <= 100 ─────────────────────
        total_min = sum(ing.min_pct for ing in ingredients)
        if total_min > 100:
            scale = 100.0 / total_min * 0.95  # leave 5% headroom
            fixes.append(
                f"[auto-fix] Sum of minimums ({total_min:.1f}%) > 100%. "
                f"Scaling all min_pct down by {scale:.2f}x"
            )
            for ing in ingredients:
                ing.min_pct = round(ing.min_pct * scale, 2)

        # ── Fix 3: Sum of max_pct must be >= 100 ─────────────────────
        total_max = sum(ing.max_pct for ing in ingredients)
        if total_max < 100:
            # Find the base/carrier ingredients and raise their caps
            bases = [ing for ing in ingredients if ing.category == "base"]
            if not bases:
                # If no base category, pick the cheapest ingredient
                bases = sorted(ingredients, key=lambda x: x.cost_per_pct)[:2]
            deficit = 100 - total_max + 5  # 5% headroom
            per_base = deficit / len(bases)
            for ing in bases:
                ing.max_pct = round(ing.max_pct + per_base, 2)
            fixes.append(
                f"[auto-fix] Sum of maximums ({total_max:.1f}%) < 100%. "
                f"Raised max_pct on base ingredients by {per_base:.1f}% each"
            )

        # ── Fix 4: Cost at minimum allocation must be <= budget ───────
        min_cost = sum(ing.cost_per_pct * ing.min_pct for ing in ingredients)
        if min_cost > budget:
            # Relax minimums on the most expensive ingredients first
            sorted_by_cost = sorted(ingredients, key=lambda x: x.cost_per_pct, reverse=True)
            overshoot = min_cost - budget
            for ing in sorted_by_cost:
                if overshoot <= 0:
                    break
                cost_contrib = ing.cost_per_pct * ing.min_pct
                if cost_contrib > 0 and ing.category != "preservative":
                    old_min = ing.min_pct
                    # Try halving the minimum first
                    ing.min_pct = round(ing.min_pct * 0.3, 2)
                    saved = ing.cost_per_pct * (old_min - ing.min_pct)
                    overshoot -= saved
                    fixes.append(
                        f"[auto-fix] {ing.name}: min_pct {old_min} -> {ing.min_pct} "
                        f"(cost relief: ${saved:.2f})"
                    )
            # If still over budget after relaxing, bump the budget
            min_cost_after = sum(ing.cost_per_pct * ing.min_pct for ing in ingredients)
            if min_cost_after > budget:
                fixes.append(
                    f"[auto-fix] Even after relaxing minimums, min cost (${min_cost_after:.2f}) "
                    f"> budget (${budget:.2f}). Budget will be raised automatically."
                )

        # ── Fix 5: Ensure min_pct <= max_pct after all adjustments ────
        for ing in ingredients:
            if ing.min_pct > ing.max_pct:
                ing.max_pct = ing.min_pct

        return fixes

    @staticmethod
    def optimize(
        ingredients: list[Ingredient],
        budget: float = DEFAULT_BUDGET,
        extra_constraints: Optional[list[dict]] = None,
    ) -> Formula:
        """
        Maximize weighted performance score subject to:
          - sum of all percentages = 100
          - total cost <= budget
          - per-ingredient min/max bounds
          - any extra constraints from the agent refinement loop

        Includes automatic feasibility repair if constraints are contradictory.
        """
        if not ingredients:
            f = Formula()
            f.solver_status = "No ingredients provided"
            f.warnings.append("Empty ingredient list")
            return f

        # ── Pre-solve feasibility repair ──────────────────────────────
        constraint_fixes = FormulaSolver._sanitize_constraints(ingredients, budget)
        for fix_msg in constraint_fixes:
            console.print(f"  [yellow]{fix_msg}[/yellow]")

        # Compute effective budget (may need to be raised)
        min_cost = sum(ing.cost_per_pct * ing.min_pct for ing in ingredients)
        effective_budget = max(budget, min_cost * 1.2)  # 20% headroom over floor
        if effective_budget > budget:
            console.print(
                f"  [yellow][auto-fix] Budget raised: ${budget:.2f} -> ${effective_budget:.2f} "
                f"(minimum feasible cost is ${min_cost:.2f})[/yellow]"
            )

        prob = pulp.LpProblem("FormulaForge", pulp.LpMaximize)

        # Decision variables
        variables: dict[str, pulp.LpVariable] = {}
        for ing in ingredients:
            variables[ing.name] = pulp.LpVariable(
                f"pct_{ing.name.replace(' ', '_')}",
                lowBound=ing.min_pct,
                upBound=ing.max_pct,
            )

        # Objective: maximize sum(efficacy * pct)
        prob += pulp.lpSum(
            ing.efficacy_score * variables[ing.name] for ing in ingredients
        ), "TotalPerformance"

        # Constraint: percentages sum to 100
        prob += (
            pulp.lpSum(variables[ing.name] for ing in ingredients) == 100,
            "SumTo100",
        )

        # Constraint: total cost within budget
        prob += (
            pulp.lpSum(ing.cost_per_pct * variables[ing.name] for ing in ingredients)
            <= effective_budget,
            "BudgetCap",
        )

        # Extra agent-suggested constraints (with safety checks)
        if extra_constraints:
            for i, ec in enumerate(extra_constraints):
                ing_name = ec.get("ingredient", "").strip().lower()
                if ing_name not in variables:
                    continue
                if "min_pct" in ec and ec["min_pct"] is not None:
                    val = float(ec["min_pct"])
                    # Don't let agent constraints exceed the variable bounds
                    val = min(val, variables[ing_name].upBound or 100)
                    prob += (
                        variables[ing_name] >= val,
                        f"AgentMin_{i}_{ing_name}",
                    )
                if "max_pct" in ec and ec["max_pct"] is not None:
                    val = float(ec["max_pct"])
                    val = max(val, variables[ing_name].lowBound or 0)
                    prob += (
                        variables[ing_name] <= val,
                        f"AgentMax_{i}_{ing_name}",
                    )

        # Solve
        solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=SOLVER_TIME_LIMIT)
        prob.solve(solver)

        formula = Formula()
        formula.solver_status = pulp.LpStatus[prob.status]

        if prob.status != pulp.constants.LpStatusOptimal:
            formula.warnings.append(f"Solver status: {formula.solver_status}")
            if prob.status == pulp.constants.LpStatusInfeasible:
                console.print(
                    "  [yellow][auto-retry] Infeasible -- resetting all min_pct to 0 "
                    "and retrying with relaxed constraints...[/yellow]"
                )
                import copy
                relaxed = copy.deepcopy(ingredients)
                for ing in relaxed:
                    ing.min_pct = 0.0
                    if ing.max_pct < 10.0 and ing.category not in ("preservative", "fragrance"):
                        ing.max_pct = max(ing.max_pct, 60.0)
                bases = [i for i in relaxed if i.category == "base"]
                if bases:
                    bases[0].max_pct = max(bases[0].max_pct, 80.0)
                else:
                    cheapest = sorted(relaxed, key=lambda x: x.cost_per_pct)[0]
                    cheapest.category = "base"
                    cheapest.max_pct = max(cheapest.max_pct, 80.0)

                relaxed_budget = max(budget * 3, 50.0)
                retry_prob = pulp.LpProblem("FormulaForge_retry", pulp.LpMaximize)
                retry_vars: dict[str, pulp.LpVariable] = {}
                for ing in relaxed:
                    retry_vars[ing.name] = pulp.LpVariable(
                        f"r_pct_{ing.name.replace(' ', '_')}",
                        lowBound=0.0,
                        upBound=ing.max_pct,
                    )
                retry_prob += pulp.lpSum(
                    ing.efficacy_score * retry_vars[ing.name] for ing in relaxed
                ), "RetryPerformance"
                retry_prob += (
                    pulp.lpSum(retry_vars[ing.name] for ing in relaxed) == 100,
                    "RetrySumTo100",
                )
                retry_prob += (
                    pulp.lpSum(ing.cost_per_pct * retry_vars[ing.name] for ing in relaxed)
                    <= relaxed_budget,
                    "RetryBudget",
                )
                retry_solver = pulp.PULP_CBC_CMD(msg=0, timeLimit=SOLVER_TIME_LIMIT)
                retry_prob.solve(retry_solver)

                if retry_prob.status == pulp.constants.LpStatusOptimal:
                    console.print("  [green][auto-retry] Retry succeeded![/green]")
                    formula = Formula()
                    formula.solver_status = "Optimal (relaxed)"
                    formula.warnings.append(
                        "Formula solved with relaxed constraints -- min percentages were reset to 0."
                    )
                    for ing in relaxed:
                        val = retry_vars[ing.name].varValue or 0.0
                        formula.ingredients[ing.name] = round(val, 4)
                    formula.total_cost = round(
                        sum(ing.cost_per_pct * (retry_vars[ing.name].varValue or 0.0)
                            for ing in relaxed), 2
                    )
                    formula.performance_score = round(pulp.value(retry_prob.objective) or 0.0, 2)
                    formula.interactions = FormulaSolver._check_interactions(formula.ingredients)
                    for interaction in formula.interactions:
                        if interaction["type"] == "conflict":
                            formula.warnings.append(
                                f"Interaction warning: {interaction['a']} + {interaction['b']} "
                                f"-- {interaction['note']}"
                            )
                    return formula
                else:
                    formula.warnings.append(
                        "Infeasible even after full constraint relaxation. "
                        "Try a more specific product description."
                    )
                    return formula

        for ing in ingredients:
            val = variables[ing.name].varValue or 0.0
            formula.ingredients[ing.name] = round(val, 4)

        formula.total_cost = round(
            sum(
                ing.cost_per_pct * (variables[ing.name].varValue or 0.0)
                for ing in ingredients
            ),
            2,
        )
        formula.performance_score = round(pulp.value(prob.objective) or 0.0, 2)

        # Check interactions
        formula.interactions = FormulaSolver._check_interactions(formula.ingredients)
        for interaction in formula.interactions:
            if interaction["type"] == "conflict":
                formula.warnings.append(
                    f"Interaction warning: {interaction['a']} + {interaction['b']} -- {interaction['note']}"
                )

        return formula

    @staticmethod
    def _check_interactions(ingredients: dict[str, float]) -> list[dict]:
        """Flag known ingredient synergies and conflicts."""
        found = []
        names = set(ingredients.keys())
        for rule in INTERACTION_RULES:
            a_match = any(rule["a"] in n for n in names if ingredients.get(n, 0) > 0)
            b_match = any(rule["b"] in n for n in names if ingredients.get(n, 0) > 0)
            if a_match and b_match:
                found.append(rule)
        return found


# ──────────────────────────────────────────────────────────────────────────────
# FormulaForge Agent (Main Orchestrator)
# ──────────────────────────────────────────────────────────────────────────────

class FormulaForge:
    """
    The core agentic orchestrator. Runs a multi-step pipeline with
    autonomous refinement loops.
    """

    # NOTE: we intentionally keep the JSON-only rule here for data steps but
    # some downstream helpers (step_explain) will override it when human prose
    # is needed.
    SYSTEM_PROMPT = (
        "You are FormulaForge, an expert cosmetic chemist AI agent. "
        "You combine deep knowledge of cosmetic science, dermatology, and "
        "formulation chemistry to design safe, effective, and cost-efficient "
        "skincare and cosmetic products. You always consider ingredient "
        "interactions, pH compatibility, regulatory limits, and skin biology. "
        "IMPORTANT: You MUST always include a primary carrier (e.g., Purified Water) "
        "with a max_pct of 100.0 to ensure the solver can always reach 100% total volume. "
        "When you output JSON, output ONLY valid JSON with no markdown fences or extra text. "
        "ALL outputs must be strictly in English."
    )

    def __init__(self):
        self.openai_client = OpenAIClient(model_id=MODEL_ID)
        self.openai_mini = OpenAIClient(model_id=MODEL_MINI_ID)
        self.solver = FormulaSolver()

    # chat_with_formula is defined later in the class (see below)

    def scan_ingredient_label(
        self,
        image_bytes: bytes,
        image_media_type: str = "image/jpeg",
    ) -> str:
        """Use Nova Vision to read a product label and generate a formulaton goal."""
        prompt = (
            "You are an expert cosmetic chemist. Look at the provided image "
            "of a cosmetic product or its ingredient list. "
            "Identify the key active ingredients and the likely purpose of the product. "
            "Write a concise 1-2 sentence formulation goal that a user could paste "
            "into a formula generator to recreate a similar product. "
            "Example: 'A hydrating anti-aging night cream featuring Niacinamide, "
            "Hyaluronic Acid, and Peptides.'\n"
            "Return ONLY the goal text, no quotes, no extra chat."
        )
        return self.openai_client.invoke(
            prompt,
            system=self.SYSTEM_PROMPT,
            image_bytes=image_bytes,
            image_media_type=image_media_type,
            max_tokens=200
        ).strip()

    # ── Step 1: Parse ─────────────────────────────────────────────────────

    def step_parse(
        self,
        user_input: str,
        image_bytes: Optional[bytes] = None,
        image_media_type: str = "image/jpeg",
    ) -> list[Ingredient]:
        """Use Nova to parse free-text (or image) into structured ingredients."""

        if image_bytes:
            prompt = (
                "You are analyzing an image of a cosmetic product label. "
                "Extract every ingredient you can identify from the label.\n\n"
                "Additionally, the user says: " + user_input + "\n\n"
                "Return a JSON array of objects, each with these keys:\n"
                '  "name": string (ingredient name, lowercase),\n'
                '  "min_pct": number (minimum viable percentage -- keep LOW, e.g. 0.1-3.0 for actives),\n'
                '  "max_pct": number (maximum safe percentage),\n'
                '  "cost_per_pct": number (estimated cost per 1% in $/100g batch),\n'
                '  "efficacy_score": number 1-10 (effectiveness rating),\n'
                '  "category": "active" | "base" | "preservative" | "fragrance"\n\n'
                "CRITICAL RULES for a valid formula:\n"
                "- The sum of ALL min_pct values MUST be well under 100 (ideally 20-40 total)\n"
                "- The sum of ALL max_pct values MUST be well over 100 (ideally 150-300 total)\n"
                "- Active ingredients: min_pct 0.1-3%, max_pct 5-25%\n"
                "- Base/carrier (water, oils, gel): min_pct 5-15%, max_pct 40-80%\n"
                "- Preservatives: min_pct 0.1-0.5%, max_pct 1-2%\n"
                "- You MUST include at least one carrier with max_pct = 100.0\n"
                "Output ONLY the JSON array, no other text."
            )
        else:
            prompt = (
                "The user wants to formulate a cosmetic product. Their request:\n\n"
                f'"{user_input}"\n\n'
                "Based on this, determine the key ingredients needed. "
                "For each ingredient, estimate realistic cosmetic formulation parameters.\n\n"
                "Return a JSON array of objects, each with these keys:\n"
                '  "name": string (ingredient name, lowercase),\n'
                '  "min_pct": number (minimum viable percentage -- keep this LOW, e.g. 0.1-3.0 for actives),\n'
                '  "max_pct": number (maximum safe percentage),\n'
                '  "cost_per_pct": number (estimated cost per 1% in $/100g batch),\n'
                '  "efficacy_score": number 1-10 (effectiveness rating),\n'
                '  "category": "active" | "base" | "preservative" | "fragrance"\n\n'
                "CRITICAL RULES for a valid formula:\n"
                "- The sum of ALL min_pct values MUST be well under 100 (ideally 20-40 total)\n"
                "- The sum of ALL max_pct values MUST be well over 100 (ideally 150-300 total)\n"
                "- Active ingredients: min_pct 0.1-3%, max_pct 5-25%\n"
                "- Base/carrier (water, oils, gel): min_pct 5-15%, max_pct 40-80%\n"
                "- Preservatives: min_pct 0.1-0.5%, max_pct 1-2%\n"
                "- You MUST include at least one carrier with max_pct = 100.0\n"
                "Include a balanced mix: actives for the user's goal, a base/carrier, "
                "at least one preservative, and optionally fragrance. "
                "Aim for 6-12 ingredients total.\n"
                "Output ONLY the JSON array, no other text."
            )

        raw = self.openai_client.invoke(
            prompt,
            system=self.SYSTEM_PROMPT,
            image_bytes=image_bytes,
            image_media_type=image_media_type,
            json_mode=True,
        )

        parsed = self._extract_json_array(raw)
        ingredients = []
        for item in parsed:
            try:
                ingredients.append(Ingredient(
                    name=str(item.get("name", "unknown")),
                    min_pct=float(item.get("min_pct", 0)),
                    max_pct=float(item.get("max_pct", 50)),
                    cost_per_pct=float(item.get("cost_per_pct", 0.1)),
                    efficacy_score=float(item.get("efficacy_score", 5)),
                    category=str(item.get("category", "active")),
                ))
            except (TypeError, ValueError) as exc:
                console.print(f"[yellow]Skipping malformed ingredient: {item} ({exc})[/yellow]")

        if not ingredients:
            raise ValueError("Nova returned no parseable ingredients. Try rephrasing your request.")

        return ingredients

    # ── Step 2: Optimize ──────────────────────────────────────────────────

    def step_optimize(
        self,
        ingredients: list[Ingredient],
        budget: float = DEFAULT_BUDGET,
        extra_constraints: Optional[list[dict]] = None,
    ) -> Formula:
        """Run the PuLP LP solver."""
        return self.solver.optimize(ingredients, budget, extra_constraints)

    # ── Step 3: Explain ───────────────────────────────────────────────────

    def step_explain(self, formula: Formula, user_goal: str, brand_name: str = "", language: str = "English") -> str:
        """Have Nova write a scientific explanation of the formula."""
        product_name = brand_name or getattr(self, '_current_brand_name', '') or user_goal
        formula_text = json.dumps(formula.ingredients, indent=2)
        prompt = (
            f'Product: "{product_name}"\n'
            f'Original goal: "{user_goal}"\n\n'
            f"Optimized formula:\n{formula_text}\n"
            f"Performance score: {formula.performance_score}\n"
            f"Cost: ${formula.total_cost}/100g\n\n"
            f"Write a 3-paragraph scientific report in professional human prose. "
            f"CRITICAL: The report MUST be written entirely in {language}. "
            f"CRITICAL: Always refer to the product as '{product_name}' — NEVER use the original goal text as the product name. "
            "Do NOT output JSON or code fences. Use clear, elegant language "
            "suitable for a luxury brand internal report."
        )
        result = self.openai_client.invoke(
            prompt,
            system=f"You are an expert cosmetic chemist writing a luxury brand report in {language}.",
            max_tokens=2048,
        )
        # Defense-in-depth: strip any code fences or JSON that slipped through
        result = re.sub(r'```[\s\S]*?```', '', result)
        result = re.sub(r'^\s*[\[{][\s\S]*?[}\]]\s*$', '', result, flags=re.MULTILINE)
        return result.strip()

    # ── Step 4: Evaluate & Suggest Refinements ────────────────────────────

    def step_evaluate(self, formula: Formula, user_goal: str, explanation: str) -> tuple[str, list[dict]]:
        """
        Nova acts as a critical reviewer: analyzes the formula for weaknesses
        and returns concrete constraint adjustments for the solver.
        """
        formula_text = json.dumps(formula.ingredients, indent=2)
        warnings_text = "\n".join(formula.warnings) if formula.warnings else "None"
        interactions_text = json.dumps(formula.interactions, indent=2) if formula.interactions else "None"

        prompt = (
            f"You are a senior cosmetic chemist reviewing this formula.\n\n"
            f"User goal: \"{user_goal}\"\n"
            f"Formula: {formula_text}\n"
            f"Performance score: {formula.performance_score}\n"
            f"Cost: ${formula.total_cost}/100g\n"
            f"Warnings: {warnings_text}\n"
            f"Interactions detected: {interactions_text}\n"
            f"Explanation provided: {explanation[:500]}...\n\n"
            "Critically evaluate this formula. Consider:\n"
            "- Are any concentrations too low to be effective or too high to be safe?\n"
            "- Are there ingredient conflicts that should be resolved?\n"
            "- Could the cost-performance ratio be improved?\n"
            "- Is the formula missing a common supporting ingredient?\n"
            "- Is the base/emollient ratio appropriate for the product type?\n\n"
            "Respond with TWO sections:\n\n"
            "SECTION 1 - EVALUATION: A 2-3 paragraph critical analysis.\n\n"
            "SECTION 2 - REFINEMENTS: A JSON array of constraint adjustments. Each object:\n"
            '  {"ingredient": "name", "min_pct": number OR null, "max_pct": number OR null, "reason": "why"}\n'
            "You may also suggest adding a NEW ingredient by including all fields from the original spec.\n\n"
            "Separate the sections with the marker: ===REFINEMENTS===\n"
            "After the marker, output ONLY the JSON array."
        )

        raw = self.openai_client.invoke(prompt, system=self.SYSTEM_PROMPT, max_tokens=3000)

        # Split evaluation text from refinements JSON
        evaluation = raw
        refinements = []

        if "===REFINEMENTS===" in raw:
            parts = raw.split("===REFINEMENTS===", 1)
            evaluation = parts[0].strip()
            try:
                refinements = self._extract_json_array(parts[1])
            except (json.JSONDecodeError, ValueError):
                console.print("[yellow]Could not parse refinement JSON, continuing without refinements.[/yellow]")

        return evaluation, refinements

    # ── Step 5: Re-optimize ───────────────────────────────────────────────

    def step_reoptimize(
        self,
        ingredients: list[Ingredient],
        refinements: list[dict],
        budget: float = DEFAULT_BUDGET,
    ) -> tuple[list[Ingredient], Formula]:
        """
        Apply refinements to ingredients and re-run the solver.
        Handles both constraint adjustments and new ingredient additions.
        """
        ing_map = {ing.name: ing for ing in ingredients}

        extra_constraints = []
        for ref in refinements:
            name = ref.get("ingredient", "").strip().lower()
            if not name:
                continue

            # New ingredient suggestion
            if name not in ing_map and ref.get("efficacy_score"):
                new_ing = Ingredient(
                    name=name,
                    min_pct=float(ref.get("min_pct", 0) or 0),
                    max_pct=float(ref.get("max_pct", 20) or 20),
                    cost_per_pct=float(ref.get("cost_per_pct", 0.1) or 0.1),
                    efficacy_score=float(ref.get("efficacy_score", 5) or 5),
                    category=str(ref.get("category", "active")),
                )
                ingredients.append(new_ing)
                ing_map[name] = new_ing
                console.print(f"  [green]+[/green] Added new ingredient: [bold]{name}[/bold]")
                continue

            # Constraint adjustment on existing ingredient
            constraint: dict[str, Any] = {"ingredient": name}
            if ref.get("min_pct") is not None:
                constraint["min_pct"] = float(ref["min_pct"])
                # Also update the Ingredient object bounds
                if name in ing_map:
                    ing_map[name].min_pct = max(ing_map[name].min_pct, float(ref["min_pct"]))
            if ref.get("max_pct") is not None:
                constraint["max_pct"] = float(ref["max_pct"])
                if name in ing_map:
                    ing_map[name].max_pct = min(ing_map[name].max_pct, float(ref["max_pct"]))
            extra_constraints.append(constraint)
            console.print(f"  [cyan]~[/cyan] Adjusted: [bold]{name}[/bold] -> {constraint}")

        formula_v2 = self.solver.optimize(ingredients, budget, extra_constraints)
        return ingredients, formula_v2

    # ── Step 6: Compare ───────────────────────────────────────────────────

    def step_compare(self, formula_v1: Formula, formula_v2: Formula, user_goal: str, language: str = "English") -> str:
        """Nova generates a comparison narrative between v1 and v2."""
        v1_json = json.dumps(formula_v1.ingredients, indent=2)
        v2_json = json.dumps(formula_v2.ingredients, indent=2)

        prompt = (
            f"Compare these two formula versions for the goal: \"{user_goal}\"\n\n"
            f"Version 1 (score={formula_v1.performance_score}, cost=${formula_v1.total_cost}):\n{v1_json}\n\n"
            f"Version 2 (score={formula_v2.performance_score}, cost=${formula_v2.total_cost}):\n{v2_json}\n\n"
            "Write a brief comparative analysis (2-3 paragraphs) highlighting:\n"
            "- What changed and why it improves the formula\n"
            "- Trade-offs made (cost vs performance, safety margins)\n"
            "- Which version you recommend and for what skin profile\n"
            "Be specific about percentage changes and their practical impact.\n"
            f"CRITICAL: The comparison MUST be written entirely in {language}.\n"
            "CRITICAL: Do NOT output JSON or code fences. Write professional prose only."
        )

        # Override the global JSON rule for narrative output
        return self.openai_client.invoke(
            prompt,
            system=f"You are a cosmetic chemistry senior reviewer translating into {language}.",
            max_tokens=1500,
        )

    # ── Step 7: Brand Identity Generation ──────────────────────────────

    def step_brand(self, user_goal: str, formula: Formula) -> dict:
        """
        Generate a bespoke luxury French product name, vision statement,
        and a reactive color palette based on the product concept.
        Returns {"name": "...", "vision": "...", "palette": {...}}.
        """
        top_ings = sorted(formula.ingredients.items(), key=lambda x: -x[1])[:3]
        top_names = ", ".join(n for n, _ in top_ings)
        prompt = (
            f'The user requested: "{user_goal}"\n'
            f"Top ingredients: {top_names}\n"
            f"Performance score: {formula.performance_score}\n\n"
            "You are a luxury brand creative director. Generate:\n"
            '1. "name": A unique, high-end French product name (e.g., "Élixir de Jeunesse", '
            '"Sérum de Lumière", "Voile de Soie") that captures the SPECIFIC benefits. '
            "Do NOT reuse generic names.\n"
            '2. "vision": A one-sentence product vision statement (English).\n'
            '3. "palette": A color palette (6-digit hex codes WITHOUT #) with keys: '
            '"primary" (deep main color), "secondary" (accent tone), '
            '"gold" (metallic accent), "accent" (light neutral). '
            'CRITICAL: The palette MUST match the ACTUAL COLORS the user described for the product. '
            'If the user mentions specific colors (black, white, blue, pink, etc.), '
            'the primary color MUST reflect those exact colors. '
            'For example: black product = primary "1A1A1A", white product = primary "F5F0EB", '
            'blue product = primary "1B3A5C", pink product = primary "C4738E". '
            'The gold/metallic accent should complement the primary. '
            'Do NOT pick random category colors — match the product description.\n\n'
            'Output ONLY valid JSON:\n'
            '{"name": "...", "vision": "...", "palette": {"primary": "...", "secondary": "...", "gold": "...", "accent": "..."}}\n'
            "No markdown fences. No extra text."
        )
        raw = self.openai_client.invoke(prompt, system=self.SYSTEM_PROMPT, max_tokens=500, json_mode=True)
        try:
            match = re.search(r'\{[\s\S]*\}', raw)
            if match:
                brand = json.loads(match.group())
                palette = brand.get("palette", {})
                # Validate hex codes (6 chars, no #)
                for key in ["primary", "secondary", "gold", "accent"]:
                    val = str(palette.get(key, "")).replace("#", "")
                    if len(val) == 6 and all(c in '0123456789abcdefABCDEF' for c in val):
                        palette[key] = val
                    else:
                        palette.pop(key, None)
                return {
                    "name": brand.get("name", user_goal),
                    "vision": brand.get("vision", ""),
                    "palette": palette,
                }
        except (json.JSONDecodeError, AttributeError):
            pass
        return {"name": user_goal, "vision": "", "palette": {}}

    # ── GPT-4o-mini Chat Integration ───────────────────────────────────────

    def chat_with_formula(self, question: str, formula_json: str, history: list[dict]) -> str:
        """Have GPT-4o-mini answer questions acting as a cosmetic chemist."""
        prompt = (
            f"Formula context (JSON):\n{formula_json}\n\n"
            f"User Question: {question}\n"
        )
        
        if history:
            history_text = "\n".join([f"{msg.get('role', 'user')}: {msg.get('content', '')}" for msg in history[-4:]])
            prompt = f"Recent Conversation:\n{history_text}\n\n" + prompt

        return self.openai_mini.invoke(
            prompt,
            system="You are an expert cosmetic chemist advising a luxury brand. Answer concisely and professionally. Do not invent ingredients not in the formula.",
            max_tokens=300
        )

    # ── GPT-4o Campaign Studio Integration ─────────────────────────────────

    def generate_campaign(self, brand_name: str, formula_name: str, vision: str, formula_json: str) -> dict:
        """Use GPT-4o to generate marketing copy."""
        prompt = (
            f"Brand: {brand_name}\nProduct Formula: {formula_name}\nBrand Vision: {vision}\n\n"
            f"Ingredient Formula Breakdown:\n{formula_json}\n\n"
            "Return a JSON object with EXACTLY three string keys: 'instagram_caption', 'tiktok_script', 'slogan'.\n"
            "The 'instagram_caption' key: a catchy, highly professional 3-sentence IG caption highlighting key ingredients. Use a minimalist Vogue aesthetic. NO emojis. Use elegant unicode symbols like ✦ or ✧ ONLY if absolutely necessary. End with 3 clean hashtags.\n"
            "The 'tiktok_script' key: a high-end 15-second TikTok video hook and script. Clean, editorial tone. NO emojis.\n"
            "The 'slogan': a punchy 4-to-6 word luxury advertising slogan.\n"
            "CRITICAL: Output valid JSON only. NO markdown blocks. Just the raw {...} JSON string."
        )
        response_text = self.openai_client.invoke(
            prompt,
            system="You are a Vogue luxury beauty marketing expert & copywriter.",
            max_tokens=1000,
            json_mode=True,
        )
        
        try:
            cleaned = response_text.replace("```json", "").replace("```", "").strip()
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {
                "instagram_caption": "Error parsing Instagram copy. Please try again.",
                "tiktok_script": "Error parsing TikTok copy. Please try again.",
                "slogan": "AI Configuration Error."
            }

    # ── o3-mini Clinical & Patent Analysis ─────────────────────────────────

    def generate_premier_analysis(self, brand_name: str, formula_json: str) -> str:
        """Use o3-mini for a highly detailed clinical and patent review (deep reasoning)."""
        prompt = (
            f"Brand: {brand_name}\nFormula (JSON):\n{formula_json}\n\n"
            "You are a dual-expert: a board-certified derma-toxicologist and a global cosmetics intellectual property lawyer. "
            "Write a detailed, rigorous but beautifully formatted Markdown report predicting the clinical safety (comedogenic ratings, allergens, stability) "
            "and evaluating if this specific combination of ingredients is novel enough to patent. "
            "Structure your response with clear headers, bullet points, and a final 'Verdict' section. "
            "Limit your response to 600 words."
        )
        try:
            reasoning_client = OpenAIClient(model_id=MODEL_REASONING_ID)
            return reasoning_client.invoke(prompt, max_tokens=1500)
        except Exception as e:
            return f"**Error connecting to o3-mini:**\n{str(e)}"

    # ── GPT-4o Manufacturing Outreach ──────────────────────────────────────

    def generate_outreach_email(self, brand_name: str, formula_json: str) -> str:
        """Use GPT-4o to write a wholesale manufacturing quote email."""
        prompt = (
            f"Brand: {brand_name}\nFormula (JSON):\n{formula_json}\n\n"
            "Write a highly professional, B2B email to a top-tier cosmetic manufacturer (e.g., in Italy or South Korea) requesting a quote for a 10,000-unit pilot run of this exact formula. "
            "Include placeholders for [Lab Name] and [My Name]. The tone must be authoritative, showing we know exactly what we want. "
            "Output ONLY the email text, no markdown block wrappers."
        )
        try:
            return self.openai_client.invoke(prompt, max_tokens=800)
        except Exception as e:
            return f"Error connecting to OpenAI: {str(e)}"

    # ── Competitor Teardown (GPT-4o Vision + o3-mini) ──────────────────

    def generate_competitor_teardown(self, image_bytes: bytes, image_format: str, our_formula_json: str) -> str:
        """Use GPT-4o Vision to read competitor label, then o3-mini to teardown the formula."""
        # 1. Vision Extraction (GPT-4o multimodal)
        vision_prompt = "Extract the complete list of ingredients from this product label photo. Output ONLY the list of ingredients, separated by commas."
        try:
            competitor_ingredients = self.openai_client.invoke(
                vision_prompt,
                image_bytes=image_bytes,
                image_media_type=f"image/{image_format}",
                max_tokens=600
            )
        except Exception as e:
            return f"Error extracting competitor ingredients via GPT-4o Vision: {str(e)}"

        # 2. Deep Reasoning Teardown (o3-mini)
        reasoning_client = OpenAIClient(model_id=MODEL_REASONING_ID)
        teardown_prompt = (
            f"You are a cutting-edge cosmetic chemist and formulation critic.\n\n"
            f"Our AI-generated optimized formula (JSON):\n{our_formula_json}\n\n"
            f"Competitor's ingredients (extracted from their label):\n{competitor_ingredients}\n\n"
            f"Write a brutal, highly detailed comparative teardown. Prove step-by-step why our new AI-generated "
            f"clean formula is scientifically superior, cleaner, more effective, and a better value than the competitor's legacy formulation. "
            f"Use beautiful Markdown formatting with headers (e.g., 'The Competitor\\'s Flaws', 'Our AI Supremacy') and specific ingredient comparisons. "
            f"Limit your response to 600 words."
        )
        try:
            return reasoning_client.invoke(
                teardown_prompt,
                system="You are a brilliant, ruthless cosmetics industry analyst.",
                max_tokens=1500
            )
        except Exception as e:
            return f"Error generating teardown via o3-mini: {str(e)}"

    # ── Step 8: Present (PPTX Generation) ─────────────────────────────

    def _generate_canvas_image(self, user_input: str, formula: Formula, output_path: str) -> Optional[str]:
        """
        Attempt to generate a product mockup image using DALL·E 3.
        Returns the image file path on success, None on failure.
        This is a creative enhancement -- failure is non-fatal.
        """
        try:
            brand_name = getattr(self, '_current_brand_name', user_input)

            # Use the user's own description for visual accuracy
            image_desc = (
                f"A single luxury cosmetic product bottle. {user_input}. "
                f"The bottle has an elegant label reading '{brand_name}'. "
                "Style: high-end product photography, clean studio lighting, soft shadows. "
                "Professional commercial product shot, centered composition, plain dark background. "
                "NO humans, NO faces, NO scenery, NO props. Pure product only."
            )
            console.print(f"  [dim]DALL-E 3 prompt: {image_desc[:120]}...[/dim]")

            # Call DALL-E 3
            resp = self.openai_client.client.images.generate(
                model=DALLE_MODEL_ID,
                prompt=image_desc[:4000],
                size="1024x1024",
                quality="hd",
                n=1,
                response_format="b64_json",
            )
            img_b64 = resp.data[0].b64_json

            img_path = output_path.replace(".pptx", "_mockup.png")
            with open(img_path, "wb") as f:
                f.write(base64.b64decode(img_b64))

            console.print(f"  [green]DALL-E 3 image saved: {img_path}[/green]")
            return img_path

        except Exception as exc:
            console.print(f"  [yellow]DALL-E 3 unavailable ({type(exc).__name__}: {exc}), using styled shapes instead[/yellow]")
            return None

    def generate_360_frames(self, user_input: str, formula: Formula, output_dir: str, num_frames: int = 6) -> list[str]:
        """
        Generate a sequence of product images at different described angles
        using DALL-E 3 for 360° interactive viewer. Returns list of frame file paths.
        Note: DALL-E 3 generates 1 image per call, so we use fewer frames (6 by default).
        """
        frames_dir = os.path.join(output_dir, "360_frames")
        os.makedirs(frames_dir, exist_ok=True)

        brand_name = getattr(self, '_current_brand_name', user_input)
        brand_vision = getattr(self, '_current_brand_vision', '')

        # Build a consistent product description for all frames
        product_desc = (
            f"A luxury cosmetic product bottle for '{brand_name}'. "
            f"Product: {brand_vision or user_input}. "
            "The bottle is a sleek, elegant frosted glass container with a metallic "
            "cap and premium embossed label. "
            "Style: High-end product photography, studio lighting, "
            "pure white seamless backdrop, no shadows. "
            "CRITICAL: ONLY the bottle, NO humans, NO faces, NO hands, NO people."
        )

        frame_paths = []
        angle_step = 360 / num_frames

        for i in range(num_frames):
            angle = int(i * angle_step)
            console.print(f"  [dim]Generating frame {i+1}/{num_frames} at {angle}°...[/dim]")

            frame_prompt = (
                f"{product_desc} "
                f"Camera angle: viewing the bottle from {angle} degrees around it "
                f"(0° is front, 90° is right side, 180° is back, 270° is left side). "
                "The bottle should be centered, consistent size, same lighting."
            )

            try:
                resp = self.openai_client.client.images.generate(
                    model=DALLE_MODEL_ID,
                    prompt=frame_prompt[:4000],
                    size="1024x1024",
                    quality="standard",
                    n=1,
                    response_format="b64_json",
                )
                img_b64 = resp.data[0].b64_json

                frame_path = os.path.join(frames_dir, f"frame_{i:02d}.png")
                with open(frame_path, "wb") as f:
                    f.write(base64.b64decode(img_b64))

                frame_paths.append(frame_path)
                console.print(f"  [green]Frame {i+1}/{num_frames} saved[/green]")

            except Exception as exc:
                console.print(f"  [yellow]Frame {i+1} failed: {exc}[/yellow]")
                # Skip failed frames — the viewer will work with whatever we get

        console.print(f"  [bold green]360° frames complete: {len(frame_paths)}/{num_frames} generated[/bold green]")
        return frame_paths

    def generate_turntable_video(self, user_input: str, output_dir: str, canvas_image_path: str = "", **kwargs) -> Optional[str]:
        """
        Generate a turntable product video by creating multiple DALL-E 3 frames
        and stitching them into an MP4 using imageio.
        Returns the local path to the MP4 on success, None on failure.
        """
        brand_name = getattr(self, '_current_brand_name', user_input)

        try:
            import re as _re
            safe_name = _re.sub(r'[^a-zA-Z0-9_\-]', '_', brand_name.replace(' ', '_').lower())
            safe_name = _re.sub(r'_+', '_', safe_name).strip('_') or 'product'

            console.print("  [dim]Generating DALL-E 3 turntable frames...[/dim]")

            # Generate frames at different angles
            num_frames = 6
            angles = [int(i * (360 / num_frames)) for i in range(num_frames)]
            frame_images = []

            for idx, angle in enumerate(angles):
                turntable_prompt = (
                    f"A luxury cosmetic product bottle, {user_input}. "
                    f"The product has a label reading '{brand_name}'. "
                    f"Camera orbiting the product at {angle} degrees "
                    f"(0° is front, 90° is right side, 180° is back, 270° is left side). "
                    "Professional studio product photography, smooth lighting. "
                    "Clean dark background, soft volumetric lighting. "
                    "NO HUMANS. NO FACES. Pure product only."
                )
                console.print(f"  [dim]Frame {idx+1}/{num_frames} at {angle}°...[/dim]")

                try:
                    resp = self.openai_client.client.images.generate(
                        model=DALLE_MODEL_ID,
                        prompt=turntable_prompt[:4000],
                        size="1024x1024",
                        quality="standard",
                        n=1,
                        response_format="b64_json",
                    )
                    img_data = base64.b64decode(resp.data[0].b64_json)

                    from PIL import Image as PILImage
                    import io
                    img = PILImage.open(io.BytesIO(img_data)).convert("RGB")
                    # Resize to 720p for video
                    img = img.resize((1280, 720), PILImage.LANCZOS)
                    frame_images.append(img)
                except Exception as frame_exc:
                    console.print(f"  [yellow]Frame {idx+1} failed: {frame_exc}[/yellow]")

            if len(frame_images) < 2:
                console.print("  [yellow]Not enough frames for video. Need at least 2.[/yellow]")
                return None

            # Stitch frames into MP4 using imageio
            import imageio
            import numpy as np

            local_path = os.path.join(output_dir, f"turntable_{safe_name}_{int(time.time())}.mp4")

            # Build smooth animation: forward + reverse for seamless loop
            all_frames = list(frame_images) + list(reversed(frame_images[1:-1]))

            # Each frame shown for ~0.5 seconds at 12fps = 6 frames per image
            fps = 12
            frames_per_image = 6
            writer = imageio.get_writer(local_path, fps=fps, codec='libx264', quality=8)
            for img in all_frames:
                arr = np.array(img)
                for _ in range(frames_per_image):
                    writer.append_data(arr)
            writer.close()

            console.print(f"  [bold green]Turntable video saved: {local_path}[/bold green]")
            return local_path

        except Exception as exc:
            console.print(f"  [yellow]Turntable video generation failed ({type(exc).__name__}: {exc})[/yellow]")
            return None


    def step_present(self, result: PipelineResult, output_dir: str = "outputs") -> str:
        """
        Generate a beautiful .pptx presentation from the pipeline result.
        Uses pptxgenjs via Node.js subprocess.
        Returns the path to the generated file.
        """
        # Build safe filename from user input
        safe_name = re.sub(r"[^a-zA-Z0-9]+", "_", result.user_input)[:40].strip("_").lower()
        pptx_filename = f"FormulaForge_{safe_name}.pptx"
        pptx_path = os.path.join(output_dir, pptx_filename)

        # Try generating a DALL-E 3 product image
        canvas_path = None
        try:
            final_formula = result.formula_v2 if result.formula_v2 and result.formula_v2.solver_status == "Optimal" else result.formula_v1
            if final_formula:
                canvas_path = self._generate_canvas_image(result.user_input, final_formula, pptx_path)
        except Exception:
            pass

        # Build the data payload for the JS generator
        def formula_to_dict(f: Optional[Formula]) -> Optional[dict]:
            if not f:
                return None
            return {
                "ingredients": f.ingredients,
                "total_cost": f.total_cost,
                "performance_score": f.performance_score,
                "solver_status": f.solver_status,
                "warnings": f.warnings,
                "interactions": f.interactions,
            }

        slide_data = {
            "user_input": result.user_input,
            "brand_name": result.brand_name,
            "brand_vision": result.brand_vision,
            "brand_palette": result.brand_palette,
            "formula_v1": formula_to_dict(result.formula_v1),
            "formula_v2": formula_to_dict(result.formula_v2),
            "explanation_v1": result.explanation_v1,
            "explanation_v2": result.explanation_v2,
            "parsed_ingredients": [
                {"name": ing.name, "category": ing.category, "efficacy_score": ing.efficacy_score}
                for ing in result.parsed_ingredients
            ],
            "canvas_image_path": canvas_path,
        }

        data_json = json.dumps(slide_data)

        # Find the JS script
        script_path = SLIDES_SCRIPT
        if not script_path.exists():
            # Also check in the same dir as this file
            alt = Path(__file__).parent / "generate_slides.js"
            if alt.exists():
                script_path = alt
            else:
                raise FileNotFoundError(f"Slide generator script not found at {script_path}")

        # Run pptxgenjs via Node
        proc = subprocess.run(
            ["node", str(script_path), pptx_path],
            input=data_json,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if proc.returncode != 0:
            err = proc.stderr.strip() or proc.stdout.strip()
            raise RuntimeError(f"Slide generation failed: {err}")

        if not os.path.exists(pptx_path):
            raise RuntimeError(f"Expected output not found: {pptx_path}")

        result.pptx_path = pptx_path
        if canvas_path:
            result.canvas_image_path = canvas_path

        console.print(f"  [bold green]Presentation saved: {pptx_path}[/bold green]")
        return pptx_path

    # ── Full Pipeline ─────────────────────────────────────────────────────

    def run(
        self,
        user_input: str,
        budget: float = DEFAULT_BUDGET,
        image_path: Optional[str] = None,
        max_loops: int = MAX_REFINEMENT_LOOPS,
    ) -> PipelineResult:
        """Execute the complete FormulaForge agentic pipeline."""

        result = PipelineResult(user_input=user_input)
        image_bytes = None
        image_media_type = "image/jpeg"

        # ── Load image if provided ────────────────────────────────────
        if image_path:
            try:
                path = Path(image_path)
                if not path.exists():
                    raise FileNotFoundError(f"Image not found: {image_path}")
                image_bytes = path.read_bytes()
                suffix = path.suffix.lower()
                media_map = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}
                image_media_type = media_map.get(suffix, "image/jpeg")
                console.print(f"[dim]Loaded image: {path.name} ({len(image_bytes)//1024}KB)[/dim]")
            except Exception as exc:
                result.errors.append(f"Image load failed: {exc}")
                console.print(f"[red]Image load failed: {exc} -- continuing with text only[/red]")
                image_bytes = None

        # ── STEP 1: Parse ─────────────────────────────────────────────
        self._step_header("1", "PARSE", "Extracting ingredients from input")
        result.steps["parse"] = StepStatus.RUNNING
        try:
            result.parsed_ingredients = self.step_parse(user_input, image_bytes, image_media_type)
            result.steps["parse"] = StepStatus.SUCCESS
            self._show_ingredients_table(result.parsed_ingredients)

            # Post-parse constraint health check
            total_min = sum(i.min_pct for i in result.parsed_ingredients)
            total_max = sum(i.max_pct for i in result.parsed_ingredients)
            min_cost = sum(i.cost_per_pct * i.min_pct for i in result.parsed_ingredients)
            console.print(
                f"  [dim]Constraint check: sum(min)={total_min:.1f}%, "
                f"sum(max)={total_max:.1f}%, min_cost=${min_cost:.2f}, "
                f"budget=${budget:.2f}[/dim]"
            )
        except Exception as exc:
            result.steps["parse"] = StepStatus.FAILED
            result.errors.append(f"Parse failed: {exc}")
            console.print(f"[red]Parse failed: {exc}[/red]")
            return result

        # ── STEP 2: Optimize v1 ───────────────────────────────────────
        self._step_header("2", "OPTIMIZE", f"Running LP solver (budget=${budget}/100g)")
        result.steps["optimize_v1"] = StepStatus.RUNNING
        try:
            result.formula_v1 = self.step_optimize(result.parsed_ingredients, budget)
            result.steps["optimize_v1"] = StepStatus.SUCCESS
            self._show_formula(result.formula_v1, "v1")
        except Exception as exc:
            result.steps["optimize_v1"] = StepStatus.FAILED
            result.errors.append(f"Optimize failed: {exc}")
            console.print(f"[red]Optimization failed: {exc}[/red]")
            return result

        if result.formula_v1.solver_status != "Optimal":
            console.print(f"[yellow]Solver returned: {result.formula_v1.solver_status}[/yellow]")
            if result.formula_v1.solver_status == "Infeasible":
                console.print("[red]Cannot find a feasible solution. Try relaxing constraints or increasing budget.[/red]")
                return result

        # ── STEP 3: Explain v1 ────────────────────────────────────────
        self._step_header("3", "EXPLAIN", "Generating scientific analysis")
        result.steps["explain_v1"] = StepStatus.RUNNING
        try:
            result.explanation_v1 = self.step_explain(result.formula_v1, user_input)
            result.steps["explain_v1"] = StepStatus.SUCCESS
            console.print(Panel(
                result.explanation_v1,
                title="[bold blue]Scientific Explanation (v1)[/bold blue]",
                border_style="blue",
                padding=(1, 2),
            ))
        except Exception as exc:
            result.steps["explain_v1"] = StepStatus.FAILED
            result.errors.append(f"Explain failed: {exc}")
            console.print(f"[yellow]Explanation generation failed: {exc}[/yellow]")
            result.explanation_v1 = "(explanation unavailable)"

        # ── Agent Refinement Loop ─────────────────────────────────────
        current_formula = result.formula_v1
        current_ingredients = list(result.parsed_ingredients)

        for loop_i in range(1, max_loops + 1):
            result.loop_count = loop_i

            # ── STEP 4: Evaluate ──────────────────────────────────────
            step_num = str(3 + (loop_i - 1) * 3 + 1)
            self._step_header(step_num, "EVALUATE", f"Agent critique & refinement (loop {loop_i}/{max_loops})")
            result.steps[f"evaluate_{loop_i}"] = StepStatus.RUNNING
            try:
                evaluation, refinements = self.step_evaluate(
                    current_formula, user_input, result.explanation_v1
                )
                result.evaluation = evaluation
                result.refinements = refinements
                result.steps[f"evaluate_{loop_i}"] = StepStatus.SUCCESS

                console.print(Panel(
                    evaluation,
                    title=f"[bold yellow]Agent Evaluation (Loop {loop_i})[/bold yellow]",
                    border_style="yellow",
                    padding=(1, 2),
                ))

                if refinements:
                    console.print(f"\n[bold cyan]Proposed refinements ({len(refinements)}):[/bold cyan]")
                    for ref in refinements:
                        reason = ref.get("reason", "")
                        console.print(f"  [dim]>[/dim] {ref.get('ingredient', '?')}: {reason}")
                else:
                    console.print("[green]Agent found no refinements needed -- formula is already strong.[/green]")
                    result.steps[f"reoptimize_{loop_i}"] = StepStatus.SKIPPED
                    break

            except Exception as exc:
                result.steps[f"evaluate_{loop_i}"] = StepStatus.FAILED
                result.errors.append(f"Evaluate failed: {exc}")
                console.print(f"[yellow]Evaluation failed: {exc} -- skipping refinement[/yellow]")
                break

            # ── STEP 5: Re-optimize ───────────────────────────────────
            step_num = str(3 + (loop_i - 1) * 3 + 2)
            self._step_header(step_num, "RE-OPTIMIZE", "Applying refinements & re-solving")
            result.steps[f"reoptimize_{loop_i}"] = StepStatus.RUNNING
            try:
                current_ingredients, formula_v2 = self.step_reoptimize(
                    current_ingredients, refinements, budget
                )
                result.formula_v2 = formula_v2
                result.steps[f"reoptimize_{loop_i}"] = StepStatus.SUCCESS
                self._show_formula(formula_v2, f"v{loop_i + 1}")

                if formula_v2.solver_status != "Optimal":
                    console.print(f"[yellow]Re-optimization status: {formula_v2.solver_status}[/yellow]")
                    break

                current_formula = formula_v2

            except Exception as exc:
                result.steps[f"reoptimize_{loop_i}"] = StepStatus.FAILED
                result.errors.append(f"Re-optimize failed: {exc}")
                console.print(f"[yellow]Re-optimization failed: {exc}[/yellow]")
                break

        # ── STEP 6: Compare ───────────────────────────────────────────
        if result.formula_v2 and result.formula_v2.solver_status == "Optimal":
            self._step_header("6", "COMPARE", "Side-by-side delta analysis")
            result.steps["compare"] = StepStatus.RUNNING
            try:
                # Generate v2 explanation
                result.explanation_v2 = self.step_explain(result.formula_v2, user_input)

                result.comparison = self.step_compare(result.formula_v1, result.formula_v2, user_input)
                result.steps["compare"] = StepStatus.SUCCESS

                self._show_comparison_table(result.formula_v1, result.formula_v2)
                console.print(Panel(
                    result.comparison,
                    title="[bold magenta]Comparative Analysis[/bold magenta]",
                    border_style="magenta",
                    padding=(1, 2),
                ))
            except Exception as exc:
                result.steps["compare"] = StepStatus.FAILED
                result.errors.append(f"Compare failed: {exc}")
                console.print(f"[yellow]Comparison failed: {exc}[/yellow]")

        # ── Summary ───────────────────────────────────────────────────
        self._show_pipeline_summary(result)

        # ── STEP 7: Present (PPTX) ───────────────────────────────────
        self._step_header("7", "PRESENT", "Generating presentation deck")
        result.steps["present"] = StepStatus.RUNNING
        try:
            pptx_path = self.step_present(result)
            result.steps["present"] = StepStatus.SUCCESS
        except Exception as exc:
            result.steps["present"] = StepStatus.FAILED
            result.errors.append(f"Presentation failed: {exc}")
            console.print(f"[yellow]Presentation generation failed: {exc}[/yellow]")

        return result

    # ── Display Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _step_header(number: str, label: str, description: str):
        console.print()
        console.rule(f"[bold bright_white] Step {number}: {label} [/bold bright_white]", style="bright_cyan")
        console.print(f"  [dim]{description}[/dim]\n")

    @staticmethod
    def _show_ingredients_table(ingredients: list[Ingredient]):
        table = Table(
            title="Parsed Ingredients",
            box=box.ROUNDED,
            show_lines=True,
            title_style="bold green",
            header_style="bold white on dark_green",
        )
        table.add_column("Ingredient", style="bold")
        table.add_column("Category", style="dim")
        table.add_column("Min %", justify="right")
        table.add_column("Max %", justify="right")
        table.add_column("Cost/1%", justify="right")
        table.add_column("Efficacy", justify="right")
        table.add_column("Notes", style="dim italic", max_width=30)

        for ing in ingredients:
            efficacy_color = "green" if ing.efficacy_score >= 7 else "yellow" if ing.efficacy_score >= 4 else "red"
            table.add_row(
                ing.name,
                ing.category,
                f"{ing.min_pct:.1f}",
                f"{ing.max_pct:.1f}",
                f"${ing.cost_per_pct:.2f}",
                f"[{efficacy_color}]{ing.efficacy_score:.1f}[/{efficacy_color}]",
                ing.notes.strip() or "-",
            )
        console.print(table)

    @staticmethod
    def _show_formula(formula: Formula, version: str = "v1"):
        table = Table(
            title=f"Optimized Formula ({version})",
            box=box.HEAVY_HEAD,
            show_lines=False,
            title_style="bold cyan",
            header_style="bold white on dark_blue",
        )
        table.add_column("Ingredient", style="bold")
        table.add_column("Percentage", justify="right")
        table.add_column("Bar", min_width=30)

        sorted_ings = sorted(formula.ingredients.items(), key=lambda x: -x[1])
        max_pct = max((v for v in formula.ingredients.values()), default=1)

        for name, pct in sorted_ings:
            if pct < 0.001:
                continue
            bar_len = int((pct / max_pct) * 28) if max_pct > 0 else 0
            bar = "[bright_cyan]" + "\u2588" * bar_len + "[/bright_cyan]"
            table.add_row(name, f"{pct:.2f}%", bar)

        console.print(table)
        console.print(
            f"  [bold]Score:[/bold] {formula.performance_score}  |  "
            f"[bold]Cost:[/bold] ${formula.total_cost}/100g  |  "
            f"[bold]Status:[/bold] {formula.solver_status}"
        )
        if formula.warnings:
            for w in formula.warnings:
                console.print(f"  [yellow]\u26a0 {w}[/yellow]")

    @staticmethod
    def _show_comparison_table(v1: Formula, v2: Formula):
        table = Table(
            title="Formula Comparison (v1 vs v2)",
            box=box.DOUBLE_EDGE,
            show_lines=True,
            title_style="bold magenta",
            header_style="bold white on purple4",
        )
        table.add_column("Ingredient", style="bold")
        table.add_column("v1 %", justify="right")
        table.add_column("v2 %", justify="right")
        table.add_column("Delta", justify="right")

        all_ingredients = sorted(set(v1.ingredients.keys()) | set(v2.ingredients.keys()))
        for name in all_ingredients:
            pct1 = v1.ingredients.get(name, 0.0)
            pct2 = v2.ingredients.get(name, 0.0)
            if pct1 < 0.001 and pct2 < 0.001:
                continue
            delta = pct2 - pct1
            delta_str = f"{delta:+.2f}%"
            delta_style = "green" if delta > 0.01 else "red" if delta < -0.01 else "dim"
            table.add_row(
                name,
                f"{pct1:.2f}%" if pct1 > 0 else "[dim]-[/dim]",
                f"{pct2:.2f}%" if pct2 > 0 else "[dim]-[/dim]",
                f"[{delta_style}]{delta_str}[/{delta_style}]",
            )

        # Summary row
        table.add_section()
        score_delta = (v2.performance_score - v1.performance_score)
        cost_delta = (v2.total_cost - v1.total_cost)
        table.add_row(
            "[bold]TOTAL SCORE[/bold]",
            str(v1.performance_score),
            str(v2.performance_score),
            f"[{'green' if score_delta >= 0 else 'red'}]{score_delta:+.2f}[/{'green' if score_delta >= 0 else 'red'}]",
        )
        table.add_row(
            "[bold]TOTAL COST[/bold]",
            f"${v1.total_cost}",
            f"${v2.total_cost}",
            f"[{'red' if cost_delta > 0 else 'green'}]{cost_delta:+.2f}[/{'red' if cost_delta > 0 else 'green'}]",
        )
        console.print(table)

    @staticmethod
    def _show_pipeline_summary(result: PipelineResult):
        console.print()
        console.rule("[bold bright_white] Pipeline Summary [/bold bright_white]", style="bright_green")

        status_icons = {
            StepStatus.SUCCESS: "[green]\u2713[/green]",
            StepStatus.FAILED:  "[red]\u2717[/red]",
            StepStatus.SKIPPED: "[dim]\u2014[/dim]",
            StepStatus.RUNNING: "[yellow]\u25cb[/yellow]",
            StepStatus.PENDING: "[dim]\u25cb[/dim]",
        }
        for step_name, status in result.steps.items():
            icon = status_icons.get(status, "?")
            console.print(f"  {icon} {step_name}: {status.value}")

        if result.errors:
            console.print(f"\n  [red]Errors ({len(result.errors)}):[/red]")
            for err in result.errors:
                console.print(f"    [red]\u2022 {err}[/red]")

        console.print(f"\n  [bold]Refinement loops completed:[/bold] {result.loop_count}")

        final = result.formula_v2 if result.formula_v2 else result.formula_v1
        if final:
            console.print(f"  [bold]Final performance score:[/bold] {final.performance_score}")
            console.print(f"  [bold]Final cost:[/bold] ${final.total_cost}/100g")

        console.print()

    # ── Utility ───────────────────────────────────────────────────────────

    @staticmethod
    def _extract_json_array(text: str) -> list[dict]:
        """Robustly extract a JSON array from LLM output."""
        # Strip markdown code fences if present
        text = re.sub(r"```(?:json)?\s*", "", text)
        text = text.replace("```", "")
        text = text.strip()

        # Try direct parse
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                return [data]
        except json.JSONDecodeError:
            pass

        # Try to find a JSON array within the text
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        # Last resort: try to find individual JSON objects
        objects = re.findall(r"\{[^{}]+\}", text)
        if objects:
            parsed = []
            for obj_str in objects:
                try:
                    parsed.append(json.loads(obj_str))
                except json.JSONDecodeError:
                    continue
            if parsed:
                return parsed

        raise ValueError(f"Could not extract JSON from Nova output:\n{text[:300]}")


# ──────────────────────────────────────────────────────────────────────────────
# CLI Interface
# ──────────────────────────────────────────────────────────────────────────────

def print_banner():
    banner = r"""
[bold bright_cyan]
  ___                        _       ___
 | __|__ _ _ _ __ _  ___ _ _| |__ _ | __|__ _ _ __ _ ___
 | _/ _ \ '_| '  \ || / _` | / _` || _/ _ \ '_/ _` / -_)
 |_|\___/_| |_|_|_\_,_\__,_|_\__,_||_|\___/_| \__, \___|
                                                |___/
[/bold bright_cyan]
[dim]AI-Powered Cosmetic Formulation Optimization Agent[/dim]
[dim]Powered by OpenAI GPT-4o + PuLP LP Solver[/dim]
"""
    console.print(banner)


def interactive_mode():
    """Run FormulaForge in interactive CLI mode."""
    print_banner()

    forge = FormulaForge()

    while True:
        console.print("\n[bold]Describe your cosmetic product goal[/bold] (or 'quit' to exit):")
        user_input = console.input("[bright_cyan]> [/bright_cyan]").strip()

        if user_input.lower() in ("quit", "exit", "q"):
            console.print("[dim]Goodbye![/dim]")
            break

        if not user_input:
            console.print("[yellow]Please enter a product description.[/yellow]")
            continue

        # Optional: image path
        console.print("[dim]Image of product label? (path or Enter to skip):[/dim]")
        image_input = console.input("[dim]> [/dim]").strip()
        image_path = image_input if image_input else None

        # Optional: budget
        console.print(f"[dim]Budget per 100g? (default ${DEFAULT_BUDGET}, Enter to skip):[/dim]")
        budget_input = console.input("[dim]> [/dim]").strip()
        try:
            budget = float(budget_input) if budget_input else DEFAULT_BUDGET
        except ValueError:
            budget = DEFAULT_BUDGET

        console.print()
        console.rule("[bold bright_white] FormulaForge Pipeline Starting [/bold bright_white]", style="bright_green")

        try:
            result = forge.run(
                user_input=user_input,
                budget=budget,
                image_path=image_path,
                max_loops=MAX_REFINEMENT_LOOPS,
            )
        except Exception as exc:
            console.print(f"\n[red bold]Pipeline error: {exc}[/red bold]")
            console.print(f"[dim]{traceback.format_exc()}[/dim]")


def single_run(user_input: str, image_path: Optional[str] = None, budget: float = DEFAULT_BUDGET):
    """Run a single formulation and return the result."""
    print_banner()
    forge = FormulaForge()
    console.rule("[bold bright_white] FormulaForge Pipeline Starting [/bold bright_white]", style="bright_green")
    return forge.run(user_input=user_input, budget=budget, image_path=image_path)


# ──────────────────────────────────────────────────────────────────────────────
# Entry Point
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # CLI single-run mode: python formula_forge.py "anti-aging serum with retinol"
        query = " ".join(sys.argv[1:])
        img = os.environ.get("FORGE_IMAGE")
        bdg = float(os.environ.get("FORGE_BUDGET", str(DEFAULT_BUDGET)))
        single_run(query, image_path=img, budget=bdg)
    else:
        interactive_mode()
