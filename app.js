const api = {
  async get(path) {
    const response = await fetch(path);
    if (!response.ok) throw new Error(`${path} returned ${response.status}`);
    return response.json();
  },
  async post(path, payload) {
    const response = await fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!response.ok) throw new Error(`${path} returned ${response.status}`);
    return response.json();
  }
};

const options = {
  shipment_mode: ["LTL", "FTL", "Parcel"],
  package_type: ["Pallet", "Box", "Crate", "Skid", "Drum", "Container", "Other"],
  location_type: [
    "Hospital", "Residential", "Warehouse", "Distribution Center", "School", "Church",
    "Oil Rig Supply Base", "Mine", "Military Base", "Construction Site", "Airport",
    "Port", "Storage Facility", "Office", "Unknown"
  ]
};

const state = {
  shipments: [],
  selected: null,
  lastPayload: null
};

const el = {
  agentEnabled: document.querySelector("#agentEnabled"),
  useGemma: document.querySelector("#useGemma"),
  modelName: document.querySelector("#modelName"),
  checkGemmaBtn: document.querySelector("#checkGemmaBtn"),
  gemmaStatus: document.querySelector("#gemmaStatus"),
  scenarioSearch: document.querySelector("#scenarioSearch"),
  scenarioList: document.querySelector("#scenarioList"),
  pageTitle: document.querySelector("#pageTitle"),
  shipmentId: document.querySelector("#shipmentId"),
  eligibilityBadge: document.querySelector("#eligibilityBadge"),
  runBtn: document.querySelector("#runBtn"),
  evaluateBtn: document.querySelector("#evaluateBtn"),
  responseStatus: document.querySelector("#responseStatus"),
  latencyBadge: document.querySelector("#latencyBadge"),
  metadataMetric: document.querySelector("#metadataMetric"),
  gemmaMetric: document.querySelector("#gemmaMetric"),
  modeMetric: document.querySelector("#modeMetric"),
  guardrailBox: document.querySelector("#guardrailBox"),
  recommendations: document.querySelector("#recommendations"),
  evaluation: document.querySelector("#evaluation"),
  auditLog: document.querySelector("#auditLog"),
  refreshAuditBtn: document.querySelector("#refreshAuditBtn")
};

function $(id) {
  return document.querySelector(`#${id}`);
}

function fillSelect(id, values) {
  const select = $(id);
  select.innerHTML = values.map((value) => `<option value="${value}">${value}</option>`).join("");
}

function percent(value) {
  return `${Math.round((Number(value) || 0) * 100)}%`;
}

function explainScore(rec, payload) {
  if (payload.gemma_status === "connected" && rec.gemma_semantic_score !== null && rec.gemma_semantic_score !== undefined) {
    return `Final score blends Gemma semantic confidence (${percent(rec.gemma_semantic_score)}), deterministic rule score (${percent(rec.rule_score)}), supporting evidence, and conflict penalties.`;
  }
  return `Final score comes from deterministic business rules because Gemma status is ${payload.gemma_status || "unknown"}.`;
}

function badgeClass(status) {
  if (["completed", "connected"].includes(status)) return "badge good";
  if (["fallback", "skipped", "abstained", "disabled"].includes(status)) return "badge warn";
  if (["error", "unavailable"].includes(status)) return "badge bad";
  return "badge neutral";
}

function scenarioLabel(shipment) {
  return `${shipment.scenario_id} · ${shipment.company_name || "Unknown Receiver"}`;
}

function renderScenarioList() {
  const query = el.scenarioSearch.value.trim().toLowerCase();
  const filtered = state.shipments.filter((shipment) =>
    Object.values(shipment).join(" ").toLowerCase().includes(query)
  );
  el.scenarioList.innerHTML = filtered.map((shipment) => `
    <button class="scenario-card ${state.selected?.scenario_id === shipment.scenario_id ? "active" : ""}" data-id="${shipment.scenario_id}">
      <strong>${scenarioLabel(shipment)}</strong>
      <span>${shipment.shipment_mode} · ${shipment.location_type} · ${shipment.ground_truth_accessorials || "No ground truth accessorials"}</span>
    </button>
  `).join("");
}

