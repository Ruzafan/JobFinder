import json
import re
import unicodedata
from typing import Any

import httpx


DEFAULT_MODELS = {
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-latest",
    "ollama": "llama3.1",
    "local": "motor-local-v1",
}


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch)).lower()


def _extract_json_block(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    # Direct parse
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    # Fenced ```json ... ```
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if match:
        try:
            parsed = json.loads(match.group(1))
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    # First balanced-ish brace span
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    raise ValueError("La respuesta de la IA no devolvió un JSON válido. Inténtalo de nuevo.")


def _format_knowledge_for_prompt(facts: list[dict[str, Any]]) -> str:
    if not facts:
        return "Ningún hecho adicional registrado todavía."

    confirmed = [f for f in facts if f.get("status") == "confirmed"]
    partial = [f for f in facts if f.get("status") == "partial"]
    denied = [f for f in facts if f.get("status") == "denied"]

    sections: list[str] = []
    if confirmed:
        lines = [
            f"- [{f.get('category', 'General')}] {f['topic']}" + (f": {f['details']}" if f.get("details") else "")
            for f in confirmed
        ]
        sections.append("CONFIRMADO POR EL CANDIDATO (SÍ tiene experiencia/conocimiento):\n" + "\n".join(lines))

    if partial:
        lines = [
            f"- [{f.get('category', 'General')}] {f['topic']} (Nivel básico/parcial)"
            + (f": {f['details']}" if f.get("details") else "")
            for f in partial
        ]
        sections.append("CONOCIMIENTO PARCIAL / BÁSICO (mencionar solo con honestidad, sin exagerar):\n" + "\n".join(lines))

    if denied:
        lines = [
            f"- [{f.get('category', 'General')}] {f['topic']}" + (f" ({f['details']})" if f.get("details") else "")
            for f in denied
        ]
        sections.append("DESCARTADO POR EL CANDIDATO (NO lo tiene; NO preguntar de nuevo y NUNCA incluirlo en el CV):\n" + "\n".join(lines))

    return "\n\n".join(sections)


# =====================================================================
# External LLM Provider Clients (Gemini, OpenAI, Anthropic, Ollama)
# =====================================================================

async def _call_llm(
    settings: dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    expect_json: bool = True,
) -> str:
    provider = (settings.get("provider") or "local").strip().lower()
    api_key = (settings.get("api_key") or "").strip()
    model = (settings.get("model") or DEFAULT_MODELS.get(provider, "")).strip()
    base_url = (settings.get("base_url") or "").strip()

    timeout = httpx.Timeout(95.0, connect=15.0)

    if provider == "gemini":
        if not api_key:
            raise RuntimeError("Falta la API Key de Gemini en Configuración.")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        gen_cfg: dict[str, Any] = {"temperature": 0.25}
        if expect_json:
            gen_cfg["responseMimeType"] = "application/json"
        payload = {
            "system_instruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
            "generationConfig": gen_cfg,
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"Error de Gemini API (HTTP {resp.status_code}): {resp.text[:300]}")
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            raise RuntimeError("Gemini no devolvió contenido en la respuesta.")
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(p.get("text", "") for p in parts)

    if provider in ("openai", "ollama"):
        if provider == "openai" and not api_key:
            raise RuntimeError("Falta la API Key de OpenAI en Configuración.")
        endpoint_base = (
            base_url.rstrip("/")
            if base_url
            else ("https://api.openai.com/v1" if provider == "openai" else "http://host.docker.internal:11434/v1")
        )
        url = f"{endpoint_base}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        payload = {
            "model": model or DEFAULT_MODELS[provider],
            "temperature": 0.25,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        if expect_json and provider == "openai":
            payload["response_format"] = {"type": "json_object"}
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"Error de {provider.upper()} (HTTP {resp.status_code}): {resp.text[:300]}")
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    if provider == "anthropic":
        if not api_key:
            raise RuntimeError("Falta la API Key de Anthropic en Configuración.")
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": model or DEFAULT_MODELS["anthropic"],
            "max_tokens": 4096,
            "temperature": 0.25,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 400:
            raise RuntimeError(f"Error de Anthropic API (HTTP {resp.status_code}): {resp.text[:300]}")
        data = resp.json()
        blocks = data.get("content") or []
        return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")

    raise RuntimeError(f"Proveedor de IA no soportado: {provider}")


async def test_ai_connection(settings: dict[str, Any]) -> dict[str, Any]:
    provider = (settings.get("provider") or "local").strip().lower()
    if provider == "local":
        return {
            "ok": True,
            "provider": "local",
            "message": "Modo Local Inteligente activo (funciona 100% en tu máquina sin API key). Añade Gemini, OpenAI, Anthropic u Ollama cuando quieras redacción avanzada con LLM.",
        }
    try:
        raw = await _call_llm(
            settings,
            system_prompt="Responde únicamente con JSON válido: {\"ok\": true, \"reply\": \"Conexión verificada\"}",
            user_prompt="Confirma que estás disponible.",
            expect_json=True,
        )
        _extract_json_block(raw)
        return {
            "ok": True,
            "provider": provider,
            "message": f"Conexión verificada correctamente con {provider.upper()} ({settings.get('model') or DEFAULT_MODELS.get(provider)}).",
        }
    except Exception as exc:
        return {
            "ok": False,
            "provider": provider,
            "message": str(exc),
        }


