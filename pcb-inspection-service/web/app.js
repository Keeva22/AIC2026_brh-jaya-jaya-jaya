const state = {
  boards: [],
  selectedBoard: null,
  stream: null,
  uploadedFile: null,
  selectedSample: null,
  facingMode: "environment",
  busy: false,
};

const $ = (selector) => document.querySelector(selector);
const els = {
  boardList: $("#boardList"),
  boardCount: $("#boardCount"),
  connectionLabel: $("#connectionLabel"),
  sessionId: $("#sessionId"),
  selectionIndex: $("#selectionIndex"),
  selectedBoardTitle: $("#selectedBoardTitle"),
  modeBadge: $("#modeBadge"),
  sourceDot: $("#sourceDot"),
  sourceLabel: $("#sourceLabel"),
  captureStage: $("#captureStage"),
  cameraLed: $("#cameraLed"),
  cameraState: $("#cameraState"),
  captureHint: $("#captureHint"),
  flipCameraButton: $("#flipCameraButton"),
  uploadButton: $("#uploadButton"),
  uploadInput: $("#uploadInput"),
  resultHeading: $("#resultHeading"),
  resultStatus: $("#resultStatus"),
  resultStatusText: $("#resultStatusText"),
  resultImageWrap: $("#resultImageWrap"),
  referenceCount: $("#referenceCount"),
  analyzedCount: $("#analyzedCount"),
  missingCount: $("#missingCount"),
  resultNote: $("#resultNote"),
  databaseControls: $("#databaseControls"),
  referenceImage: $("#referenceImage"),
  referenceMeta: $("#referenceMeta"),
  sampleList: $("#sampleList"),
  actionLed: $("#actionLed"),
  actionMessage: $("#actionMessage"),
  inspectButton: $("#inspectButton"),
  inspectButtonLabel: $("#inspectButtonLabel"),
  componentList: $("#componentList"),
  reportChip: $("#reportChip"),
  methodTitle: $("#methodTitle"),
  methodDescription: $("#methodDescription"),
  toast: $("#toast"),
  captureCanvas: $("#captureCanvas"),
  footerClock: $("#footerClock"),
};

function setText(element, value) {
  element.textContent = value;
}

function showToast(message, duration = 4200) {
  setText(els.toast, message);
  els.toast.classList.add("show");
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => els.toast.classList.remove("show"), duration);
}

function formatError(payload) {
  if (!payload) return "Terjadi error saat memproses inspeksi.";
  if (typeof payload.detail === "string") return payload.detail;
  return "Server tidak dapat menyelesaikan inspeksi.";
}

function stopCamera() {
  if (state.stream) {
    state.stream.getTracks().forEach((track) => track.stop());
    state.stream = null;
  }
}

function renderBoards() {
  els.boardList.replaceChildren();
  state.boards.forEach((board, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "board-button";
    button.dataset.boardId = board.id;
    const top = document.createElement("span");
    top.className = "board-button-top";
    const name = document.createElement("span");
    name.className = "board-name";
    name.textContent = board.name;
    const number = document.createElement("span");
    number.className = "board-index";
    number.textContent = String(index + 1).padStart(2, "0");
    top.append(name, number);
    const mode = document.createElement("span");
    mode.className = "board-mode";
    mode.textContent = board.tag;
    const description = document.createElement("span");
    description.className = "board-description";
    description.textContent = board.description;
    button.append(top, mode, description);
    button.addEventListener("click", () => selectBoard(board.id));
    els.boardList.append(button);
  });
  setText(els.boardCount, String(state.boards.length).padStart(2, "0"));
}

function setSelectedButton(boardId) {
  document.querySelectorAll(".board-button").forEach((button) => {
    button.classList.toggle("selected", button.dataset.boardId === boardId);
  });
}