function renderShipment() {
  const shipment = state.selected;
  if (!shipment) return;
  el.pageTitle.textContent = "Accessorial Recommendation";
  el.shipmentId.textContent = shipment.scenario_id;
  el.eligibilityBadge.textContent = shipment.shipment_mode === "LTL" ? "Eligible LTL" : "Skipped";
  el.eligibilityBadge.className = shipment.shipment_mode === "LTL" ? "badge good" : "badge warn";

  Object.keys(options).forEach((id) => {
    $(id).value = shipment[id] || options[id][0];
  });
  ["pieces", "weight_lb", "company_name", "origin_address", "destination_address", "notes"].forEach((id) => {
    $(id).value = shipment[id] || "";
  });
  $("loading_dock_available").checked = String(shipment.loading_dock_available).toLowerCase() === "true";
  $("forklift_available").checked = String(shipment.forklift_available).toLowerCase() === "true";
  renderScenarioList();
}

function readShipment() {
  return {
    ...state.selected,
    shipment_mode: $("shipment_mode").value,
    package_type: $("package_type").value,
    pieces: Number($("pieces").value || 0),
    weight_lb: Number($("weight_lb").value || 0),
    location_type: $("location_type").value,
    company_name: $("company_name").value,
    origin_address: $("origin_address").value,
    destination_address: $("destination_address").value,
    loading_dock_available: $("loading_dock_available").checked,
    forklift_available: $("forklift_available").checked,
    notes: $("notes").value
  };
}

function renderPayload(payload) {
  state.lastPayload = payload;
  el.responseStatus.textContent = payload.status?.replaceAll("_", " ") || "Unknown";
  el.latencyBadge.textContent = `${payload.latency_ms ?? 0} ms`;
  el.latencyBadge.className = Number(payload.latency_ms || 0) > 500 ? "badge warn" : "badge neutral";
  el.metadataMetric.textContent = percent(payload.metadata_completeness);
  el.gemmaMetric.textContent = (payload.gemma_status || "unknown").replaceAll("_", " ");
  el.modeMetric.textContent = payload.gemma_status === "connected" ? "Rules + Gemma" : "Rules fallback";

  const guardrails = payload.guardrails?.length ? payload.guardrails : ["No guardrails triggered."];
  el.guardrailBox.textContent = `${payload.reason || "Recommendation completed."} ${payload.gemma_note || ""} ${guardrails.join(" ")}`;

  if (!payload.recommendations?.length) {
    el.recommendations.innerHTML = "<p>No accessorial recommendations returned for this shipment.</p>";
    return;
  }

  const sorted = [...payload.recommendations].sort((a, b) => b.confidence - a.confidence);
  el.recommendations.innerHTML = sorted.map((rec) => {
    const css = rec.confidence >= 0.9 ? "good" : rec.confidence >= 0.7 ? "warn" : "neutral";
    const gemma = rec.gemma_semantic_score === null || rec.gemma_semantic_score === undefined
      ? "Gemma score: not used"
      : `Gemma score: ${percent(rec.gemma_semantic_score)}`;
    const evidence = rec.evidence?.length
      ? rec.evidence.map((item) => `<li>${item}</li>`).join("")
      : "<li>No supporting evidence found.</li>";
    const conflicts = rec.contradicting_evidence?.length
      ? rec.contradicting_evidence.map((item) => `<li>${item}</li>`).join("")
      : "<li>No contradicting evidence found.</li>";
    return `
      <article class="rec-card">
        <div class="rec-head">
          <h4>${rec.accessorial}</h4>
          <span class="badge ${css}">${percent(rec.confidence)} · ${rec.action}</span>
        </div>
        <p>${rec.explanation}</p>
        <div class="bar"><span style="width:${percent(rec.confidence)}"></span></div>
        <div class="evidence">
          <strong>${rec.rollout_action}</strong> · Rule score: ${percent(rec.rule_score)} · ${gemma}<br />
          Evidence: ${(rec.evidence || []).join(" ") || "No supporting evidence."}
          ${(rec.contradicting_evidence || []).length ? `<br />Contradicting evidence: ${rec.contradicting_evidence.join(" ")}` : ""}
        </div>
        <details class="explainability" open>
          <summary>Why this recommendation?</summary>
          <p>${explainScore(rec, payload)}</p>
          <div class="explain-grid">
            <div>
              <span>Inputs</span>
              <strong>Rules ${percent(rec.rule_score)}</strong>
              <em>${gemma}</em>
            </div>
            <div>
              <span>Decision</span>
              <strong>${rec.action}</strong>
              <em>${rec.rollout_action}</em>
            </div>
          </div>
          <div class="explain-columns">
            <div>
              <span>Supporting evidence</span>
              <ul>${evidence}</ul>
            </div>
            <div>
              <span>Contradicting evidence</span>
              <ul>${conflicts}</ul>
            </div>
          </div>
        </details>
      </article>
    `;
  }).join("");
}

