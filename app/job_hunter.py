import asyncio
import html
import json
import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Optional
from urllib.parse import quote_plus, unquote

import httpx
from bs4 import BeautifulSoup

from app import ai_engine, database


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


# =====================================================================
# Country Configuration & Normalization
# =====================================================================

COUNTRY_CONFIGS: dict[str, dict[str, Any]] = {
    "españa": {
        "name": "España",
        "li_location": "Spain",
        "continent": "eu",
        "allow_tecnoempleo": True,
        "allow_arbeitnow": True,
        "allowed_remotive": ["spain", "españa", "europe", "eu", "emea", "worldwide", "anywhere"],
        "forbidden_remotive": ["usa only", "us only", "united states only", "canada only", "latam only", "uk only", "north america only"],
        "allowed_jobicy": ["emea", "europe", "spain", "anywhere", "worldwide"],
        "forbidden_locations": ["estados unidos", "united states", "usa", "carolina", "california", "florida", "texas", "new york", "colorado", "arizona", "illinois", "washington", "georgia", "ohio", "virginia", "massachusetts"],
    },
    "spain": {
        "name": "España",
        "li_location": "Spain",
        "continent": "eu",
        "allow_tecnoempleo": True,
        "allow_arbeitnow": True,
        "allowed_remotive": ["spain", "españa", "europe", "eu", "emea", "worldwide", "anywhere"],
        "forbidden_remotive": ["usa only", "us only", "united states only", "canada only", "latam only", "uk only", "north america only"],
        "allowed_jobicy": ["emea", "europe", "spain", "anywhere", "worldwide"],
        "forbidden_locations": ["estados unidos", "united states", "usa", "carolina", "california", "florida", "texas", "new york", "colorado", "arizona", "illinois"],
    },
    "europa": {
        "name": "Europa",
        "li_location": "European Union",
        "continent": "eu",
        "allow_tecnoempleo": True,
        "allow_arbeitnow": True,
        "allowed_remotive": ["europe", "eu", "emea", "worldwide", "anywhere", "spain", "germany", "france", "uk"],
        "forbidden_remotive": ["usa only", "us only", "united states only", "canada only", "latam only", "north america only"],
        "allowed_jobicy": ["emea", "europe", "anywhere", "worldwide"],
        "forbidden_locations": ["estados unidos", "united states", "usa", "carolina", "california", "florida", "texas", "new york"],
    },
    "europe": {
        "name": "Europa",
        "li_location": "European Union",
        "continent": "eu",
        "allow_tecnoempleo": True,
        "allow_arbeitnow": True,
        "allowed_remotive": ["europe", "eu", "emea", "worldwide", "anywhere"],
        "forbidden_remotive": ["usa only", "us only", "united states only", "canada only", "latam only"],
        "allowed_jobicy": ["emea", "europe", "anywhere", "worldwide"],
        "forbidden_locations": ["estados unidos", "united states", "usa"],
    },
    "global": {
        "name": "Remoto Global",
        "li_location": "",
        "continent": "all",
        "allow_tecnoempleo": True,
        "allow_arbeitnow": True,
        "allowed_remotive": ["worldwide", "anywhere", "global", "all"],
        "forbidden_remotive": ["usa only", "us only"],
        "allowed_jobicy": ["anywhere", "worldwide", "emea", "latam", "europe", "usa"],
        "forbidden_locations": [],
    },
    "estados unidos": {
        "name": "Estados Unidos",
        "li_location": "United States",
        "continent": "na",
        "allow_tecnoempleo": False,
        "allow_arbeitnow": False,
        "allowed_remotive": ["usa", "united states", "north america", "worldwide", "anywhere"],
        "forbidden_remotive": ["europe only", "latam only", "uk only", "spain only"],
        "allowed_jobicy": ["usa", "north america", "anywhere", "worldwide"],
        "forbidden_locations": ["españa", "spain", "madrid", "barcelona"],
    },
    "usa": {
        "name": "Estados Unidos",
        "li_location": "United States",
        "continent": "na",
        "allow_tecnoempleo": False,
        "allow_arbeitnow": False,
        "allowed_remotive": ["usa", "united states", "north america", "worldwide", "anywhere"],
        "forbidden_remotive": ["europe only", "latam only", "uk only", "spain only"],
        "allowed_jobicy": ["usa", "north america", "anywhere", "worldwide"],
        "forbidden_locations": ["españa", "spain"],
    },
    "méxico": {
        "name": "México",
        "li_location": "Mexico",
        "continent": "latam",
        "allow_tecnoempleo": False,
        "allow_arbeitnow": False,
        "allowed_remotive": ["mexico", "méxico", "latam", "latin america", "worldwide", "anywhere"],
        "forbidden_remotive": ["usa only", "us only", "europe only", "uk only"],
        "allowed_jobicy": ["latam", "anywhere", "worldwide"],
        "forbidden_locations": ["estados unidos", "united states", "españa", "spain"],
    },
    "mexico": {
        "name": "México",
        "li_location": "Mexico",
        "continent": "latam",
        "allow_tecnoempleo": False,
        "allow_arbeitnow": False,
        "allowed_remotive": ["mexico", "méxico", "latam", "latin america", "worldwide", "anywhere"],
        "forbidden_remotive": ["usa only", "us only", "europe only"],
        "allowed_jobicy": ["latam", "anywhere", "worldwide"],
        "forbidden_locations": ["estados unidos", "united states", "españa", "spain"],
    },
    "argentina": {
        "name": "Argentina",
        "li_location": "Argentina",
        "continent": "latam",
        "allow_tecnoempleo": False,
        "allow_arbeitnow": False,
        "allowed_remotive": ["argentina", "latam", "latin america", "worldwide", "anywhere"],
        "forbidden_remotive": ["usa only", "us only", "europe only"],
        "allowed_jobicy": ["latam", "anywhere", "worldwide"],
        "forbidden_locations": ["estados unidos", "united states", "españa", "spain"],
    },
    "colombia": {
        "name": "Colombia",
        "li_location": "Colombia",
        "continent": "latam",
        "allow_tecnoempleo": False,
        "allow_arbeitnow": False,
        "allowed_remotive": ["colombia", "latam", "latin america", "worldwide", "anywhere"],
        "forbidden_remotive": ["usa only", "us only", "europe only"],
        "allowed_jobicy": ["latam", "anywhere", "worldwide"],
        "forbidden_locations": ["estados unidos", "united states", "españa", "spain"],
    },
    "chile": {
        "name": "Chile",
        "li_location": "Chile",
        "continent": "latam",
        "allow_tecnoempleo": False,
        "allow_arbeitnow": False,
        "allowed_remotive": ["chile", "latam", "latin america", "worldwide", "anywhere"],
        "forbidden_remotive": ["usa only", "us only", "europe only"],
        "allowed_jobicy": ["latam", "anywhere", "worldwide"],
        "forbidden_locations": ["estados unidos", "united states", "españa", "spain"],
    },
    "reino unido": {
        "name": "Reino Unido",
        "li_location": "United Kingdom",
        "continent": "eu",
        "allow_tecnoempleo": False,
        "allow_arbeitnow": False,
        "allowed_remotive": ["uk", "united kingdom", "europe", "worldwide", "anywhere"],
        "forbidden_remotive": ["usa only", "us only", "latam only"],
        "allowed_jobicy": ["uk", "europe", "anywhere", "worldwide"],
        "forbidden_locations": ["estados unidos", "united states", "españa"],
    },
    "uk": {
        "name": "Reino Unido",
        "li_location": "United Kingdom",
        "continent": "eu",
        "allow_tecnoempleo": False,
        "allow_arbeitnow": False,
        "allowed_remotive": ["uk", "united kingdom", "europe", "worldwide", "anywhere"],
        "forbidden_remotive": ["usa only", "us only", "latam only"],
        "allowed_jobicy": ["uk", "europe", "anywhere", "worldwide"],
        "forbidden_locations": ["estados unidos", "united states"],
    },
    "alemania": {
        "name": "Alemania",
        "li_location": "Germany",
        "continent": "eu",
        "allow_tecnoempleo": False,
        "allow_arbeitnow": True,
        "allowed_remotive": ["germany", "deutschland", "europe", "worldwide", "anywhere"],
        "forbidden_remotive": ["usa only", "us only", "latam only"],
        "allowed_jobicy": ["europe", "emea", "anywhere", "worldwide"],
        "forbidden_locations": ["estados unidos", "united states"],
    },
    "germany": {
        "name": "Alemania",
        "li_location": "Germany",
        "continent": "eu",
        "allow_tecnoempleo": False,
        "allow_arbeitnow": True,
        "allowed_remotive": ["germany", "deutschland", "europe", "worldwide", "anywhere"],
        "forbidden_remotive": ["usa only", "us only", "latam only"],
        "allowed_jobicy": ["europe", "emea", "anywhere", "worldwide"],
        "forbidden_locations": ["estados unidos", "united states"],
    },
    "francia": {
        "name": "Francia",
        "li_location": "France",
        "continent": "eu",
        "allow_tecnoempleo": False,
        "allow_arbeitnow": True,
        "allowed_remotive": ["france", "europe", "worldwide", "anywhere"],
        "forbidden_remotive": ["usa only", "us only"],
        "allowed_jobicy": ["europe", "anywhere", "worldwide"],
        "forbidden_locations": ["estados unidos", "united states"],
    },
    "italia": {
        "name": "Italia",
        "li_location": "Italy",
        "continent": "eu",
        "allow_tecnoempleo": False,
        "allow_arbeitnow": True,
        "allowed_remotive": ["italy", "europe", "worldwide", "anywhere"],
        "forbidden_remotive": ["usa only", "us only"],
        "allowed_jobicy": ["europe", "anywhere", "worldwide"],
        "forbidden_locations": ["estados unidos", "united states"],
    },
}