# =====================================================================
# Smart Local Engine (Zero-API-Key Deterministic Fallback)
# =====================================================================

SKILL_CATALOG: list[tuple[str, str, list[str]]] = [
    # (Canonical Name, Category, Synonyms/Aliases)
    ("Python", "Habilidad técnica", ["python", "py"]),
    ("JavaScript", "Habilidad técnica", ["javascript", "js", "ecmascript"]),
    ("TypeScript", "Habilidad técnica", ["typescript", "ts"]),
    ("Java", "Habilidad técnica", ["java", "spring", "spring boot", "springboot"]),
    ("C#", "Habilidad técnica", ["c#", ".net", "dotnet", "asp.net"]),
    ("C++", "Habilidad técnica", ["c++", "cpp"]),
    ("Go", "Habilidad técnica", ["golang", " go "]),
    ("Rust", "Habilidad técnica", ["rust"]),
    ("PHP", "Habilidad técnica", ["php", "laravel", "symfony", "wordpress"]),
    ("SQL", "Habilidad técnica", ["sql", "postgresql", "postgres", "mysql", "mariadb", "sqlite", "sql server", "oracle"]),
    ("NoSQL / MongoDB", "Habilidad técnica", ["nosql", "mongodb", "mongo", "redis", "dynamodb", "elasticsearch"]),
    ("React", "Habilidad técnica", ["react", "reactjs", "react.js", "next.js", "nextjs"]),
    ("Angular", "Habilidad técnica", ["angular"]),
    ("Vue.js", "Habilidad técnica", ["vue", "vuejs", "vue.js", "nuxt"]),
    ("HTML / CSS", "Habilidad técnica", ["html", "html5", "css", "css3", "tailwind", "sass", "scss"]),
    ("Node.js", "Habilidad técnica", ["node.js", "nodejs", "express", "nestjs"]),
    ("FastAPI / Django / Flask", "Habilidad técnica", ["fastapi", "django", "flask"]),
    ("APIs REST / GraphQL", "Habilidad técnica", ["api rest", "rest api", "restful", "apis", "graphql", "microservicios", "microservices"]),
    ("Docker", "Herramienta", ["docker", "docker compose", "contenedores", "containers", "containerization"]),
    ("Kubernetes", "Herramienta", ["kubernetes", "k8s", "helm", "openshift"]),
    ("AWS", "Herramienta", ["aws", "amazon web services", "ec2", "s3", "lambda", "ecs"]),
    ("Azure", "Herramienta", ["azure", "microsoft azure"]),
    ("Google Cloud (GCP)", "Herramienta", ["gcp", "google cloud"]),
    ("CI/CD", "Herramienta", ["ci/cd", "cicd", "github actions", "gitlab ci", "jenkins", "integracion continua", "despliegue continuo"]),
    ("Git", "Herramienta", ["git", "github", "gitlab", "bitbucket", "control de versiones"]),
    ("Linux", "Herramienta", ["linux", "ubuntu", "debian", "bash", "shell scripting", "unix"]),
    ("Terraform / IaC", "Herramienta", ["terraform", "ansible", "infraestructura como codigo", "infrastructure as code"]),
    ("Testing / QA", "Habilidad técnica", ["testing", "pruebas unitarias", "unit testing", "pytest", "jest", "cypress", "playwright", "selenium", "tdd", "qa"]),
    ("Ciberseguridad", "Habilidad técnica", ["ciberseguridad", "cybersecurity", "seguridad informatica", "owasp", "iso 27001", "pentesting"]),
    ("Machine Learning / IA", "Habilidad técnica", ["machine learning", "inteligencia artificial", "deep learning", "nlp", "llm", "llms", "ia generativa", "pytorch", "tensorflow", "scikit-learn"]),
    ("Data Analysis / BI", "Habilidad técnica", ["power bi", "powerbi", "tableau", "looker", "pandas", "excel avanzado", "analisis de datos", "data analysis", "etl", "spark"]),
    ("SEO / Marketing Digital", "Habilidad técnica", ["seo", "sem", "google analytics", "ga4", "google ads", "meta ads", "marketing digital", "crm", "hubspot", "salesforce"]),
    ("Diseño UX/UI", "Habilidad técnica", ["figma", "ux", "ui", "ux/ui", "diseno de producto", "prototipado", "adobe xd"]),
    ("Metodologías Ágiles (Scrum/Kanban)", "Experiencia", ["scrum", "kanban", "agile", "agil", "agiles", "jira", "confluence", "sprints"]),
    ("Gestión de Proyectos", "Experiencia", ["gestion de proyectos", "project management", "pmp", "planificacion", "stakeholders", "roadmap"]),
    ("Liderazgo / Gestión de Equipos", "Soft skill", ["liderazgo", "gestion de equipos", "team lead", "tech lead", "mentoring", "mentoria", "coordinacion de equipos"]),
    ("Facturación y Conciliación Bancaria", "Habilidad técnica", ["facturacion", "conciliacion bancaria", "cobros y pagos", "gestion de cobros", "facturas", "cuentas por cobrar", "cuentas por pagar", "emision de facturas"]),
    ("Gestión Documental y Archivo", "Habilidad técnica", ["gestion documental", "control documental", "archivo", "expedientes", "archivo digital", "trazabilidad documental", "custodia documental", "registro documental"]),
    ("Sistemas ERP / CRM", "Herramienta", ["erp", "crm", "sap", "navision", "sage", "salesforce", "hubspot", "odoo", "zoho", "a3", "factusol", "contasol"]),
    ("Trámites Telemáticos y Certificados Digitales", "Habilidad técnica", ["certificados digitales", "tramitacion telematica", "tramites telematicos", "sede electronica", "seguridad social", "aeat", "hacienda", "notaria", "presentacion de impuestos"]),
    ("Secretaría y Gestión de Agendas", "Experiencia", ["secretaria", "recepcion", "gestion de agendas", "secretaria virtual", "recepcionista", "asistente de direccion", "organizacion de viajes", "asistente de administracion"]),
    ("Contabilidad y Fiscalidad", "Habilidad técnica", ["contabilidad", "asientos contables", "impuestos", "iva", "irpf", "balances", "cuentas anuales", "plan general contable", "asstax", "fiscal"]),
    ("Recursos Humanos y Nóminas", "Experiencia", ["nominas", "rrhh", "recursos humanos", "altas y bajas", "contratos laborales", "seguridad social", "seleccion de personal", "contratos legales"]),
    ("Microsoft Office / Ofimática", "Herramienta", ["office", "microsoft office", "word", "excel", "powerpoint", "outlook", "google workspace", "google sheets", "hojas de calculo", "ofimatica"]),
    ("Atención Telefónica y Multicanal", "Experiencia", ["atencion telefonica", "recepcion de llamadas", "centralita", "atencion presencial", "gestion de correo", "correspondencia", "atencion al cliente"]),
    ("Ventas / Desarrollo de Negocio", "Experiencia", ["ventas", "b2b", "b2c", "prospeccion", "negociacion", "account manager", "comercial"]),
    ("Inglés", "Idioma", ["ingles", "english", "b2", "c1", "c2", "fluent english", "ingles fluido", "ingles tecnico"]),
    ("Español", "Idioma", ["espanol", "castellano", "spanish"]),
    ("Catalán", "Idioma", ["catalan", "catala"]),
    ("Francés", "Idioma", ["frances", "french"]),
    ("Alemán", "Idioma", ["aleman", "german"]),
    ("Trabajo en equipo y comunicación", "Soft skill", ["trabajo en equipo", "comunicacion", "teamwork", "communication", "colaboracion"]),
    ("Resolución de problemas", "Soft skill", ["resolucion de problemas", "problem solving", "pensamiento analitico", "proactividad"]),
]