async function checkGemma() {
  el.gemmaStatus.textContent = "Checking local Ollama...";
  try {
    const health = await api.get(`/api/health?model=${encodeURIComponent(el.modelName.value)}`);
    if (health.connected) {
      const gemmas = health.gemma_models.length ? health.gemma_models.join(", ") : "no Gemma models found";
      el.gemmaStatus.textContent = `${health.message} Gemma models: ${gemmas}. Requested model ${health.requested_model_available ? "is available" : "is not listed"}.`;
    } else {
      el.gemmaStatus.textContent = health.message;
    }
  } catch (error) {
    el.gemmaStatus.textContent = `Gemma check failed: ${error.message}`;
  }
}

async function runAgent() {
  el.responseStatus.textContent = "Running...";
  el.recommendations.innerHTML = "<p>Evaluating shipment metadata, deterministic rules, and local Gemma if enabled.</p>";
  const payload = await api.post("/api/recommend", {
    shipment: readShipment(),
    agent_enabled: el.agentEnabled.checked,
    use_gemma: el.useGemma.checked,
    model_name: el.modelName.value
  });
  renderPayload(payload);
  await loadAudit();
}

async function evaluateDataset() {
  el.evaluation.textContent = "Running offline evaluation...";
  const metrics = await api.get("/api/evaluate");
  el.evaluation.innerHTML = `
    <div class="eval-grid">
      <div><span>Precision</span><strong>${percent(metrics.precision)}</strong></div>
      <div><span>Recall</span><strong>${percent(metrics.recall)}</strong></div>
      <div><span>F1</span><strong>${percent(metrics.f1)}</strong></div>
      <div><span>Avg latency</span><strong>${metrics.avg_latency_ms.toFixed(2)} ms</strong></div>
    </div>
    <p>Confusion totals: TP=${metrics.tp}, FP=${metrics.fp}, FN=${metrics.fn}, TN=${metrics.tn}</p>
    <table>
      <thead><tr><th>Accessorial</th><th>Precision</th><th>Recall</th><th>F1</th><th>TP</th><th>FP</th><th>FN</th></tr></thead>
      <tbody>
        ${metrics.per_accessorial.map((row) => `
          <tr>
            <td>${row.accessorial}</td><td>${percent(row.precision)}</td><td>${percent(row.recall)}</td><td>${percent(row.f1)}</td>
            <td>${row.tp}</td><td>${row.fp}</td><td>${row.fn}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `;
}

async function loadAudit() {
  const payload = await api.get("/api/audit");
  el.auditLog.innerHTML = payload.audit.length
    ? payload.audit.map((entry) => {
      const visible = entry.recommendations
        .filter((rec) => rec.confidence >= 0.7)
        .map((rec) => rec.accessorial)
        .join(", ") || "No review-or-higher recommendations";
      return `
        <div class="audit-entry">
          <strong><span>${entry.scenario_id || "Manual"}</span><span>${entry.gemma_status}</span></strong>
          <p>${entry.status} · ${visible}</p>
          <p>${entry.created_at}</p>
        </div>
      `;
    }).join("")
    : "<p>No local audit rows yet.</p>";
}

async function init() {
  Object.entries(options).forEach(([id, values]) => fillSelect(id, values));
  const payload = await api.get("/api/shipments");
  state.shipments = payload.shipments;
  state.selected = state.shipments[0];
  renderShipment();
  await checkGemma();
  await loadAudit();
}

el.scenarioList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-id]");
  if (!button) return;
  state.selected = state.shipments.find((shipment) => shipment.scenario_id === button.dataset.id);
  renderShipment();
});
el.scenarioSearch.addEventListener("input", renderScenarioList);
el.checkGemmaBtn.addEventListener("click", checkGemma);
el.runBtn.addEventListener("click", () => runAgent().catch((error) => {
  el.responseStatus.textContent = "Error";
  el.guardrailBox.textContent = error.message;
}));
el.evaluateBtn.addEventListener("click", () => evaluateDataset().catch((error) => {
  el.evaluation.textContent = error.message;
}));
el.refreshAuditBtn.addEventListener("click", loadAudit);

init().catch((error) => {
  el.pageTitle.textContent = "App failed to start";
  el.guardrailBox.textContent = error.message;
});