def resolve_country_config(country_name: str) -> dict[str, Any]:
    norm = (country_name or "España").strip().lower()
    if norm in COUNTRY_CONFIGS:
        return COUNTRY_CONFIGS[norm]
    for k, v in COUNTRY_CONFIGS.items():
        if k in norm or norm in k:
            return v
    # Generic custom country
    return {
        "name": country_name.strip() if country_name else "España",
        "li_location": country_name.strip() if country_name else "Spain",
        "continent": "custom",
        "allow_tecnoempleo": False,
        "allow_arbeitnow": False,
        "allowed_remotive": [norm, "worldwide", "anywhere", "global"],
        "forbidden_remotive": ["usa only", "us only", "united states only"] if norm not in ("usa", "estados unidos", "united states") else [],
        "allowed_jobicy": ["anywhere", "worldwide", norm],
        "forbidden_locations": ["estados unidos", "united states", "usa"] if norm not in ("usa", "estados unidos", "united states") else [],
    }


def _clean_html_text(raw_html: str) -> str:
    if not raw_html:
        return ""
    try:
        soup = BeautifulSoup(raw_html, "html.parser")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text("\n")
        lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
        return "\n".join(ln for ln in lines if ln)
    except Exception:
        return re.sub(r"<[^>]+>", " ", raw_html).strip()


def _detect_modality(text: str, location: str) -> str:
    combined = f"{text} {location}".lower()
    if any(k in combined for k in ("100% remoto", "full remote", "remoto", "remote", "teletrabajo", "work from home")):
        if any(k in combined for k in ("híbrido", "hibrido", "hybrid")):
            return "hybrid"
        return "remote"
    if any(k in combined for k in ("híbrido", "hibrido", "hybrid")):
        return "hybrid"
    return "onsite"


# =====================================================================
# Auto-detection of Search Preferences & Queries from CV Profile
# =====================================================================

def auto_detect_preferences_from_cv(cv_profile: dict[str, Any], facts: list[dict[str, Any]]) -> dict[str, Any]:
    raw_text = (cv_profile.get("raw_text") or "").strip()
    headline = (cv_profile.get("headline") or "").strip()
    norm_text = raw_text.lower()

    # 1. Detect target roles from headline or top lines
    roles: list[str] = []
    headline_sources = [headline] if headline else []
    # Also inspect top lines of raw_text for multi-role subtitles (e.g., "Administrativa | Control Documental, Facturación...")
    for line in [ln.strip() for ln in raw_text.splitlines() if ln.strip()][:4]:
        if any(sep in line for sep in ("|", "•", "/")):
            # Skip contact/location info lines
            if any(k in line.lower() for k in ("@", "http", "linkedin", "github", "tel", "tlf", "phone", "mail", "gmail", "yahoo", "hotmail")):
                continue
            if line not in headline_sources:
                headline_sources.append(line)

    for h_src in headline_sources:
        parts = re.split(r"[|/•,\n–—]", h_src)
        for p in parts:
            clean = re.sub(r"\b(en remoto|remoto|remote|híbrido|hibrido|presencial)\b", "", p, flags=re.IGNORECASE).strip()
            if 3 <= len(clean) <= 40 and not any(ch in clean for ch in "@.:"):
                if clean.lower() not in [r.lower() for r in roles]:
                    roles.append(clean)

    # Detect job titles from experience history headers in the CV (e.g., "Administrativa — ASSTAX CONSULTING")
    exp_matches = re.findall(
        r"(?:^|\n)\s*([A-Za-zÁÉÍÓÚÑáéíóúñ\s/]{4,35})\s*[—–-]\s*[A-Za-z0-9ÁÉÍÓÚÑáéíóúñ\s.,]{3,40}",
        raw_text,
    )
    stop_words = (
        "experiencia", "educacion", "educación", "formacion", "formación",
        "extracto", "idiomas", "aptitudes", "page", "cv", "curriculum",
        "grado", "universidad", "universitat", "instituto", "colegio",
        "facultat", "facultad", "ifp", "fp", "bachillerato", "escola",
        "pompeu", "fabra", "uab", "ub", "upc", "upf", "licenciatura", "master", "máster"
    )
    for em in exp_matches:
        clean_em = em.strip()
        if 4 <= len(clean_em) <= 35 and clean_em.lower() not in [r.lower() for r in roles]:
            if not any(stop in clean_em.lower() for stop in stop_words):
                roles.append(clean_em)

    # Comprehensive catalog of candidate professions across all fields
    role_candidates = [
        # Administración, Oficina y Gestión
        "Auxiliar Administrativo", "Administrativa", "Administrativo", "Secretaria", "Secretario",
        "Recepcionista", "Office Manager", "Asistente de Dirección", "Gestión Administrativa",
        "Técnico Administrativo", "Facturación", "Control Documental", "Secretaría Virtual",
        "Tramitador de Asistencia", "Tramitador", "Gestor Documental", "Grabador de Datos",
        # Finanzas & Contabilidad
        "Contable", "Técnico Contable", "Auditor", "Controller", "Asesor Fiscal", "Gestor de Cobros",
        # Recursos Humanos
        "Recursos Humanos", "Técnico de Selección", "Gestión de Personal", "HR Generalist", "Talent Acquisition",
        # Atención al Cliente & Soporte
        "Atención al Cliente", "Customer Support", "Teleoperador", "Call Center", "Soporte al Usuario",
        # Comercial & Ventas
        "Comercial", "Ejecutivo de Cuentas", "Asesor Comercial", "Ventas", "Vendedor", "Dependiente",
        # Marketing & Comunicación
        "Marketing", "Community Manager", "Content Creator", "Copywriter", "SEO", "Especialista Marketing",
        # Tecnología & IT
        "Backend Developer", "Full Stack Developer", "Frontend Developer",
        "Python Developer", "Software Engineer", "DevOps Engineer",
        "Cloud Engineer", "Data Engineer", "Data Analyst",
        "Mobile Developer", "QA Engineer", "Product Manager",
        "Tech Lead", "System Administrator", "Scrum Master",
    ]
    for cand in role_candidates:
        if re.search(r"\b" + re.escape(cand.lower()) + r"\b", norm_text):
            if cand.lower() not in [r.lower() for r in roles]:
                roles.append(cand)
                if len(roles) >= 4:
                    break

    if not roles:
        # Check first non-empty lines for possible title
        lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
        for ln in lines[1:4]:
            if 3 <= len(ln) <= 40 and not any(ch in ln for ch in "@.:"):
                roles.append(ln)
                break
    if not roles:
        roles = ["Administrativo"]

    # 2. Detect country, location & modality
    country = "España"
    location = "España"
    for city in ["Madrid", "Barcelona", "Valencia", "Sevilla", "Málaga", "Bilbao", "Zaragoza", "Alicante"]:
        if re.search(r"\b" + re.escape(city.lower()) + r"\b", norm_text):
            location = f"{city}, España"
            country = "España"
            break
    if "méxico" in norm_text or "mexico" in norm_text:
        country = "México"
        location = "México"
    elif "argentina" in norm_text:
        country = "Argentina"
        location = "Argentina"
    elif "colombia" in norm_text:
        country = "Colombia"
        location = "Colombia"
    elif "chile" in norm_text:
        country = "Chile"
        location = "Chile"
    elif "estados unidos" in norm_text or "usa" in norm_text or "united states" in norm_text:
        country = "Estados Unidos"
        location = "Estados Unidos"

    modality = "remote" if any(w in norm_text for w in ("remoto", "remote", "teletrabajo", "a distancia")) else "all"

    # 3. Detect experience level
    level = "mid"
    year_matches = re.findall(r"(\d+)\+?\s*(?:años|anos|years)", norm_text)
    if year_matches:
        try:
            years = max(int(y) for y in year_matches if int(y) < 30)
            if years <= 2:
                level = "junior"
            elif years >= 5:
                level = "senior"
            else:
                level = "mid"
        except Exception:
            level = "mid"

    # 4. Detect strong keywords to include across all sectors
    top_keywords: list[str] = []
    confirmed_facts = [f["topic"] for f in facts if f.get("status") == "confirmed"]
    for f in confirmed_facts:
        if f not in top_keywords:
            top_keywords.append(f)

    for canonical, _, aliases in ai_engine.SKILL_CATALOG:
        if any(ai_engine._contains_alias(ai_engine._strip_accents(raw_text), a) for a in aliases):
            if canonical not in top_keywords:
                top_keywords.append(canonical)
        if len(top_keywords) >= 8:
            break

    # 5. Keywords to exclude (from denied facts)
    excluded = [f["topic"] for f in facts if f.get("status") == "denied"]

    return {
        "target_roles": roles[:4],
        "location": location,
        "country": country,
        "modality": modality,
        "experience_level": level,
        "keywords_include": top_keywords[:8],
        "keywords_exclude": excluded[:10],
        "min_salary": None,
        "preferred_sources": ["linkedin", "remotive", "jobicy"],
    }