function resetResult() {
  setText(els.resultHeading, "Waiting for input");
  els.resultStatus.className = "result-status status-idle";
  setText(els.resultStatusText, "IDLE");
  els.resultImageWrap.innerHTML = '<div class="result-placeholder"><span>◌</span><p>Annotated result will appear here</p></div>';
  setText(els.referenceCount, "—");
  setText(els.analyzedCount, "—");
  setText(els.missingCount, "—");
  setText(els.resultNote, "Run an inspection to populate the quality report.");
  els.componentList.innerHTML = '<div class="list-empty">Hasil lokasi akan muncul setelah inspeksi.</div>';
  els.reportChip.className = "report-chip";
  setText(els.reportChip, "NO REPORT");
  setText(els.methodTitle, "Ready when you are.");
  setText(els.methodDescription, "Kamera akan disejajarkan dengan reference PCB sebelum component slots dicocokkan.");
}

function renderEmptyCapture(message = "Choose a board to begin", detail = "Camera or reference image akan tampil di sini.") {
  els.captureStage.className = "capture-stage";
  els.captureStage.innerHTML = "";
  const empty = document.createElement("div");
  empty.className = "empty-stage";
  empty.innerHTML = '<div class="empty-icon">⌁</div>';
  const title = document.createElement("strong");
  title.textContent = message;
  const copy = document.createElement("span");
  copy.textContent = detail;
  empty.append(title, copy);
  els.captureStage.append(empty);
}

function setCaptureImage(url, className = "") {
  els.captureStage.className = `capture-stage ${className}`.trim();
  els.captureStage.innerHTML = "";
  const image = document.createElement("img");
  image.src = url;
  image.alt = "Current PCB input";
  image.className = className.includes("upload") ? "upload-preview" : "";
  els.captureStage.append(image);
}

function renderCameraStage() {
  els.captureStage.className = "capture-stage camera-stage";
  els.captureStage.innerHTML = "";
  const video = document.createElement("video");
  video.id = "cameraVideo";
  video.autoplay = true;
  video.muted = true;
  video.playsInline = true;
  if (state.facingMode === "user") video.classList.add("flipped");
  const overlay = document.createElement("div");
  overlay.className = "camera-overlay";
  els.captureStage.append(video, overlay);
  video.srcObject = state.stream;
}

async function startCamera(board) {
  stopCamera();
  if (!navigator.mediaDevices?.getUserMedia) {
    renderEmptyCapture("Camera API unavailable", "Upload a frame untuk melanjutkan inspeksi board ini.");
    setText(els.cameraState, "UPLOAD FALLBACK");
    els.cameraLed.className = "state-led fail";
    els.flipCameraButton.hidden = true;
    els.inspectButton.disabled = !state.uploadedFile;
    showToast("Browser tidak menyediakan akses kamera. Gunakan Upload Frame.");
    return;
  }
  renderEmptyCapture("Requesting camera access", "Izinkan kamera di browser untuk menampilkan live frame.");
  setText(els.cameraState, "REQUESTING CAMERA");
  els.cameraLed.className = "state-led";
  try {
    state.stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: state.facingMode, width: { ideal: 1280 }, height: { ideal: 720 } },
    });
    if (!state.selectedBoard || state.selectedBoard.id !== board.id) return;
    renderCameraStage();
    setText(els.cameraState, "CAMERA LIVE");
    setText(els.captureHint, "PRESS INSPECT TO CAPTURE");
    els.sourceDot.className = "toolbar-dot live";
    els.cameraLed.className = "state-led live";
    els.flipCameraButton.hidden = false;
    els.inspectButton.disabled = false;
    setText(els.actionMessage, "Live frame siap dianalisis oleh inspection engine.");
  } catch (error) {
    stopCamera();
    renderEmptyCapture("Camera permission needed", "Tekan Upload Frame jika kamera tidak tersedia di perangkat demo.");
    setText(els.cameraState, "CAMERA BLOCKED");
    els.cameraLed.className = "state-led fail";
    els.flipCameraButton.hidden = true;
    els.inspectButton.disabled = !state.uploadedFile;
    showToast(`Akses kamera gagal: ${error.message || "permission denied"}`);
  }
}

