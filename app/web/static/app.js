// SlideCast Studio Web Client
let selectedPdfFile = null;
let selectedAudioFile = null;
let currentProject = null;
let slideDurations = [];
let pollInterval = null;

document.addEventListener("DOMContentLoaded", () => {
  initFileUploads();
  initKeyModal();
  checkKeyStatus();
  initAuth();

  document.getElementById("btnProcessUpload").addEventListener("click", uploadFiles);
  document.getElementById("btnAiSync").addEventListener("click", triggerAiSync);
  document.getElementById("btnAutoBalance").addEventListener("click", balanceToAudio);
  document.getElementById("btnRenderVideo").addEventListener("click", triggerRender);
});

// Key Modal Logic
function initKeyModal() {
  const modal = document.getElementById("keyModal");
  const btnOpen = document.getElementById("btnOpenKeyModal");
  const btnClose = document.getElementById("btnCloseKeyModal");
  const btnCancel = document.getElementById("btnCancelKey");
  const btnSave = document.getElementById("btnSaveKey");

  btnOpen.onclick = () => (modal.style.display = "flex");
  btnClose.onclick = btnCancel.onclick = () => (modal.style.display = "none");

  btnSave.onclick = async () => {
    const key = document.getElementById("inputApiKey").value.trim();
    const adminToken = document.getElementById("inputAdminToken").value.trim();
    const errEl = document.getElementById("keyModalError");
    errEl.style.display = "none";
    const formData = new FormData();
    formData.append("key", key);
    const headers = {};
    if (adminToken) headers["X-Admin-Token"] = adminToken;

    const res = await fetch("/api/config/key", { method: "POST", headers, body: formData });
    if (res.ok) {
      modal.style.display = "none";
      document.getElementById("inputAdminToken").value = "";
      checkKeyStatus();
    } else {
      let msg = "Falha ao salvar a chave.";
      try {
        const data = await res.json();
        if (data.detail) msg = data.detail;
      } catch (e) { /* keep default message */ }
      errEl.textContent = msg;
      errEl.style.display = "block";
    }
  };
}

async function checkKeyStatus() {
  try {
    const res = await fetch("/api/config/key");
    const data = await res.json();
    const el = document.getElementById("keyStatusText");
    if (data.configured) {
      el.textContent = `Gemini Ativo (${data.masked})`;
      el.style.color = "#10b981";
    } else {
      el.textContent = "Configurar Chave Gemini";
      el.style.color = "";
    }
  } catch (e) {
    console.error(e);
  }
}

// File Uploads & Drag-and-Drop
function initFileUploads() {
  setupDropZone("pdfDropZone", "pdfInput", (file) => {
    if (file && file.name.toLowerCase().endsWith(".pdf")) {
      selectedPdfFile = file;
      document.getElementById("pdfEmptyView").style.display = "none";
      document.getElementById("pdfLoadedView").style.display = "block";
      document.getElementById("pdfFileName").textContent = file.name;
      document.getElementById("pdfFileBadge").textContent = `${(file.size / (1024 * 1024)).toFixed(1)} MB`;
      checkBothFilesSelected();
    } else {
      alert("Por favor selecione um arquivo no formato PDF.");
    }
  });

  setupDropZone("audioDropZone", "audioInput", (file) => {
    if (file) {
      selectedAudioFile = file;
      document.getElementById("audioEmptyView").style.display = "none";
      document.getElementById("audioLoadedView").style.display = "block";
      document.getElementById("audioFileName").textContent = file.name;
      document.getElementById("audioFileBadge").textContent = `${(file.size / (1024 * 1024)).toFixed(1)} MB`;
      checkBothFilesSelected();
    }
  });
}

function setupDropZone(dropId, inputId, onFile) {
  const dropEl = document.getElementById(dropId);
  const inputEl = document.getElementById(inputId);

  inputEl.addEventListener("change", (e) => {
    if (e.target.files.length > 0) onFile(e.target.files[0]);
  });

  dropEl.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropEl.classList.add("dragover");
  });

  dropEl.addEventListener("dragleave", () => {
    dropEl.classList.remove("dragover");
  });

  dropEl.addEventListener("drop", (e) => {
    e.preventDefault();
    dropEl.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      onFile(e.dataTransfer.files[0]);
    }
  });
}

function checkBothFilesSelected() {
  if (selectedPdfFile && selectedAudioFile) {
    document.getElementById("uploadActionRow").style.display = "block";
  }
}