def _is_tech_role(query_list: list[str], cv_text: str) -> bool:
    combined = f"{' '.join(query_list)} {cv_text[:800]}".lower()
    tech_keywords = [
        "developer", "software", "backend", "frontend", "full stack", "fullstack",
        "devops", "python", "javascript", "react", "docker", "kubernetes", "cloud",
        "aws", "java", "c#", "c++", "php", "sql", "linux", "git", "microservicios",
        "programador", "desarrollador", "ingeniero de software", "sistemas"
    ]
    return any(k in combined for k in tech_keywords)


def get_search_queries_for_cv(
    cv_profile: dict[str, Any],
    facts: list[dict[str, Any]],
    search_prefs: dict[str, Any],
    from_cv: bool = False,
) -> list[str]:
    """Generates high-affinity search queries anchored in the user's uploaded CV and profession."""
    detected = auto_detect_preferences_from_cv(cv_profile, facts)
    detected_roles = detected.get("target_roles") or []

    pref_roles = search_prefs.get("target_roles") or []
    norm_cv = (cv_profile.get("raw_text") or "").lower()

    # If from_cv is True or if stored search_prefs don't match the active CV, prioritize the real CV!
    if from_cv or not pref_roles or not any(r.lower() in norm_cv for r in pref_roles):
        roles = detected_roles
    else:
        roles = pref_roles

    if not roles:
        roles = ["Administrativo"]

    primary_role = roles[0]
    queries: list[str] = []

    # In Spanish, search both inclusive and common base forms for the role (e.g. Administrativa -> Administrativo)
    canonical = primary_role
    if primary_role.lower().endswith("a") and not primary_role.lower().endswith("ia"):
        canonical = primary_role[:-1] + "o"

    queries.append(canonical)
    if primary_role != canonical:
        queries.append(primary_role)

    p_low = primary_role.lower()
    if "administrativ" in p_low:
        if "Auxiliar Administrativo" not in queries:
            queries.append("Auxiliar Administrativo")
    elif "secretar" in p_low:
        if "Recepcionista" not in queries:
            queries.append("Recepcionista")

    # Add secondary role or top skill if available
    skills = detected.get("keywords_include") or []
    if skills and len(queries) < 3:
        top_skill = skills[0]
        if top_skill.lower() not in p_low:
            queries.append(f"{canonical} {top_skill}")
    elif len(roles) > 1 and len(queries) < 3:
        queries.append(roles[1])

    return list(dict.fromkeys(q.strip() for q in queries if q.strip()))[:3]


# =====================================================================
# Connector 1: LinkedIn Jobs (Public Guest API - Country Aware)
# =====================================================================

