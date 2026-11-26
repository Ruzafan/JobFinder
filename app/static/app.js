(() => {
  const state = {
    cv: null,
    facts: [],
    jobs: [],
    currentJob: null,
    settings: null,
    network: { lan_url: window.location.origin, local_url: "http://localhost:8000", port: "8000" },
    kbFilter: "",
    selectedProvider: "local",
    qaSelections: {}, // question_id -> { status, details, save_to_knowledge, topic, category }
    hunterPrefs: null,
    discoveredJobs: [],
    hunterFilter: "all",
    hunterModality: "all",
    hunterCountry: "España",
    customCountry: "",
  };

  const DEFAULT_MODELS = {
    local: "motor-local-v1",
    gemini: "gemini-2.5-flash",
    openai: "gpt-4o-mini",
    anthropic: "claude-3-5-sonnet-latest",
    ollama: "llama3.1",
  };

  const PROVIDER_LABELS = {
    local: "Modo Local",
    gemini: "Google Gemini",
    openai: "OpenAI",
    anthropic: "Claude",
    ollama: "Ollama Local",
  };

  const $ = (id) => document.getElementById(id);

  // ---------- Helpers ----------
  function showLoading(msg = "Procesando...") {
    $("loadingText").textContent = msg;
    $("loadingOverlay").classList.remove("hidden");
  }

  function hideLoading() {
    $("loadingOverlay").classList.add("hidden");
  }

  let toastTimer = null;
  function showToast(msg, isError = false) {
    const el = $("toast");
    el.textContent = msg;
    el.className = "toast" + (isError ? " error" : "");
    el.classList.remove("hidden");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.add("hidden"), 4000);
  }

  async function api(url, opts = {}) {
    const res = await fetch(url, opts);
    const contentType = res.headers.get("content-type") || "";
    const data = contentType.includes("application/json") ? await res.json() : await res.text();
    if (!res.ok) {
      const detail = typeof data === "object" && data?.detail ? data.detail : `Error HTTP ${res.status}`;
      throw new Error(detail);
    }
    return data;
  }

  function esc(str) {
    return String(str ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderMarkdownToHtml(md) {
    const lines = String(md || "").replace(/\r\n/g, "\n").split("\n");
    const out = [];
    let inList = false;

    const inlineFmt = (txt) =>
      esc(txt)
        .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
        .replace(/`(.+?)`/g, "<code>$1</code>");

    for (const raw of lines) {
      const line = raw.trim();
      if (!line) {
        if (inList) { out.push("</ul>"); inList = false; }
        continue;
      }
      if (line.startsWith("# ")) {
        if (inList) { out.push("</ul>"); inList = false; }
        out.push(`<h1>${inlineFmt(line.slice(2))}</h1>`);
      } else if (line.startsWith("## ")) {
        if (inList) { out.push("</ul>"); inList = false; }
        out.push(`<h2>${inlineFmt(line.slice(3))}</h2>`);
      } else if (line.startsWith("### ")) {
        if (inList) { out.push("</ul>"); inList = false; }
        out.push(`<h3>${inlineFmt(line.slice(4))}</h3>`);
      } else if (/^[-*•]\s+/.test(line)) {
        if (!inList) { out.push("<ul>"); inList = true; }
        out.push(`<li>${inlineFmt(line.replace(/^[-*•]\s+/, ""))}</li>`);
      } else if (/^[-_*]{3,}$/.test(line)) {
        if (inList) { out.push("</ul>"); inList = false; }
        out.push("<hr/>");
      } else {
        if (inList) { out.push("</ul>"); inList = false; }
        out.push(`<p>${inlineFmt(line)}</p>`);
      }
    }
    if (inList) out.push("</ul>");
    return out.join("\n");
  }

  function switchView(viewName) {
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    document.querySelectorAll(".nav-item").forEach((n) => n.classList.remove("active"));
    const target = $(`view-${viewName}`);
    if (target) target.classList.add("active");
    const navBtn = document.querySelector(`.nav-item[data-view="${viewName}"]`);
    if (navBtn) navBtn.classList.add("active");
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // ---------- Minimal SVG QR Generator (Pure JS, works offline on LAN!) ----------
  // Uses a clean fallback badge + quick-copy if QR API is not loaded, OR renders an inline visual matrix
  function renderLanQr(url) {
    const wrap = $("wifiQrWrap");
    // Render crisp QR using free lightweight QR image when online, with clean offline fallback
    const encoded = encodeURIComponent(url);
    wrap.innerHTML = `
      <img
        src="https://api.qrserver.com/v1/create-qr-code/?size=180x180&margin=6&data=${encoded}"
        alt="Código QR para abrir ${esc(url)}"
        width="180"
        height="180"
        style="display:block;border-radius:6px;"
        onerror="this.parentElement.innerHTML='<div style=\\'color:#334155;font-size:0.85rem;padding:12px;text-align:center;\\'>Escribe esta dirección en el navegador de tu móvil:<br/><strong>${esc(url)}</strong></div>'"
      />
    `;
  }

  // ---------- Initial Data Load ----------
  async function loadAll() {
    try {
      const [cvRes, kbRes, jobsRes, setRes, netRes, prefsRes, hunterRes] = await Promise.all([
        api("/api/cv"),
        api("/api/knowledge"),
        api("/api/jobs"),
        api("/api/settings"),
        api("/api/network-info"),
        api("/api/hunter/preferences"),
        api("/api/hunter/jobs"),
      ]);
      state.cv = cvRes.cv;
      state.facts = kbRes.facts || [];
      state.jobs = jobsRes.jobs || [];
      state.settings = setRes.settings;
      state.network = netRes;
      state.hunterPrefs = prefsRes.preferences;
      state.discoveredJobs = hunterRes.jobs || [];

      renderCvState();
      renderKnowledge();
      renderHistory();
      renderSettings();
      renderNetwork();
      renderHunter();
    } catch (err) {
      showToast(err.message, true);
    }
  }

  function renderNetwork() {
    const lanUrl = state.network.lan_url || window.location.origin;
    const localUrl = state.network.local_url || "http://localhost:8000";
    $("settingsLanUrl").textContent = lanUrl;
    $("modalLanUrl").textContent = lanUrl;
    $("modalLocalUrl").textContent = localUrl;
    $("settingsPort").textContent = state.network.port || "8000";
    renderLanQr(lanUrl);
  }

  // ---------- Base CV ----------
  function renderCvState() {
    const hasCv = Boolean(state.cv && state.cv.raw_text && state.cv.raw_text.trim().length >= 20);
    const badge = $("navCvStatus");
    badge.textContent = hasCv ? "Listo" : "Pendiente";
    badge.className = "nav-badge " + (hasCv ? "ok" : "warn");
    $("missingCvBanner").classList.toggle("hidden", hasCv);
    $("hunterMissingCvBanner").classList.toggle("hidden", hasCv);

    if (state.cv) {
      $("cvFullName").value = state.cv.full_name || "";
      $("cvHeadline").value = state.cv.headline || "";
      $("cvRawText").value = state.cv.raw_text || "";
      if (state.cv.filename) {
        $("uploadedFileBadge").textContent = `Archivo actual: ${state.cv.filename}`;
        $("uploadedFileBadge").classList.remove("hidden");
      }
      if (state.cv.updated_at) {
        const dt = new Date(state.cv.updated_at);
        $("cvLastUpdated").textContent = `Última actualización: ${dt.toLocaleString("es-ES")}`;
      }
    }
  }

  async function handleFileUpload(file) {
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    showLoading(`Leyendo ${file.name}...`);
    try {
      const res = await api("/api/cv/upload", { method: "POST", body: form });
      state.cv = res.cv;
      renderCvState();
      showToast(`CV importado correctamente (${res.chars_extracted} caracteres extraídos).`);
    } catch (err) {
      showToast(err.message, true);
    } finally {
      hideLoading();
      $("cvFileInput").value = "";
    }
  }

  async function saveBaseCv() {
    const raw_text = $("cvRawText").value.trim();
    if (raw_text.length < 20) {
      showToast("Introduce al menos un resumen de tu CV antes de guardarlo.", true);
      return;
    }
    showLoading("Guardando CV Base...");
    try {
      const res = await api("/api/cv", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          full_name: $("cvFullName").value.trim(),
          headline: $("cvHeadline").value.trim(),
          raw_text,
        }),
      });
      state.cv = res.cv;
      renderCvState();
      showToast("CV Base guardado como fuente de verdad.");
    } catch (err) {
      showToast(err.message, true);
    } finally {
      hideLoading();
    }
  }

  // ---------- Knowledge Base ----------
  function renderKnowledge() {
    const all = state.facts || [];
    $("navKbCount").textContent = all.length;
    $("kbStatConfirmed").textContent = all.filter((f) => f.status === "confirmed").length;
    $("kbStatPartial").textContent = all.filter((f) => f.status === "partial").length;
    $("kbStatDenied").textContent = all.filter((f) => f.status === "denied").length;

    const search = ($("kbSearchInput").value || "").trim().toLowerCase();
    const filtered = all.filter((f) => {
      if (state.kbFilter && f.status !== state.kbFilter) return false;
      if (search) {
        const hay = `${f.topic} ${f.details} ${f.category}`.toLowerCase();
        if (!hay.includes(search)) return false;
      }
      return true;
    });

    const container = $("kbList");
    if (!filtered.length) {
      container.innerHTML = `<div class="empty-inline">Aún no hay elementos aquí. A medida que respondas preguntas sobre ofertas (o añadas datos arriba), tu memoria permanente crecerá automáticamente.</div>`;
      return;
    }

    const statusMeta = {
      confirmed: { label: "✅ Confirmado", cls: "tag-ok" },
      partial: { label: "🟡 Parcial / Básico", cls: "tag-warn" },
      denied: { label: "⛔ Descartado", cls: "tag-no" },
    };

    container.innerHTML = filtered
      .map((f) => {
        const st = statusMeta[f.status] || statusMeta.confirmed;
        const src = f.source === "qa_session" ? "Aprendido de oferta" : "Manual";
        return `
          <div class="kb-card" data-fact-id="${f.id}">
            <div class="kb-card-main">
              <div>
                <span class="tag ${st.cls}">${st.label}</span>
                <span class="tag tag-soft">${esc(f.category)}</span>
                <span class="muted small"> · ${src}</span>
              </div>
              <div style="font-weight:700;margin-top:4px;">${esc(f.topic)}</div>
              ${f.details ? `<div class="muted small" style="margin-top:4px;">${esc(f.details)}</div>` : ""}
            </div>
            <div class="kb-card-actions">
              <button class="btn btn-ghost btn-sm" data-cycle-fact="${f.id}" title="Cambiar estado">Cambiar estado</button>
              <button class="btn btn-danger btn-sm" data-del-fact="${f.id}" title="Eliminar">Eliminar</button>
            </div>
          </div>
        `;
      })
      .join("");
  }

  async function addKnowledgeFact() {
    const topic = $("kbNewTopic").value.trim();
    if (!topic) {
      showToast("Escribe el nombre de la habilidad o experiencia.", true);
      return;
    }
    try {
      await api("/api/knowledge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic,
          category: $("kbNewCategory").value,
          status: $("kbNewStatus").value,
          details: $("kbNewDetails").value.trim(),
          source: "manual",
        }),
      });
      $("kbNewTopic").value = "";
      $("kbNewDetails").value = "";
      const kbRes = await api("/api/knowledge");
      state.facts = kbRes.facts || [];
      renderKnowledge();
      showToast("Guardado en tu memoria permanente.");
    } catch (err) {
      showToast(err.message, true);
    }
  }

  // ---------- Job Analysis & Honest Adaptation ----------
  async function fetchUrl() {
    const url = $("jobUrlInput").value.trim();
    if (!url) {
      showToast("Pega primero la URL de la oferta.", true);
      return;
    }
    $("urlStatusMsg").textContent = "Leyendo página de la oferta...";
    $("urlStatusMsg").className = "field-hint";
    showLoading("Extrayendo texto de la oferta...");
    try {
      const res = await api("/api/jobs/fetch-url", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      });
      if (!res.success) {
        $("urlStatusMsg").textContent = res.error || "No se pudo extraer automáticamente.";
        $("urlStatusMsg").className = "field-hint error";
        showToast(res.error || "No se pudo leer la URL. Pega la descripción abajo.", true);
        return;
      }
      if (res.title && !$("jobTitleInput").value.trim()) $("jobTitleInput").value = res.title;
      if (res.company && !$("jobCompanyInput").value.trim()) $("jobCompanyInput").value = res.company;
      $("jobDescInput").value = res.description || "";
      $("urlStatusMsg").textContent = `Oferta extraída correctamente (${res.method}). Revisa el texto y pulsa Analizar.`;
      $("urlStatusMsg").className = "field-hint ok";
      showToast("Descripción de la oferta extraída correctamente.");
    } catch (err) {
      $("urlStatusMsg").textContent = err.message;
      $("urlStatusMsg").className = "field-hint error";
      showToast(err.message, true);
    } finally {
      hideLoading();
    }
  }

  async function analyzeJob() {
    const source_url = $("jobUrlInput").value.trim();
    const job_description = $("jobDescInput").value.trim();
    if (!source_url && job_description.length < 30) {
      showToast("Pega una URL válida o la descripción completa de la oferta.", true);
      return;
    }
    showLoading("Comparando la oferta con tu CV base y tu memoria...");
    try {
      const res = await api("/api/jobs/analyze", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          source_url: source_url || null,
          job_title: $("jobTitleInput").value.trim() || null,
          company: $("jobCompanyInput").value.trim() || null,
          job_description: job_description || null,
          target_language: $("targetLangSelect").value,
        }),
      });
      state.currentJob = res.job;
      renderAnalysisWorkspace();
      const jobsRes = await api("/api/jobs");
      state.jobs = jobsRes.jobs || [];
      renderHistory();
      showToast("Análisis completado. Revisa los puntos cumplidos y las preguntas por confirmar.");
      $("analysisWorkspace").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      showToast(err.message, true);
    } finally {
      hideLoading();
    }
  }

  function renderAnalysisWorkspace() {
    const job = state.currentJob;
    if (!job) {
      $("analysisWorkspace").classList.add("hidden");
      $("btnResetAnalysis").classList.add("hidden");
      return;
    }

    $("analysisWorkspace").classList.remove("hidden");
    $("btnResetAnalysis").classList.remove("hidden");

    const an = job.analysis || {};
    $("resProviderTag").textContent = `Motor: ${PROVIDER_LABELS[job.provider_used] || job.provider_used}`;
    $("resJobTitle").textContent = job.job_title || an.job_title || "Oferta de empleo";
    const metaParts = [];
    if (job.company) metaParts.push(job.company);
    if (an.offer_language) metaParts.push(`Idioma oferta: ${an.offer_language.toUpperCase()}`);
    if (job.source_url) metaParts.push(job.source_url);
    $("resJobMeta").textContent = metaParts.join(" · ");

    $("resMatchScore").textContent = `${job.match_score ?? an.match_score ?? 0}%`;
    $("resAtsScore").textContent = `${job.ats_score ?? an.ats_score ?? 0}%`;
    $("resSummary").textContent = an.summary || "Análisis disponible.";

    // Keywords
    const kws = an.ats_keywords || {};
    const renderChips = (elId, arr, cls) => {
      const list = Array.isArray(arr) ? arr : [];
      $(elId).innerHTML = list.length
        ? list.map((k) => `<span class="chip ${cls}">${esc(k)}</span>`).join("")
        : `<span class="muted small">Ninguna</span>`;
    };
    renderChips("kwMatched", kws.matched, "chip-ok");
    renderChips("kwHighlight", kws.to_highlight, "chip-hi");
    renderChips("kwMissing", kws.missing, "chip-miss");

    // Matched requirements
    const matched = an.matched_requirements || [];
    $("matchedCount").textContent = matched.length;
    $("matchedList").innerHTML = matched.length
      ? matched
          .map(
            (m) => `
          <div class="req-item">
            <div class="req-title">✅ ${esc(m.requirement)}</div>
            <div class="req-sub">${esc(m.evidence || "")}</div>
          </div>`
          )
          .join("")
      : `<div class="muted small">No se detectaron coincidencias directas aún. Confirma tus habilidades arriba.</div>`;

    // Missing requirements
    const missing = an.missing_requirements || [];
    $("missingCount").textContent = missing.length;
    $("missingList").innerHTML = missing.length
      ? missing
          .map(
            (m) => `
          <div class="req-item">
            <div class="req-title">⚠️ ${esc(m.requirement)} ${m.importance ? `<span class="tag tag-soft">${esc(m.importance)}</span>` : ""}</div>
            <div class="req-sub">${esc(m.honest_advice || "")}</div>
          </div>`
          )
          .join("")
      : `<div class="muted small">No hay carencias críticas descartadas.</div>`;

    // Unclear requirements (Interactive Q&A)
    const unclear = an.unclear_requirements || [];
    state.qaSelections = {};
    if (unclear.length) {
      $("unclearSection").classList.remove("hidden");
      $("unclearList").innerHTML = unclear
        .map((q) => {
          const qid = q.id || q.topic;
          state.qaSelections[qid] = {
            question_id: qid,
            topic: q.topic || q.requirement,
            category: q.suggested_category || "Habilidad técnica",
            status: null,
            details: "",
            save_to_knowledge: true,
          };
          return `
            <div class="qa-item" data-qid="${esc(qid)}">
              <div class="qa-top">
                <span class="qa-topic">${esc(q.topic || q.requirement)}</span>
                <span class="tag tag-soft">${esc(q.suggested_category || "General")}</span>
              </div>
              <div class="qa-question">${esc(q.question || q.why_unclear)}</div>
              <div class="qa-choices">
                <button type="button" class="choice-pill" data-qa-qid="${esc(qid)}" data-qa-status="confirmed">✅ Sí, lo tengo</button>
                <button type="button" class="choice-pill" data-qa-qid="${esc(qid)}" data-qa-status="partial">🟡 Parcial / básico</button>
                <button type="button" class="choice-pill" data-qa-qid="${esc(qid)}" data-qa-status="denied">⛔ No lo tengo</button>
              </div>
              <div class="qa-meta-row">
                <input type="text" data-qa-details="${esc(qid)}" placeholder="Detalles opcionales reales (proyectos, años, herramientas...)" />
                <label class="checkbox-inline">
                  <input type="checkbox" data-qa-save="${esc(qid)}" checked />
                  Guardar en mi memoria permanente
                </label>
              </div>
            </div>
          `;
        })
        .join("");
    } else {
      $("unclearSection").classList.add("hidden");
    }

    // Adapted CV section
    const md = (job.adapted_cv_markdown || "").trim();
    if (md) {
      $("adaptedCvEmpty").classList.add("hidden");
      $("adaptedCvContainer").classList.remove("hidden");
      $("cvTabPreview").innerHTML = renderMarkdownToHtml(md);
      $("adaptedCvEditor").value = md;

      const changes = job.changelog || [];
      $("auditChanges").innerHTML = changes.length
        ? changes
            .map(
              (c) => `
            <div class="audit-row">
              <strong>${esc(c.section || "General")}:</strong> ${esc(c.change || "")}
              ${c.reason ? `<div class="muted small">${esc(c.reason)}</div>` : ""}
            </div>`
            )
            .join("")
        : `<div class="muted small">Sin notas de cambios.</div>`;

      const kwsInt = job.keywords_integrated || [];
      $("auditKeywords").innerHTML = kwsInt.length
        ? kwsInt
            .map(
              (k) => `
            <div class="audit-row">
              <span class="chip chip-ok">${esc(k.keyword || k)}</span>
              <span class="muted small" style="margin-left:6px;">${esc(k.justification || "")}</span>
            </div>`
            )
            .join("")
        : `<div class="muted small">Sin palabras clave listadas.</div>`;

      const honesty = job.honesty_notes || [];
      $("auditHonesty").innerHTML = honesty.length
        ? honesty.map((h) => `<li>${esc(h)}</li>`).join("")
        : `<li>Todo el contenido se basa exclusivamente en tu CV base y tu memoria confirmada.</li>`;
    } else {
      $("adaptedCvEmpty").classList.remove("hidden");
      $("adaptedCvContainer").classList.add("hidden");
    }
  }

  async function submitQaAndAdapt() {
    if (!state.currentJob) return;
    const answers = Object.values(state.qaSelections).filter((a) => a.status !== null);
    if (!answers.length) {
      showToast("Selecciona al menos una respuesta (o pulsa 'Generar CV' abajo para adaptar sin responder).", true);
      return;
    }
    showLoading("Guardando en tu memoria y generando CV adaptado honesto...");
    try {
      const res = await api(`/api/jobs/${state.currentJob.id}/answers`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          answers,
          extra_instructions: $("qaExtraInstructions").value.trim(),
          target_language: $("targetLangSelect").value,
        }),
      });
      state.currentJob = res.job;
      renderAnalysisWorkspace();
      const [kbRes, jobsRes] = await Promise.all([api("/api/knowledge"), api("/api/jobs")]);
      state.facts = kbRes.facts || [];
      state.jobs = jobsRes.jobs || [];
      renderKnowledge();
      renderHistory();
      showToast(`¡Listo! ${res.saved_facts_count} dato(s) guardados en tu memoria y CV adaptado.`);
    } catch (err) {
      showToast(err.message, true);
    } finally {
      hideLoading();
    }
  }

  async function adaptCv(extraInstructions = "") {
    if (!state.currentJob) return;
    showLoading("Generando CV adaptado honesto para filtros ATS...");
    try {
      const res = await api(`/api/jobs/${state.currentJob.id}/adapt`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          extra_instructions: extraInstructions,
          target_language: $("targetLangSelect").value,
        }),
      });
      state.currentJob = res.job;
      renderAnalysisWorkspace();
      const jobsRes = await api("/api/jobs");
      state.jobs = jobsRes.jobs || [];
      renderHistory();
      showToast("CV adaptado generado. Puedes descargarlo en PDF o Word.");
    } catch (err) {
      showToast(err.message, true);
    } finally {
      hideLoading();
    }
  }

  // ---------- History ----------
  function renderHistory() {
    const list = state.jobs || [];
    $("navHistoryCount").textContent = list.length;
    const el = $("historyList");
    if (!list.length) {
      el.innerHTML = `<div class="empty-inline">Todavía no has analizado ninguna oferta. Empieza en <strong>Analizar oferta</strong>.</div>`;
      return;
    }
    el.innerHTML = list
      .map((j) => {
        const dt = new Date(j.updated_at).toLocaleDateString("es-ES", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
        return `
          <div class="history-card" data-open-job="${j.id}">
            <div class="history-main">
              <div style="font-weight:700;font-size:1rem;">${esc(j.job_title)} ${j.company ? `<span class="muted">· ${esc(j.company)}</span>` : ""}</div>
              <div class="muted small" style="margin-top:4px;">
                Encaje: <strong>${j.match_score}%</strong> · ATS: <strong>${j.ats_score}%</strong> ·
                ${j.has_adapted_cv ? `<span style="color:#86efac;">CV adaptado listo</span>` : "Solo análisis"} ·
                ${dt}
              </div>
            </div>
            <div class="history-actions">
              <button class="btn btn-secondary btn-sm" data-open-job="${j.id}">Abrir</button>
              <button class="btn btn-danger btn-sm" data-del-job="${j.id}">Borrar</button>
            </div>
          </div>
        `;
      })
      .join("");
  }

  async function openHistoryJob(jobId) {
    showLoading("Cargando análisis...");
    try {
      const res = await api(`/api/jobs/${jobId}`);
      state.currentJob = res.job;
      $("jobUrlInput").value = res.job.source_url || "";
      $("jobTitleInput").value = res.job.job_title || "";
      $("jobCompanyInput").value = res.job.company || "";
      $("jobDescInput").value = res.job.raw_description || "";
      $("targetLangSelect").value = res.job.target_language || "auto";
      renderAnalysisWorkspace();
      switchView("analyze");
    } catch (err) {
      showToast(err.message, true);
    } finally {
      hideLoading();
    }
  }

  // ---------- Settings ----------
  function selectProviderUI(provider) {
    state.selectedProvider = provider;
    document.querySelectorAll(".provider-card").forEach((c) => {
      c.classList.toggle("active", c.dataset.provider === provider);
    });
    const isLocal = provider === "local";
    const isOllama = provider === "ollama";
    $("apiKeyRow").classList.toggle("hidden", isLocal);
    $("baseUrlRow").classList.toggle("hidden", !(isOllama || provider === "openai"));
    if (!$("setModel").value.trim() || Object.values(DEFAULT_MODELS).includes($("setModel").value.trim())) {
      $("setModel").value = DEFAULT_MODELS[provider] || "";
    }
  }

  function renderSettings() {
    const s = state.settings;
    if (!s) return;
    const p = s.provider || "local";
    $("providerBadgeText").textContent = PROVIDER_LABELS[p] || p;
    $("localModeTip").classList.toggle("hidden", p !== "local");

    $("setModel").value = s.model || DEFAULT_MODELS[p] || "";
    $("setBaseUrl").value = s.base_url || "http://host.docker.internal:11434/v1";
    $("setTone").value = s.tone || "profesional y directo";
    $("setDefaultLang").value = s.default_language || "auto";
    $("setApiKey").value = "";
    $("apiKeySavedHint").textContent = s.has_api_key ? `(Guardada: ${s.api_key_masked})` : "(Sin guardar)";
    selectProviderUI(p);
  }

  async function saveSettings() {
    const keyInput = $("setApiKey").value.trim();
    showLoading("Guardando configuración...");
    try {
      const res = await api("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: state.selectedProvider,
          api_key: keyInput ? keyInput : null, // keep existing if blank
          model: $("setModel").value.trim(),
          base_url: $("setBaseUrl").value.trim(),
          default_language: $("setDefaultLang").value,
          tone: $("setTone").value.trim(),
        }),
      });
      state.settings = res.settings;
      renderSettings();
      showToast("Configuración guardada correctamente.");
    } catch (err) {
      showToast(err.message, true);
    } finally {
      hideLoading();
    }
  }

  async function testAi() {
    $("testAiResult").textContent = "Probando...";
    try {
      const res = await api("/api/settings/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: state.selectedProvider,
          api_key: $("setApiKey").value.trim() || null,
          model: $("setModel").value.trim() || null,
          base_url: $("setBaseUrl").value.trim() || null,
        }),
      });
      $("testAiResult").textContent = res.message;
      $("testAiResult").style.color = res.ok ? "#86efac" : "#fca5a5";
      showToast(res.message, !res.ok);
    } catch (err) {
      $("testAiResult").textContent = err.message;
      $("testAiResult").style.color = "#fca5a5";
    }
  }

  // ---------- Event Wiring ----------
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.view));
  });
  document.querySelectorAll("[data-goto]").forEach((btn) => {
    btn.addEventListener("click", () => switchView(btn.dataset.goto));
  });
  $("btnProviderBadge").addEventListener("click", () => switchView("settings"));

  // Wi-Fi Modal
  const toggleWifiModal = (show) => $("wifiModal").classList.toggle("hidden", !show);
  $("btnOpenWifiModal").addEventListener("click", () => toggleWifiModal(true));
  $("btnCloseWifiModal").addEventListener("click", () => toggleWifiModal(false));
  $("wifiModalBackdrop").addEventListener("click", () => toggleWifiModal(false));

  const copyLanUrl = async () => {
    try {
      await navigator.clipboard.writeText(state.network.lan_url);
      showToast("Enlace Wi-Fi copiado al portapapeles.");
    } catch {
      showToast("Copia manualmente: " + state.network.lan_url);
    }
  };
  $("btnCopyLanUrl").addEventListener("click", copyLanUrl);
  $("btnCopyModalLan").addEventListener("click", copyLanUrl);

  // Drop zone & CV base
  const dz = $("dropZone");
  dz.addEventListener("click", () => $("cvFileInput").click());
  $("cvFileInput").addEventListener("change", (e) => handleFileUpload(e.target.files[0]));
  dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("dragover"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("dragover"));
  dz.addEventListener("drop", (e) => {
    e.preventDefault();
    dz.classList.remove("dragover");
    handleFileUpload(e.dataTransfer.files[0]);
  });
  $("btnSaveCv").addEventListener("click", saveBaseCv);

  $("btnLoadSampleCv").addEventListener("click", () => {
    $("cvFullName").value = "Alex Martínez López";
    $("cvHeadline").value = "Desarrollador Backend & Automatización | Python, SQL, APIs REST";
    $("cvRawText").value = `Alex Martínez López
Madrid, España | alex.martinez@ejemplo.com | linkedin.com/in/alexmartinez

PERFIL
Desarrollador de software con 4 años de experiencia creando APIs en Python (FastAPI y Django), automatizando procesos y administrando bases de datos PostgreSQL y MySQL.

EXPERIENCIA PROFESIONAL
Desarrollador Backend — Soluciones Digitales Iberia (2022 - Actualidad)
- Diseño y mantenimiento de APIs REST con Python y FastAPI para más de 25.000 usuarios activos.
- Optimización de consultas SQL en PostgreSQL reduciendo tiempos de respuesta en un 40%.
- Integración de flujos de despliegue automatizados con GitHub Actions y contenedores en servidores Linux.
- Colaboración diaria en equipo ágil usando Scrum y Jira.

Desarrollador Junior — Agencia Web Norte (2020 - 2022)
- Desarrollo de paneles administrativos con JavaScript, HTML5, CSS3 y APIs en Node.js.
- Pruebas unitarias con Pytest y soporte técnico de incidencias de segundo nivel.

FORMACIÓN
Grado en Ingeniería Informática — Universidad Politécnica (2016 - 2020)

IDIOMAS
Español (Nativo), Inglés (Nivel B2 lectura y conversación técnica).`;
    showToast("CV de ejemplo cargado. Pulsa 'Guardar CV Base' para usarlo.");
  });

  $("btnLoadDemoJob").addEventListener("click", () => {
    $("jobTitleInput").value = "Backend Python Developer (Remoto)";
    $("jobCompanyInput").value = "CloudScale Tech";
    $("jobDescInput").value = `Buscamos un Backend Python Developer para unirse a nuestro equipo de plataforma.

Requisitos imprescindibles:
- Más de 3 años de experiencia desarrollando servicios con Python (FastAPI o Django).
- Sólidos conocimientos en SQL (PostgreSQL) y diseño de APIs REST.
- Experiencia trabajando con Docker y Linux en entornos de producción.
- Control de versiones con Git y flujos de CI/CD.
- Nivel de inglés B2 o superior para documentación técnica.

Muy valorable:
- Experiencia con Kubernetes o AWS.
- Conocimientos de TypeScript / React para colaborar con frontend.
- Experiencia con pruebas automatizadas (Pytest) y metodologías ágiles (Scrum).`;
    showToast("Oferta de ejemplo lista. Pulsa 'Analizar encaje'.");
  });

  // Analyze & Q&A
  $("btnFetchUrl").addEventListener("click", fetchUrl);
  $("btnAnalyzeJob").addEventListener("click", analyzeJob);
  $("btnResetAnalysis").addEventListener("click", () => {
    state.currentJob = null;
    $("jobUrlInput").value = "";
    $("jobTitleInput").value = "";
    $("jobCompanyInput").value = "";
    $("jobDescInput").value = "";
    $("urlStatusMsg").textContent = "";
    renderAnalysisWorkspace();
  });

  $("unclearList").addEventListener("click", (e) => {
    const btn = e.target.closest("[data-qa-qid]");
    if (!btn) return;
    const qid = btn.dataset.qaQid;
    const status = btn.dataset.qaStatus;
    if (!state.qaSelections[qid]) return;
    state.qaSelections[qid].status = status;

    const card = btn.closest(".qa-item");
    card.querySelectorAll(".choice-pill").forEach((p) => {
      p.classList.remove("selected-confirmed", "selected-partial", "selected-denied");
    });
    btn.classList.add(`selected-${status}`);
  });

  $("unclearList").addEventListener("input", (e) => {
    const inp = e.target.closest("[data-qa-details]");
    if (inp && state.qaSelections[inp.dataset.qaDetails]) {
      state.qaSelections[inp.dataset.qaDetails].details = inp.value;
    }
  });

  $("unclearList").addEventListener("change", (e) => {
    const chk = e.target.closest("[data-qa-save]");
    if (chk && state.qaSelections[chk.dataset.qaSave]) {
      state.qaSelections[chk.dataset.qaSave].save_to_knowledge = chk.checked;
    }
  });

  $("btnSubmitAnswers").addEventListener("click", submitQaAndAdapt);
  $("btnAdaptNow").addEventListener("click", () => adaptCv($("refineInstructions").value.trim()));
  $("btnRefineCv").addEventListener("click", () => adaptCv($("refineInstructions").value.trim()));

  // CV Tabs & Exports
  document.querySelectorAll("[data-cv-tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll("[data-cv-tab]").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const name = tab.dataset.cvTab;
      $("cvTabPreview").classList.toggle("hidden", name !== "preview");
      $("cvTabEdit").classList.toggle("hidden", name !== "edit");
      $("cvTabAudit").classList.toggle("hidden", name !== "audit");
    });
  });

  $("btnSaveManualCv").addEventListener("click", async () => {
    if (!state.currentJob) return;
    const md = $("adaptedCvEditor").value.trim();
    try {
      const res = await api(`/api/jobs/${state.currentJob.id}/cv`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ adapted_cv_markdown: md }),
      });
      state.currentJob = res.job;
      $("cvTabPreview").innerHTML = renderMarkdownToHtml(md);
      showToast("Cambios manuales guardados en el CV adaptado.");
    } catch (err) {
      showToast(err.message, true);
    }
  });

  $("btnCopyCv").addEventListener("click", async () => {
    const md = state.currentJob?.adapted_cv_markdown || "";
    if (!md) return;
    try {
      await navigator.clipboard.writeText(md);
      showToast("CV copiado al portapapeles.");
    } catch {
      showToast("No se pudo copiar automáticamente.", true);
    }
  });
  $("btnDownloadPdf").addEventListener("click", () => {
    if (state.currentJob) window.open(`/api/jobs/${state.currentJob.id}/export/pdf`, "_blank");
  });
  $("btnDownloadDocx").addEventListener("click", () => {
    if (state.currentJob) window.open(`/api/jobs/${state.currentJob.id}/export/docx`, "_blank");
  });
  $("btnDownloadMd").addEventListener("click", () => {
    if (state.currentJob) window.open(`/api/jobs/${state.currentJob.id}/export/md`, "_blank");
  });

  // Knowledge Base events
  $("btnAddKbFact").addEventListener("click", addKnowledgeFact);
  $("kbSearchInput").addEventListener("input", renderKnowledge);
  document.querySelectorAll("[data-kb-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-kb-filter]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.kbFilter = btn.dataset.kbFilter;
      renderKnowledge();
    });
  });

  $("kbList").addEventListener("click", async (e) => {
    const delBtn = e.target.closest("[data-del-fact]");
    if (delBtn) {
      const id = delBtn.dataset.delFact;
      try {
        await api(`/api/knowledge/${id}`, { method: "DELETE" });
        state.facts = state.facts.filter((f) => String(f.id) !== String(id));
        renderKnowledge();
        showToast("Elemento eliminado de tu memoria.");
      } catch (err) {
        showToast(err.message, true);
      }
      return;
    }
    const cycBtn = e.target.closest("[data-cycle-fact]");
    if (cycBtn) {
      const id = cycBtn.dataset.cycleFact;
      const fact = state.facts.find((f) => String(f.id) === String(id));
      if (!fact) return;
      const order = ["confirmed", "partial", "denied"];
      const next = order[(order.indexOf(fact.status) + 1) % order.length];
      try {
        const res = await api(`/api/knowledge/${id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ status: next }),
        });
        fact.status = res.fact.status;
        renderKnowledge();
      } catch (err) {
        showToast(err.message, true);
      }
    }
  });

  // History events
  $("historyList").addEventListener("click", async (e) => {
    const delBtn = e.target.closest("[data-del-job]");
    if (delBtn) {
      e.stopPropagation();
      const id = delBtn.dataset.delJob;
      try {
        await api(`/api/jobs/${id}`, { method: "DELETE" });
        state.jobs = state.jobs.filter((j) => String(j.id) !== String(id));
        if (state.currentJob && String(state.currentJob.id) === String(id)) {
          state.currentJob = null;
          renderAnalysisWorkspace();
        }
        renderHistory();
        showToast("Oferta eliminada del historial.");
      } catch (err) {
        showToast(err.message, true);
      }
      return;
    }
    const openEl = e.target.closest("[data-open-job]");
    if (openEl) {
      openHistoryJob(openEl.dataset.openJob);
    }
  });

  // ---------- Job Hunter & Discovery ----------
  function renderHunter() {
    const prefs = state.hunterPrefs || {};
    const roles = Array.isArray(prefs.target_roles) ? prefs.target_roles : [];

    // Set quick search inputs if not already typed by user
    if (!$("hunterQueryInput").value && roles.length) {
      $("hunterQueryInput").value = roles[0];
    }
    if (!$("hunterLocationInput").value && prefs.location) {
      $("hunterLocationInput").value = prefs.location;
    }

    // Update direct portal launcher buttons (InfoJobs, Indeed, LinkedIn)
    const activeQ = $("hunterQueryInput").value.trim() || (roles[0] || "Administrativo");
    const activeLoc = $("hunterLocationInput").value.trim() || (prefs.location || "España");
    const cleanCity = activeLoc.split(",")[0].trim();
    const activeCountry = state.hunterCountry || (prefs.country || "España");

    if ($("linkLaunchInfojobs")) {
      $("linkLaunchInfojobs").href = `https://www.infojobs.net/jobsearch/search-results/list.xhtml?keyword=${encodeURIComponent(activeQ)}&location=${encodeURIComponent(cleanCity)}&segmentId=`;
    }
    if ($("linkLaunchIndeed")) {
      const cLow = activeCountry.toLowerCase();
      const indeedDomain = (cLow === "méxico" || cLow === "mexico") ? "mx.indeed.com" : (cLow === "estados unidos" || cLow === "usa") ? "www.indeed.com" : (cLow === "reino unido" || cLow === "uk") ? "uk.indeed.com" : "es.indeed.com";
      $("linkLaunchIndeed").href = `https://${indeedDomain}/jobs?q=${encodeURIComponent(activeQ)}&l=${encodeURIComponent(cleanCity)}`;
    }
    if ($("linkLaunchLinkedin")) {
      $("linkLaunchLinkedin").href = `https://www.linkedin.com/jobs/search/?keywords=${encodeURIComponent(activeQ)}&location=${encodeURIComponent(cleanCity)}`;
    }

    // Update country toggle buttons
    let matchedCountryBtn = false;
    document.querySelectorAll(".country-btn").forEach((btn) => {
      const isCustom = btn.dataset.country === "custom";
      if (!isCustom) {
        const isMatch = btn.dataset.country.toLowerCase() === activeCountry.toLowerCase();
        btn.classList.toggle("active", isMatch);
        if (isMatch) matchedCountryBtn = true;
      }
    });

    const customBtn = $("btnCustomCountry");
    const customBox = $("customCountryBox");
    if (!matchedCountryBtn && activeCountry) {
      if (customBtn) customBtn.classList.add("active");
      if (customBox) customBox.classList.remove("hidden");
      if ($("hunterCustomCountryInput")) $("hunterCustomCountryInput").value = activeCountry;
    } else if (matchedCountryBtn) {
      if (customBtn) customBtn.classList.remove("active");
      if (customBox) customBox.classList.add("hidden");
    }

    // Update modality toggle buttons
    document.querySelectorAll(".modality-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.modality === (state.hunterModality || "all"));
    });

    // Prefs drawer inputs
    $("prefRolesInput").value = roles.join(", ");
    if ($("prefCountryInput")) $("prefCountryInput").value = prefs.country || activeCountry;
    $("prefLevelSelect").value = prefs.experience_level || "mid";
    $("prefKeywordsInclude").value = (prefs.keywords_include || []).join(", ");
    $("prefKeywordsExclude").value = (prefs.keywords_exclude || []).join(", ");

    // Discovered jobs filtering
    const all = state.discoveredJobs || [];
    const highMatches = all.filter((j) => (j.match_score || 0) >= 70);
    const badge = $("navHunterCount");
    if (highMatches.length > 0) {
      badge.textContent = `${highMatches.length} afines`;
      badge.classList.remove("hidden");
    } else {
      badge.classList.add("hidden");
    }

    const filter = state.hunterFilter || "all";
    const mod = state.hunterModality || "all";
    const filtered = all.filter((j) => {
      if (j.status === "dismissed") return false;
      if (filter === "high" && (j.match_score || 0) < 70) return false;
      if (filter === "remote" && j.modality !== "remote") return false;
      if (filter === "saved" && j.status !== "saved") return false;

      // Filter by active modality toggle
      if (mod !== "all") {
        if (mod === "remote" && j.modality !== "remote") return false;
        if (mod === "hybrid" && j.modality !== "hybrid" && j.modality !== "remote") return false;
        if (mod === "onsite" && j.modality !== "onsite") return false;
      }
      return true;
    });

    $("discoveredCount").textContent = filtered.length;
    const feed = $("discoveredJobsFeed");
    const emptyNotice = $("hunterEmptyFeed");

    if (!filtered.length) {
      emptyNotice.classList.remove("hidden");
      feed.innerHTML = "";
      return;
    }
    emptyNotice.classList.add("hidden");

    feed.innerHTML = filtered
      .map((j) => {
        const score = j.match_score || 0;
        const scoreClass = score >= 75 ? "high" : score >= 55 ? "med" : "low";
        const modClass = j.modality || "onsite";
        const modLabel = j.modality === "remote" ? "100% Remoto" : j.modality === "hybrid" ? "Híbrido" : "Presencial";
        const isSaved = j.status === "saved";
        const isApplied = j.status === "applied";

        const matchedChips = (j.match_reasons || [])
          .map((m) => `<span class="chip chip-ok">✓ ${esc(m)}</span>`)
          .join("");
        const missingChips = (j.missing_skills || [])
          .slice(0, 4)
          .map((m) => `<span class="chip chip-miss">○ ${esc(m)}</span>`)
          .join("");

        return `
          <div class="job-card ${isApplied ? "is-applied" : ""} ${isSaved ? "is-saved" : ""}" data-discovered-id="${j.id}">
            <div class="job-card-header">
              <div style="flex:1; min-width:0;">
                <div class="job-card-title">${esc(j.title)}</div>
                <div class="job-card-meta">
                  ${j.company ? `<strong>${esc(j.company)}</strong> ·` : ""}
                  <span>📍 ${esc(j.location || "España")}</span> ·
                  <span class="modality-tag ${esc(modClass)}">${esc(modLabel)}</span> ·
                  <span class="tag tag-soft">${esc(j.source || "Web")}</span>
                  ${j.salary_text ? `· <span style="color:#86efac;font-weight:600;">💰 ${esc(j.salary_text)}</span>` : ""}
                  ${j.published_at ? `· <span>${esc(j.published_at)}</span>` : ""}
                </div>
              </div>
              <div class="match-badge ${scoreClass}">
                <span class="score-num">${score}%</span>
                <span class="score-lbl">Afinidad</span>
              </div>
            </div>

            <div class="job-card-snippet">
              ${esc(j.description_snippet || "")}
            </div>

            <div class="job-card-skills">
              ${matchedChips}
              ${missingChips}
            </div>

            <div class="job-card-actions">
              <div class="btn-group">
                <button class="btn btn-primary btn-sm btn-adapt-fast" data-adapt-discovered="${j.id}">
                  ⚡ ${isApplied ? "Re-adaptar mi CV" : "Adaptar mi CV a esta oferta"}
                </button>
                <a href="${esc(j.source_url)}" target="_blank" rel="noopener noreferrer" class="btn btn-ghost btn-sm">
                  🔗 Ver oferta original ↗
                </a>
              </div>
              <div class="btn-group">
                <button class="btn btn-ghost btn-sm" data-toggle-save="${j.id}">
                  ${isSaved ? "⭐ Guardada" : "☆ Guardar"}
                </button>
                <button class="btn btn-danger btn-sm" data-dismiss-job="${j.id}" title="Descartar y no volver a mostrar">
                  ✕ Descartar
                </button>
              </div>
            </div>
          </div>
        `;
      })
      .join("");
  }

  async function autoDetectHunterPrefs() {
    showLoading("Analizando tu CV base y memoria para deducir preferencias de búsqueda...");
    try {
      const res = await api("/api/hunter/preferences/auto-detect", { method: "POST" });
      state.hunterPrefs = res.preferences;
      renderHunter();
      $("hunterPrefsDrawer").classList.remove("hidden");
      showToast("Preferencias detectadas automáticamente a partir de tu CV.");
    } catch (err) {
      showToast(err.message, true);
    } finally {
      hideLoading();
    }
  }

  async function saveHunterPrefs() {
    const roles = $("prefRolesInput").value.split(",").map((s) => s.trim()).filter(Boolean);
    const inc = $("prefKeywordsInclude").value.split(",").map((s) => s.trim()).filter(Boolean);
    const exc = $("prefKeywordsExclude").value.split(",").map((s) => s.trim()).filter(Boolean);
    const countryVal = $("prefCountryInput") ? $("prefCountryInput").value.trim() : (state.hunterCountry || "España");
    showLoading("Guardando preferencias...");
    try {
      const res = await api("/api/hunter/preferences", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          target_roles: roles,
          location: $("hunterLocationInput").value.trim() || countryVal || "España",
          country: countryVal || "España",
          modality: state.hunterModality || "all",
          experience_level: $("prefLevelSelect").value,
          keywords_include: inc,
          keywords_exclude: exc,
          preferred_sources: ["linkedin", "tecnoempleo", "remotive", "arbeitnow", "jobicy", "wwr"],
        }),
      });
      state.hunterPrefs = res.preferences;
      if (res.preferences.country) state.hunterCountry = res.preferences.country;
      renderHunter();
      $("hunterPrefsSavedHint").textContent = "✓ Guardado";
      setTimeout(() => { $("hunterPrefsSavedHint").textContent = ""; }, 2500);
      showToast("Preferencias de búsqueda guardadas.");
    } catch (err) {
      showToast(err.message, true);
    } finally {
      hideLoading();
    }
  }

  async function runHunterSearch(fromCv = false) {
    const query = $("hunterQueryInput").value.trim();
    const location = $("hunterLocationInput").value.trim();
    const modality = state.hunterModality || "all";

    let country = state.hunterCountry || "España";
    const customInput = $("hunterCustomCountryInput");
    if (customInput && !$("customCountryBox").classList.contains("hidden") && customInput.value.trim()) {
      country = customInput.value.trim();
    }

    const modLabel = modality === 'remote' ? '100% Remoto' : modality === 'hybrid' ? 'Híbrido' : modality === 'onsite' ? 'Presencial' : 'todas las modalidades';
    const loadingMsg = fromCv
      ? `Analizando tu CV y buscando ofertas en ${country} (${modLabel})...`
      : `Buscando ofertas activas de "${query || 'tu perfil'}" en ${country}...`;

    showLoading(loadingMsg);
    try {
      const res = await api("/api/hunter/search", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: query || null,
          location: location || null,
          country: country || "España",
          modality: modality || null,
          from_cv: fromCv,
          limit: 45,
        }),
      });
      state.discoveredJobs = res.jobs || [];
      renderHunter();
      showToast(`¡Búsqueda completada! Se encontraron ${res.count} ofertas en ${country}.`);
    } catch (err) {
      showToast(err.message, true);
    } finally {
      hideLoading();
    }
  }

  async function convertDiscoveredJob(jobId) {
    showLoading("Analizando oferta y adaptando tu CV honestamente...");
    try {
      const res = await api(`/api/hunter/jobs/${jobId}/convert-to-analysis`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target_language: "auto" }),
      });
      state.currentJob = res.job_analysis;

      const disc = state.discoveredJobs.find((j) => String(j.id) === String(jobId));
      if (disc) disc.status = "applied";

      const jobsRes = await api("/api/jobs");
      state.jobs = jobsRes.jobs || [];
      renderHistory();
      renderHunter();

      renderAnalysisWorkspace();
      switchView("analyze");
      showToast("¡CV adaptado generado con éxito! Puedes revisarlo o descargarlo en PDF/Word.");
      $("analysisWorkspace").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      showToast(err.message, true);
    } finally {
      hideLoading();
    }
  }

  async function toggleSaveJob(jobId) {
    const job = state.discoveredJobs.find((j) => String(j.id) === String(jobId));
    if (!job) return;
    const nextStatus = job.status === "saved" ? "new" : "saved";
    try {
      const res = await api(`/api/hunter/jobs/${jobId}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: nextStatus }),
      });
      job.status = res.job.status;
      renderHunter();
      showToast(nextStatus === "saved" ? "Oferta guardada en tus favoritos." : "Oferta desmarcada.");
    } catch (err) {
      showToast(err.message, true);
    }
  }

  async function dismissJob(jobId) {
    try {
      await api(`/api/hunter/jobs/${jobId}/status`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "dismissed" }),
      });
      state.discoveredJobs = state.discoveredJobs.filter((j) => String(j.id) !== String(jobId));
      renderHunter();
      showToast("Oferta descartada. No volverá a mostrarse.");
    } catch (err) {
      showToast(err.message, true);
    }
  }

  // Settings events
  $("providerCards").addEventListener("click", (e) => {
    const card = e.target.closest("[data-provider]");
    if (card) selectProviderUI(card.dataset.provider);
  });
  $("btnSaveSettings").addEventListener("click", saveSettings);
  $("btnTestAi").addEventListener("click", testAi);

  // Hunter events
  $("btnTogglePrefs").addEventListener("click", () => {
    $("hunterPrefsDrawer").classList.toggle("hidden");
  });
  $("btnAutoDetectPrefs").addEventListener("click", autoDetectHunterPrefs);
  $("btnSaveHunterPrefs").addEventListener("click", saveHunterPrefs);
  $("btnSearchFromCv").addEventListener("click", () => runHunterSearch(true));
  $("btnRunHunterSearch").addEventListener("click", () => runHunterSearch(false));

  const updateLauncherLinks = () => {
    const q = $("hunterQueryInput").value.trim() || "Administrativo";
    const loc = $("hunterLocationInput").value.trim() || state.hunterCountry || "España";
    const cleanCity = loc.split(",")[0].trim();
    const cLow = (state.hunterCountry || "España").toLowerCase();
    if ($("linkLaunchInfojobs")) {
      $("linkLaunchInfojobs").href = `https://www.infojobs.net/jobsearch/search-results/list.xhtml?keyword=${encodeURIComponent(q)}&location=${encodeURIComponent(cleanCity)}&segmentId=`;
    }
    if ($("linkLaunchIndeed")) {
      const indeedDomain = (cLow === "méxico" || cLow === "mexico") ? "mx.indeed.com" : (cLow === "estados unidos" || cLow === "usa") ? "www.indeed.com" : (cLow === "reino unido" || cLow === "uk") ? "uk.indeed.com" : "es.indeed.com";
      $("linkLaunchIndeed").href = `https://${indeedDomain}/jobs?q=${encodeURIComponent(q)}&l=${encodeURIComponent(cleanCity)}`;
    }
    if ($("linkLaunchLinkedin")) {
      $("linkLaunchLinkedin").href = `https://www.linkedin.com/jobs/search/?keywords=${encodeURIComponent(q)}&location=${encodeURIComponent(cleanCity)}`;
    }
  };
  $("hunterQueryInput").addEventListener("input", updateLauncherLinks);
  $("hunterLocationInput").addEventListener("input", updateLauncherLinks);

  // Country toggle buttons
  document.querySelectorAll(".country-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      if (btn.dataset.country === "custom") {
        $("customCountryBox").classList.toggle("hidden");
        document.querySelectorAll(".country-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        if (!$("customCountryBox").classList.contains("hidden")) {
          $("hunterCustomCountryInput").focus();
        }
      } else {
        $("customCountryBox").classList.add("hidden");
        state.hunterCountry = btn.dataset.country;
        document.querySelectorAll(".country-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        renderHunter();
      }
    });
  });

  if ($("hunterCustomCountryInput")) {
    $("hunterCustomCountryInput").addEventListener("change", (e) => {
      const val = e.target.value.trim();
      if (val) {
        state.hunterCountry = val;
      }
    });
  }

  document.querySelectorAll(".modality-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      state.hunterModality = btn.dataset.modality;
      document.querySelectorAll(".modality-btn").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      renderHunter();
    });
  });

  $("btnHunterQuickRefresh").addEventListener("click", async () => {
    showLoading("Actualizando ofertas...");
    try {
      const res = await api("/api/hunter/jobs");
      state.discoveredJobs = res.jobs || [];
      renderHunter();
    } catch (err) {
      showToast(err.message, true);
    } finally {
      hideLoading();
    }
  });

  document.querySelectorAll("[data-hunter-filter]").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("[data-hunter-filter]").forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      state.hunterFilter = btn.dataset.hunterFilter;
      renderHunter();
    });
  });

  $("discoveredJobsFeed").addEventListener("click", (e) => {
    const adaptBtn = e.target.closest("[data-adapt-discovered]");
    if (adaptBtn) {
      convertDiscoveredJob(adaptBtn.dataset.adaptDiscovered);
      return;
    }
    const saveBtn = e.target.closest("[data-toggle-save]");
    if (saveBtn) {
      toggleSaveJob(saveBtn.dataset.toggleSave);
      return;
    }
    const dismissBtn = e.target.closest("[data-dismiss-job]");
    if (dismissBtn) {
      dismissJob(dismissBtn.dataset.dismissJob);
      return;
    }
  });

  // Boot
  loadAll();
})();

