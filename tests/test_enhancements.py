from fastapi.testclient import TestClient
from app.database import init_db
from app.main import app

init_db()
client = TestClient(app)

def test_health():
    res = client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"

def test_multi_profile_cv():
    # List profiles
    res = client.get("/api/cv/profiles")
    assert res.status_code == 200
    profiles = res.json()["profiles"]
    assert len(profiles) >= 1

    # Create a new profile
    new_prof = {
        "profile_name": "Administrativa y Facturación",
        "full_name": "Gaële Rose Parés",
        "headline": "Responsable de Administración y Facturación",
        "raw_text": "Gaële Rose Parés\nAdministrativa con 8 años de experiencia en facturación, gestión documental y atención al cliente en Barcelona.",
        "set_active": True
    }
    create_res = client.post("/api/cv/profiles", json=new_prof)
    assert create_res.status_code == 200
    created = create_res.json()["profile"]
    assert created["profile_name"] == "Administrativa y Facturación"
    assert created["is_active"] == 1
    new_id = created["id"]

    # Switch active profile back to 1
    switch_res = client.post("/api/cv/profiles/1/active")
    assert switch_res.status_code == 200
    assert switch_res.json()["profile"]["id"] == 1

    # Delete the created profile
    del_res = client.delete(f"/api/cv/profiles/{new_id}")
    assert del_res.status_code == 200

def test_kanban_application_tracker():
    # Create application
    payload = {
        "job_title": "Administrativa Comercial",
        "company": "Empresa Demo SL",
        "location": "Barcelona",
        "stage": "saved",
        "salary_discussed": "24.000€",
        "contact_name": "Marta RRHH",
        "notes": "Primera toma de contacto prometedora"
    }
    create_res = client.post("/api/tracker", json=payload)
    assert create_res.status_code == 200
    app_data = create_res.json()["application"]
    app_id = app_data["id"]
    assert app_data["job_title"] == "Administrativa Comercial"
    assert app_data["stage"] == "saved"

    # List applications
    list_res = client.get("/api/tracker")
    assert list_res.status_code == 200
    apps = list_res.json()["applications"]
    assert any(a["id"] == app_id for a in apps)

    # Change stage to interviewing
    patch_res = client.patch(f"/api/tracker/{app_id}", json={"stage": "interviewing", "notes": "Entrevista fijada para el jueves"})
    assert patch_res.status_code == 200
    assert patch_res.json()["application"]["stage"] == "interviewing"

    # Delete application
    del_res = client.delete(f"/api/tracker/{app_id}")
    assert del_res.status_code == 200

def test_cover_letter_pitch_and_interview_prep():
    # Analyze a job offer first
    job_payload = {
        "job_title": "Auxiliar Administrativo / Facturación",
        "company": "Logística Catalana",
        "job_description": "Empresa de logística en Barcelona precisa Auxiliar Administrativo con experiencia en facturación, albaranes, ERP y atención telefónica a clientes. Muy valorable nivel de catalán y paquete Office.",
        "target_language": "es"
    }
    analyze_res = client.post("/api/jobs/analyze", json=job_payload)
    assert analyze_res.status_code == 200
    job_id = analyze_res.json()["job"]["id"]

    # Adapt CV
    adapt_res = client.post(f"/api/jobs/{job_id}/adapt", json={"extra_instructions": ""})
    assert adapt_res.status_code == 200

    # 1. Cover letter generation
    cl_res = client.post(f"/api/jobs/{job_id}/cover-letter", json={"tone": "profesional y persuasivo"})
    assert cl_res.status_code == 200
    cl_md = cl_res.json()["cover_letter_markdown"]
    assert len(cl_md) > 50
    assert "Carta de Presentación" in cl_md or "Logística Catalana" in cl_md

    # Cover letter export PDF and DOCX
    cl_pdf_res = client.get(f"/api/jobs/{job_id}/export-cover-letter/pdf")
    assert cl_pdf_res.status_code == 200
    assert cl_pdf_res.headers["content-type"] == "application/pdf"
    assert len(cl_pdf_res.content) > 500

    cl_docx_res = client.get(f"/api/jobs/{job_id}/export-cover-letter/docx")
    assert cl_docx_res.status_code == 200
    assert len(cl_docx_res.content) > 500

    # 2. Recruiter pitch generation
    pitch_res = client.post(f"/api/jobs/{job_id}/recruiter-pitch", json={"channel": "linkedin", "recipient_name": "Laura"})
    assert pitch_res.status_code == 200
    pitch_text = pitch_res.json()["recruiter_pitch_text"]
    assert len(pitch_text) > 40
    assert "Laura" in pitch_text

    # 3. Interview simulator
    prep_res = client.post(f"/api/jobs/{job_id}/interview-prep", json={"target_language": "es"})
    assert prep_res.status_code == 200
    prep_data = prep_res.json()["interview_prep"]
    assert "questions" in prep_data
    assert len(prep_data["questions"]) >= 5
    assert "star_framework" in prep_data["questions"][0]
    assert "smart_questions_to_ask" in prep_data
    assert len(prep_data["smart_questions_to_ask"]) >= 3

    # 4. ATS Templates export with compact & strict_one_page
    pdf_harvard = client.get(f"/api/jobs/{job_id}/export/pdf?template=harvard&strict_one_page=false")
    assert pdf_harvard.status_code == 200

    pdf_compact = client.get(f"/api/jobs/{job_id}/export/pdf?template=compact&strict_one_page=true")
    assert pdf_compact.status_code == 200

    docx_res = client.get(f"/api/jobs/{job_id}/export/docx?template=modern")
    assert docx_res.status_code == 200

def test_daily_digest_and_bookmarklet():
    # Bookmarklet script endpoint
    bm_res = client.get("/api/bookmarklet.js")
    assert bm_res.status_code == 200
    assert "javascript" in bm_res.headers["content-type"]

    # Daily digest latest
    digest_res = client.get("/api/digest/latest")
    assert digest_res.status_code == 200

if __name__ == "__main__":
    print("Testing health...")
    test_health()
    print("Testing multi-profile CV...")
    test_multi_profile_cv()
    print("Testing kanban application tracker...")
    test_kanban_application_tracker()
    print("Testing cover letter, recruiter pitch & interview simulator...")
    test_cover_letter_pitch_and_interview_prep()
    print("Testing daily digest & bookmarklet...")
    test_daily_digest_and_bookmarklet()
    print("ALL ENHANCEMENTS PASSED SUCCESSFULLY!")

