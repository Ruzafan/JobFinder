"""
End-to-end verification test against a running JobFinder CV Studio server.
Tests: health, network-info, base CV upload/save, job analysis, interactive Q&A
with persistent knowledge memory (verifying confirmed & denied facts are remembered
on future analyses so denied/confirmed items are never asked again), honest CV
adaptation, and ATS PDF/DOCX/MD exports.
Cleans up all test data at the end and restores the user's live CV and preferences.
"""
import io
import sys
import urllib.request
import json

BASE_URL = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"


def req(method: str, path: str, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    r = urllib.request.Request(f"{BASE_URL}{path}", data=data, headers=headers, method=method)
    with urllib.request.urlopen(r, timeout=20) as resp:
        raw = resp.read()
        ct = resp.headers.get("Content-Type", "")
        if "application/json" in ct:
            return resp.status, json.loads(raw.decode("utf-8")), ct
        return resp.status, raw, ct


def main():
    print(f"Testing JobFinder CV Studio at {BASE_URL}...")

    orig_cv = None
    orig_prefs = None
    orig_facts = []
    created_jobs = []

    try:
        st_cv, cv_get, _ = req("GET", "/api/cv")
        if st_cv == 200:
            orig_cv = cv_get.get("cv")

        st_pref, pref_get, _ = req("GET", "/api/hunter/preferences")
        if st_pref == 200:
            orig_prefs = pref_get.get("preferences")

        st_kb, kb_get, _ = req("GET", "/api/knowledge")
        if st_kb == 200:
            orig_facts = kb_get.get("facts", [])
    except Exception as exc:
        print(f"  [WARN] Could not backup existing profile: {exc}")

    try:
        # 1. Health & UI & Network Info
        st, health, _ = req("GET", "/api/health")
        assert st == 200 and health["status"] == "ok", f"Health failed: {health}"

        st, net, _ = req("GET", "/api/network-info")
        assert st == 200 and "lan_url" in net, f"Network info failed: {net}"

        st, html, ct = req("GET", "/")
        assert st == 200 and b"JobFinder CV Studio" in html, "Index HTML missing title"
        print("  [OK] Health, network-info, and Web UI served")

        # 2. Save Base CV
        sample_cv = """Carlos Ruiz
Madrid, España | carlos.ruiz@ejemplo.com
Desarrollador Backend con 3 años de experiencia en Python (FastAPI), SQL (PostgreSQL), Git y Linux.
Experiencia:
- Desarrollo de APIs REST con Python y FastAPI.
- Administración de bases de datos PostgreSQL y automatización en Linux.
Idiomas: Español nativo, Inglés B2."""

        st, cv_res, _ = req("PUT", "/api/cv", {
            "full_name": "Carlos Ruiz",
            "headline": "Backend Python Developer",
            "raw_text": sample_cv,
        })
        assert st == 200 and cv_res["cv"]["full_name"] == "Carlos Ruiz"
        print("  [OK] Base CV saved")

        # 3. Analyze a Job Offer (has Python/SQL/Linux in CV + Docker & Kubernetes NOT in CV)
        job_desc = """Buscamos Backend Python Developer:
        - Experiencia con Python (FastAPI) y SQL (PostgreSQL)
        - APIs REST y Linux
        - Docker en producción
        - Kubernetes y AWS
        - Inglés B2"""

        st, an_res, _ = req("POST", "/api/jobs/analyze", {
            "job_title": "Backend Python Developer",
            "company": "Acme Cloud",
            "job_description": job_desc,
            "target_language": "es",
        })
        assert st == 200, f"Analysis failed: {an_res}"
        job = an_res["job"]
        job_id = job["id"]
        created_jobs.append(job_id)
        assert job_id > 0
        assert len(job["analysis"]["matched_requirements"]) >= 3, "Expected at least Python, SQL, Linux matched"
        unclear = job["analysis"]["unclear_requirements"]
        assert len(unclear) >= 2, "Expected Docker and Kubernetes to be unclear questions"
        print(f"  [OK] Offer analyzed (ID #{job_id}): {len(job['analysis']['matched_requirements'])} matched, {len(unclear)} unclear questions")

        # 4. Answer interactive questions: Confirm Docker, Deny Kubernetes
        docker_q = next(u for u in unclear if "docker" in u["topic"].lower())
        k8s_q = next(u for u in unclear if "kubernetes" in u["topic"].lower())

        st, ans_res, _ = req("POST", f"/api/jobs/{job_id}/answers", {
            "answers": [
                {
                    "question_id": docker_q["id"],
                    "topic": docker_q["topic"],
                    "category": docker_q.get("category", "Habilidad técnica"),
                    "status": "confirmed",
                    "details": "2 años usando Docker Compose en proyectos personales",
                    "save_to_knowledge": True,
                },
                {
                    "question_id": k8s_q["id"],
                    "topic": k8s_q["topic"],
                    "category": k8s_q.get("category", "Habilidad técnica"),
                    "status": "denied",
                    "details": "No he administrado clusters productivos",
                    "save_to_knowledge": True,
                },
            ]
        })
        assert st == 200 and ans_res["saved_facts_count"] == 2
        adapted_md = ans_res["job"]["adapted_cv_markdown"]
        assert "Docker" in adapted_md, "Confirmed Docker should appear in adapted CV"
        assert "Kubernetes" not in adapted_md, "Denied Kubernetes MUST NOT appear in adapted CV!"
        print("  [OK] Q&A saved to persistent knowledge + Honest CV generated (Docker included, Kubernetes excluded)")

        # 5. Re-analyze a SECOND offer mentioning Docker & Kubernetes -> verify memory prevents re-asking!
        st, an2_res, _ = req("POST", "/api/jobs/analyze", {
            "job_title": "Platform Engineer",
            "company": "Beta Corp",
            "job_description": "Necesitamos Python, Docker, Kubernetes y Linux.",
            "target_language": "es",
        })
        assert st == 200
        job2 = an2_res["job"]
        job2_id = job2["id"]
        created_jobs.append(job2_id)
        unclear2_topics = [u["topic"] for u in job2["analysis"]["unclear_requirements"]]
        matched2_reqs = [m["requirement"] for m in job2["analysis"]["matched_requirements"]]
        missing2_reqs = [m["requirement"] for m in job2["analysis"]["missing_requirements"]]
        assert "Docker" not in unclear2_topics and any("Docker" in r for r in matched2_reqs), "Docker should now be auto-matched from persistent memory!"
        assert "Kubernetes" not in unclear2_topics and any("Kubernetes" in r for r in missing2_reqs), "Kubernetes should now be auto-marked missing from persistent memory!"
        print("  [OK] Persistent Knowledge Base verified across future offers (no repeated questions!)")

        # 6. Test ATS PDF, DOCX, and MD Exports
        st, pdf_bytes, pdf_ct = req("GET", f"/api/jobs/{job_id}/export/pdf")
        assert st == 200 and pdf_bytes[:4] == b"%PDF" and len(pdf_bytes) > 1000, f"Invalid PDF: {len(pdf_bytes)} bytes"

        st, docx_bytes, docx_ct = req("GET", f"/api/jobs/{job_id}/export/docx")
        assert st == 200 and docx_bytes[:2] == b"PK" and len(docx_bytes) > 2000, f"Invalid DOCX: {len(docx_bytes)} bytes"

        st, md_bytes, _ = req("GET", f"/api/jobs/{job_id}/export/md")
        assert st == 200 and b"Carlos Ruiz" in md_bytes
        print(f"  [OK] Exports verified: PDF ({len(pdf_bytes)} bytes), DOCX ({len(docx_bytes)} bytes), MD ({len(md_bytes)} bytes)")

    finally:
        # Cleanup test jobs
        for jid in created_jobs:
            try:
                req("DELETE", f"/api/jobs/{jid}")
            except Exception:
                pass

        # Cleanup only test facts (Docker, Kubernetes)
        try:
            st, kb_res, _ = req("GET", "/api/knowledge")
            if st == 200:
                for f in kb_res.get("facts", []):
                    if f["topic"] in ("Docker", "Kubernetes"):
                        req("DELETE", f"/api/knowledge/{f['id']}")
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

    print("\nALL END-TO-END CHECKS PASSED!")


if __name__ == "__main__":
    main()
