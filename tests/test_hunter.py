"""
End-to-end tests for Job Hunter & Discovery system in JobFinder CV Studio:
- Preferences GET & PUT
- Preferences auto-detect from CV Base
- Multi-source search & scoring against candidate profile (tech & non-tech)
- Multi-country & modality routing
- List discovered jobs with filters (score, modality, search)
- Job status updates (save, dismiss)
- 1-click conversion from discovered job to honest adapted CV (with PDF/Word export)
- Automatic backup and restore of live user CV and preferences so tests never overwrite user data
"""
import json
import sys
import urllib.request

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def req(method: str, path: str, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    r = urllib.request.Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=25) as resp:
        raw = resp.read()
        ct = resp.headers.get("Content-Type", "")
        if "application/json" in ct:
            return resp.status, json.loads(raw.decode("utf-8")), ct
        return resp.status, raw, ct


def main():
    print(f"Testing Job Hunter & Discovery at {BASE_URL}...")

    # Backup existing user data to ensure live DB is never corrupted
    orig_cv = None
    orig_prefs = None
    created_analysis_ids = []
    created_job_ids = []

    try:
        st_cv, cv_get, _ = req("GET", "/api/cv")
        if st_cv == 200:
            orig_cv = cv_get.get("cv")

        st_pref, pref_get, _ = req("GET", "/api/hunter/preferences")
        if st_pref == 200:
            orig_prefs = pref_get.get("preferences")
    except Exception as exc:
        print(f"  [WARN] Could not backup existing profile: {exc}")

    try:
        # =========================================================
        # 1. Tech Candidate Test (Marc Developer)
        # =========================================================
        sample_cv = """Marc Developer
Barcelona, España | marc@ejemplo.com
Senior Python Backend Developer con 5 años de experiencia creando microservicios en Python (FastAPI, Django), PostgreSQL, Docker y Linux.
Experiencia:
- Arquitectura de microservicios en FastAPI y Docker.
- Optimización de bases de datos PostgreSQL.
Idiomas: Español nativo, Inglés B2."""

        st, cv_res, _ = req("PUT", "/api/cv", {
            "full_name": "Marc Developer",
            "headline": "Senior Python Backend Developer | FastAPI & Cloud",
            "raw_text": sample_cv,
        })
        assert st == 200 and cv_res["cv"]["full_name"] == "Marc Developer"
        print("  [OK] Tech Test CV set up")

        # 2. Preferences GET and Auto-detect
        st, prefs_res, _ = req("GET", "/api/hunter/preferences")
        assert st == 200 and "target_roles" in prefs_res["preferences"]
        print("  [OK] Preferences retrieved")

        st, detect_res, _ = req("POST", "/api/hunter/preferences/auto-detect")
        assert st == 200
        detected = detect_res["preferences"]
        assert any("Python" in r or "Backend" in r for r in detected["target_roles"]), f"Unexpected roles: {detected['target_roles']}"
        assert "Barcelona, España" in detected["location"]
        print(f"  [OK] Auto-detected preferences: roles={detected['target_roles']}, loc={detected['location']}")

        # 3. Save updated preferences
        st, save_pref_res, _ = req("PUT", "/api/hunter/preferences", {
            "target_roles": ["Python Developer", "Backend Engineer"],
            "location": "España",
            "country": "España",
            "modality": "remote",
            "experience_level": "senior",
            "keywords_include": ["Python", "FastAPI", "Docker", "PostgreSQL"],
            "keywords_exclude": ["PHP", "WordPress"],
            "preferred_sources": ["remotive", "arbeitnow", "web_boards"],
        })
        assert st == 200
        saved = save_pref_res["preferences"]
        assert saved["modality"] == "remote"
        assert saved.get("country") == "España"
        assert "PHP" in saved["keywords_exclude"]
        print("  [OK] Preferences updated with country=España")

        # 4. Search anchored directly to the uploaded CV (from_cv=True) for España
        st, search_res, _ = req("POST", "/api/hunter/search", {
            "from_cv": True,
            "country": "España",
            "modality": "all",
            "limit": 25,
        })
        assert st == 200
        jobs = search_res["jobs"]
        assert len(jobs) > 0, "Expected at least 1 job discovered from CV"
        for j in jobs:
            loc_low = (j.get("location") or "").lower()
            assert "estados unidos" not in loc_low and "united states" not in loc_low, f"US job leaked in Spain search: {j['title']} ({j['location']})"
        first_job = jobs[0]
        assert "match_score" in first_job
        assert "match_reasons" in first_job
        sources_found = list({j.get("source") for j in jobs})
        print(f"  [OK] Tech Search for España found {len(jobs)} verified jobs across sources: {sources_found}. Zero US jobs leaked. Top: «{first_job['title']}» ({first_job['match_score']}% affinity)")

        # 4b. Test search for another country (México)
        st, search_mex, _ = req("POST", "/api/hunter/search", {
            "query": "Python Developer",
            "country": "México",
            "modality": "all",
            "limit": 10,
        })
        assert st == 200 and len(search_mex["jobs"]) > 0
        mex_jobs = search_mex["jobs"]
        print(f"  [OK] Country search for México succeeded ({len(mex_jobs)} jobs). Top: «{mex_jobs[0]['title']}» in {mex_jobs[0]['location']}")

        # 4c. Test modality filter (hybrid / remote)
        st, search_hybrid, _ = req("POST", "/api/hunter/search", {
            "from_cv": True,
            "country": "España",
            "modality": "hybrid",
            "limit": 15,
        })
        assert st == 200 and len(search_hybrid["jobs"]) > 0
        print(f"  [OK] Hybrid Modality search succeeded ({len(search_hybrid['jobs'])} jobs)")

        # 5. List discovered jobs with filters
        st, list_res, _ = req("GET", "/api/hunter/jobs?min_score=50")
        assert st == 200 and list_res["count"] > 0
        print(f"  [OK] Filtered list retrieved ({list_res['count']} jobs >= 50% match)")

        # 6. Status update: Toggle Save and Dismiss
        target_job = list_res["jobs"][0]
        job_id = target_job["id"]
        created_job_ids.append(job_id)
        st, patch_res, _ = req("PATCH", f"/api/hunter/jobs/{job_id}/status", {"status": "saved"})
        assert st == 200 and patch_res["job"]["status"] == "saved"

        st, saved_list, _ = req("GET", "/api/hunter/jobs?status=saved")
        assert st == 200 and any(j["id"] == job_id for j in saved_list["jobs"])
        print("  [OK] Job status saved & verified in saved filter")

        # 7. Convert discovered job to adapted CV (1-click pipeline!)
        st, convert_res, _ = req("POST", f"/api/hunter/jobs/{job_id}/convert-to-analysis", {
            "target_language": "es",
            "extra_instructions": "Enfocar en APIs y arquitectura",
        })
        assert st == 200
        analysis_job = convert_res["job_analysis"]
        analysis_id = analysis_job["id"]
        created_analysis_ids.append(analysis_id)
        assert len(analysis_job.get("adapted_cv_markdown", "")) > 100, "Adapted CV markdown should be populated"
        print(f"  [OK] 1-Click Convert: Created analysis #{analysis_id} and generated adapted CV ({len(analysis_job['adapted_cv_markdown'])} chars)")

        # 8. Export PDF and DOCX for the converted job
        st, pdf_bytes, _ = req("GET", f"/api/jobs/{analysis_id}/export/pdf")
        assert st == 200 and pdf_bytes[:4] == b"%PDF"

        st, docx_bytes, _ = req("GET", f"/api/jobs/{analysis_id}/export/docx")
        assert st == 200 and docx_bytes[:2] == b"PK"
        print(f"  [OK] Converted job exports verified: PDF ({len(pdf_bytes)} bytes), Word ({len(docx_bytes)} bytes)")

        # =========================================================
        # 9. Non-Tech / Administrative Profile Test
        # Verifies that an administrative CV searches administrative offers, NOT python/tech!
        # =========================================================
        admin_cv = """Gaële Parés
Barcelona, España | gaele@ejemplo.com
Administrativa y Auxiliar de Gestión Documental con más de 5 años de experiencia en facturación, contabilidad, gestión de cobros y atención al cliente.
Experiencia:
- Administrativa — Gestión de facturas, conciliación bancaria y archivo documental.
- Auxiliar Administrativa — Atención telefónica y presencial, redacción de informes y archivo.
Idiomas: Español nativo, Catalán nativo, Francés bilingüe."""

        st, cv_admin_res, _ = req("PUT", "/api/cv", {
            "full_name": "Gaële Parés",
            "headline": "Administrativa / Auxiliar Administrativo",
            "raw_text": admin_cv,
        })
        assert st == 200
        print("  [OK] Administrative CV set up")

        # Auto-detect preferences for administrative CV
        st, det_admin_res, _ = req("POST", "/api/hunter/preferences/auto-detect")
        assert st == 200
        admin_prefs = det_admin_res["preferences"]
        assert any("administrativ" in r.lower() or "facturación" in r.lower() for r in admin_prefs["target_roles"]), f"Expected administrative role, got: {admin_prefs['target_roles']}"
        assert not any("python" in r.lower() or "developer" in r.lower() for r in admin_prefs["target_roles"]), f"Tech roles leaked into admin profile: {admin_prefs['target_roles']}"
        print(f"  [OK] Admin Auto-detect verified: {admin_prefs['target_roles']}")

        # Search anchored to CV
        st, admin_search_res, _ = req("POST", "/api/hunter/search", {
            "from_cv": True,
            "country": "España",
            "modality": "all",
            "limit": 20,
        })
        assert st == 200
        admin_jobs = admin_search_res["jobs"]
        assert len(admin_jobs) > 0, "Expected administrative jobs to be found"

        # Verify NO python/developer jobs returned for an administrative candidate!
        for aj in admin_jobs:
            title_low = aj["title"].lower()
            desc_low = aj["description_snippet"].lower()
            assert "python developer" not in title_low and "backend developer" not in title_low, f"Tech job leaked in administrative search: {aj['title']}"
            assert "full stack" not in title_low and "devops" not in title_low, f"Tech job leaked: {aj['title']}"

        print(f"  [OK] Administrative search verified ({len(admin_jobs)} jobs). 0% tech leakage. Top: «{admin_jobs[0]['title']}» ({admin_jobs[0]['match_score']}%)")

    finally:
        # Cleanup any jobs and analyses created during test
        for aid in created_analysis_ids:
            try:
                req("DELETE", f"/api/jobs/{aid}")
            except Exception:
                pass
        for jid in created_job_ids:
            try:
                req("DELETE", f"/api/hunter/jobs/{jid}")
            except Exception:
                pass

        # RESTORE original live CV and preferences so user workspace is 100% preserved
        if orig_cv and orig_cv.get("raw_text"):
            try:
                req("PUT", "/api/cv", {
                    "full_name": orig_cv.get("full_name") or "",
                    "headline": orig_cv.get("headline") or "",
                    "raw_text": orig_cv.get("raw_text") or "",
                    "filename": orig_cv.get("filename") or "",
                })
                print("  [RESTORE] Original user CV successfully restored.")
            except Exception as exc:
                print(f"  [WARN] Failed restoring original CV: {exc}")

        if orig_prefs:
            try:
                req("PUT", "/api/hunter/preferences", {
                    "target_roles": orig_prefs.get("target_roles") or [],
                    "location": orig_prefs.get("location") or "España",
                    "country": orig_prefs.get("country") or "España",
                    "modality": orig_prefs.get("modality") or "all",
                    "experience_level": orig_prefs.get("experience_level") or "mid",
                    "keywords_include": orig_prefs.get("keywords_include") or [],
                    "keywords_exclude": orig_prefs.get("keywords_exclude") or [],
                    "min_salary": orig_prefs.get("min_salary"),
                    "preferred_sources": orig_prefs.get("preferred_sources") or ["linkedin"],
                })
                print("  [RESTORE] Original search preferences successfully restored.")
            except Exception as exc:
                print(f"  [WARN] Failed restoring original preferences: {exc}")

    print("\nALL JOB HUNTER CHECKS (TECH + ADMINISTRATIVE) PASSED SUCCESSFULLY!")


if __name__ == "__main__":
    main()