async def fetch_linkedin_jobs(
    query: str,
    location: str = "",
    country: str = "España",
    modality: str = "all",
    limit: int = 25,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    cfg = resolve_country_config(country)

    loc_input = location.strip()
    if loc_input and loc_input.lower() not in ("españa", "spain", "europa", "global", "todas", "all", "estados unidos", "usa"):
        loc_clean = loc_input
    else:
        loc_clean = cfg["li_location"]

    # LinkedIn modality codes: 1=On-site, 2=Remote, 3=Hybrid
    f_wt = ""
    if modality == "remote":
        f_wt = "&f_WT=2"
    elif modality == "hybrid":
        f_wt = "&f_WT=3"
    elif modality == "onsite":
        f_wt = "&f_WT=1"

    loc_param = f"&location={quote_plus(loc_clean)}" if loc_clean else ""
    url = (
        f"https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search"
        f"?keywords={quote_plus(query)}{loc_param}{f_wt}&start=0"
    )

    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }

    try:
        async with httpx.AsyncClient(timeout=14.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select("li")
            for c in cards:
                title_el = c.select_one(".base-search-card__title")
                comp_el = c.select_one(".base-search-card__subtitle")
                loc_el = c.select_one(".job-search-card__location")
                link_el = c.select_one("a.base-card__full-link")
                date_el = c.select_one(".job-search-card__listdate") or c.select_one("time")

                if not title_el or not link_el:
                    continue

                raw_url = link_el.get("href", "").split("?")[0].strip()
                if not raw_url:
                    continue

                title = title_el.get_text(strip=True)
                company = comp_el.get_text(strip=True) if comp_el else ""
                job_loc = loc_el.get_text(strip=True) if loc_el else (loc_clean or cfg["name"])
                pub_date = date_el.get_text(strip=True) if date_el else "Reciente"

                # Accurately detect modality: LinkedIn often broadens guest searches and returns on-site jobs
                # even when &f_WT=2 was requested. Never blindly assign "remote" to physical city locations!
                job_mod = _detect_modality(title, job_loc)
                if job_mod == "onsite" and modality == "remote":
                    known_cities = (
                        "madrid", "barcelona", "valencia", "sevilla", "málaga", "malaga", "bilbao",
                        "zaragoza", "alicante", "valladolid", "vigo", "gijón", "gijon", "a coruña",
                        "coruña", "palma", "granada", "murcia", "san roque", "algeciras", "santa susanna",
                        "las palmas", "guadalajara", "monterrey", "puebla", "querétaro", "queretaro",
                    )
                    if not any(city in job_loc.lower() for city in known_cities):
                        if job_loc.strip().lower() in ("españa", "spain", "worldwide", "anywhere", "global"):
                            job_mod = "remote"

                results.append({
                    "external_id": f"li_{abs(hash(raw_url))}",
                    "source": "LinkedIn",
                    "title": title,
                    "company": company,
                    "location": job_loc,
                    "country": cfg["name"],
                    "modality": job_mod,
                    "source_url": raw_url,
                    "description_snippet": f"Oferta en LinkedIn para {title} en {company} ({job_loc}). Postulación directa disponible.",
                    "raw_description": f"{title}\nEmpresa: {company}\nUbicación: {job_loc}\nModalidad: {job_mod}\nEnlace: {raw_url}",
                    "salary_text": "",
                    "published_at": pub_date,
                })
                if len(results) >= limit:
                    break
    except Exception:
        pass
    return results


# =====================================================================
# Connector 2: Tecnoempleo (Spain #1 Tech Job Board - Spain Only)
# =====================================================================

async def fetch_tecnoempleo_jobs(
    query: str,
    country: str = "España",
    modality: str = "all",
    limit: int = 25,
) -> list[dict[str, Any]]:
    cfg = resolve_country_config(country)
    if not cfg.get("allow_tecnoempleo", True):
        return []

    results: list[dict[str, Any]] = []
    # If remote, add filter parameter pr=,58, (Teletrabajo 100%)
    remote_param = "&pr=,58," if modality == "remote" else ""
    url = f"https://www.tecnoempleo.com/ofertas-trabajo/?te={quote_plus(query)}{remote_param}"

    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "es-ES,es;q=0.9",
        "Referer": "https://www.tecnoempleo.com/",
    }

    try:
        async with httpx.AsyncClient(timeout=14.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            for a in soup.find_all("a"):
                href = a.get("href", "")
                if "rf-" not in href:
                    continue

                full_url = href if href.startswith("http") else f"https://www.tecnoempleo.com{href}"
                full_url = full_url.split("?")[0].strip()

                raw_title = a.get_text(strip=True)
                if not raw_title or len(raw_title) < 4:
                    continue

                parent = a.find_parent(["div", "tr", "article"])
                card_text = parent.get_text(" ") if parent else raw_title

                company = ""
                loc = "España"
                for word in ["Madrid", "Barcelona", "Valencia", "Sevilla", "Málaga", "Bilbao", "Remoto", "Teletrabajo"]:
                    if word.lower() in card_text.lower():
                        loc = word
                        break

                job_mod = _detect_modality(card_text, loc)

                results.append({
                    "external_id": f"tecno_{abs(hash(full_url))}",
                    "source": "Tecnoempleo",
                    "title": raw_title,
                    "company": company,
                    "location": loc,
                    "country": "España",
                    "modality": job_mod,
                    "source_url": full_url,
                    "description_snippet": f"Oferta técnica en Tecnoempleo: {raw_title}. {card_text[:200].strip()}...",
                    "raw_description": f"{raw_title}\nUbicación: {loc}\nModalidad: {job_mod}\n{card_text[:1200]}",
                    "salary_text": "",
                    "published_at": "Reciente",
                })
                if len(results) >= limit:
                    break
    except Exception:
        pass
    return results


# =====================================================================
# Connector 3: Remotive (Country & Worldwide Remote Tech Jobs API)
# =====================================================================

async def fetch_remotive_jobs(query: str, country: str = "España", limit: int = 25) -> list[dict[str, Any]]:
    endpoint = f"https://remotive.com/api/remote-jobs?search={quote_plus(query)}&limit={limit * 2}"
    results: list[dict[str, Any]] = []
    cfg = resolve_country_config(country)
    try:
        async with httpx.AsyncClient(timeout=14.0) as client:
            resp = await client.get(endpoint, headers={"User-Agent": USER_AGENT})
            if resp.status_code != 200:
                return []
            data = resp.json()
            jobs = data.get("jobs") or []
            for j in jobs:
                geo = str(j.get("candidate_required_location") or "Worldwide").strip()
                geo_lower = geo.lower()

                # Filter out forbidden regions (e.g. USA Only when country is España/Europe)
                has_forbidden = any(f in geo_lower for f in cfg.get("forbidden_remotive", []))
                if "usa" in geo_lower and cfg["continent"] not in ("na", "all"):
                    if not any(k in geo_lower for k in ("europe", "eu", "emea", "spain", "españa", "worldwide", "anywhere")):
                        has_forbidden = True

                if has_forbidden:
                    continue

                if cfg["continent"] != "all":
                    is_allowed = any(a in geo_lower for a in cfg.get("allowed_remotive", []))
                    if not is_allowed:
                        continue

                desc_text = _clean_html_text(j.get("description", ""))
                snippet = desc_text[:280].replace("\n", " ").strip()
                results.append({
                    "external_id": f"remotive_{j.get('id')}",
                    "source": "Remotive",
                    "title": str(j.get("title") or "").strip(),
                    "company": str(j.get("company_name") or "").strip(),
                    "location": f"{geo} (Remoto)",
                    "country": cfg["name"],
                    "modality": "remote",
                    "source_url": str(j.get("url") or "").strip(),
                    "description_snippet": snippet,
                    "raw_description": desc_text[:14000],
                    "salary_text": str(j.get("salary") or "").strip(),
                    "published_at": str(j.get("publication_date") or "").strip(),
                })
                if len(results) >= limit:
                    break
    except Exception:
        pass
    return results


# =====================================================================
# Connector 4: Arbeitnow (European & Remote Jobs API - Filtered)
# =====================================================================

async def fetch_arbeitnow_jobs(query: str, country: str = "España", modality: str = "all", limit: int = 25) -> list[dict[str, Any]]:
    cfg = resolve_country_config(country)
    if not cfg.get("allow_arbeitnow", True):
        return []

    endpoint = "https://www.arbeitnow.com/api/job-board-api"
    results: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=14.0) as client:
            resp = await client.get(endpoint, headers={"User-Agent": USER_AGENT})
            if resp.status_code != 200:
                return []
            data = resp.json()
            jobs = data.get("data") or []
            q_norm = query.lower().strip()
            for j in jobs:
                title = str(j.get("title") or "")
                desc_html = str(j.get("description") or "")
                company = str(j.get("company_name") or "")
                tags = " ".join(str(t) for t in j.get("tags") or [])
                haystack = f"{title} {company} {tags} {desc_html}".lower()

                if q_norm and not any(term in haystack for term in q_norm.split()):
                    continue

                is_remote = bool(j.get("remote"))
                job_mod = "remote" if is_remote else "hybrid"

                if modality != "all":
                    if modality == "remote" and job_mod != "remote":
                        continue
                    if modality == "onsite" and job_mod == "remote":
                        continue

                loc = str(j.get("location") or ("Remote" if is_remote else "Europa"))
                loc_lower = loc.lower()

                # If country is Spain and job is not remote, only accept if located in Spain
                if cfg["name"] == "España" and not is_remote:
                    if not any(sp in loc_lower for sp in ("spain", "españa", "madrid", "barcelona", "valencia", "sevilla", "málaga", "bilbao", "zaragoza", "alicante")):
                        continue

                # If country is outside Europe and job is not remote, skip European onsite jobs
                if cfg["continent"] in ("latam", "na") and not is_remote:
                    continue

                desc_text = _clean_html_text(desc_html)

                results.append({
                    "external_id": f"arbeitnow_{j.get('slug')}",
                    "source": "Arbeitnow",
                    "title": title.strip(),
                    "company": company.strip(),
                    "location": loc,
                    "country": cfg["name"],
                    "modality": job_mod,
                    "source_url": str(j.get("url") or "").strip(),
                    "description_snippet": desc_text[:280].replace("\n", " ").strip(),
                    "raw_description": desc_text[:14000],
                    "salary_text": "",
                    "published_at": "",
                })
                if len(results) >= limit:
                    break
    except Exception:
        pass
    return results