function renderSamples(board) {
  els.sampleList.replaceChildren();
  (board.sample_images || []).forEach((sample, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "sample-button";
    button.dataset.index = String(index);
    const image = document.createElement("img");
    image.src = sample.url;
    image.alt = sample.label;
    const label = document.createElement("span");
    label.textContent = sample.label;
    button.append(image, label);
    button.addEventListener("click", () => selectSample(sample, button));
    els.sampleList.append(button);
  });
  const first = board.sample_images?.[0];
  if (first) {
    state.selectedSample = first;
    const firstButton = els.sampleList.querySelector(".sample-button");
    if (firstButton) firstButton.classList.add("selected");
    setCaptureImage(first.url, "upload-preview");
    setText(els.cameraState, "SAMPLE READY");
    els.cameraLed.className = "state-led live";
    setText(els.captureHint, "REFERENCE DATABASE INPUT");
    els.inspectButton.disabled = false;
  }
}

function selectSample(sample, button) {
  state.selectedSample = sample;
  state.uploadedFile = null;
  document.querySelectorAll(".sample-button").forEach((item) => item.classList.remove("selected"));
  button.classList.add("selected");
  setCaptureImage(sample.url, "upload-preview");
  setText(els.cameraState, "SAMPLE READY");
  els.cameraLed.className = "state-led live";
  setText(els.captureHint, "REFERENCE DATABASE INPUT");
  els.inspectButton.disabled = false;
  setText(els.actionMessage, `${sample.label} sample dipilih untuk inspeksi.`);
}

function configureBoardView(board) {
  state.uploadedFile = null;
  state.selectedSample = null;
  els.uploadInput.value = "";
  els.inspectButton.disabled = true;
  els.flipCameraButton.hidden = true;
  els.databaseControls.hidden = board.mode !== "database";
  els.sourceDot.className = "toolbar-dot";
  setText(els.selectedBoardTitle, board.name);
  setText(els.modeBadge, board.mode === "camera" ? "LIVE CAMERA / AUTO ALIGN" : "REFERENCE DATABASE / SLOT CHECK");
  els.modeBadge.className = `mode-badge ${board.mode}`;
  setText(els.sourceLabel, board.mode === "camera" ? "CAMERA INPUT" : "DATABASE INPUT");
  setText(els.actionMessage, board.mode === "camera" ? "Starting camera stream..." : "Select a test sample from the reference database.");
  setText(els.cameraState, board.mode === "camera" ? "STARTING CAMERA" : "SELECT SAMPLE");
  els.cameraLed.className = "state-led";
  setText(els.captureHint, board.mode === "camera" ? "INITIALIZING" : "REFERENCE DATABASE INPUT");
  setText(els.referenceMeta, board.mode === "database" ? "NORMAL PCB / BASELINE" : "NORMAL PCB / BASELINE");
  if (board.reference_image) els.referenceImage.src = board.reference_image;
  resetResult();
}

async function selectBoard(boardId) {
  const board = state.boards.find((item) => item.id === boardId);
  if (!board) return;
  stopCamera();
  state.selectedBoard = board;
  setSelectedButton(board.id);
  const index = state.boards.indexOf(board) + 1;
  setText(els.selectionIndex, String(index).padStart(2, "0"));
  configureBoardView(board);
  if (board.mode === "camera") {
    await startCamera(board);
  } else {
    renderSamples(board);
  }
}

function handleUpload(file) {
  if (!file || !state.selectedBoard) return;
  state.uploadedFile = file;
  state.selectedSample = null;
  const url = URL.createObjectURL(file);
  setCaptureImage(url, "upload-preview");
  setText(els.cameraState, "UPLOADED FRAME READY");
  els.cameraLed.className = "state-led live";
  setText(els.captureHint, "UPLOADED IMAGE INPUT");
  els.inspectButton.disabled = false;
  setText(els.actionMessage, `${file.name} siap dianalisis oleh inspection engine.`);
}

async function captureCameraFrame() {
  if (state.uploadedFile) return state.uploadedFile;
  const video = $("#cameraVideo");
  if (!video || video.readyState < 2) throw new Error("Frame kamera belum siap.");
  const canvas = els.captureCanvas;
  canvas.width = video.videoWidth || 1280;
  canvas.height = video.videoHeight || 720;
  const context = canvas.getContext("2d");
  if (state.facingMode === "environment") {
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
  } else {
    context.save();
    context.translate(canvas.width, 0);
    context.scale(-1, 1);
    context.drawImage(video, 0, 0, canvas.width, canvas.height);
    context.restore();
  }
  const blob = await new Promise((resolve, reject) => canvas.toBlob((value) => value ? resolve(value) : reject(new Error("Capture frame gagal.")), "image/jpeg", .94));
  return new File([blob], `${state.selectedBoard.id}-camera-${Date.now()}.jpg`, { type: "image/jpeg" });
}