def _contains_alias(norm_text: str, alias: str) -> bool:
    a = _strip_accents(alias).strip()
    if not a:
        return False
    # Special handling for short or symbolic tokens like c#, c++, .net, js, ts, go
    if len(a) <= 2 or any(ch in a for ch in "+#."):
        pattern = r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])"
    else:
        pattern = r"\b" + re.escape(a) + r"\b"
    return bool(re.search(pattern, norm_text))


def _find_evidence_snippet(raw_text: str, aliases: list[str]) -> str:
    for line in raw_text.splitlines():
        clean = line.strip()
        if not clean:
            continue
        norm_line = _strip_accents(clean)
        for alias in aliases:
            if _contains_alias(norm_line, alias):
                return clean[:160]
    return ""


def _detect_language(text: str) -> str:
    norm = _strip_accents(text)
    es_hits = sum(1 for w in ["experiencia", "requisitos", "buscamos", "puesto", "conocimientos", "empresa", "ofrecemos", "habilidades"] if w in norm)
    en_hits = sum(1 for w in ["experience", "requirements", "looking for", "responsibilities", "skills", "qualifications", "we offer", "role"] if w in norm)
    return "en" if en_hits > es_hits + 1 else "es"


def _guess_job_title(description: str, fallback: str = "") -> str:
    if fallback.strip():
        return fallback.strip()
    for line in description.splitlines():
        s = line.strip().strip("#*-• ")
        if 4 <= len(s) <= 90 and not s.lower().startswith(("http", "ubicación", "location", "requisitos", "descripción")):
            return s
    return "Oferta de empleo"