# =====================================================================
# Connector 5: Jobicy (Country & Remote Jobs API - Filtered)
# =====================================================================

async def fetch_jobicy_jobs(query: str, country: str = "España", limit: int = 20) -> list[dict[str, Any]]:
    cfg = resolve_country_config(country)
    endpoint = f"https://jobicy.com/api/v2/remote-jobs?count={limit * 2}&tag={quote_plus(query)}"
    results: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=14.0) as client:
            resp = await client.get(endpoint, headers={"User-Agent": USER_AGENT})
            if resp.status_code != 200:
                return []
            jobs = resp.json().get("jobs") or []
            for j in jobs:
                geo = str(j.get("jobGeo") or "Remoto Global").strip()
                geo_lower = geo.lower()

                # Country constraint check
                if cfg["continent"] != "all":
                    if "usa" in geo_lower and cfg["continent"] not in ("na",):
                        if not any(k in geo_lower for k in ("emea", "europe", "spain", "worldwide", "anywhere")):
                            continue
                    if not any(a in geo_lower for a in cfg.get("allowed_jobicy", [])):
                        continue

                title = str(j.get("jobTitle") or "").strip()
                company = str(j.get("companyName") or "").strip()
                url = str(j.get("url") or "").strip()
                desc_text = _clean_html_text(j.get("jobDescription") or "")
                if not title or not url:
                    continue
                results.append({
                    "external_id": f"jobicy_{j.get('id')}",
                    "source": "Jobicy",
                    "title": title,
                    "company": company,
                    "location": f"{geo} (Remoto)",
                    "country": cfg["name"],
                    "modality": "remote",
                    "source_url": url,
                    "description_snippet": desc_text[:280].replace("\n", " ").strip(),
                    "raw_description": desc_text[:14000],
                    "salary_text": "",
                    "published_at": str(j.get("pubDate") or ""),
                })
                if len(results) >= limit:
                    break
    except Exception:
        pass
    return results


# =====================================================================
# Connector 6: WeWorkRemotely (Country-Filtered Programming RSS)
# =====================================================================

async def fetch_wwr_jobs(query: str, country: str = "España", limit: int = 20) -> list[dict[str, Any]]:
    cfg = resolve_country_config(country)
    feed_url = "https://weworkremotely.com/categories/remote-programming-jobs.rss"
    results: list[dict[str, Any]] = []
    q_norm = query.lower().strip()
    try:
        async with httpx.AsyncClient(timeout=14.0, follow_redirects=True) as client:
            resp = await client.get(feed_url, headers={"User-Agent": USER_AGENT})
            if resp.status_code != 200:
                return []
            root = ET.fromstring(resp.text)
            for it in root.findall(".//item"):
                title_node = it.find("title")
                link_node = it.find("link")
                desc_node = it.find("description")
                date_node = it.find("pubDate")

                if title_node is None or link_node is None:
                    continue

                full_title = (title_node.text or "").strip()
                url = (link_node.text or "").strip()
                desc_text = _clean_html_text(desc_node.text or "") if desc_node is not None else ""

                # Filter US-only locks if country is not USA/Global
                haystack = f"{full_title} {desc_text}".lower()
                if cfg["continent"] not in ("na", "all"):
                    if any(us_k in haystack for us_k in ("us only", "usa only", "united states only", "north america only")):
                        continue

                company = ""
                title = full_title
                if ": " in full_title:
                    parts = full_title.split(": ", 1)
                    company = parts[0].strip()
                    title = parts[1].strip()

                if q_norm and not any(term in haystack for term in q_norm.split()):
                    continue

                results.append({
                    "external_id": f"wwr_{abs(hash(url))}",
                    "source": "WeWorkRemotely",
                    "title": title,
                    "company": company,
                    "location": f"Remoto ({cfg['name']}/Global)",
                    "country": cfg["name"],
                    "modality": "remote",
                    "source_url": url,
                    "description_snippet": desc_text[:280].replace("\n", " ").strip(),
                    "raw_description": desc_text[:14000],
                    "salary_text": "",
                    "published_at": (date_node.text or "")[:16] if date_node is not None else "Reciente",
                })
                if len(results) >= limit:
                    break
    except Exception:
        pass
    return results


# =====================================================================
# Connector 7: InfoJobs (Official Developer API + Public Web Search)
# =====================================================================

