import logging
import os
import re
import socket
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from app import ai_engine, database, document_io, job_hunter, scraper
from app.models import (
    AdaptCVRequest,
    AnalyzeJobRequest,
    ConvertToAnalysisRequest,
    CVProfileUpdate,
    DiscoveredJobStatusUpdate,
    FetchUrlRequest,
    JobSearchQuery,
    KnowledgeFactCreate,
    KnowledgeFactUpdate,
    SearchPreferencesUpdate,
    SettingsUpdate,
    SubmitAnswersRequest,
    TestAIRequest,
    UpdateAdaptedCVRequest,
)

load_dotenv()

STATIC_DIR = Path(__file__).resolve().parent / "static"

app = FastAPI(
    title="JobFinder CV Studio",
    description="Asistente local de adaptación honesta de CV y optimización ATS con base de conocimiento persistente.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    database.init_db()


def _detect_lan_ip() -> str:
    env_host = (os.getenv("LAN_HOST") or "").strip()
    if env_host:
        return env_host
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        sock.close()
        return ip
    except Exception:
        return "127.0.0.1"


def _safe_filename(name: str, ext: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", (name or "cv_adaptado").strip())
    slug = slug.strip("_")[:60] or "cv_adaptado"
    return f"{slug}.{ext}"


# --- Health & Network Info ---

@app.get("/api/health")
def health():
    settings = database.get_settings(mask_key=True)
    cv = database.get_cv_profile()
    facts = database.list_knowledge_facts()
    return {
        "status": "ok",
        "provider": settings.get("provider", "local"),
        "has_cv": bool(cv and cv.get("raw_text")),
        "knowledge_count": len(facts),
    }


@app.get("/api/network-info")
def network_info():
    lan_ip = _detect_lan_ip()
    port = os.getenv("PORT", "8000")
    return {
        "lan_ip": lan_ip,
        "port": port,
        "lan_url": f"http://{lan_ip}:{port}",
        "local_url": f"http://localhost:{port}",
    }


# --- Base CV ---

def _sync_preferences_from_cv(cv_dict: dict, overwrite_custom: bool = False) -> None:
    try:
        facts = database.list_knowledge_facts()
        detected = job_hunter.auto_detect_preferences_from_cv(cv_dict, facts)
        current_prefs = database.get_search_preferences() or {}

        norm_cv = (cv_dict.get("raw_text") or "").lower()
        curr_roles = current_prefs.get("target_roles") or []
        roles_match = any(r.lower() in norm_cv for r in curr_roles) if curr_roles else False

        if overwrite_custom or not roles_match:
            target_roles = detected.get("target_roles", [])
            location = detected.get("location", "España")
            country = detected.get("country", "España")
            modality = detected.get("modality", "all")
            database.clear_discovered_jobs()
        else:
            target_roles = curr_roles
            location = current_prefs.get("location") or detected.get("location", "España")
            country = current_prefs.get("country") or detected.get("country", "España")
            modality = current_prefs.get("modality") or detected.get("modality", "all")

        database.save_search_preferences(
            target_roles=target_roles,
            location=location,
            country=country,
            modality=modality,
            experience_level=detected.get("experience_level", "mid"),
            keywords_include=detected.get("keywords_include", []),
            keywords_exclude=current_prefs.get("keywords_exclude") if not overwrite_custom else detected.get("keywords_exclude", []),
            min_salary=current_prefs.get("min_salary"),
            preferred_sources=detected.get("preferred_sources", ["linkedin", "remotive", "jobicy"]),
        )
    except Exception as exc:
        logging.getLogger("jobfinder").warning(f"Error syncing search preferences: {exc}")


@app.get("/api/cv")
def get_cv():
    cv = database.get_cv_profile()
    return {"cv": cv}


@app.put("/api/cv")
def update_cv(payload: CVProfileUpdate):
    saved = database.save_cv_profile(
        full_name=payload.full_name,
        headline=payload.headline,
        raw_text=payload.raw_text,
        filename=payload.filename or "",
    )
    _sync_preferences_from_cv(saved, overwrite_custom=False)
    return {"cv": saved}


@app.post("/api/cv/upload")
async def upload_cv(file: UploadFile = File(...)):
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="El archivo está vacío.")
    if len(content) > 15 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="El archivo supera el límite de 15 MB.")

    try:
        extracted = document_io.extract_text_from_upload(file.filename or "cv.txt", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"No se pudo leer el archivo: {exc}")

    if len(extracted.strip()) < 20:
        raise HTTPException(
            status_code=400,
            detail="No se pudo extraer texto legible del archivo (si es un PDF escaneado como imagen, copia y pega el texto directamente).",
        )

    first_line = next((ln.strip() for ln in extracted.splitlines() if ln.strip()), "")
    full_name = first_line[:80] if len(first_line) <= 70 else ""

    temp_cv = {
        "full_name": full_name,
        "headline": "",
        "raw_text": extracted,
        "filename": file.filename or "cv",
    }
    facts = database.list_knowledge_facts()
    detected = job_hunter.auto_detect_preferences_from_cv(temp_cv, facts)
    headline = " / ".join(detected.get("target_roles", [])[:2])

    saved = database.save_cv_profile(
        full_name=full_name,
        headline=headline,
        raw_text=extracted,
        filename=file.filename or "cv",
    )
    _sync_preferences_from_cv(saved, overwrite_custom=True)
    return {"cv": saved, "chars_extracted": len(extracted)}