def quick_score_job(
    job_offer: dict[str, Any],
    cv_profile: dict[str, Any],
    facts: list[dict[str, Any]],
) -> dict[str, Any]:
    cv_text = cv_profile.get("raw_text", "")
    headline = cv_profile.get("headline", "")
    norm_cv = _strip_accents(f"{headline} {cv_text}")

    job_title = job_offer.get("title", "")
    job_desc = f"{job_offer.get('title', '')} {job_offer.get('description_snippet', '')} {job_offer.get('raw_description', '')}"
    norm_job = _strip_accents(job_desc)

    # Index facts
    confirmed_set = {_strip_accents(f["topic"]) for f in facts if f.get("status") == "confirmed"}
    partial_set = {_strip_accents(f["topic"]) for f in facts if f.get("status") == "partial"}
    denied_set = {_strip_accents(f["topic"]) for f in facts if f.get("status") == "denied"}

    matched_skills: list[str] = []
    missing_skills: list[str] = []
    denied_hits: list[str] = []

    for canonical, _, aliases in SKILL_CATALOG:
        has_in_job = any(_contains_alias(norm_job, a) for a in aliases)
        if not has_in_job:
            continue

        c_norm = _strip_accents(canonical)
        if c_norm in denied_set:
            denied_hits.append(canonical)
            continue

        has_in_cv = any(_contains_alias(norm_cv, a) for a in aliases)
        if has_in_cv or c_norm in confirmed_set:
            matched_skills.append(canonical)
        elif c_norm in partial_set:
            matched_skills.append(f"{canonical} (básico)")
        else:
            missing_skills.append(canonical)

    total_reqs = len(matched_skills) + len(missing_skills) + len(denied_hits)
    if total_reqs == 0:
        base_score = 60
    else:
        # Score ratio
        ratio = (len(matched_skills) * 1.0) / (len(matched_skills) + len(missing_skills) * 0.9 + len(denied_hits) * 2.0)
        base_score = int(round(ratio * 100))

    # Bonus if role matches headline
    norm_headline = _strip_accents(headline)
    norm_title = _strip_accents(job_title)
    if any(tok in norm_title for tok in norm_headline.split() if len(tok) >= 4):
        base_score += 8

    # Penalty if denied skills were explicitly hit
    if denied_hits:
        base_score = max(10, base_score - (len(denied_hits) * 20))

    final_score = max(15, min(97, base_score))

    return {
        "score": final_score,
        "matched_skills": list(dict.fromkeys(matched_skills)),
        "missing_skills": list(dict.fromkeys(missing_skills)),
        "denied_skills": list(dict.fromkeys(denied_hits)),
    }