async def fetch_infojobs_jobs(
    query: str,
    location: str = "",
    country: str = "España",
    modality: str = "all",
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Fetches job listings from InfoJobs via official API (if configured) or public listing search."""
    cfg = resolve_country_config(country)
    # InfoJobs is Spain / Italy focused
    if cfg.get("continent") not in ("eu", "all") and country.strip().lower() not in ("españa", "spain", "italia", "italy"):
        return []

    client_id = os.getenv("INFOJOBS_CLIENT_ID", "").strip()
    client_secret = os.getenv("INFOJOBS_CLIENT_SECRET", "").strip()

    results: list[dict[str, Any]] = []

    # 1. Official Developer API (if credentials provided)
    if client_id and client_secret:
        try:
            api_url = f"https://api.infojobs.net/api/7/offer?q={quote_plus(query)}"
            loc_clean = location.strip().split(",")[0].strip()
            if loc_clean and loc_clean.lower() not in ("españa", "spain", "global", "todas", "all"):
                api_url += f"&province={quote_plus(loc_clean)}"
            if modality == "remote":
                api_url += "&teleworking=teletrabajo-posible"
            elif modality == "onsite":
                api_url += "&teleworking=no-teletrabajo"

            async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
                resp = await client.get(
                    api_url,
                    auth=httpx.BasicAuth(client_id, client_secret),
                    headers={"Accept": "application/json"},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for item in (data.get("items") or [])[:limit]:
                        code = item.get("id") or item.get("code") or ""
                        title = item.get("title") or ""
                        prov = item.get("province", {}).get("value") or item.get("city") or "España"
                        comp = item.get("company", {}).get("name") or "Empresa"
                        url = item.get("link") or f"https://www.infojobs.net/ver-oferta/{code}"
                        tele = (item.get("teleworking", {}).get("value") or "").lower()
                        item_mod = "remote" if ("remoto" in tele or "teletrabajo" in tele) else ("hybrid" if "híbrido" in tele else "onsite")
                        req_min = item.get("requirementMin") or ""
                        sal = item.get("salaryDescription") or ""

                        results.append({
                            "external_id": f"ij_{code}",
                            "source": "InfoJobs",
                            "title": title.strip(),
                            "company": comp.strip(),
                            "location": f"{prov}, España" if "españa" not in prov.lower() else prov,
                            "country": "España",
                            "modality": item_mod,
                            "source_url": url,
                            "description_snippet": req_min[:280].replace("\n", " ").strip(),
                            "raw_description": req_min[:14000],
                            "salary_text": sal,
                            "published_at": (item.get("published") or "")[:10] or "Reciente",
                        })
                    if results:
                        return results
        except Exception:
            pass

    # 2. Public web search endpoint (falls back gracefully if gated)
    try:
        loc_clean = location.strip().split(",")[0].strip()
        loc_param = f"&location={quote_plus(loc_clean)}" if loc_clean and loc_clean.lower() not in ("españa", "spain", "global", "all") else ""
        web_url = f"https://www.infojobs.net/jobsearch/search-results/list.xhtml?keyword={quote_plus(query)}{loc_param}&segmentId="
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        }
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(web_url, headers=headers)
            if resp.status_code == 200 and "__INITIAL_PROPS__" in resp.text:
                soup = BeautifulSoup(resp.text, "html.parser")
                for sc in soup.find_all("script"):
                    txt = sc.text or ""
                    if "window.__INITIAL_PROPS__" in txt:
                        m = re.search(r'window\.__INITIAL_PROPS__\s*=\s*JSON\.parse\(("(?:\\.|[^"\\])*")\);', txt)
                        if m:
                            raw_json = json.loads(m.group(1))
                            data = json.loads(raw_json)
                            offers = data.get("offers", [])
                            for o in offers[:limit]:
                                code = o.get("code") or ""
                                title = o.get("title") or ""
                                desc = o.get("description") or ""
                                city = o.get("city") or "España"
                                comp = o.get("companyName") or ""
                                link = o.get("link") or ""
                                if link.startswith("//"):
                                    url = f"https:{link}"
                                elif link.startswith("/"):
                                    url = f"https://www.infojobs.net{link}"
                                else:
                                    url = link or f"https://www.infojobs.net/ver-oferta/{code}"
                                if "?" in url:
                                    url = url.split("?")[0]

                                tele = (o.get("teleworking") or "").lower()
                                if "100%" in tele or "teletrabajo" in tele or "remoto" in tele:
                                    item_mod = "remote"
                                elif "híbrido" in tele or "hibrido" in tele:
                                    item_mod = "hybrid"
                                else:
                                    item_mod = "onsite"

                                sal_obj = o.get("salary") or {}
                                sal_range = sal_obj.get("range") or {}
                                sal_min = sal_range.get("min")
                                sal_max = sal_range.get("max")
                                sal_curr = sal_obj.get("currency") or "€"
                                sal_period = sal_obj.get("period") or ""
                                sal_str = ""
                                if sal_min and sal_max:
                                    p_str = "/mes" if sal_period == "MONTH" else "/año" if sal_period == "YEAR" else ""
                                    sal_str = f"{sal_min:,} - {sal_max:,}{sal_curr}{p_str}".replace(",", ".") if sal_min != sal_max else f"{sal_min:,}{sal_curr}{p_str}".replace(",", ".")

                                results.append({
                                    "external_id": f"ij_{code}",
                                    "source": "InfoJobs",
                                    "title": title.strip(),
                                    "company": comp.strip(),
                                    "location": f"{city}, España" if "españa" not in city.lower() else city,
                                    "country": "España",
                                    "modality": item_mod,
                                    "source_url": url,
                                    "description_snippet": desc[:280].replace("\n", " ").strip(),
                                    "raw_description": desc[:14000],
                                    "salary_text": sal_str,
                                    "published_at": (o.get("publishedAt") or "")[:10] or "Reciente",
                                })
                            if results:
                                return results
    except Exception:
        pass

    return results


# =====================================================================
# Connector 8: Indeed (Direct Web Search Endpoint with Safety Gatekeeper)
# =====================================================================

async def fetch_indeed_jobs(
    query: str,
    location: str = "",
    country: str = "España",
    modality: str = "all",
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Attempts Indeed search; safely handles Cloudflare / anti-bot challenges without crashing or bypassing access controls."""
    cfg = resolve_country_config(country)
    domain = "es.indeed.com" if country.strip().lower() in ("españa", "spain") else "www.indeed.com"
    if "méxico" in country.lower() or "mexico" in country.lower():
        domain = "mx.indeed.com"
    elif "reino unido" in country.lower() or "uk" in country.lower():
        domain = "uk.indeed.com"

    loc_clean = location.strip().split(",")[0].strip()
    loc_param = f"&l={quote_plus(loc_clean)}" if loc_clean else f"&l={quote_plus(cfg['name'])}"
    url = f"https://{domain}/jobs?q={quote_plus(query)}{loc_param}"
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }
    results: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            # Indeed returns 403 when Cloudflare challenge is active
            if resp.status_code == 403 or "cf-mitigated" in resp.headers or "verify you are human" in resp.text.lower():
                return []
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                cards = soup.select(".job_seen_beacon, .resultContent")
                for c in cards:
                    t_el = c.select_one("h2.jobTitle span, h2.jobTitle a")
                    comp_el = c.select_one("[data-testid='company-name'], .companyName")
                    loc_el = c.select_one("[data-testid='text-location'], .companyLocation")
                    link_el = c.select_one("h2.jobTitle a, a[data-jk]")
                    snip_el = c.select_one(".job-snippet, .underShelfFooter")
                    if not t_el or not link_el:
                        continue
                    t_str = t_el.get_text(strip=True)
                    jk = link_el.get("data-jk") or ""
                    href = link_el.get("href") or ""
                    full_url = f"https://{domain}{href}" if href.startswith("/") else (f"https://{domain}/viewjob?jk={jk}" if jk else href)
                    loc_text = loc_el.get_text(strip=True) if loc_el else cfg["name"]
                    job_mod = _detect_modality(t_str, loc_text)
                    results.append({
                        "external_id": f"indeed_{jk or abs(hash(full_url))}",
                        "source": "Indeed",
                        "title": t_str,
                        "company": comp_el.get_text(strip=True) if comp_el else "",
                        "location": loc_text,
                        "country": cfg["name"],
                        "modality": job_mod,
                        "source_url": full_url,
                        "description_snippet": snip_el.get_text(" ", strip=True)[:280] if snip_el else "",
                        "raw_description": snip_el.get_text(" ", strip=True) if snip_el else "",
                        "salary_text": "",
                        "published_at": "Reciente",
                    })
                    if len(results) >= limit:
                        break
    except Exception:
        pass
    return results


# =====================================================================
# Fallback Demo Offers (Country-Specific & Profession-Aware)
# =====================================================================

