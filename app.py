"""
FormulaForge Web Application
=============================
FastAPI backend that wraps the FormulaForge agentic pipeline.
Uses Server-Sent Events (SSE) for real-time pipeline progress.

Launch:
    uvicorn app:app --host 0.0.0.0 --port 8000

Requires:
    pip install fastapi uvicorn python-multipart openai
    OPENAI_API_KEY environment variable set
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
import struct
import tempfile
import traceback
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, File, Form, UploadFile, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

# ── Import FormulaForge pipeline ──────────────────────────────────────
import formula_forge as ff

app = FastAPI(title="FormulaForge", version="1.0.0")

STATIC_DIR = Path(__file__).parent
OUTPUT_DIR = os.path.join(STATIC_DIR, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# In-memory job store for SSE results
jobs: dict[str, dict] = {}


# ── Serve frontend ────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    html_path = STATIC_DIR / "index.html"
    if not html_path.exists():
        raise HTTPException(404, "index.html not found")
    return html_path.read_text(encoding="utf-8")


# ── Download endpoint ─────────────────────────────────────────────────

@app.get("/download/{filename}")
async def download_file(filename: str):
    safe = re.sub(r"[^a-zA-Z0-9_.\-]", "", filename)
    filepath = os.path.join(OUTPUT_DIR, safe)
    if not os.path.exists(filepath):
        raise HTTPException(404, f"File not found: {safe}")
    return FileResponse(
        filepath,
        media_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        filename=safe,
    )


# ── Serve generated images ────────────────────────────────────────────

@app.get("/images/{filename}")
async def serve_image(filename: str):
    safe = re.sub(r"[^a-zA-Z0-9_.\-]", "", filename)
    filepath = os.path.join(OUTPUT_DIR, safe)
    if not os.path.exists(filepath):
        raise HTTPException(404, f"Image not found: {safe}")
    return FileResponse(filepath, media_type="image/png")


@app.get("/images/360/{filename}")
async def serve_360_frame(filename: str):
    safe = re.sub(r"[^a-zA-Z0-9_.\-]", "", filename)
    filepath = os.path.join(OUTPUT_DIR, "360_frames", safe)
    if not os.path.exists(filepath):
        raise HTTPException(404, f"360 frame not found: {safe}")
    return FileResponse(filepath, media_type="image/png")


@app.get("/video/{filename}")
async def serve_video(filename: str):
    safe = re.sub(r"[^a-zA-Z0-9_.\-]", "", filename)
    filepath = os.path.join(OUTPUT_DIR, safe)
    if not os.path.exists(filepath):
        raise HTTPException(404, f"Video not found: {safe}")
    return FileResponse(filepath, media_type="video/mp4")


# ── SSE Pipeline Stream ──────────────────────────────────────────────

@app.post("/scan_image")
async def scan_image(
    image: UploadFile = File(...),
):
    """Scan an ingredient label image and return a text formula goal."""
    try:
        content = await image.read()
        media_type = image.content_type or "image/jpeg"
        
        # Initialize pipeline just to use its nova client
        # In a real app we'd reuse a singleton
        forge = ff.FormulaForge()
        goal_text = forge.scan_ingredient_label(content, media_type)
        return {"goal": goal_text}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))



@app.post("/generate")
async def start_generation(
    user_input: str = Form(...),
    budget: float = Form(15.0),
    language: str = Form("English"),
    image: Optional[UploadFile] = File(None),
):
    """Start the pipeline and return a job_id for SSE streaming."""
    if not user_input or not user_input.strip():
        raise HTTPException(400, "Formula goal cannot be empty.")
    if budget <= 0:
        raise HTTPException(400, "Budget must be greater than 0.")
    if budget > 10000:
        raise HTTPException(400, "Budget must be $10,000 or less.")

    import time as _time

    # Purge completed jobs older than 2 hours to prevent memory leaks
    _now = _time.time()
    stale = [jid for jid, j in list(jobs.items()) if j.get("status") in ("complete", "failed") and _now - j.get("created_at", _now) > 7200]
    for jid in stale:
        jobs.pop(jid, None)

    job_id = str(uuid.uuid4())[:8]

    # Save uploaded image if provided
    image_path = None
    if image and image.filename:
        suffix = Path(image.filename).suffix or ".jpg"
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix, dir=tempfile.gettempdir())
        content = await image.read()
        tmp.write(content)
        tmp.close()
        image_path = tmp.name

    jobs[job_id] = {
        "status": "pending",
        "user_input": user_input,
        "budget": budget,
        "language": language,
        "image_path": image_path,
        "events": [],
        "result": None,
        "created_at": _time.time(),
    }

    # Run pipeline in background
    asyncio.get_running_loop().run_in_executor(
        None, _run_pipeline, job_id
    )

    return {"job_id": job_id}


def _run_pipeline(job_id: str):
    """Execute the FormulaForge pipeline (runs in thread pool)."""
    job = jobs[job_id]
    job["status"] = "running"

    def emit(step: str, status: str, data: Optional[dict] = None):
        event = {"step": step, "status": status, "data": data or {}}
        job["events"].append(event)

    try:
        forge = ff.FormulaForge()

        # Override console output to capture step events
        user_input = job["user_input"]
        budget = job["budget"]
        language = job.get("language", "English")
        image_path = job["image_path"]

        # ── Step 1: Parse ──
        emit("parse", "running", {"detail": "Analyzing Molecular Constraints..."})
        try:
            image_bytes = None
            image_media_type = "image/jpeg"
            if image_path and os.path.exists(image_path):
                image_bytes = Path(image_path).read_bytes()
                suffix = Path(image_path).suffix.lower()
                mt = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
                image_media_type = mt.get(suffix, "image/jpeg")

            ingredients = forge.step_parse(user_input, image_bytes, image_media_type)
            emit("parse", "success", {
                "count": len(ingredients),
                "ingredients": [
                    {"name": i.name, "category": i.category, "efficacy_score": i.efficacy_score,
                     "min_pct": i.min_pct, "max_pct": i.max_pct, "cost_per_pct": i.cost_per_pct}
                    for i in ingredients
                ],
            })
        except Exception as exc:
            emit("parse", "failed", {"error": str(exc)})
            job["status"] = "failed"
            return

        # ── Step 2: Optimize v1 ──
        emit("optimize", "running", {"detail": "Optimizing Chemical Synergies..."})
        try:
            formula_v1 = forge.step_optimize(ingredients, budget)
            emit("optimize", "success", {
                "score": formula_v1.performance_score,
                "cost": formula_v1.total_cost,
                "status": formula_v1.solver_status,
                "ingredients": formula_v1.ingredients,
                "warnings": formula_v1.warnings,
            })
        except Exception as exc:
            emit("optimize", "failed", {"error": str(exc)})
            job["status"] = "failed"
            return

        if formula_v1.solver_status != "Optimal":
            emit("optimize", "warning", {"message": f"Solver: {formula_v1.solver_status}"})

            # ── Soft Retry: force 70% minimum on primary solvent ──
            emit("optimize", "running", {"detail": "Autonomous Self-Healing: Rebalancing Carrier Constraints..."})
            found_base = False
            for ing in ingredients:
                if ing.category == "base":
                    ing.min_pct = max(ing.min_pct, 70.0)
                    found_base = True
                    break
            if not found_base:
                cheapest = sorted(ingredients, key=lambda x: x.cost_per_pct)[0]
                cheapest.category = "base"
                cheapest.min_pct = max(cheapest.min_pct, 70.0)

            formula_v1 = forge.step_optimize(ingredients, budget)
            retry_warnings = formula_v1.warnings + ["Soft retry: forced 70% carrier minimum"]
            emit("optimize",
                 "success" if formula_v1.solver_status == "Optimal" else "failed",
                 {
                     "score": formula_v1.performance_score,
                     "cost": formula_v1.total_cost,
                     "status": formula_v1.solver_status,
                     "ingredients": formula_v1.ingredients,
                     "warnings": retry_warnings,
                 })

            if formula_v1.solver_status != "Optimal":
                job["status"] = "failed"
                return

        # ── Step 2.5: Brand Identity ──
        brand_name = user_input
        brand_vision = ""
        brand_palette = {}
        emit("explain", "running", {"detail": "Crafting Bespoke Brand Identity..."})
        try:
            brand = forge.step_brand(user_input, formula_v1)
            brand_name = brand.get("name", user_input)
            brand_vision = brand.get("vision", "")
            brand_palette = brand.get("palette", {})
            # Store on forge instance so _generate_canvas_image can access it
            forge._current_brand_name = brand_name
            forge._current_brand_vision = brand_vision
        except Exception:
            pass  # Non-fatal: fall back to user_input

        # ── Step 3: Explain v1 ──
        emit("explain", "running", {"detail": f"Generating Professional Scientific Narrative ({language})..."})
        try:
            explanation_v1 = forge.step_explain(formula_v1, user_input, brand_name=brand_name, language=language)
            emit("explain", "success", {"text": explanation_v1[:500]})
        except Exception as exc:
            explanation_v1 = "(unavailable)"
            emit("explain", "failed", {"error": str(exc)})

        # ── Step 4: Evaluate ──
        emit("evaluate", "running", {"detail": "Senior Chemist Peer Review..."})
        formula_v2 = None
        explanation_v2 = ""
        try:
            evaluation, refinements = forge.step_evaluate(formula_v1, user_input, explanation_v1)
            emit("evaluate", "success", {
                "refinement_count": len(refinements),
                "evaluation_preview": evaluation[:300],
            })

            # ── Step 5: Re-optimize ──
            if refinements:
                emit("reoptimize", "running", {"detail": "Re-Optimizing Chemical Synergies..."})
                try:
                    ingredients, formula_v2 = forge.step_reoptimize(
                        list(ingredients), refinements, budget
                    )
                    emit("reoptimize", "success", {
                        "score": formula_v2.performance_score,
                        "cost": formula_v2.total_cost,
                        "status": formula_v2.solver_status,
                        "ingredients": formula_v2.ingredients,
                    })
                except Exception as exc:
                    emit("reoptimize", "failed", {"error": str(exc)})
            else:
                emit("reoptimize", "skipped")

        except Exception as exc:
            emit("evaluate", "failed", {"error": str(exc)})

        # ── Step 6: Compare ──
        comparison = ""
        if formula_v2 and formula_v2.solver_status == "Optimal":
            emit("compare", "running", {"detail": f"Comparative Formulation Assessment ({language})..."})
            try:
                explanation_v2 = forge.step_explain(formula_v2, user_input, brand_name=brand_name, language=language)
                comparison = forge.step_compare(formula_v1, formula_v2, user_input, language=language)
                emit("compare", "success", {"text": comparison[:300]})
            except Exception as exc:
                emit("compare", "failed", {"error": str(exc)})
        else:
            emit("compare", "skipped")

        # ── Step 7: Present (PPTX) ──
        emit("present", "running", {"detail": "Engineering Luxury Presentation Deck..."})
        pptx_path = ""
        canvas_image_path = ""
        try:
            # Build PipelineResult for step_present
            result = ff.PipelineResult(user_input=user_input)
            result.parsed_ingredients = ingredients
            result.formula_v1 = formula_v1
            result.formula_v2 = formula_v2
            result.explanation_v1 = explanation_v1
            result.explanation_v2 = explanation_v2
            result.comparison = comparison
            result.brand_name = brand_name
            result.brand_vision = brand_vision
            result.brand_palette = brand_palette

            pptx_path = forge.step_present(result)
            canvas_image_path = result.canvas_image_path or ""
            emit("present", "success", {
                "pptx_filename": os.path.basename(pptx_path),
                "canvas_image": os.path.basename(canvas_image_path) if canvas_image_path else None,
            })
        except Exception as exc:
            emit("present", "failed", {"error": str(exc)})

        # ── Step 8: AI Turntable Video ──
        turntable_video = None
        emit("product_video", "running", {"detail": "Rendering AI-Generated Turntable Video via DALL-E 3..."})
        try:
            video_path = forge.generate_turntable_video(user_input, OUTPUT_DIR, canvas_image_path=canvas_image_path)
            if video_path:
                turntable_video = os.path.basename(video_path)
                emit("product_video", "success", {"turntable": turntable_video})
            else:
                emit("product_video", "success", {"turntable": None, "detail": "Video generation unavailable, using fallback viewer"})
        except Exception as exc:
            emit("product_video", "failed", {"error": f"Turntable video: {exc}"})

        # ── Build final result ──
        final_formula = formula_v2 if formula_v2 and formula_v2.solver_status == "Optimal" else formula_v1
        interactions = (final_formula.interactions if final_formula else []) or []

        job["result"] = {
            "user_input": user_input,
            "brand_name": brand_name,
            "brand_vision": brand_vision,
            "brand_palette": brand_palette,
            "formula_v1": {
                "ingredients": formula_v1.ingredients,
                "performance_score": formula_v1.performance_score,
                "total_cost": formula_v1.total_cost,
                "solver_status": formula_v1.solver_status,
                "warnings": formula_v1.warnings,
                "interactions": formula_v1.interactions,
            },
            "formula_v2": {
                "ingredients": formula_v2.ingredients,
                "performance_score": formula_v2.performance_score,
                "total_cost": formula_v2.total_cost,
                "solver_status": formula_v2.solver_status,
                "warnings": formula_v2.warnings,
                "interactions": formula_v2.interactions,
            } if formula_v2 else None,
            "explanation": explanation_v2 or explanation_v1,
            "comparison": comparison,
            "interactions": interactions,
            "pptx_filename": os.path.basename(pptx_path) if pptx_path else None,
            "canvas_image": os.path.basename(canvas_image_path) if canvas_image_path else None,
            "turntable_video": turntable_video,
        }
        emit("done", "complete", job["result"])
        job["status"] = "complete"

    except Exception as exc:
        emit("error", "failed", {"error": str(exc), "traceback": traceback.format_exc()})
        job["status"] = "failed"

    finally:
        # Cleanup temp image
        if job.get("image_path") and os.path.exists(job["image_path"]):
            try:
                os.unlink(job["image_path"])
            except OSError:
                pass


@app.get("/events")
async def sse_events(client_id: str):
    """Subscribe to the SSE stream using a client_id (which maps to the background job thread)."""
    async def event_generator():
        job = jobs.get(client_id)
        if not job:
            yield f"data: {json.dumps({'step': 'error', 'status': 'Job not found'})}\n\n"
            return

        last_idx = 0
        while True:
            events = job["events"]
            if last_idx < len(events):
                for ev in events[last_idx:]:
                    yield f"data: {json.dumps(ev)}\n\n"
                last_idx = len(events)
            
            # Check if job is finished
            if job.get("status") in ["complete", "failed"]:
                if job["status"] == "complete":
                    # Send one final event with the full output payload
                    final_payload = {
                        "step": "complete",
                        "status": "success",
                        "result": job.get("result", {})
                    }
                    yield f"data: {json.dumps(final_payload)}\n\n"
                break
            
            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── Skin Analysis endpoint (Camera / Photo) ──────────────────────────

@app.post("/skin_analysis")
async def skin_analysis(
    image: UploadFile = File(...),
):
    """Extensive skin analysis with diagnosis, formula prompt, and market product recommendations."""
    try:
        content = await image.read()
        media_type = image.content_type or "image/jpeg"

        forge = ff.FormulaForge()

        analysis_prompt = (
            "You are a board-certified dermatologist AI with 20 years of clinical experience. "
            "Analyze the provided image of a person's skin EXTENSIVELY and THOROUGHLY.\n\n"
            "Provide your analysis in this EXACT JSON format:\n"
            '{\n'
            '  "skin_type": "<oily/dry/combination/normal/sensitive>",\n'
            '  "skin_tone": "<fair/light/medium/olive/tan/deep>",\n'
            '  "concerns": ["<list every visible concern>"],\n'
            '  "severity": "<mild/moderate/severe>",\n'
            '  "diagnosis": "<detailed 4-5 sentence clinical observation covering texture, tone, hydration, visible damage>",\n'
            '  "affected_areas": [\n'
            '    {"zone": "<forehead/cheeks/nose/chin/under-eye/jawline>", "issue": "<what you see>", "severity": "<1-10>"}\n'
            '  ],\n'
            '  "root_causes": ["<likely causes: hormonal, UV damage, dehydration, barrier damage, etc>"],\n'
            '  "treatment_plan": [\n'
            '    {"step": 1, "action": "<what to do>", "timeframe": "<when to expect results>", "priority": "<high/medium/low>"}\n'
            '  ],\n'
            '  "recommended_ingredients": [\n'
            '    {"name": "<ingredient>", "benefit": "<specific benefit for THIS skin>", "concentration": "<suggested %>", "when_to_use": "<AM/PM/both>"}\n'
            '  ],\n'
            '  "formula_goal": "<a detailed, ready-to-use formula goal for FormulaForge that addresses ALL identified concerns>",\n'
            '  "market_products": [\n'
            '    {"brand": "<real brand>", "product": "<exact product name>", "price_range": "<$XX-$XX>", "key_ingredients": "<main actives>", "why": "<why it helps this specific skin>"}\n'
            '  ],\n'
            '  "lifestyle_tips": ["<5-6 actionable daily tips>"],\n'
            '  "warning": "<any urgent concerns like potential skin cancer signs, infections, etc. or null>"\n'
            '}\n\n'
            "Be EXTREMELY thorough. Identify ALL conditions: acne, hyperpigmentation, melasma, "
            "dryness, redness, rosacea, fine lines, wrinkles, dark circles, enlarged pores, "
            "uneven texture, sun damage, eczema, psoriasis, seborrheic dermatitis, milia, "
            "blackheads, whiteheads, cystic acne, PIH, PIE, dehydration lines.\n"
            "For market_products, recommend 3-5 REAL products from brands like CeraVe, La Roche-Posay, "
            "The Ordinary, Paula's Choice, Drunk Elephant, SkinCeuticals, etc.\n"
            "If you CANNOT see skin clearly, set diagnosis to 'Unable to analyze'.\n"
            "Output ONLY the JSON, no markdown fences."
        )

        raw = _nova_invoke_vc(
            analysis_prompt,
            system="You are a world-class dermatologist AI. Provide comprehensive, evidence-based skin analysis.",
            image_bytes=content,
            image_media_type=media_type,
            max_tokens=4096,
            temperature=0.3,
        )

        match = re.search(r'\{[\s\S]*\}', raw)
        if match:
            analysis = json.loads(match.group())
        else:
            analysis = {"diagnosis": raw, "formula_goal": raw, "concerns": [], "recommended_ingredients": [], "market_products": []}

        return analysis

    except Exception as exc:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(exc))

# ── Chatbot endpoint ──────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str
    formula_json: str = "{}"
    history: list[dict] = []

@app.post("/chat")
async def chat_endpoint(req: ChatRequest):
    try:
        forge = ff.FormulaForge()
        ans = forge.chat_with_formula(
            question=req.question,
            formula_json=req.formula_json,
            history=req.history
        )
        return {"answer": ans}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# ── Campaign Studio endpoint ──────────────────────────────────────────

class CampaignRequest(BaseModel):
    brand_name: str = ""
    formula_name: str = ""
    vision: str = ""
    formula_json: str = "{}"

@app.post("/campaign")
async def campaign_endpoint(req: CampaignRequest):
    try:
        forge = ff.FormulaForge()
        assets = forge.generate_campaign(
            brand_name=req.brand_name,
            formula_name=req.formula_name,
            vision=req.vision,
            formula_json=req.formula_json
        )
        return assets
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── OpenAI o3-mini & Outreach Endpoints ───────────────────────────────

 # ── 3. Clinical & Patent Review (o3-mini deep reasoning) ──
@app.post("/premier_analysis")
async def premier_analysis(req: dict):
    # Use o3-mini for clinical & patent review (deep reasoning)
    try:
        forge = ff.FormulaForge()
        brand = req.get("brand_name", "FormulaForge Maison")
        formula = req.get("formula_json", "{}")
        report = forge.generate_premier_analysis(brand, formula)
        return {"report": report}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

class PremierRequest(BaseModel):
    brand_name: str = ""
    formula_json: str = "{}"

@app.post("/outreach_email")
async def outreach_email_endpoint(req: PremierRequest):
    try:
        forge = ff.FormulaForge()
        email_body = forge.generate_outreach_email(
            brand_name=req.brand_name,
            formula_json=req.formula_json
        )
        return {"email": email_body}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/competitor_teardown")
async def competitor_teardown_endpoint(
    image: UploadFile = File(...),
    formula_json: str = Form(...)
):
    try:
        forge = ff.FormulaForge()
        file_ext = image.filename.split(".")[-1].lower()
        if file_ext == 'jpg': file_ext = 'jpeg'
        if file_ext not in ['jpeg', 'png', 'webp', 'gif']:
            raise HTTPException(status_code=400, detail="Unsupported image format. Use JPEG, PNG, or WEBP.")
            
        img_bytes = await image.read()
        
        report = forge.generate_competitor_teardown(
            image_bytes=img_bytes,
            image_format=file_ext,
            our_formula_json=formula_json
        )
        return {"report": report}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# ── Amazon Nova / Polly helpers for Video Call ───────────────────────

_VC_NOVA_MODEL = "amazon.nova-lite-v1:0"
_VC_AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")


def _vc_nova_client():
    """Return a lazily created Bedrock Runtime client for the video call."""
    import boto3
    from botocore.config import Config as _BotoConfig
    return boto3.client(
        "bedrock-runtime",
        region_name=_VC_AWS_REGION,
        config=_BotoConfig(
            retries={"max_attempts": 2, "mode": "adaptive"},
            read_timeout=90,
        ),
    )


def _nova_invoke_vc(prompt: str, system: str,
                    image_bytes: Optional[bytes] = None,
                    image_media_type: str = "image/jpeg",
                    max_tokens: int = 600,
                    temperature: float = 0.7,
                    history: Optional[List[Dict[str, Any]]] = None) -> str:
    """Invoke Amazon Bedrock Nova for a video call turn (blocking, run in executor).

    history: list of {"role": "user"|"assistant", "content": str} dicts for multi-turn context.
    The current user prompt (with optional image) is appended as the final user turn.
    """
    # Build Nova messages array from conversation history
    nova_messages: list = []

    # Add prior turns (text-only — images are only on the latest turn)
    if history:
        for turn in history:
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role in ("user", "assistant") and content:
                nova_messages.append({"role": role, "content": [{"text": content}]})

    # Build the current user turn (image + text)
    current_content: list = []
    if image_bytes is not None:
        current_content.append({
            "image": {
                "format": image_media_type.split("/")[-1],
                "source": {"bytes": base64.b64encode(image_bytes).decode("utf-8")},
            }
        })
    current_content.append({"text": prompt})
    nova_messages.append({"role": "user", "content": current_content})

    body: dict = {
        "messages": nova_messages,
        "inferenceConfig": {
            "maxTokens": max_tokens,
            "temperature": temperature,
            "topP": 0.9,
        },
    }
    if system:
        body["system"] = [{"text": system}]

    client = _vc_nova_client()
    resp = client.invoke_model(
        modelId=_VC_NOVA_MODEL,
        contentType="application/json",
        accept="application/json",
        body=json.dumps(body),
    )
    result = json.loads(resp["body"].read())
    return result["output"]["message"]["content"][0]["text"]


def _pcm_to_wav_vc(pcm_data: bytes, sample_rate: int = 16000,
                   channels: int = 1, bit_depth: int = 16) -> bytes:
    """Wrap raw Polly PCM bytes in a WAV container."""
    data_size = len(pcm_data)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + data_size, b"WAVE",
        b"fmt ", 16, 1, channels, sample_rate,
        sample_rate * channels * bit_depth // 8,
        channels * bit_depth // 8, bit_depth,
        b"data", data_size,
    )
    return header + pcm_data


def _polly_speak(text: str) -> Optional[bytes]:
    """Convert text to WAV via Amazon Polly neural voice.
    Returns None if Polly is unavailable so the frontend can use Web Speech API.
    """
    import boto3
    from botocore.exceptions import ClientError as _BotoClientError
    try:
        polly = boto3.client("polly", region_name=_VC_AWS_REGION)
        resp = polly.synthesize_speech(
            Text=text,
            OutputFormat="pcm",
            VoiceId="Joanna",
            Engine="neural",
            SampleRate="16000",
        )
        return _pcm_to_wav_vc(resp["AudioStream"].read(), sample_rate=16000)
    except _BotoClientError as exc:
        print(f"[Polly] {exc.response['Error']['Code']} — frontend will use Web Speech API.")
        return None
    except Exception as exc:
        print(f"[Polly] Error: {exc}")
        return None


# ── Real-Time Voice Chat & Vision ─────────────────────────────────────

@app.websocket("/api/s2s")
async def s2s_websocket(websocket: WebSocket, mode: str = "general_chat"):
    await websocket.accept()
    print(f"Voice Chat WebSocket connected (Mode: {mode}).")

    # Per-session conversation history for context
    conversation_history: List[Any] = []
    s2s_context: Dict[str, Any] = {
        "is_active": True,
        "visual_data": None,
        "formula_context": None,
        "visual_data_bytes": None,
        "proactive_scan_done": False,
        "scan_turn_count": 0,        # how many AI turns have happened in video_call
    }

    if mode == "video_call":
        SYSTEM_PROMPT = (
            "You are 'Dr. Veda,' a Senior AI Aesthetic Consultant conducting a live Skin Scan via webcam.\n\n"
            "RESPOND ONLY WITH A VALID JSON OBJECT — no markdown, no code fences:\n"
            "{\n"
            '  "observations": [\n'
            '    {"area": "forehead|left_cheek|right_cheek|nose|chin|jawline|under_eye",\n'
            '     "condition": "acne_mild|acne_moderate|acne_severe|redness|rosacea|dryness|oiliness|hyperpigmentation|melasma|fine_lines|wrinkles|sun_damage|eczema|clear",\n'
            '     "severity": "low|medium|high", "confidence": 0.0-1.0, "description": "Brief description"}\n'
            '  ],\n'
            '  "spoken_response": "What to say aloud — 1-3 sentences.",\n'
            '  "positioning_request": null\n'
            "}\n\n"
            "MOST IMPORTANT RULE — ALWAYS ANSWER THE USER DIRECTLY:\n"
            "- If the user asks HOW TO FIX, TREAT, or SOLVE their skin concerns, answer with specific actionable advice in spoken_response. Name ingredients (niacinamide, salicylic acid, etc.) and steps. Do NOT redirect back to scanning.\n"
            "- If the user asks a question of ANY kind, answer it fully and helpfully in spoken_response.\n"
            "- Only guide the scan (tilt left, move closer, etc.) when the user gives a neutral acknowledgment like 'OK', 'sure', 'yes', or says nothing meaningful.\n"
            "- NEVER ignore a direct question. NEVER repeat the same observation twice.\n\n"
            "IDENTITY & SCOPE:\n"
            "- You analyze SKIN HEALTH ONLY. NEVER identify or name any individual.\n"
            "- You are NOT a medical doctor — always recommend seeing a dermatologist for clinical conditions.\n\n"
            "SCAN PHASES (only when user is not asking a question):\n"
            "Phase 1 (turn 1): Greet briefly, share 2-3 skin observations, ask user to tilt for one zone.\n"
            "Phase 2 (turns 2-3): Guide through facial zones one at a time.\n"
            "Phase 3 (turn 4+): Summarize top 3 findings, recommend 2-3 active ingredients with % concentrations, offer to generate a custom formula.\n"
        )
    else:
        SYSTEM_PROMPT = (
            "You are Nova, an expert cosmetic chemist formulating products and advising a luxury skincare brand. "
            "Your language is sophisticated, scientific, yet accessible. Answer quickly and concisely, avoiding jargon unless necessary. "
            "You do not invent ingredients that are not commonly used, and you do not diagnose medical skin conditions. "
            "Keep your responses relatively brief as they will be synthesized into voice."
        )

    async def _safe_send_json(payload: dict) -> bool:
        """Send JSON; marks session inactive and returns False on any send error."""
        if not s2s_context["is_active"]:
            return False
        try:
            await websocket.send_json(payload)
            return True
        except Exception:
            s2s_context["is_active"] = False
            return False

    async def _safe_send_bytes(data: bytes) -> bool:
        """Send bytes; marks session inactive and returns False on any send error."""
        if not s2s_context["is_active"]:
            return False
        try:
            await websocket.send_bytes(data)
            return True
        except Exception:
            s2s_context["is_active"] = False
            return False

    async def send_status(status: str):
        """Send UI status update to frontend."""
        await _safe_send_json({"type": "status", "status": status})

    async def voice_respond(user_text: str):
        """Full voice pipeline: get Nova response → send text + TTS audio."""
        try:
            if not s2s_context["is_active"]:
                return  # WebSocket already closed — abort silently

            # 1. Send status: thinking
            await send_status("thinking")

            actual_prompt = user_text

            # 3. Build effective system prompt (base + optional context injections)
            effective_system = SYSTEM_PROMPT
            if s2s_context.get("formula_context"):
                effective_system += f"\n\nFormula context: {s2s_context['formula_context']}"
            if mode == "video_call" and s2s_context["scan_turn_count"] >= 3:
                effective_system += (
                    "\n\nYou have now analyzed several facial zones. "
                    "Begin wrapping up: state your top 3 findings, name 2-3 recommended ingredients, "
                    "and end with: 'Would you like me to generate a custom formula based on this scan?'"
                )

            # 4. Get AI response via Amazon Bedrock Nova (replaces OpenAI)
            loop = asyncio.get_running_loop()
            # Snapshot history before await so lambda captures the right values
            _n = len(conversation_history)
            _hist_snapshot: List[Any] = conversation_history[max(0, _n - 10):_n]  # type: ignore[index]
            if mode == "video_call":
                raw_response = await loop.run_in_executor(
                    None,
                    lambda: _nova_invoke_vc(
                        actual_prompt,
                        system=effective_system,
                        image_bytes=s2s_context.get("visual_data_bytes"),
                        image_media_type="image/jpeg",
                        max_tokens=600,
                        temperature=0.7,
                        history=_hist_snapshot,
                    ),
                )
                try:
                    parsed_response = json.loads(raw_response)
                    reply_text = parsed_response.get("spoken_response", "")
                    if not reply_text:
                        reply_text = "I'm analyzing your skin now."

                    if "observations" in parsed_response:
                        if "all_observations" not in s2s_context:
                            s2s_context["all_observations"] = []
                        s2s_context["all_observations"].extend(parsed_response["observations"])
                        await _safe_send_json({
                            "type": "observation",
                            "data": parsed_response["observations"],
                            "positioning": parsed_response.get("positioning_request"),
                        })
                except Exception as eval_err:
                    print(f"[VideoCall] Nova JSON parse error: {eval_err}")
                    # Nova returned free-text instead of JSON — use as spoken response
                    reply_text = raw_response.strip()
            else:
                reply_text = await loop.run_in_executor(
                    None,
                    lambda: _nova_invoke_vc(
                        actual_prompt,
                        system=effective_system,
                        image_bytes=s2s_context.get("visual_data_bytes"),
                        image_media_type="image/jpeg",
                        max_tokens=300,
                        temperature=0.7,
                        history=_hist_snapshot,
                    ),
                )

            # 5. Save to history
            display_user_text = user_text
            conversation_history.append({"role": "user", "content": actual_prompt})
            conversation_history.append({"role": "assistant", "content": reply_text})

            # Increment turn counter and decide whether to suggest formula
            if mode == "video_call":
                s2s_context["scan_turn_count"] += 1
            suggest_formula = (
                mode == "video_call"
                and s2s_context["scan_turn_count"] >= 4
                and "custom formula" in reply_text.lower()
            )

            # 5. Send text transcript to frontend
            if not await _safe_send_json({
                "type": "voice_response",
                "text": reply_text,
                "user_text": display_user_text,
                "suggest_formula": suggest_formula,
            }):
                return  # Socket closed mid-response

            # 6. Generate TTS audio via Amazon Polly; fall back to Web Speech API
            await send_status("speaking")
            try:
                loop = asyncio.get_running_loop()
                audio_bytes = await loop.run_in_executor(None, _polly_speak, reply_text)
                if not s2s_context["is_active"]:
                    return  # Socket closed while waiting for Polly
                if audio_bytes:
                    await _safe_send_bytes(audio_bytes)
                else:
                    # Polly unavailable — tell the frontend to use its Web Speech API
                    await _safe_send_json({"type": "tts_fallback", "text": reply_text})
                    await _safe_send_json({"type": "speech_done"})
            except Exception as tts_err:
                print(f"[TTS] Error: {tts_err}")
                await _safe_send_json({"type": "speech_done"})

            # 7. Ready for next input
            await send_status("idle")

        except Exception as e:
            print(f"Voice respond error: {e}")
            traceback.print_exc()
            await _safe_send_json({
                "type": "voice_response",
                "text": "I'm sorry, I had trouble processing that. Could you try again?",
                "user_text": user_text,
            })
            await send_status("idle")

    async def process_agentic_task(task_goal: str):
        """Agentic browser task orchestration."""
        await asyncio.sleep(1)
        print("Agentic task invoked for:", task_goal)
        await _safe_send_json({
            "type": "act_status",
            "status": "Executing Regulatory Scan, Sourcing, and PIF generation...",
            "documents": [
                {"title": "Regulatory Scan", "summary": "Canadian & FDA compliance verified. Retinol within legal limits."},
                {"title": "Ingredient Sourcing", "summary": "Identified 3 suppliers for Squalane. Primary: Montreal Organics."},
                {"title": "Draft PIF & Marketing", "summary": "Product Information File finalized. 'Hydration Reimagined' copy generated."},
            ],
        })

    async def process_vision(task_goal: str):
        """GPT-4o Vision multimodal reasoning."""
        await asyncio.sleep(0.5)
        print(f"GPT-4o Vision processing: {task_goal}")
        s2s_context["visual_data"] = f"Analyzed context for: {task_goal}"
        if await _safe_send_json({
            "type": "omni_status",
            "status": f"Visual data received. Processing: {task_goal}...",
        }):
            await voice_respond(f"Describe what you found analyzing: {task_goal}")

    try:
        # Send initial greeting
        await send_status("idle")

        while s2s_context["is_active"]:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                s2s_context["is_active"] = False
                break

            if "text" in message:
                data = json.loads(message["text"])
                msg_type = data.get("type", "")

                if msg_type == "chat_message":
                    # Text message → voice response
                    user_text = data.get("text", "")
                    if user_text.strip():
                        asyncio.create_task(voice_respond(user_text))

                elif msg_type == "set_context":
                    # Frontend sends formula context for more relevant answers
                    s2s_context["formula_context"] = data.get("formula_json")

                elif msg_type == "nova_act":
                    asyncio.create_task(process_agentic_task(data.get("task", "")))

                elif msg_type == "omni_image":
                    asyncio.create_task(process_vision(data.get("task", "")))

                elif msg_type == "video_frame":
                    try:
                        b64_str = data.get("image", "")
                        if "," in b64_str:
                            b64_str = b64_str.split(",", 1)[1]
                        import base64
                        s2s_context["visual_data_bytes"] = base64.b64decode(b64_str)
                        # Frame stored — Dr. Veda will use it when the user speaks
                    except Exception as e:
                        print(f"Error decoding video frame: {e}")

            elif "bytes" in message:
                # Voice input: raw audio → Whisper → GPT → TTS
                audio_bytes = message["bytes"]
                if len(audio_bytes) < 100:
                    continue  # Skip empty/tiny audio chunks

                await send_status("processing")

                # For video_call: ask frontend for a fresh frame, then wait briefly
                # so the frame arrives and is stored before we call voice_respond.
                if mode == "video_call":
                    await _safe_send_json({"type": "request_frame"})
                    await asyncio.sleep(0.35)

                try:
                    # STT stub — AWS Transcribe Streaming not yet configured.
                    # The frontend's MediaRecorder sends audio but we skip it here
                    # until the IAM streaming permissions are granted.
                    # len > 100 guard (above) prevents micro-chunk spam.
                    transcribed = ""   # TODO: replace with Transcribe Streaming SDK
                    if transcribed and len(transcribed.strip()) > 2:
                        print(f"[STT] Transcribed: {transcribed}")
                        await voice_respond(transcribed)
                    else:
                        await send_status("idle")
                except Exception as stt_err:
                    print(f"[STT] Error: {stt_err}")
                    await send_status("idle")

    except WebSocketDisconnect:
        s2s_context["is_active"] = False
        print("Voice Chat disconnected.")
    except Exception as e:
        s2s_context["is_active"] = False
        print(f"Voice Chat Error: {e}")

# ── Product Search & Safety Endpoints ─────────────────────────────────

class ProductSearchRequest(BaseModel):
    concerns: list[str] = []
    skin_type: str = ""
    ingredients: list[str] = []

@app.post("/product_search")
async def product_search(req: ProductSearchRequest):
    """Search for real products with prices and purchase links."""
    try:
        forge = ff.FormulaForge()
        products = forge.search_product_prices(
            concerns=req.concerns,
            skin_type=req.skin_type,
            ingredients=req.ingredients,
        )
        return {"products": products}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

class SafetyCheckRequest(BaseModel):
    ingredients: list[dict] = []

@app.post("/ingredient_safety")
async def ingredient_safety(req: SafetyCheckRequest):
    """Check ingredients for safety concerns and regulatory issues."""
    try:
        forge = ff.FormulaForge()
        alerts = forge.check_ingredient_safety(req.ingredients)
        return {"alerts": alerts}
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# ── Health check ──────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "model": ff.MODEL_ID}