def _local_analyze_job(
    cv_text: str,
    facts: list[dict[str, Any]],
    job_description: str,
    job_title: str = "",
    company: str = "",
) -> dict[str, Any]:
    norm_cv = _strip_accents(cv_text)
    norm_job = _strip_accents(job_description)

    # Index persistent facts by normalized topic & text
    fact_list = []
    for f in facts:
        fact_list.append({
            "raw": f,
            "norm_topic": _strip_accents(f.get("topic", "")),
            "norm_all": _strip_accents(f"{f.get('topic', '')} {f.get('details', '')}"),
            "status": f.get("status", "confirmed"),
        })

    matched_reqs: list[dict[str, Any]] = []
    unclear_reqs: list[dict[str, Any]] = []
    missing_reqs: list[dict[str, Any]] = []
    kw_matched: list[str] = []
    kw_to_highlight: list[str] = []
    kw_missing: list[str] = []

    seen_topics: set[str] = set()

    for canonical, category, aliases in SKILL_CATALOG:
        matched_aliases_in_job = [a for a in aliases if _contains_alias(norm_job, a)]
        if not matched_aliases_in_job:
            continue

        seen_topics.add(_strip_accents(canonical))
        display_kw = canonical

        # 1) Check persistent knowledge base first (takes precedence for confirmed/partial/denied)
        kb_match = None
        for fl in fact_list:
            if (
                fl["norm_topic"] == _strip_accents(canonical)
                or any(_contains_alias(fl["norm_all"], a) for a in aliases)
            ):
                kb_match = fl
                break

        cv_aliases_found = [a for a in aliases if _contains_alias(norm_cv, a)]

        if cv_aliases_found:
            snippet = _find_evidence_snippet(cv_text, cv_aliases_found)
            matched_reqs.append({
                "requirement": canonical,
                "category": category,
                "evidence": f"Encontrado en tu CV base: «{snippet}»" if snippet else "Mencionado en tu CV base.",
                "keywords_matched": list(dict.fromkeys([display_kw] + matched_aliases_in_job[:2])),
            })
            kw_matched.append(display_kw)
            kw_to_highlight.append(display_kw)
        elif kb_match:
            st = kb_match["status"]
            details = kb_match["raw"].get("details", "")
            if st == "confirmed":
                matched_reqs.append({
                    "requirement": canonical,
                    "category": category,
                    "evidence": f"Confirmado en tu Base de Conocimiento: {details or kb_match['raw']['topic']}",
                    "keywords_matched": [display_kw],
                })
                kw_matched.append(display_kw)
                kw_to_highlight.append(display_kw)
            elif st == "partial":
                matched_reqs.append({
                    "requirement": f"{canonical} (nivel básico/parcial)",
                    "category": category,
                    "evidence": f"Registrado como parcial en tu Base de Conocimiento: {details or 'Conocimiento inicial'}",
                    "keywords_matched": [display_kw],
                })
                kw_to_highlight.append(f"{display_kw} (básico)")
            else:
                # Explicitly denied before — NEVER ask again!
                missing_reqs.append({
                    "requirement": canonical,
                    "importance": "Requerido/valorable en la oferta",
                    "honest_advice": f"Marcaste previamente que no cuentas con {canonical}. No se incluirá en el CV para mantener total honestidad.",
                })
                kw_missing.append(display_kw)
        else:
            # Not in CV and not yet confirmed/denied in KB -> Ask the user!
            qid = f"q_{re.sub(r'[^a-z0-9]+', '_', _strip_accents(canonical)).strip('_')}"
            unclear_reqs.append({
                "id": qid,
                "topic": canonical,
                "suggested_category": category,
                "requirement": f"{canonical} ({', '.join(matched_aliases_in_job[:3])})",
                "why_unclear": f"La oferta menciona {', '.join(matched_aliases_in_job[:3])}, pero no aparece explícitamente en tu CV base ni en tu memoria.",
                "question": f"¿Tienes experiencia o conocimientos reales con {canonical}? Si es así, cuéntame brevemente en qué proyectos o nivel lo has usado.",
            })
            kw_missing.append(display_kw)

    # Also inspect explicit bullet requirements for years of experience or degrees not in catalog
    year_match = re.search(r"(\d+)\+?\s*(?:años|anos|years)\s+(?:de\s+)?(?:experiencia|experience)", norm_job)
    if year_match:
        req_years = year_match.group(1)
        year_topic = f"Experiencia mínima de {req_years} años en el rol"
        already_in_kb = any(_strip_accents(year_topic) in fl["norm_all"] or "anos de experiencia" in fl["norm_all"] for fl in fact_list)
        if not already_in_kb and len(unclear_reqs) < 8:
            unclear_reqs.append({
                "id": f"q_years_{req_years}",
                "topic": year_topic,
                "suggested_category": "Experiencia",
                "requirement": f"Al menos {req_years} años de experiencia relevante",
                "why_unclear": "Conviene confirmar si tu experiencia acumulada (incluyendo proyectos propios o prácticas) alcanza este rango.",
                "question": f"La oferta pide alrededor de {req_years} años de experiencia. ¿Consideras que cumples este punto (o cuántos años reales puedes acreditar)?",
            })

    # Keep questions manageable (max 8 most relevant)
    unclear_reqs = unclear_reqs[:8]

    total_reqs = len(matched_reqs) + len(unclear_reqs) + len(missing_reqs)
    if total_reqs > 0:
        match_score = int(round((len(matched_reqs) / total_reqs) * 100))
        ats_score = min(98, int(round(((len(matched_reqs) + 0.35 * len(unclear_reqs)) / total_reqs) * 100)))
    else:
        match_score = 50
        ats_score = 55

    detected_lang = _detect_language(job_description)
    summary = (
        f"Análisis local completado: cumples claramente {len(matched_reqs)} requisitos, "
        f"hay {len(unclear_reqs)} puntos por confirmar contigo para enriquecer tu memoria permanente "
        f"y {len(missing_reqs)} requisitos descartados que no se fabricarán."
    )

    return {
        "job_title": _guess_job_title(job_description, job_title),
        "company": company.strip(),
        "offer_language": detected_lang,
        "match_score": match_score,
        "ats_score": ats_score,
        "summary": summary,
        "matched_requirements": matched_reqs,
        "unclear_requirements": unclear_reqs,
        "missing_requirements": missing_reqs,
        "ats_keywords": {
            "matched": list(dict.fromkeys(kw_matched)),
            "to_highlight": list(dict.fromkeys(kw_to_highlight)),
            "missing": list(dict.fromkeys(kw_missing)),
        },
    }