def _get_demo_offers(query: str, location: str, country: str = "España", modality: str = "all") -> list[dict[str, Any]]:
    cfg = resolve_country_config(country)
    loc_base = location or cfg["name"]
    is_tech = _is_tech_role([query], query)

    if not is_tech:
        # Non-tech (e.g. Administrativa, Contable, Atención al cliente, etc.)
        demo = [
            {
                "external_id": "demo_admin_1",
                "source": "LinkedIn",
                "title": f"Auxiliar {query}/a - Facturación y Gestión Documental",
                "company": "Servicios Empresariales Integrales",
                "location": location or f"Barcelona, {cfg['name']}",
                "country": cfg["name"],
                "modality": "remote",
                "source_url": f"https://linkedin.com/jobs/view/demo-{query.lower()}-101",
                "description_snippet": f"Buscamos {query} con experiencia en gestión documental, facturación, conciliación bancaria y ERP.",
                "raw_description": (
                    f"Puesto de {query} en modalidad remota/híbrida.\n"
                    "Responsabilidades:\n"
                    "- Registro y control del ciclo de facturación y cobros.\n"
                    "- Gestión documental y archivo de expedientes.\n"
                    "- Manejo de sistemas ERP/CRM y ofimática.\n"
                    "- Atención a clientes y resolución de incidencias."
                ),
                "salary_text": "22.000€ - 26.000€",
                "published_at": "Hace 1 día",
            },
            {
                "external_id": "demo_admin_2",
                "source": "LinkedIn",
                "title": f"{query} de Oficina y Soporte Administrativo",
                "company": "Grupo Logístico y Comercial",
                "location": location or f"Madrid, {cfg['name']}",
                "country": cfg["name"],
                "modality": "hybrid",
                "source_url": f"https://linkedin.com/jobs/view/demo-{query.lower()}-202",
                "description_snippet": f"Puesto híbrido de {query} para tramitación de expedientes, control documental y facturación.",
                "raw_description": (
                    f"Puesto de {query} para soporte operativo y administrativo.\n"
                    "Requisitos:\n"
                    "- Experiencia previa en administración, facturación y gestión de expedientes.\n"
                    "- Dominio de Microsoft Office (Excel, Word).\n"
                    "- Capacidad de organización y gestión autónoma."
                ),
                "salary_text": "21.000€ - 25.000€",
                "published_at": "Hace 2 días",
            },
            {
                "external_id": "demo_admin_ij",
                "source": "InfoJobs",
                "title": f"{query} de Facturación y Cuentas a Cobrar",
                "company": "Distribuciones Mediterráneo",
                "location": location or f"Barcelona, {cfg['name']}",
                "country": cfg["name"],
                "modality": "hybrid",
                "source_url": "https://www.infojobs.net/barcelona/administrativo-facturacion/of-idemo123",
                "description_snippet": f"Empresa líder busca {query} para gestión de facturación, emisión de recibos y conciliación bancaria.",
                "raw_description": (
                    f"Puesto en InfoJobs para {query}.\n"
                    "Requisitos:\n"
                    "- Experiencia en ciclo de facturación y control documental.\n"
                    "- Trámites telemáticos y certificados digitales.\n"
                    "- Trabajo híbrido (2 días teletrabajo)."
                ),
                "salary_text": "23.000€ - 27.000€",
                "published_at": "Hace 1 día",
            },
            {
                "external_id": "demo_admin_indeed",
                "source": "Indeed",
                "title": f"Auxiliar {query}/a - Gestión y Atención al Cliente",
                "company": "Consultoría y Asistencia Global",
                "location": location or f"Madrid, {cfg['name']}",
                "country": cfg["name"],
                "modality": "remote",
                "source_url": "https://es.indeed.com/viewjob?jk=demo456",
                "description_snippet": f"Vacante en Indeed para {query} con habilidades en atención multicanal, trámites y archivo digital.",
                "raw_description": (
                    f"Vacante publicada en Indeed para {query}.\n"
                    "Requisitos:\n"
                    "- Registro y archivo documental.\n"
                    "- Atención telefónica y gestión de correspondencia.\n"
                    "- Modalidad 100% remota."
                ),
                "salary_text": "20.000€ - 24.000€",
                "published_at": "Hoy",
            },
        ]
    elif cfg["continent"] == "latam":
        demo = [
            {
                "external_id": "demo_latam_1",
                "source": "LinkedIn",
                "title": f"Senior {query} Developer",
                "company": f"NextGen Cloud {cfg['name']}",
                "location": f"{loc_base} / Remoto",
                "country": cfg["name"],
                "modality": "remote",
                "source_url": f"https://linkedin.com/jobs/view/demo-{query.lower()}-latam",
                "description_snippet": f"Buscamos desarrollador con experiencia en {query}, FastAPI, Docker y PostgreSQL en {cfg['name']}.",
                "raw_description": f"Desarrollador {query} en {cfg['name']}.\nRequisitos:\n- Experiencia con {query}.\n- SQL y Docker.\n- Modalidad 100% remota.",
                "salary_text": "3.500$ - 4.800$ USD/mes",
                "published_at": "Hace 1 día",
            },
            {
                "external_id": "demo_latam_2",
                "source": "Remotive",
                "title": f"Backend Engineer {query}",
                "company": "Latam Tech Hub",
                "location": f"{cfg['name']} (Híbrido)",
                "country": cfg["name"],
                "modality": "hybrid",
                "source_url": f"https://remotive.com/jobs/demo-latam-backend-{query.lower()}",
                "description_snippet": f"Puesto híbrido para desarrollo y optimización de microservicios con {query}.",
                "raw_description": f"Backend Engineer en {cfg['name']}.\nRequisitos:\n- {query}, APIs REST, Git y Linux.",
                "salary_text": "3.000$ - 4.200$ USD/mes",
                "published_at": "Hace 2 días",
            },
        ]
    elif cfg["continent"] == "na":
        demo = [
            {
                "external_id": "demo_us_1",
                "source": "LinkedIn",
                "title": f"Senior {query} Developer",
                "company": "NextGen Cloud US",
                "location": "Austin, TX / Remote",
                "country": "Estados Unidos",
                "modality": "remote",
                "source_url": f"https://linkedin.com/jobs/view/demo-us-{query.lower()}",
                "description_snippet": f"Leading US tech team looking for {query} engineer with cloud and Docker experience.",
                "raw_description": f"Senior {query} Engineer.\nRequirements: {query}, AWS, PostgreSQL, microservices.",
                "salary_text": "$120,000 - $145,000",
                "published_at": "Hace 1 día",
            },
            {
                "external_id": "demo_us_2",
                "source": "Jobicy",
                "title": f"Software Engineer - {query}",
                "company": "Apex Digital USA",
                "location": "New York, NY",
                "country": "Estados Unidos",
                "modality": "hybrid",
                "source_url": f"https://jobicy.com/jobs/demo-us-{query.lower()}",
                "description_snippet": f"Hybrid {query} developer role based in NYC with modern tech stack.",
                "raw_description": f"Software Engineer ({query}) in New York.\nRequirements: {query}, REST APIs, SQL, Docker.",
                "salary_text": "$110,000 - $130,000",
                "published_at": "Hace 2 días",
            },
        ]
    else:
        # Default: Spain & Europe Tech
        demo = [
            {
                "external_id": "demo_es_1",
                "source": "LinkedIn",
                "title": f"Senior {query} Developer",
                "company": "NextGen Cloud Iberia",
                "location": location or "Madrid / Remoto",
                "country": "España",
                "modality": "remote",
                "source_url": "https://es.linkedin.com/jobs/view/demo-python-developer-101",
                "description_snippet": f"Buscamos desarrollador con experiencia en {query}, FastAPI, Docker, PostgreSQL y arquitectura de microservicios. Trabajo 100% remoto en España.",
                "raw_description": (
                    f"Buscamos un {query} Developer para unirse a nuestro equipo de plataforma en España.\n"
                    "Requisitos:\n"
                    f"- Más de 3 años de experiencia con {query} (FastAPI o Django).\n"
                    "- Sólidos conocimientos de SQL (PostgreSQL) y diseño de APIs REST.\n"
                    "- Experiencia con Docker y Linux en producción.\n"
                    "- Control de versiones con Git y flujos CI/CD.\n"
                    "- Nivel de inglés B2 para comunicación técnica."
                ),
                "salary_text": "45.000€ - 55.000€",
                "published_at": "Hace 1 día",
            },
            {
                "external_id": "demo_es_2",
                "source": "Tecnoempleo",
                "title": f"Desarrollador Backend {query} / APIs",
                "company": "Soluciones Digitales 360",
                "location": location or "Barcelona, España",
                "country": "España",
                "modality": "hybrid",
                "source_url": "https://www.tecnoempleo.com/demo-backend-python-202/rf-demo1234",
                "description_snippet": "Puesto híbrido para desarrollo y optimización de APIs REST con integración continua y bases de datos relacionales.",
                "raw_description": (
                    "Desarrollador Backend para participar en proyectos de gran escala en España.\n"
                    "Requisitos:\n"
                    f"- Experiencia demostrable en desarrollo backend con {query}.\n"
                    "- Conocimiento de bases de datos relacionales (PostgreSQL, MySQL).\n"
                    "- Pruebas automatizadas (Pytest) y metodologías ágiles (Scrum).\n"
                    "- Trabajo híbrido flexible con 2 días de oficina."
                ),
                "salary_text": "38.000€ - 46.000€",
                "published_at": "Hace 2 días",
            },
            {
                "external_id": "demo_es_3",
                "source": "Remotive",
                "title": f"Full Stack {query} & TypeScript Engineer",
                "company": "OmniFlow Global",
                "location": "Remoto (España / UE)",
                "country": "España",
                "modality": "remote",
                "source_url": "https://remotive.com/jobs/demo-fullstack-python-303",
                "description_snippet": f"Equipo internacional 100% remoto disponible para candidatos en España y Europa. Stack principal: {query}, React / TypeScript, Docker, Cloud.",
                "raw_description": (
                    "Looking for a Full Stack Engineer to build fast, scalable web apps.\n"
                    "Requirements:\n"
                    f"- Experience with {query} & REST APIs.\n"
                    "- Frontend familiarity with TypeScript or React.\n"
                    "- Git, CI/CD, and Docker basics.\n"
                    "- Good English communication skills."
                ),
                "salary_text": "50.000$ - 65.000$",
                "published_at": "Hoy",
            },
            {
                "external_id": "demo_es_4",
                "source": "LinkedIn",
                "title": f"Ingeniero de Software {query} (Presencial)",
                "company": "Innovación Tecnológica Madrid",
                "location": "Madrid, España",
                "country": "España",
                "modality": "onsite",
                "source_url": "https://es.linkedin.com/jobs/view/demo-software-engineer-madrid-404",
                "description_snippet": f"Puesto presencial en nuestras oficinas de Madrid para ingenieros de software con experiencia en {query} y bases de datos.",
                "raw_description": f"Ingeniero de software presencial en Madrid.\nRequisitos: {query}, SQL, Linux, trabajo en equipo presencial.",
                "salary_text": "40.000€ - 48.000€",
                "published_at": "Hace 3 días",
            },
        ]

    if modality == "all":
        return demo
    return [d for d in demo if d["modality"] == modality or (modality == "hybrid" and d["modality"] == "remote")]