async function uploadFiles() {
  const btn = document.getElementById("btnProcessUpload");
  btn.disabled = true;
  btn.textContent = "Processando arquivos...";

  const formData = new FormData();
  formData.append("pdf_file", selectedPdfFile);
  formData.append("audio_file", selectedAudioFile);

  try {
    const res = await fetch("/api/upload", {
      method: "POST",
      body: formData,
    });

    if (res.status === 401) {
      location.reload();
      return;
    }

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Erro ao processar arquivos.");
    }

    currentProject = await res.json();
    renderTimeline(currentProject);

    document.getElementById("syncSection").style.display = "block";
    document.getElementById("exportSection").style.display = "block";
    document.getElementById("syncSection").scrollIntoView({ behavior: "smooth" });
  } catch (e) {
    alert("Erro: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Processar Arquivos e Iniciar";
  }
}

// Timeline Rendering
function renderTimeline(project) {
  document.getElementById("badgeSlideCount").textContent = `Slides: ${project.page_count}`;
  document.getElementById("badgeAudioDuration").textContent = `Áudio: ${project.formatted_audio_duration}`;

  slideDurations = project.slides.map((s) => s.duration);
  updateTotalSlidesLabel();

  const container = document.getElementById("slidesTimeline");
  container.innerHTML = "";

  project.slides.forEach((slide) => {
    const card = document.createElement("div");
    card.className = "slide-card";
    card.innerHTML = `
      <div class="slide-card-header">Slide ${slide.slide_number}</div>
      <img src="${slide.thumbnail_url}" class="slide-thumb" alt="Slide ${slide.slide_number}">
      <div class="slide-duration-row">
        <span>Duração:</span>
        <input type="number" step="0.5" min="0.5" max="3600" class="slide-duration-input" value="${slide.duration}" data-index="${slide.index}">
      </div>
    `;

    const input = card.querySelector(".slide-duration-input");
    input.addEventListener("input", (e) => {
      const val = parseFloat(e.target.value) || 0.5;
      slideDurations[slide.index] = val;
      updateTotalSlidesLabel();
    });

    container.appendChild(card);
  });
}

function updateTotalSlidesLabel() {
  const sum = slideDurations.reduce((a, b) => a + b, 0);
  const badge = document.getElementById("badgeTotalSlideDuration");
  badge.textContent = `Total dos Slides: ${sum.toFixed(1)}s`;

  if (currentProject) {
    const diff = Math.abs(sum - currentProject.audio_duration);
    if (diff <= 0.5) {
      badge.className = "badge badge-success";
    } else {
      badge.className = "badge badge-warning";
    }
  }
}

function balanceToAudio() {
  if (!currentProject) return;
  const count = currentProject.page_count;
  const equal = currentProject.audio_duration / count;
  slideDurations = Array(count).fill(parseFloat(equal.toFixed(1)));

  const inputs = document.querySelectorAll(".slide-duration-input");
  inputs.forEach((inp, idx) => {
    inp.value = slideDurations[idx];
  });
  updateTotalSlidesLabel();
}

async function triggerAiSync() {
  if (!currentProject) return;
  const btn = document.getElementById("btnAiSync");
  const statusEl = document.getElementById("aiSyncStatus");

  btn.disabled = true;
  statusEl.textContent = "✨ IA analisando áudio e slides...";

  try {
    const res = await fetch(`/api/projects/${currentProject.project_id}/ai-sync`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });

    if (res.status === 401) {
      location.reload();
      return;
    }

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Falha na sincronização");
    }

    const data = await res.json();
    slideDurations = data.durations;

    const inputs = document.querySelectorAll(".slide-duration-input");
    inputs.forEach((inp, idx) => {
      if (idx < slideDurations.length) {
        inp.value = slideDurations[idx];
      }
    });

    updateTotalSlidesLabel();
    statusEl.textContent = "✓ Sincronizado com IA!";
  } catch (e) {
    statusEl.textContent = "";
    alert("Erro na IA: " + e.message);
  } finally {
    btn.disabled = false;
  }
}

async function triggerRender() {
  if (!currentProject) return;

  const btn = document.getElementById("btnRenderVideo");
  const progressBox = document.getElementById("renderProgressContainer");
  const statusText = document.getElementById("renderStatusText");
  const percentText = document.getElementById("renderProgressPercent");
  const progressBar = document.getElementById("renderProgressBar");

  const [resW, resH] = document.getElementById("selectResolution").value.split("x").map(Number);
  const fps = parseInt(document.getElementById("selectFps").value);

  btn.disabled = true;
  progressBox.style.display = "block";
  statusText.textContent = "Enviando para fila de renderização...";
  percentText.textContent = "0%";
  progressBar.style.width = "0%";

  try {
    const res = await fetch(`/api/projects/${currentProject.project_id}/render`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        durations: slideDurations,
        resolution_w: resW,
        resolution_h: resH,
        fps: fps,
      }),
    });

    if (res.status === 401) {
      location.reload();
      return;
    }

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Erro ao iniciar renderização");
    }

    const jobData = await res.json();
    pollJob(jobData.job_id);
  } catch (e) {
    alert("Erro: " + e.message);
    btn.disabled = false;
    progressBox.style.display = "none";
  }
}