async function getInspectionFile() {
  if (state.uploadedFile) return state.uploadedFile;
  if (state.selectedBoard.mode === "camera") return captureCameraFrame();
  if (!state.selectedSample) throw new Error("Pilih sample image terlebih dahulu.");
  const response = await fetch(state.selectedSample.url);
  if (!response.ok) throw new Error("Sample image tidak dapat dibaca.");
  const blob = await response.blob();
  const extension = blob.type.includes("png") ? "png" : "jpg";
  return new File([blob], `${state.selectedBoard.id}-sample.${extension}`, { type: blob.type || "image/jpeg" });
}

function setBusy(busy) {
  state.busy = busy;
  els.inspectButton.disabled = busy;
  els.inspectButtonLabel.textContent = busy ? "ANALYZING..." : "INSPECT BOARD";
  els.actionLed.className = busy ? "action-led live" : "action-led";
  if (busy) {
    els.resultStatus.className = "result-status busy";
    setText(els.resultStatusText, "RUNNING");
    setText(els.resultHeading, "Analyzing board...");
    setText(els.actionMessage, "Alignment dan component slot matching sedang berjalan.");
  }
}

function locationLabel(item) {
  const center = item.center || item.detection?.center;
  if (!Array.isArray(center) || center.length < 2) return "location unavailable";
  return `x ${Math.round(center[0])} · y ${Math.round(center[1])}`;
}

function renderComponentReport(result) {
  const missing = result.missing || [];
  els.componentList.replaceChildren();
  if (missing.length === 0) {
    const row = document.createElement("div");
    row.className = "component-row ok";
    row.innerHTML = '<span class="row-dot"></span><strong>ALL EXPECTED SLOTS</strong><span>reference matched</span><span class="row-status">PASS</span>';
    els.componentList.append(row);
  } else {
    missing.slice(0, 12).forEach((item) => {
      const row = document.createElement("div");
      row.className = "component-row";
      const dot = document.createElement("span");
      dot.className = "row-dot";
      const label = document.createElement("strong");
      label.textContent = item.component_id || `SLOT ${String((item.reference_index ?? 0) + 1).padStart(2, "0")}`;
      const location = document.createElement("span");
      location.textContent = `${item.class || "component"} · ${locationLabel(item)}`;
      const status = document.createElement("span");
      status.className = "row-status";
      status.textContent = "MISSING";
      row.append(dot, label, location, status);
      els.componentList.append(row);
    });
    if (missing.length > 12) {
      const more = document.createElement("div");
      more.className = "list-empty";
      more.textContent = `+ ${missing.length - 12} slot lain ditandai oleh engine.`;
      els.componentList.append(more);
    }
  }
}