# =====================================================================
# Main Orchestrator: Search Across Portals, Filter & Score
# =====================================================================

async def search_and_score_jobs(
    cv_profile: dict[str, Any],
    facts: list[dict[str, Any]],
    search_prefs: dict[str, Any],
    query_override: Optional[str] = None,
    location_override: Optional[str] = None,
    country_override: Optional[str] = None,
    modality_override: Optional[str] = None,
    roles_override: Optional[list[str]] = None,
    from_cv: bool = False,
    limit: int = 45,
) -> list[dict[str, Any]]:
    # 0. Determine country & country config
    country = (country_override or search_prefs.get("country") or "España").strip()
    country_cfg = resolve_country_config(country)

    # 1. Determine queries to search
    queries: list[str] = []
    cleaned_override = [r.strip() for r in (roles_override or []) if r and r.strip()]
    if cleaned_override:
        queries = list(dict.fromkeys(cleaned_override))[:6]
    elif query_override and query_override.strip() and not from_cv:
        queries = [query_override.strip()]
    else:
        queries = get_search_queries_for_cv(cv_profile, facts, search_prefs, from_cv=from_cv)

    if not queries:
        queries = ["Administrativo"]

    is_tech = _is_tech_role(queries, cv_profile.get("raw_text") or "")

    location = (location_override or search_prefs.get("location") or country_cfg["name"]).strip()
    desired_modality = modality_override or search_prefs.get("modality") or "all"
    excluded_keywords = [k.lower().strip() for k in search_prefs.get("keywords_exclude") or [] if k.strip()]

    # 2. Launch concurrent tasks across portals according to country and profession type
    tasks = []
    for q in queries:
        # Universal portals (both tech and non-tech: LinkedIn, InfoJobs, Indeed)
        tasks.append(fetch_linkedin_jobs(q, location=location, country=country, modality=desired_modality, limit=25))
        tasks.append(fetch_infojobs_jobs(q, location=location, country=country, modality=desired_modality, limit=25))
        tasks.append(fetch_indeed_jobs(q, location=location, country=country, modality=desired_modality, limit=20))

        # Tecnoempleo and WeWorkRemotely ONLY for tech profiles!
        if is_tech:
            if country_cfg.get("allow_tecnoempleo", True):
                tasks.append(fetch_tecnoempleo_jobs(q, country=country, modality=desired_modality, limit=20))
            if desired_modality in ("all", "remote", "hybrid"):
                tasks.append(fetch_wwr_jobs(q, country=country, limit=15))

        # Remote / European general portals
        if desired_modality in ("all", "remote", "hybrid"):
            tasks.append(fetch_remotive_jobs(q, country=country, limit=15))
            if is_tech and country_cfg.get("allow_arbeitnow", True):
                tasks.append(fetch_arbeitnow_jobs(q, country=country, modality=desired_modality, limit=15))
            if is_tech:
                tasks.append(fetch_jobicy_jobs(q, country=country, limit=15))

    fetched_lists = await asyncio.gather(*tasks, return_exceptions=True)

    raw_candidates: list[dict[str, Any]] = []
    for fl in fetched_lists:
        if isinstance(fl, list):
            raw_candidates.extend(fl)

    # Fallback demo offers if network blocked or zero results
    if not raw_candidates:
        raw_candidates = _get_demo_offers(queries[0], location, country=country, modality=desired_modality)

    # 3. Deduplicate by URL and normalized (title + company)
    deduped: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_keys: set[str] = set()

    for item in raw_candidates:
        url = item.get("source_url", "").strip()
        if not url or url in seen_urls:
            continue
        key = f"{item.get('title', '').strip().lower()}:::{item.get('company', '').strip().lower()}"
        if key in seen_keys:
            continue

        seen_urls.add(url)
        seen_keys.add(key)

        combined_text = f"{item.get('title', '')} {item.get('description_snippet', '')} {item.get('raw_description', '')}".lower()
        if any(ex in combined_text for ex in excluded_keywords):
            continue

        # Country incompatibility gatekeeper
        job_loc_lower = f"{item.get('location', '')} {item.get('title', '')} {item.get('description_snippet', '')}".lower()
        if any(f in job_loc_lower for f in country_cfg.get("forbidden_locations", [])):
            if not any(ok in job_loc_lower for ok in ("worldwide", "remoto global", "anywhere", country_cfg["name"].lower())):
                continue

        job_mod = item.get("modality", "onsite")
        if desired_modality != "all":
            if desired_modality == "remote" and job_mod != "remote":
                continue
            if desired_modality == "hybrid" and job_mod not in ("hybrid", "remote"):
                continue
            if desired_modality == "onsite" and job_mod not in ("onsite", "hybrid"):
                continue

        # Tag job with country
        item["country"] = item.get("country") or country_cfg["name"]

        # Score against CV Base + Knowledge Facts
        scored = ai_engine.quick_score_job(
            job_offer=item,
            cv_profile=cv_profile,
            facts=facts,
        )
        item["match_score"] = scored["score"]
        item["match_reasons"] = scored["matched_skills"]
        item["missing_skills"] = scored["missing_skills"]

        deduped.append(item)

    # If all raw candidates were filtered out (e.g. strict modality filter), provide fallback demo offers
    if not deduped:
        fallback_demos = _get_demo_offers(queries[0], location, country=country, modality=desired_modality)
        for item in fallback_demos:
            item["country"] = item.get("country") or country_cfg["name"]
            scored = ai_engine.quick_score_job(
                job_offer=item,
                cv_profile=cv_profile,
                facts=facts,
            )
            item["match_score"] = scored["score"]
            item["match_reasons"] = scored["matched_skills"]
            item["missing_skills"] = scored["missing_skills"]
            deduped.append(item)

    # 4. Sort by match_score descending
    deduped.sort(key=lambda x: x.get("match_score", 0), reverse=True)
    top_jobs = deduped[:limit]

    # 5. Persist to SQLite
    database.save_discovered_jobs(top_jobs)

    # Return persisted list with database IDs
    return database.list_discovered_jobs(
        country=country_cfg["name"],
        modality=desired_modality if desired_modality != "all" else None,
        limit=limit,
    )