def _local_adapt_cv(
    cv_profile: dict[str, Any],
    facts: list[dict[str, Any]],
    job_title: str,
    company: str,
    analysis: dict[str, Any],
    extra_instructions: str = "",
) -> dict[str, Any]:
    raw_cv = (cv_profile.get("raw_text") or "").strip()
    full_name = (cv_profile.get("full_name") or "").strip()
    headline = (cv_profile.get("headline") or "").strip()

    cv_lines = [ln.rstrip() for ln in raw_cv.splitlines()]
    non_empty = [ln.strip() for ln in cv_lines if ln.strip()]
    if not full_name and non_empty:
        full_name = non_empty[0].lstrip("# ").strip()

    # Extract contact info line if present (email, phone, linkedin)
    contact_lines = []
    for ln in non_empty[:6]:
        if any(tok in ln.lower() for tok in ("@", "linkedin", "github", "+34", "tel", "http", "madrid", "barcelona", "valencia", "sevilla", "españa")):
            if ln != full_name:
                contact_lines.append(ln)

    kw_matched = analysis.get("ats_keywords", {}).get("matched", []) or []
    kw_highlight = analysis.get("ats_keywords", {}).get("to_highlight", []) or []
    confirmed_facts = [f for f in facts if f.get("status") == "confirmed"]
    partial_facts = [f for f in facts if f.get("status") == "partial"]
    denied_facts = [f for f in facts if f.get("status") == "denied"]

    # Build verified skills matched to the job + other confirmed facts
    relevant_confirmed = []
    norm_job_kws = [_strip_accents(k) for k in kw_matched + kw_highlight]
    for f in confirmed_facts:
        nt = _strip_accents(f["topic"])
        if any(nt in k or k in nt for k in norm_job_kws) or f.get("source") == "qa_session":
            relevant_confirmed.append(f)

    role_line = headline or f"Perfil orientado a {job_title}"
    if kw_matched:
        top_kws = ", ".join(kw_matched[:6])
        summary_text = (
            f"Profesional con experiencia acreditada en {top_kws}. "
            f"Trayectoria alineada con los requisitos clave del puesto de {job_title}"
            + (f" en {company}" if company else "")
            + ", enfocada en aportar valor real desde la experiencia demostrable."
        )
    else:
        summary_text = (
            f"Profesional con experiencia verificable orientada al puesto de {job_title}"
            + (f" en {company}" if company else "")
            + "."
        )

    md_parts = [f"# {full_name or 'Curriculum Vitae'}"]
    md_parts.append(f"**{role_line}**")
    if contact_lines:
        md_parts.append(" | ".join(contact_lines[:2]))

    md_parts.append("\n## Perfil Profesional")
    md_parts.append(summary_text)

    if kw_highlight or relevant_confirmed or partial_facts:
        md_parts.append("\n## Competencias Clave Alineadas con la Oferta")
        if kw_matched:
            md_parts.append(f"- **Competencias principales verificadas:** {', '.join(kw_matched)}")
        if relevant_confirmed:
            for f in relevant_confirmed:
                detail = f" — {f['details']}" if f.get("details") else ""
                md_parts.append(f"- **{f['topic']}**{detail}")
        if partial_facts:
            partial_items = [
                f"{f['topic']}" + (f" ({f['details']})" if f.get("details") else " (nivel inicial/básico)")
                for f in partial_facts
                if any(_strip_accents(f["topic"]) in _strip_accents(k) or _strip_accents(k) in _strip_accents(f["topic"]) for k in kw_highlight)
            ]
            if partial_items:
                md_parts.append(f"- **Conocimientos complementarios (nivel básico):** {', '.join(partial_items)}")

    md_parts.append("\n## Experiencia y Trayectoria (Base Verificada)")
    # Include the original CV content cleanly structured (skipping duplicated name line)
    body_lines = []
    skipped_name = False
    for ln in cv_lines:
        stripped = ln.strip()
        if not skipped_name and stripped and stripped.lstrip("# ").strip() == full_name:
            skipped_name = True
            continue
        if stripped in contact_lines:
            continue
        body_lines.append(ln)
    md_parts.append("\n".join(body_lines).strip())

    changes = [
        {
            "section": "Perfil Profesional",
            "change": f"Se redactó un resumen inicial enfocado al puesto de {job_title} destacando únicamente competencias presentes en tu CV base y tu memoria confirmada.",
            "reason": "Aumenta la relevancia en los primeros segundos de lectura (ATS y reclutador).",
        },
        {
            "section": "Competencias Clave",
            "change": f"Se agruparon {len(kw_matched)} palabras clave verificadas de la oferta en un bloque visible en la parte superior.",
            "reason": "Facilita el emparejamiento exacto con filtros ATS/IA sin añadir nada falso.",
        },
    ]
    if relevant_confirmed:
        changes.append({
            "section": "Memoria Persistente",
            "change": f"Se incorporaron {len(relevant_confirmed)} hechos confirmados por ti en tu Base de Conocimiento.",
            "reason": "Completa puntos que no figuraban explícitamente en el CV original.",
        })
    if extra_instructions.strip():
        changes.append({
            "section": "Nota del modo local",
            "change": f"Instrucción registrada: «{extra_instructions.strip()}». Para reescritura profunda por párrafos con tus indicaciones, configura Gemini, OpenAI, Anthropic u Ollama en Configuración.",
            "reason": "El modo local preserva tu texto original íntegro para garantizar 0% de invenciones.",
        })

    keywords_integrated = [
        {"keyword": kw, "justification": "Verificado en tu CV base o en tu Base de Conocimiento confirmada."}
        for kw in kw_matched
    ]

    honesty_notes = []
    for m in analysis.get("missing_requirements", []):
        honesty_notes.append(f"Omitido intencionadamente: {m.get('requirement')} (no confirmado o descartado por el candidato).")
    for d in denied_facts:
        note = f"Respetado descarte permanente: {d['topic']} no se incluyó en el CV."
        if note not in honesty_notes:
            honesty_notes.append(note)
    if not honesty_notes:
        honesty_notes.append("Todos los datos del CV adaptado provienen exclusivamente de tu CV base y tus confirmaciones reales.")

    return {
        "adapted_cv_markdown": "\n\n".join(p for p in md_parts if p).strip(),
        "adapted_cv_structured": {"full_name": full_name, "headline": role_line},
        "changes_made": changes,
        "keywords_integrated": keywords_integrated,
        "honesty_notes": honesty_notes,
    }


# =====================================================================
# Public Async Orchestrators
# =====================================================================