function pollJob(jobId) {
  if (pollInterval) clearInterval(pollInterval);

  pollInterval = setInterval(async () => {
    try {
      const res = await fetch(`/api/jobs/${jobId}`);
      if (res.status === 401) {
        clearInterval(pollInterval);
        location.reload();
        return;
      }
      if (!res.ok) return;

      const job = await res.json();
      const statusText = document.getElementById("renderStatusText");
      const percentText = document.getElementById("renderProgressPercent");
      const progressBar = document.getElementById("renderProgressBar");

      const pct = Math.round(job.progress * 100);
      percentText.textContent = `${pct}%`;
      progressBar.style.width = `${pct}%`;
      statusText.textContent = job.message;

      if (job.status === "completed") {
        clearInterval(pollInterval);
        document.getElementById("renderProgressContainer").style.display = "none";
        document.getElementById("resultSection").style.display = "block";

        const videoPlayer = document.getElementById("videoPlayer");
        videoPlayer.src = job.video_url;

        const downloadBtn = document.getElementById("btnDownloadVideo");
        downloadBtn.href = job.download_url;

        document.getElementById("resultSection").scrollIntoView({ behavior: "smooth" });
      } else if (job.status === "failed") {
        clearInterval(pollInterval);
        alert("Erro na renderização: " + (job.error || "Falha desconhecida"));
        document.getElementById("btnRenderVideo").disabled = false;
      }
    } catch (e) {
      console.error("Polling error:", e);
    }
  }, 1000);
}

// Auth & subscription
function planLabel(plan) {
  const left = plan.renders_limit === 0 ? "ilimitados" : `${plan.renders_left} restantes`;
  if (plan.state === "trial") {
    const end = plan.trial_ends_at ? new Date(plan.trial_ends_at).toLocaleDateString("pt-BR") : "";
    return `Teste grátis até ${end} · ${left}`;
  }
  if (plan.state === "active") return `Assinante · ${left} vídeos/mês`;
  if (plan.state === "past_due") return "Pagamento pendente — atualize o cartão";
  return "Teste encerrado — assine para continuar";
}

function handleCheckoutParam() {
  const params = new URLSearchParams(location.search);
  const status = params.get("checkout");
  if (!status) return;
  const banner = document.getElementById("checkoutBanner");
  banner.style.display = "inline-block";
  banner.textContent =
    status === "success"
      ? "Pagamento confirmado! Sua assinatura ativa em alguns segundos."
      : "Assinatura não concluída. Tente novamente quando quiser.";
  history.replaceState(null, "", location.pathname);
}

async function initAuth() {
  handleCheckoutParam();
  let me = null;
  try {
    const res = await fetch("/api/auth/me");
    if (res.ok) me = await res.json();
  } catch (e) {
    console.error(e);
  }
  const logged = !!me;
  document.getElementById("authGate").style.display = logged ? "none" : "block";
  document.getElementById("uploadSection").style.display = logged ? "block" : "none";
  document.getElementById("accountBadge").style.display = logged ? "inline-block" : "none";
  document.getElementById("btnLogout").style.display = logged ? "inline-block" : "none";
  document.getElementById("btnLogin").onclick = () => authRequest("/api/auth/login");
  document.getElementById("btnRegister").onclick = () => authRequest("/api/auth/register");
  if (!logged) return;

  document.getElementById("accountBadge").textContent =
    `${me.user.email} · ${planLabel(me.plan)}`;
  const needsSub = me.plan.state === "trial" || me.plan.state === "expired" || me.plan.state === "past_due";
  document.getElementById("btnSubscribe").style.display =
    needsSub && me.billing_configured ? "inline-block" : "none";
  document.getElementById("btnPortal").style.display =
    me.plan.has_subscription ? "inline-block" : "none";

  document.getElementById("btnLogout").onclick = async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    location.reload();
  };
  document.getElementById("btnSubscribe").onclick = () => billingRedirect("/api/billing/checkout");
  document.getElementById("btnPortal").onclick = () => billingRedirect("/api/billing/portal");
}

async function authRequest(path) {
  const email = document.getElementById("authEmail").value.trim();
  const password = document.getElementById("authPassword").value;
  const errEl = document.getElementById("authError");
  errEl.style.display = "none";
  try {
    const res = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }),
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || "Falha na autenticação.");
    }
    location.reload();
  } catch (e) {
    errEl.textContent = e.message;
    errEl.style.display = "block";
  }
}

async function billingRedirect(path) {
  try {
    const res = await fetch(path, { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Falha na cobrança.");
    location.href = data.url;
  } catch (e) {
    alert("Erro: " + e.message);
  }
}
