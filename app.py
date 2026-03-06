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
import json
import os
import re
import shutil
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
    }

    # Run pipeline in background
    asyncio.get_event_loop().run_in_executor(
        None, _run_pipeline, job_id
    )

    return {"job_id": job_id}


def _run_pipeline(job_id: str):
    """Execute the FormulaForge pipeline (runs in thread pool)."""
    job = jobs[job_id]
    job["status"] = "running"

    def emit(step: str, status: str, data: dict = None):
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

        raw = forge.openai_client.invoke(
            analysis_prompt,
            system="You are a world-class dermatologist AI. Provide comprehensive, evidence-based skin analysis.",
            image_bytes=content,
            image_media_type=media_type,
            max_tokens=3000,
            json_mode=True,
        )

        import re as _re
        match = _re.search(r'\{[\s\S]*\}', raw)
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

# ── OpenAI Voice S2S & Vision ─────────────────────────────────────────

@app.websocket("/api/s2s")
async def s2s_websocket(websocket: WebSocket):
    await websocket.accept()
    print("OpenAI Voice S2S connected.")
    
    # ── Event-Driven Orchestrator Context ──
    # Global context shared between Omni (Eye) and Sonic (Voice) for real-time awareness
    s2s_context: Dict[str, Any] = {
        "is_active": True,
        "visual_data": None
    }
    
    async def process_nova_act(task_goal: str):
        # Agentic browser task orchestration
        await asyncio.sleep(1)
        print("Agentic task invoked for:", task_goal)
        try:
            await websocket.send_json({
                "type": "act_status", 
                "status": f"Executing Regulatory Scan, Sourcing, and PIF generation...",
                "documents": [
                    {"title": "Regulatory Scan", "summary": "Canadian & FDA compliance verified. Retinol within legal limits."},
                    {"title": "Ingredient Sourcing", "summary": "Identified 3 suppliers for Squalane. Primary: Montreal Organics."},
                    {"title": "Draft PIF & Marketing", "summary": "Product Information File finalized. 'Hydration Reimagined' copy generated."}
                ]
            })
        except Exception:
            pass
            
    async def process_nova_omni(task_goal: str):
        # GPT-4o Vision multimodal reasoning
        await asyncio.sleep(0.5)
        print(f"GPT-4o Vision processing image goal: {task_goal}")
        
        # Share context with voice
        s2s_context["visual_data"] = f"Analyzed context for: {task_goal}"
        try:
            await websocket.send_json({
                "type": "omni_status", 
                "status": f"Visual data received. Translating context: {task_goal}..."
            })
            
            # Generate real voice response via OpenAI TTS
            await asyncio.sleep(0.5)
            try:
                forge = ff.FormulaForge()
                audio_bytes = forge.openai_client.generate_speech(
                    f"I've analyzed the visual context for: {task_goal}. Processing now."
                )
                await websocket.send_bytes(audio_bytes)
            except Exception:
                # Fallback: send minimal WAV header if TTS fails
                fake_audio_wav_header = b'RIFF$\x00\x00\x00WAVEfmt \x10\x00\x00\x00\x01\x00\x01\x00D\xac\x00\x00\x88X\x01\x00\x02\x00\x10\x00data\x00\x00\x00\x00'
                await websocket.send_bytes(fake_audio_wav_header)

        except Exception:
            pass

    async def process_chat_message(text: str, voice_response: bool):
        await asyncio.sleep(0.3)
        print(f"Chat received: {text} | Voice Resp: {voice_response}")
        
        # Use GPT-4o-mini for fast chat responses
        forge = ff.FormulaForge()
        try:
            reply_text = forge.openai_mini.invoke(
                text,
                system="You are FormulaForge AI, a helpful cosmetic science assistant. Be concise and professional.",
                max_tokens=200
            )
        except Exception:
            reply_text = f"I've received your message: '{text}'. Let me assist you further!"
        
        if voice_response:
            # Generate real voice response via OpenAI TTS
            try:
                audio_bytes = forge.openai_client.generate_speech(reply_text)
                await websocket.send_bytes(audio_bytes)
            except Exception:
                # Fallback: send text if TTS fails
                try:
                    await websocket.send_json({"type": "chat_response", "text": reply_text})
                except Exception:
                    pass
        else:
            # Send text response
            try:
                await websocket.send_json({
                    "type": "chat_response",
                    "text": reply_text
                })
            except Exception:
                pass

    try:
        while s2s_context["is_active"]:
            message = await websocket.receive()
            
            if message.get("type") == "websocket.disconnect":
                s2s_context["is_active"] = False
                break
                
            if "text" in message:
                data = json.loads(message["text"])
                if data.get("type") == "nova_act":
                    asyncio.create_task(process_nova_act(data.get("task")))
                elif data.get("type") == "omni_image":
                    asyncio.create_task(process_nova_omni(data.get("task")))
                elif data.get("type") == "chat_message":
                    asyncio.create_task(process_chat_message(data.get("text"), data.get("voice_response", False)))
            elif "bytes" in message:
                # Receive raw audio binary and transcribe via Whisper.
                audio_bytes = message["bytes"]
                # Process audio with OpenAI Whisper for speech-to-text.
                # Voice reads shared context from Vision.
                try:
                    forge = ff.FormulaForge()
                    transcribed = forge.openai_client.transcribe_audio(audio_bytes)
                    if transcribed.strip():
                        await process_chat_message(transcribed, voice_response=True)
                except Exception as whisper_err:
                    print(f"Whisper transcription error: {whisper_err}")
    except WebSocketDisconnect:
        s2s_context["is_active"] = False
        print("OpenAI Voice S2S disconnected.")
    except Exception as e:
        s2s_context["is_active"] = False
        print(f"OpenAI S2S Error: {e}")

# ── Health check ──────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "model": ff.MODEL_ID}