ANALYZE_SYSTEM_PROMPT = """Eres un consultor experto en selección de personal, sistemas ATS (Applicant Tracking Systems) y optimización HONESTA de currículums.

REGLAS INQUEBRANTABLES DE HONESTIDAD:
1. NUNCA inventes ni asumas habilidades, años de experiencia, títulos, empresas, logros ni idiomas que no estén en el CV BASE o en la BASE DE CONOCIMIENTO CONFIRMADA.
2. Si un requisito ya aparece en "DESCARTADO POR EL CANDIDATO", clasifícalo en `missing_requirements` y NUNCA lo pongas en `unclear_requirements` (no vuelvas a preguntar lo que el candidato ya dijo que no tiene).
3. Si un requisito ya aparece en "CONFIRMADO" o "PARCIAL" en la Base de Conocimiento, úsalo como evidencia real en `matched_requirements` y NO vuelvas a preguntarlo.
4. Pon en `unclear_requirements` SOLO requisitos importantes de la oferta donde realmente no queda claro si el candidato los cumple según su CV base y su memoria (máximo 7 preguntas concretas, útiles y respetuosas).
5. Responde SIEMPRE en español para los textos de análisis, preguntas y consejos (aunque la oferta esté en inglés).

Devuelve ÚNICAMENTE un objeto JSON válido con esta estructura exacta:
{
  "job_title": "Título del puesto detectado",
  "company": "Empresa detectada o cadena vacía",
  "offer_language": "es" | "en",
  "match_score": 0-100,
  "ats_score": 0-100,
  "summary": "Resumen claro en 2-3 frases de cómo encaja el perfil real con la oferta",
  "matched_requirements": [
    {
      "requirement": "Requisito de la oferta",
      "category": "Habilidad técnica | Herramienta | Experiencia | Idioma | Certificación | Soft skill | Otro",
      "evidence": "Evidencia exacta sacada del CV base o de la base de conocimiento",
      "keywords_matched": ["palabra clave 1", "palabra clave 2"]
    }
  ],
  "unclear_requirements": [
    {
      "id": "q_1",
      "topic": "Nombre corto y reutilizable del tema (ej: Docker en producción, Inglés B2)",
      "suggested_category": "Habilidad técnica | Herramienta | Experiencia | Idioma | Certificación | Soft skill | Otro",
      "requirement": "Qué pide exactamente la oferta",
      "why_unclear": "Por qué no queda claro con la información actual",
      "question": "Pregunta directa y breve al candidato para confirmar si cumple este punto y en qué nivel"
    }
  ],
  "missing_requirements": [
    {
      "requirement": "Requisito claramente ausente o descartado",
      "importance": "Imprescindible | Valorable",
      "honest_advice": "Consejo honesto (cómo mitigarlo o aceptarlo sin mentir)"
    }
  ],
  "ats_keywords": {
    "matched": ["keywords que el candidato YA cumple"],
    "to_highlight": ["keywords reales prioritarias a destacar en el CV"],
    "missing": ["keywords de la oferta que faltan o están por confirmar"]
  }
}"""


ADAPT_SYSTEM_PROMPT = """Eres un especialista senior en redacción de CV optimizados para filtros ATS / IA con ÉTICA ESTRICTA (cero mentiras, cero exageraciones inventadas).

REGLAS INQUEBRANTABLES:
1. PROHIBIDO INVENTAR: No inventes empresas, fechas, cargos, titulaciones, métricas numéricas, certificaciones ni tecnologías que no figuren en el CV BASE o en los HECHOS CONFIRMADOS.
2. RESPETA LOS DESCARTES: Cualquier habilidad marcada como DESCARTADA por el candidato tiene prohibido aparecer en el CV.
3. HONESTIDAD EN NIVEL PARCIAL: Si un hecho está marcado como PARCIAL/BÁSICO, menciónalo con transparencia (ej. "conocimientos básicos de...", "uso inicial de...").
4. OPTIMIZACIÓN ATS INTELIGENTE:
   - Usa la terminología exacta y palabras clave de la oferta SOLO cuando describan de forma veraz experiencia o habilidades reales del candidato.
   - Reordena viñetas y secciones para dar protagonismo a lo más relevante para esta oferta.
   - Redacta un Perfil Profesional claro, potente y específico para el puesto.
   - Formato Markdown limpio de una sola columna (`# Nombre`, subtítulo, contacto, `## Perfil Profesional`, `## Competencias Clave`, `## Experiencia Profesional`, `## Formación`, `## Idiomas`, etc.) fácil de leer por sistemas ATS.
5. IDIOMA DEL CV: Si se indica idioma `en`, redacta el CV en inglés; si `es`, en español; si `auto`, usa el mismo idioma de la oferta de empleo. Los campos `changes_made`, `keywords_integrated` y `honesty_notes` escríbelos siempre en español.

Devuelve ÚNICAMENTE un objeto JSON válido con esta estructura exacta:
{
  "adapted_cv_markdown": "Texto completo del CV adaptado en Markdown limpio listo para exportar a PDF/DOCX",
  "changes_made": [
    {
      "section": "Sección modificada",
      "change": "Qué se ha adaptado",
      "reason": "Cómo mejora el encaje ATS manteniendo 100% veracidad"
    }
  ],
  "keywords_integrated": [
    {
      "keyword": "Palabra clave exacta de la oferta integrada",
      "justification": "De qué parte real del CV base o memoria confirmada proviene"
    }
  ],
  "honesty_notes": [
    "Lista de requisitos o carencias que NO se han incluido para no mentir"
  ]
}"""