# --- Persistent Knowledge Base ---

@app.get("/api/knowledge")
def list_knowledge(
    status: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
):
    facts = database.list_knowledge_facts(status=status, query=q)
    return {"facts": facts}


@app.post("/api/knowledge")
def add_knowledge(payload: KnowledgeFactCreate):
    fact = database.upsert_knowledge_fact(
        topic=payload.topic,
        category=payload.category,
        status=payload.status,
        details=payload.details,
        source=payload.source or "manual",
    )
    return {"fact": fact}


@app.put("/api/knowledge/{fact_id}")
def edit_knowledge(fact_id: int, payload: KnowledgeFactUpdate):
    updated = database.update_knowledge_fact(fact_id, payload.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Hecho no encontrado.")
    return {"fact": updated}


@app.delete("/api/knowledge/{fact_id}")
def remove_knowledge(fact_id: int):
    deleted = database.delete_knowledge_fact(fact_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Hecho no encontrado.")
    return {"deleted": True}


# --- Job Offer Scraping & Analysis ---

@app.post("/api/jobs/fetch-url")
async def fetch_job_url(payload: FetchUrlRequest):
    result = await scraper.fetch_job_from_url(payload.url)
    return result


@app.post("/api/jobs/analyze")
async def analyze_job(payload: AnalyzeJobRequest):
    cv = database.get_cv_profile()
    if not cv or len((cv.get("raw_text") or "").strip()) < 20:
        raise HTTPException(
            status_code=400,
            detail="Primero debes subir o guardar tu CV base en la pestaña 'Mi CV Base'.",
        )

    description = (payload.job_description or "").strip()
    title = (payload.job_title or "").strip()
    company = (payload.company or "").strip()
    source_url = (payload.source_url or "").strip()

    if not description and source_url:
        scraped = await scraper.fetch_job_from_url(source_url)
        if not scraped.get("success"):
            raise HTTPException(status_code=422, detail=scraped.get("error", "No se pudo leer la URL."))
        description = scraped.get("description", "").strip()
        title = title or scraped.get("title", "")
        company = company or scraped.get("company", "")

    if len(description) < 30:
        raise HTTPException(
            status_code=400,
            detail="Introduce una URL válida o pega la descripción completa de la oferta de empleo.",
        )

    settings = database.get_settings(mask_key=False)
    facts = database.list_knowledge_facts()

    try:
        analysis, provider_used = await ai_engine.analyze_job_offer(
            settings=settings,
            cv_profile=cv,
            facts=facts,
            job_description=description,
            job_title=title,
            company=company,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error al analizar la oferta con IA: {exc}")

    record = database.create_job_analysis(
        job_title=title or analysis.get("job_title", "Oferta de empleo"),
        company=company or analysis.get("company", ""),
        source_url=source_url,
        raw_description=description,
        target_language=payload.target_language or "auto",
        analysis=analysis,
        provider_used=provider_used,
    )
    return {"job": record}


@app.get("/api/jobs")
def list_jobs():
    return {"jobs": database.list_job_analyses()}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: int):
    job = database.get_job_analysis(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Análisis no encontrado.")
    return {"job": job}


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: int):
    deleted = database.delete_job_analysis(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Análisis no encontrado.")
    return {"deleted": True}


@app.post("/api/jobs/{job_id}/answers")
async def submit_answers_and_adapt(job_id: int, payload: SubmitAnswersRequest):
    job = database.get_job_analysis(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Análisis no encontrado.")

    cv = database.get_cv_profile()
    if not cv:
        raise HTTPException(status_code=400, detail="Falta el CV base.")

    saved_facts = []
    answer_records = []
    for item in payload.answers:
        rec = item.model_dump()
        answer_records.append(rec)
        if item.save_to_knowledge:
            fact = database.upsert_knowledge_fact(
                topic=item.topic,
                category=item.category,
                status=item.status,
                details=item.details,
                source="qa_session",
            )
            saved_facts.append(fact)

    settings = database.get_settings(mask_key=False)
    all_facts = database.list_knowledge_facts()

    try:
        # Re-run analysis with the freshly learned knowledge so scores & matched points update!
        updated_analysis, provider_used = await ai_engine.analyze_job_offer(
            settings=settings,
            cv_profile=cv,
            facts=all_facts,
            job_description=job["raw_description"],
            job_title=job["job_title"],
            company=job["company"],
        )
        adapted, provider_used = await ai_engine.adapt_cv_honestly(
            settings=settings,
            cv_profile=cv,
            facts=all_facts,
            job_title=job["job_title"],
            company=job["company"],
            job_description=job["raw_description"],
            analysis=updated_analysis,
            target_language=payload.target_language or job.get("target_language") or "auto",
            extra_instructions=payload.extra_instructions,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error al adaptar el CV con IA: {exc}")

    updated_job = database.update_job_analysis(
        job_id,
        analysis=updated_analysis,
        answers=answer_records,
        adapted_cv_markdown=adapted.get("adapted_cv_markdown", ""),
        adapted_cv_structured=adapted.get("adapted_cv_structured", {}),
        changelog=adapted.get("changes_made", []),
        keywords_integrated=adapted.get("keywords_integrated", []),
        honesty_notes=adapted.get("honesty_notes", []),
        provider_used=provider_used,
    )
    return {
        "job": updated_job,
        "saved_facts_count": len(saved_facts),
        "saved_facts": saved_facts,
    }


@app.post("/api/jobs/{job_id}/adapt")
async def adapt_job_cv(job_id: int, payload: AdaptCVRequest):
    job = database.get_job_analysis(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Análisis no encontrado.")

    cv = database.get_cv_profile()
    if not cv:
        raise HTTPException(status_code=400, detail="Falta el CV base.")

    settings = database.get_settings(mask_key=False)
    all_facts = database.list_knowledge_facts()

    try:
        adapted, provider_used = await ai_engine.adapt_cv_honestly(
            settings=settings,
            cv_profile=cv,
            facts=all_facts,
            job_title=job["job_title"],
            company=job["company"],
            job_description=job["raw_description"],
            analysis=job["analysis"],
            target_language=payload.target_language or job.get("target_language") or "auto",
            extra_instructions=payload.extra_instructions,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error al adaptar el CV con IA: {exc}")

    updated_job = database.update_job_analysis(
        job_id,
        adapted_cv_markdown=adapted.get("adapted_cv_markdown", ""),
        adapted_cv_structured=adapted.get("adapted_cv_structured", {}),
        changelog=adapted.get("changes_made", []),
        keywords_integrated=adapted.get("keywords_integrated", []),
        honesty_notes=adapted.get("honesty_notes", []),
        provider_used=provider_used,
    )
    return {"job": updated_job}


@app.put("/api/jobs/{job_id}/cv")
def save_manual_adapted_cv(job_id: int, payload: UpdateAdaptedCVRequest):
    updated = database.update_job_analysis(job_id, adapted_cv_markdown=payload.adapted_cv_markdown)
    if not updated:
        raise HTTPException(status_code=404, detail="Análisis no encontrado.")
    return {"job": updated}


# --- Exports (ATS PDF, DOCX, Markdown) ---

@app.get("/api/jobs/{job_id}/export/{fmt}")
def export_adapted_cv(job_id: int, fmt: str):
    job = database.get_job_analysis(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Análisis no encontrado.")
    md = (job.get("adapted_cv_markdown") or "").strip()
    if not md:
        raise HTTPException(status_code=400, detail="Todavía no se ha generado un CV adaptado para esta oferta.")

    base_name = f"CV_{job.get('job_title', 'Adaptado')}_{job.get('company', '')}"
    fmt = fmt.lower()

    if fmt == "pdf":
        data = document_io.generate_ats_pdf(md, title=job.get("job_title", "Curriculum Vitae"))
        filename = _safe_filename(base_name, "pdf")
        return Response(
            content=data,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if fmt == "docx":
        data = document_io.generate_ats_docx(md, title=job.get("job_title", "Curriculum Vitae"))
        filename = _safe_filename(base_name, "docx")
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    if fmt in ("md", "markdown"):
        filename = _safe_filename(base_name, "md")
        return Response(
            content=md.encode("utf-8"),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    raise HTTPException(status_code=400, detail="Formato no válido. Usa pdf, docx o md.")


# --- Settings ---

@app.get("/api/settings")
def get_settings():
    return {"settings": database.get_settings(mask_key=True)}


@app.put("/api/settings")
def update_settings(payload: SettingsUpdate):
    saved = database.save_settings(
        provider=payload.provider,
        api_key=payload.api_key,
        model=payload.model,
        base_url=payload.base_url,
        default_language=payload.default_language,
        tone=payload.tone,
    )
    return {"settings": saved}


@app.post("/api/settings/test")
async def test_settings(payload: TestAIRequest):
    current = database.get_settings(mask_key=False)
    test_cfg = {
        "provider": payload.provider or current["provider"],
        "api_key": payload.api_key if (payload.api_key is not None and payload.api_key != "") else current["api_key"],
        "model": payload.model if payload.model is not None else current["model"],
        "base_url": payload.base_url if payload.base_url is not None else current["base_url"],
    }
    return await ai_engine.test_ai_connection(test_cfg)


# --- Job Hunter & Discovery Endpoints ---

@app.get("/api/hunter/preferences")
def get_hunter_preferences():
    return {"preferences": database.get_search_preferences()}


@app.put("/api/hunter/preferences")
def update_hunter_preferences(payload: SearchPreferencesUpdate):
    saved = database.save_search_preferences(
        target_roles=payload.target_roles,
        location=payload.location,
        country=payload.country,
        modality=payload.modality,
        experience_level=payload.experience_level,
        keywords_include=payload.keywords_include,
        keywords_exclude=payload.keywords_exclude,
        min_salary=payload.min_salary,
        preferred_sources=payload.preferred_sources,
    )
    return {"preferences": saved}


@app.post("/api/hunter/preferences/auto-detect")
def auto_detect_hunter_preferences():
    cv = database.get_cv_profile()
    if not cv or len((cv.get("raw_text") or "").strip()) < 20:
        raise HTTPException(
            status_code=400,
            detail="Primero guarda tu CV Base en la pestaña 'Mi CV Base' para autodetectar tus preferencias.",
        )
    facts = database.list_knowledge_facts()
    detected = job_hunter.auto_detect_preferences_from_cv(cv, facts)
    return {"preferences": detected}


@app.post("/api/hunter/search")
async def run_job_search(payload: JobSearchQuery):
    cv = database.get_cv_profile()
    if not cv or len((cv.get("raw_text") or "").strip()) < 20:
        raise HTTPException(
            status_code=400,
            detail="Primero debes subir o guardar tu CV Base para poder buscar y puntuar ofertas compatibles.",
        )
    facts = database.list_knowledge_facts()
    prefs = database.get_search_preferences()

    try:
        results = await job_hunter.search_and_score_jobs(
            cv_profile=cv,
            facts=facts,
            search_prefs=prefs,
            query_override=payload.query,
            location_override=payload.location,
            country_override=payload.country,
            modality_override=payload.modality,
            from_cv=payload.from_cv,
            limit=payload.limit or 45,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Error durante la búsqueda de ofertas: {exc}")

    return {"jobs": results, "count": len(results)}


@app.get("/api/hunter/jobs")
def get_discovered_jobs(
    status: Optional[str] = Query(default=None),
    min_score: int = Query(default=0),
    modality: Optional[str] = Query(default=None),
    country: Optional[str] = Query(default=None),
    q: Optional[str] = Query(default=None),
    limit: int = Query(default=60),
):
    jobs = database.list_discovered_jobs(
        status=status,
        min_score=min_score,
        modality=modality,
        country=country,
        query=q,
        limit=limit,
    )
    return {"jobs": jobs, "count": len(jobs)}


@app.patch("/api/hunter/jobs/{job_id}/status")
def patch_discovered_job_status(job_id: int, payload: DiscoveredJobStatusUpdate):
    updated = database.update_discovered_job_status(job_id, payload.status)
    if not updated:
        raise HTTPException(status_code=404, detail="Oferta no encontrada.")
    return {"job": updated}


@app.delete("/api/hunter/jobs/{job_id}")
def delete_discovered_job(job_id: int):
    deleted = database.delete_discovered_job(job_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Oferta no encontrada.")
    return {"deleted": True}


@app.post("/api/hunter/jobs/{job_id}/convert-to-analysis")
async def convert_discovered_job_to_analysis(job_id: int, payload: ConvertToAnalysisRequest):
    disc_job = database.get_discovered_job(job_id)
    if not disc_job:
        raise HTTPException(status_code=404, detail="Oferta descubierta no encontrada.")

    cv = database.get_cv_profile()
    if not cv or len((cv.get("raw_text") or "").strip()) < 20:
        raise HTTPException(status_code=400, detail="Falta tu CV base para analizar y adaptar la oferta.")

    settings = database.get_settings(mask_key=False)
    facts = database.list_knowledge_facts()

    job_title = disc_job.get("title") or "Oferta de empleo"
    company = disc_job.get("company") or ""
    description = disc_job.get("raw_description") or disc_job.get("description_snippet") or ""

    try:
        analysis, provider_used = await ai_engine.analyze_job_offer(
            settings=settings,
            cv_profile=cv,
            facts=facts,
            job_description=description,
            job_title=job_title,
            company=company,
        )

        job_analysis_record = database.create_job_analysis(
            job_title=job_title,
            company=company,
            source_url=disc_job.get("source_url") or "",
            raw_description=description,
            target_language=payload.target_language or "auto",
            analysis=analysis,
            provider_used=provider_used,
        )

        # Directly adapt CV honestly
        adapted, provider_used = await ai_engine.adapt_cv_honestly(
            settings=settings,
            cv_profile=cv,
            facts=facts,
            job_title=job_title,
            company=company,
            job_description=description,
            analysis=analysis,
            target_language=payload.target_language or "auto",
            extra_instructions=payload.extra_instructions or "",
        )

        updated_analysis = database.update_job_analysis(
            job_analysis_record["id"],
            adapted_cv_markdown=adapted.get("adapted_cv_markdown", ""),
            adapted_cv_structured=adapted.get("adapted_cv_structured", {}),
            changelog=adapted.get("changes_made", []),
            keywords_integrated=adapted.get("keywords_integrated", []),
            honesty_notes=adapted.get("honesty_notes", []),
            provider_used=provider_used,
        )

        # Mark discovered job as applied
        database.update_discovered_job_status(job_id, "applied")

    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Error al analizar y adaptar el CV: {exc}")

    return {
        "job_analysis": updated_analysis,
        "discovered_job": database.get_discovered_job(job_id),
    }


# --- Static Frontend ---

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def serve_index():
    return FileResponse(str(STATIC_DIR / "index.html"))
