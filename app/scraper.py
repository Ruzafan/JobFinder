import html
import json
import re
from typing import Any
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

BOT_BLOCK_MARKERS = [
    "cf-browser-verification",
    "attention required! | cloudflare",
    "verify you are human",
    "access denied",
    "enable javascript and cookies",
    "captcha",
    "authwall",
    "sign in to view",
    "inicia sesión para ver",
]


def _clean_text(text: str) -> str:
    text = html.unescape(text or "")
    text = re.sub(r"\r\n?", "\n", text)
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    cleaned: list[str] = []
    blank_streak = 0
    for ln in lines:
        if not ln:
            blank_streak += 1
            if blank_streak <= 1:
                cleaned.append("")
        else:
            blank_streak = 0
            cleaned.append(ln)
    return "\n".join(cleaned).strip()


def _extract_jsonld_job(soup: BeautifulSoup) -> dict[str, str] | None:
    scripts = soup.find_all("script", type="application/ld+json")
    for script in scripts:
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        try:
            payload = json.loads(raw)
        except Exception:
            continue

        candidates: list[Any] = []
        if isinstance(payload, list):
            candidates.extend(payload)
        elif isinstance(payload, dict):
            if "@graph" in payload and isinstance(payload["@graph"], list):
                candidates.extend(payload["@graph"])
            candidates.append(payload)

        for item in candidates:
            if not isinstance(item, dict):
                continue
            item_type = item.get("@type", "")
            types = item_type if isinstance(item_type, list) else [item_type]
            if any("JobPosting" in str(t) for t in types):
                title = str(item.get("title") or "").strip()
                org = item.get("hiringOrganization")
                company = ""
                if isinstance(org, dict):
                    company = str(org.get("name") or "").strip()
                elif isinstance(org, str):
                    company = org.strip()

                desc_raw = str(item.get("description") or "")
                desc_text = BeautifulSoup(desc_raw, "html.parser").get_text("\n")
                location = ""
                job_loc = item.get("jobLocation")
                if isinstance(job_loc, list) and job_loc:
                    job_loc = job_loc[0]
                if isinstance(job_loc, dict):
                    addr = job_loc.get("address")
                    if isinstance(addr, dict):
                        parts = [
                            addr.get("addressLocality", ""),
                            addr.get("addressRegion", ""),
                            addr.get("addressCountry", ""),
                        ]
                        location = ", ".join(p for p in parts if p)

                extras = []
                for field, label in [
                    ("qualifications", "Requisitos"),
                    ("skills", "Habilidades"),
                    ("responsibilities", "Responsabilidades"),
                    ("experienceRequirements", "Experiencia"),
                ]:
                    val = item.get(field)
                    if isinstance(val, str) and val.strip():
                        extras.append(f"{label}: {BeautifulSoup(val, 'html.parser').get_text(' ')}")
                    elif isinstance(val, list) and val:
                        extras.append(f"{label}: {', '.join(str(x) for x in val)}")

                full_desc = _clean_text(desc_text)
                if extras:
                    full_desc += "\n\n" + "\n".join(extras)
                if location:
                    full_desc = f"Ubicación: {location}\n\n{full_desc}"

                if len(full_desc) >= 80:
                    return {
                        "title": title,
                        "company": company,
                        "description": full_desc[:18000],
                    }
    return None


def _extract_main_html(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript", "svg", "iframe", "header", "footer", "nav", "aside", "form"]):
        tag.decompose()

    selectors = [
        "[class*='job-description']",
        "[class*='jobDescription']",
        "[id*='job-description']",
        "[id*='jobDescription']",
        "[class*='description__text']",
        "[class*='posting-page']",
        "article",
        "main",
        "[role='main']",
    ]
    best_text = ""
    for sel in selectors:
        for node in soup.select(sel):
            text = _clean_text(node.get_text("\n"))
            if len(text) > len(best_text):
                best_text = text
        if len(best_text) >= 400:
            break

    if len(best_text) < 250:
        body = soup.body or soup
        best_text = _clean_text(body.get_text("\n"))

    return best_text[:18000]


async def fetch_job_from_url(url: str) -> dict[str, Any]:
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return {
            "success": False,
            "error": "La URL no es válida. Debe empezar por http:// o https://",
        }

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
    }

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=18.0) as client:
            resp = await client.get(url, headers=headers)
    except httpx.TimeoutException:
        return {
            "success": False,
            "error": "La página tardó demasiado en responder. Copia y pega la descripción de la oferta manualmente.",
        }
    except Exception as exc:
        return {
            "success": False,
            "error": f"No se pudo conectar con la URL ({type(exc).__name__}). Pega la descripción directamente.",
        }

    if resp.status_code in (401, 403, 429):
        return {
            "success": False,
            "error": (
                f"Esta web bloquea la lectura automática (HTTP {resp.status_code}) o requiere iniciar sesión. "
                "Copia y pega el texto de la oferta en el cuadro de descripción y funcionará perfectamente."
            ),
        }

    if resp.status_code >= 400:
        return {
            "success": False,
            "error": f"La URL devolvió un error HTTP {resp.status_code}. Comprueba el enlace o pega el texto de la oferta.",
        }

    body_text = resp.text or ""
    lower_sample = body_text[:6000].lower()
    if any(marker in lower_sample for marker in BOT_BLOCK_MARKERS) and len(body_text) < 25000:
        return {
            "success": False,
            "error": (
                "La web protege la oferta con verificación antibot o inicio de sesión. "
                "Copia y pega la descripción de la oferta manualmente abajo."
            ),
        }

    soup = BeautifulSoup(body_text, "html.parser")

    # 1) Try structured JSON-LD JobPosting first
    jsonld = _extract_jsonld_job(soup)
    if jsonld:
        return {
            "success": True,
            "source_url": str(resp.url),
            "title": jsonld["title"],
            "company": jsonld["company"],
            "description": jsonld["description"],
            "method": "json-ld",
        }

    # 2) Extract title/company from meta tags + HTML
    page_title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title and og_title.get("content"):
        page_title = str(og_title["content"]).strip()
    elif soup.title and soup.title.string:
        page_title = soup.title.string.strip()

    company = ""
    og_site = soup.find("meta", property="og:site_name")
    if og_site and og_site.get("content"):
        site_name = str(og_site["content"]).strip()
        if site_name.lower() not in ("linkedin", "indeed", "infojobs", "glassdoor", "tecnoempleo"):
            company = site_name

    # Clean common suffixes like "Senior Dev - Empresa | LinkedIn"
    if " | " in page_title:
        page_title = page_title.split(" | ")[0].strip()

    description = _extract_main_html(soup)
    if len(description) < 100:
        return {
            "success": False,
            "error": (
                "No se pudo extraer suficiente texto útil de esta página (probablemente carga el contenido con JavaScript o requiere login). "
                "Copia y pega la descripción de la oferta abajo."
            ),
        }

    return {
        "success": True,
        "source_url": str(resp.url),
        "title": page_title[:160],
        "company": company[:120],
        "description": description,
        "method": "html",
    }