async def analyze_job_offer(
    settings: dict[str, Any],
    cv_profile: dict[str, Any],
    facts: list[dict[str, Any]],
    job_description: str,
    job_title: str = "",
    company: str = "",
) -> tuple[dict[str, Any], str]:
    provider = (settings.get("provider") or "local").strip().lower()
    if provider == "local":
        return (
            _local_analyze_job(cv_profile.get("raw_text", ""), facts, job_description, job_title, company),
            "local",
        )

    user_prompt = f"""=== CV BASE DEL CANDIDATO ===
Nombre: {cv_profile.get('full_name') or '(detectar del CV)'}
Titular: {cv_profile.get('headline') or ''}

{cv_profile.get('raw_text', '')[:16000]}

=== BASE DE CONOCIMIENTO PERSISTENTE DEL CANDIDATO ===
{_format_knowledge_for_prompt(facts)}

=== OFERTA DE EMPLEO A ANALIZAR ===
Puesto indicado: {job_title or '(detectar)'}
Empresa indicada: {company or '(detectar)'}

{job_description[:16000]}
"""
    raw = await _call_llm(settings, ANALYZE_SYSTEM_PROMPT, user_prompt, expect_json=True)
    parsed = _extract_json_block(raw)

    # Normalize expected keys safely
    parsed.setdefault("job_title", _guess_job_title(job_description, job_title))
    parsed.setdefault("company", company)
    parsed.setdefault("offer_language", _detect_language(job_description))
    parsed.setdefault("match_score", 0)
    parsed.setdefault("ats_score", parsed.get("match_score", 0))
    parsed.setdefault("summary", "")
    parsed.setdefault("matched_requirements", [])
    parsed.setdefault("unclear_requirements", [])
    parsed.setdefault("missing_requirements", [])
    parsed.setdefault("ats_keywords", {"matched": [], "to_highlight": [], "missing": []})

    # Ensure every unclear question has an id and topic
    for idx, item in enumerate(parsed["unclear_requirements"]):
        if not item.get("id"):
            item["id"] = f"q_{idx + 1}"
        if not item.get("topic"):
            item["topic"] = str(item.get("requirement", f"Requisito {idx + 1}"))[:80]
        if not item.get("suggested_category"):
            item["suggested_category"] = "Habilidad técnica"

    return parsed, provider


async def adapt_cv_honestly(
    settings: dict[str, Any],
    cv_profile: dict[str, Any],
    facts: list[dict[str, Any]],
    job_title: str,
    company: str,
    job_description: str,
    analysis: dict[str, Any],
    target_language: str = "auto",
    extra_instructions: str = "",
) -> tuple[dict[str, Any], str]:
    provider = (settings.get("provider") or "local").strip().lower()
    if provider == "local":
        return (
            _local_adapt_cv(cv_profile, facts, job_title, company, analysis, extra_instructions),
            "local",
        )

    tone = settings.get("tone") or "profesional y directo"
    lang_choice = target_language if target_language != "auto" else (analysis.get("offer_language") or "es")

    user_prompt = f"""=== CONFIGURACIÓN ===
Idioma deseado para el CV adaptado: {lang_choice}
Tono deseado: {tone}
Instrucciones adicionales del usuario: {extra_instructions or 'Ninguna'}

=== CV BASE DEL CANDIDATO ===
Nombre: {cv_profile.get('full_name') or '(detectar del CV)'}
Titular: {cv_profile.get('headline') or ''}

{cv_profile.get('raw_text', '')[:16000]}

=== BASE DE CONOCIMIENTO PERSISTENTE DEL CANDIDATO ===
{_format_knowledge_for_prompt(facts)}

=== OFERTA DE EMPLEO ===
Puesto: {job_title}
Empresa: {company}

{job_description[:14000]}

=== ANÁLISIS PREVIO ===
Keywords ATS prioritarias verificadas: {json.dumps(analysis.get('ats_keywords', {}), ensure_ascii=False)}
Requisitos cumplidos: {json.dumps(analysis.get('matched_requirements', []), ensure_ascii=False)}
Requisitos ausentes/descartados (NO INVENTAR): {json.dumps(analysis.get('missing_requirements', []), ensure_ascii=False)}
"""
    raw = await _call_llm(settings, ADAPT_SYSTEM_PROMPT, user_prompt, expect_json=True)
    parsed = _extract_json_block(raw)
    parsed.setdefault("adapted_cv_markdown", "")
    parsed.setdefault("changes_made", [])
    parsed.setdefault("keywords_integrated", [])
    parsed.setdefault("honesty_notes", [])
    parsed.setdefault("adapted_cv_structured", {})
    return parsed, provider