function renderResult(result) {
  const status = String(result.status || "FAIL").toUpperCase();
  const pass = status === "PASS";
  const missing = Number(result.missing_count ?? result.missing?.length ?? 0);
  const referenceCount = Number(result.reference_count || 0);
  const detected = Number(result.detected_count ?? 0);
  const analyzed = result.matched_count ?? Math.min(detected || referenceCount, referenceCount);
  setText(els.resultHeading, pass ? "Board accepted" : "Missing component detected");
  els.resultStatus.className = `result-status ${pass ? "pass" : "fail"}`;
  setText(els.resultStatusText, pass ? "PASS" : "FAIL");
  const resultImage = result.result_image;
  els.resultImageWrap.innerHTML = "";
  if (resultImage) {
    const image = document.createElement("img");
    image.src = `${resultImage}${resultImage.includes("?") ? "&" : "?"}t=${Date.now()}`;
    image.alt = `Annotated ${result.board || "PCB"} inspection result`;
    image.addEventListener("error", () => {
      els.resultImageWrap.innerHTML = '<div class="result-placeholder"><span>!</span><p>Hasil tersimpan, preview belum tersedia.</p></div>';
    });
    els.resultImageWrap.append(image);
  } else {
    els.resultImageWrap.innerHTML = '<div class="result-placeholder"><span>!</span><p>Annotated result belum dikirim server.</p></div>';
  }
  setText(els.referenceCount, result.reference_count ?? "—");
  setText(els.analyzedCount, analyzed);
  setText(els.missingCount, missing);
  setText(els.resultNote, pass ? "Semua expected component slots terverifikasi terhadap reference." : `${missing} lokasi komponen perlu diperiksa pada hasil annotated.`);
  els.reportChip.className = `report-chip ${pass ? "pass" : "fail"}`;
  setText(els.reportChip, pass ? "PASS / VERIFIED" : `${missing} FLAGGED SLOT${missing > 1 ? "S" : ""}`);
  renderComponentReport(result);
  setText(els.methodTitle, `${result.alignment_method || "Reference slot comparison"}`);
  setText(els.methodDescription, result.mode === "database" ? "Citra test disejajarkan dengan database reference normal, lalu setiap slot dibandingkan untuk menandai perbedaan." : "Frame kamera disejajarkan ke canonical PCB reference, lalu YOLO detections dicocokkan ke expected component slots.");
}

async function inspectBoard() {
  if (!state.selectedBoard || state.busy) return;
  setBusy(true);
  try {
    const file = await getInspectionFile();
    const formData = new FormData();
    formData.append("file", file, file.name);
    const response = await fetch(`/api/inspect/${state.selectedBoard.id}`, { method: "POST", body: formData });
    const payload = await response.json().catch(() => null);
    if (!response.ok) throw new Error(formatError(payload));
    renderResult(payload);
    setText(els.actionMessage, `Inspection selesai · ${payload.status || "RESULT"} · ${new Date().toLocaleTimeString("id-ID")}`);
    showToast(`Inspection ${payload.status || "completed"} untuk ${state.selectedBoard.name}.`, 3000);
  } catch (error) {
    els.resultStatus.className = "result-status fail";
    setText(els.resultStatusText, "ERROR");
    setText(els.resultHeading, "Inspection failed");
    setText(els.resultNote, error.message || "Unexpected inspection error.");
    setText(els.actionMessage, "Periksa koneksi backend atau input image, lalu coba lagi.");
    showToast(error.message || "Inspection gagal.");
  } finally {
    setBusy(false);
    if (state.selectedBoard?.mode === "camera" && state.stream) {
      els.inspectButton.disabled = false;
    }
  }
}

async function flipCamera() {
  if (!state.selectedBoard || state.selectedBoard.mode !== "camera") return;
  state.facingMode = state.facingMode === "environment" ? "user" : "environment";
  await startCamera(state.selectedBoard);
}

async function boot() {
  setText(els.sessionId, Math.random().toString(36).slice(2, 8).toUpperCase());
  try {
    const response = await fetch("/api/boards");
    if (!response.ok) throw new Error("Boards endpoint unavailable");
    const payload = await response.json();
    state.boards = payload.boards || [];
    renderBoards();
    setText(els.connectionLabel, "ENGINE ONLINE");
    if (state.boards[0]) await selectBoard(state.boards[0].id);
  } catch (error) {
    setText(els.connectionLabel, "ENGINE OFFLINE");
    els.boardList.innerHTML = '<div class="list-empty">Backend belum aktif. Jalankan <span class="mono">uvicorn backend.main:app</span> lalu refresh halaman.</div>';
    showToast("Backend belum aktif. Jalankan server lokal terlebih dahulu.", 7000);
  }
}

els.uploadButton.addEventListener("click", () => els.uploadInput.click());
els.uploadInput.addEventListener("change", (event) => handleUpload(event.target.files?.[0]));
els.inspectButton.addEventListener("click", inspectBoard);
els.flipCameraButton.addEventListener("click", flipCamera);
window.addEventListener("beforeunload", stopCamera);
window.setInterval(() => setText(els.footerClock, new Date().toLocaleTimeString("en-GB")), 1000);
boot();
