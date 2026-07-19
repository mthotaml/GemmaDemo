import csv
import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, List, Tuple

APP_DIR = Path(__file__).parent
DATA_FILE = APP_DIR / "sample_shipments.csv"
DB_FILE = APP_DIR / "freightpop_edge_agent.sqlite"

APPROVED_ACCESSORIALS = [
    "Liftgate Delivery",
    "Limited Access Delivery",
    "Residential Delivery",
    "Inside Delivery",
    "Appointment Required",
]

AUTO_APPLY_THRESHOLD = 0.90
REVIEW_THRESHOLD = 0.70
MIN_METADATA_COMPLETENESS = 0.70
LATENCY_WARNING_MS = 500


def bool_value(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def load_csv_rows() -> List[Dict]:
    with DATA_FILE.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    rows = load_csv_rows()
    columns = list(rows[0].keys()) if rows else []
    with db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS shipments (
                scenario_id TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scenario_id TEXT,
                status TEXT,
                gemma_status TEXT,
                recommendations TEXT,
                metadata TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        for row in rows:
            normalized = {column: row.get(column, "") for column in columns}
            conn.execute(
                "INSERT OR REPLACE INTO shipments (scenario_id, payload) VALUES (?, ?)",
                (normalized["scenario_id"], json.dumps(normalized)),
            )


def shipments() -> List[Dict]:
    with db() as conn:
        rows = conn.execute("SELECT payload FROM shipments ORDER BY scenario_id").fetchall()
    return [json.loads(row["payload"]) for row in rows]


def metadata_completeness(shipment: Dict) -> float:
    required = [
        "shipment_mode",
        "origin_address",
        "destination_address",
        "company_name",
        "package_type",
        "pieces",
        "weight_lb",
        "location_type",
    ]
    present = sum(1 for field in required if str(shipment.get(field, "")).strip())
    return present / len(required)


def rule_scores(shipment: Dict) -> Dict[str, Dict]:
    company = str(shipment.get("company_name", "")).lower()
    destination = str(shipment.get("destination_address", "")).lower()
    location = str(shipment.get("location_type", "")).lower()
    notes = str(shipment.get("notes", "")).lower()
    package = str(shipment.get("package_type", "")).lower()
    weight = float(shipment.get("weight_lb") or 0)
    dock = bool_value(shipment.get("loading_dock_available"))
    forklift = bool_value(shipment.get("forklift_available"))
    text = " ".join([company, destination, location, notes])

    output = {}

    score = 0.05
    evidence, conflicts = [], []
    if not dock:
        score += 0.28
        evidence.append("Destination does not have a loading dock.")
    else:
        score -= 0.22
        conflicts.append("A loading dock is available.")
    if not forklift:
        score += 0.22
        evidence.append("Destination does not have a forklift.")
    else:
        score -= 0.20
        conflicts.append("A forklift is available.")
    if weight >= 1000:
        score += 0.28
        evidence.append(f"Shipment weight is {weight:,.0f} lb.")
    elif weight >= 400:
        score += 0.18
        evidence.append(f"Shipment weight is {weight:,.0f} lb.")
    elif weight >= 150:
        score += 0.08
    if package in {"pallet", "skid", "crate", "drum", "container"}:
        score += 0.10
        evidence.append(f"Package type is {package}.")
    if any(k in text for k in ["liftgate", "lift gate", "powered unloading", "no dock"]):
        score += 0.20
        evidence.append("Notes explicitly indicate liftgate or unloading support.")
    output["Liftgate Delivery"] = {
        "rule_score": clamp(score),
        "evidence": evidence,
        "conflicts": conflicts,
        "explanation": "Powered unloading support may be required based on site equipment, shipment weight, and package type.",
    }

    score = 0.04
    evidence, conflicts = [], []
    restricted_types = [
        "hospital", "school", "church", "military", "oil rig", "mine",
        "construction", "airport", "port", "storage", "government", "prison",
    ]
    matched = [x for x in restricted_types if x in text]
    if matched:
        score += 0.58
        evidence.append(f"Restricted or non-standard facility signal detected: {matched[0]}.")
    if any(k in text for k in [
        "security", "gate code", "escort", "restricted", "appointment",
        "limited hours", "marine terminal", "job site", "guard shack",
        "twic", "clearance", "guarded",
    ]):
        score += 0.27
        evidence.append("Notes indicate controlled access or delivery constraints.")
    if location in {"warehouse", "distribution center"} and dock and forklift:
        score -= 0.30
        conflicts.append("Standard commercial receiving capabilities are available.")
    output["Limited Access Delivery"] = {
        "rule_score": clamp(score),
        "evidence": evidence,
        "conflicts": conflicts,
        "explanation": "The destination may require extra time or controlled access because it is not a standard commercial receiving site.",
    }

    score = 0.02
    evidence, conflicts = [], []
    if location == "residential" or any(k in text for k in ["residence", "residential", "home", "apartment", "condo"]):
        score += 0.78
        evidence.append("Destination is identified as a residence.")
    if any(k in destination for k in ["apt ", "apartment", "unit "]):
        score += 0.12
        evidence.append("Address contains residential-unit indicators.")
    if any(k in text for k in ["hospital", "warehouse", "distribution center", "school", "airport", "port"]):
        score -= 0.45
        conflicts.append("Commercial or institutional facility indicators reduce residential likelihood.")
    output["Residential Delivery"] = {
        "rule_score": clamp(score),
        "evidence": evidence,
        "conflicts": conflicts,
        "explanation": "Residential service is indicated when the delivery is to a private home or residential building.",
    }

    score = 0.04
    evidence, conflicts = [], []
    if any(k in text for k in [
        "inside delivery", "deliver inside", "icu", "receiving room", "freight elevator",
        "floor", "suite", "room", "white glove", "carry inside", "front door",
        "administration building", "storage unit",
    ]):
        score += 0.65
        evidence.append("Notes indicate delivery beyond the curb or loading area.")
    if any(k in text for k in ["hospital", "office", "school"]):
        score += 0.12
        evidence.append("Facility type can require delivery to an interior receiving point.")
    if any(k in text for k in ["dock delivery only", "curbside", "leave at dock"]):
        score -= 0.45
        conflicts.append("Notes specify dock-only or curbside delivery.")
    output["Inside Delivery"] = {
        "rule_score": clamp(score),
        "evidence": evidence,
        "conflicts": conflicts,
        "explanation": "Inside delivery may be needed when freight must move beyond the normal exterior receiving point.",
    }

    score = 0.03
    evidence, conflicts = [], []
    if any(k in text for k in [
        "appointment", "schedule delivery", "call before", "notify before",
        "receiving hours", "security clearance", "time window", "scheduled",
        "call consignee",
    ]):
        score += 0.76
        evidence.append("Notes or facility signals require coordination before arrival.")
    if any(k in text for k in ["24/7 receiving", "twenty-four-hour receiving", "no appointment required"]):
        score -= 0.55
        conflicts.append("Destination indicates open receiving without appointment.")
    output["Appointment Required"] = {
        "rule_score": clamp(score),
        "evidence": evidence,
        "conflicts": conflicts,
        "explanation": "An appointment is recommended when receiving access or timing must be coordinated in advance.",
    }

    return output


def call_local_gemma(shipment: Dict, model_name: str) -> Tuple[Dict[str, Dict], str]:
    prompt = {
        "task": "Explain and score each approved freight accessorial from 0.0 to 1.0.",
        "approved_accessorials": APPROVED_ACCESSORIALS,
        "shipment": shipment,
        "instructions": [
            "Return JSON only.",
            "Do not invent accessorial names.",
            "Use shipment fields and notes as evidence.",
            "Return an object named accessorial_analysis.",
            "Each key in accessorial_analysis must be an approved accessorial name.",
            "Each value must include score, rationale, supporting_evidence, and contradicting_evidence.",
            "score must be a number from 0.0 to 1.0.",
            "rationale must be one concise sentence explaining why Gemma assigned that score.",
            "supporting_evidence and contradicting_evidence must be arrays of short strings copied or inferred from shipment fields.",
        ],
        "example_response_shape": {
            "accessorial_analysis": {
                "Liftgate Delivery": {
                    "score": 0.92,
                    "rationale": "No dock, no forklift, and palletized freight indicate liftgate need.",
                    "supporting_evidence": ["No loading dock", "No forklift"],
                    "contradicting_evidence": []
                }
            }
        },
    }
    payload = json.dumps({
        "model": model_name,
        "prompt": json.dumps(prompt),
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.0},
    }).encode("utf-8")
    req = urllib.request.Request(
        "http://localhost:11434/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=25) as response:
        raw = json.loads(response.read().decode("utf-8"))
    parsed = json.loads(raw.get("response", "{}"))
    analysis = parsed.get("accessorial_analysis", {})
    legacy_scores = parsed.get("scores", {})
    clean = {}
    for name in APPROVED_ACCESSORIALS:
        item = analysis.get(name, {})
        if isinstance(item, dict):
            score = item.get("score", legacy_scores.get(name, 0.0))
            rationale = str(item.get("rationale", "")).strip()
            supporting = item.get("supporting_evidence", [])
            contradicting = item.get("contradicting_evidence", [])
        else:
            score = legacy_scores.get(name, item if item else 0.0)
            rationale = ""
            supporting = []
            contradicting = []
        clean[name] = {
            "score": clamp(float(score or 0.0)),
            "rationale": rationale or "Gemma returned a semantic score without a rationale.",
            "supporting_evidence": [str(value) for value in supporting if str(value).strip()],
            "contradicting_evidence": [str(value) for value in contradicting if str(value).strip()],
        }
    return clean, f"Local Gemma response blended with deterministic rules using {model_name}."


def build_recommendations(shipment: Dict, use_gemma: bool, model_name: str) -> Tuple[List[Dict], Dict]:
    start = time.perf_counter()
    completeness = metadata_completeness(shipment)
    guardrails = []

    if str(shipment.get("shipment_mode", "")).upper() != "LTL":
        return [], {
            "status": "skipped",
            "reason": "The agent runs only for eligible LTL shipments.",
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            "metadata_completeness": completeness,
            "guardrails": ["LTL eligibility guardrail triggered."],
            "gemma_status": "not_invoked",
            "gemma_note": "Gemma skipped because shipment is not LTL.",
        }

    if completeness < MIN_METADATA_COMPLETENESS:
        return [], {
            "status": "abstained",
            "reason": "Critical shipment metadata is incomplete.",
            "latency_ms": round((time.perf_counter() - start) * 1000, 2),
            "metadata_completeness": completeness,
            "guardrails": ["Metadata completeness guardrail triggered."],
            "gemma_status": "not_invoked",
            "gemma_note": "Gemma skipped because metadata is incomplete.",
        }

    rules = rule_scores(shipment)
    gemma_analysis = {}
    gemma_status = "disabled"
    gemma_note = "Rules-only mode."

    if use_gemma:
        try:
            gemma_analysis, gemma_note = call_local_gemma(shipment, model_name)
            gemma_status = "connected"
        except Exception as exc:
            gemma_status = "fallback"
            gemma_note = f"Gemma unavailable; deterministic fallback used ({type(exc).__name__})."
            guardrails.append("Local-model failure fallback activated.")

    recommendations = []
    for accessorial in APPROVED_ACCESSORIALS:
        item = rules[accessorial]
        rule_score = item["rule_score"]
        semantic_score = None
        gemma_explanation = None
        if gemma_status == "connected":
            gemma_item = gemma_analysis.get(accessorial, {})
            semantic_score = gemma_item.get("score", rule_score)
            gemma_explanation = {
                "rationale": gemma_item.get("rationale", ""),
                "supporting_evidence": gemma_item.get("supporting_evidence", []),
                "contradicting_evidence": gemma_item.get("contradicting_evidence", []),
            }
            evidence_strength = min(1.0, 0.35 + 0.16 * len(item["evidence"]))
            conflict_penalty = min(0.30, 0.10 * len(item["conflicts"]))
            final_score = clamp(
                0.45 * semantic_score
                + 0.35 * rule_score
                + 0.20 * evidence_strength
                - conflict_penalty
            )
        else:
            final_score = rule_score

        if final_score >= AUTO_APPLY_THRESHOLD:
            action = "Suggest"
            rollout = "Auto-apply eligible"
        elif final_score >= REVIEW_THRESHOLD:
            action = "Review"
            rollout = "Human confirmation required"
        else:
            action = "Do not apply"
            rollout = "Exclude from automation"

        recommendations.append({
            "accessorial": accessorial,
            "confidence": final_score,
            "rule_score": rule_score,
            "gemma_semantic_score": semantic_score,
            "gemma_explanation": gemma_explanation,
            "explanation": item["explanation"],
            "evidence": item["evidence"],
            "contradicting_evidence": item["conflicts"],
            "action": action,
            "rollout_action": rollout,
        })

    latency_ms = round((time.perf_counter() - start) * 1000, 2)
    if latency_ms > LATENCY_WARNING_MS:
        guardrails.append("Latency threshold exceeded; operator should verify recommendations.")

    return recommendations, {
        "status": "completed",
        "reason": "Recommendation completed.",
        "latency_ms": latency_ms,
        "metadata_completeness": completeness,
        "guardrails": guardrails,
        "gemma_status": gemma_status,
        "gemma_note": gemma_note,
    }


def parse_truth(value: str) -> set:
    if not str(value or "").strip():
        return set()
    return {item.strip() for item in str(value).split("|") if item.strip()}


def evaluate_dataset(threshold: float = REVIEW_THRESHOLD) -> Dict:
    tp = fp = fn = tn = 0
    per_accessorial = {name: {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for name in APPROVED_ACCESSORIALS}
    latencies = []

    for row in shipments():
        recs, meta = build_recommendations(row, use_gemma=False, model_name="")
        latencies.append(meta["latency_ms"])
        predicted = {r["accessorial"] for r in recs if r["confidence"] >= threshold}
        actual = parse_truth(row.get("ground_truth_accessorials", ""))
        for name in APPROVED_ACCESSORIALS:
            p = name in predicted
            a = name in actual
            if p and a:
                tp += 1
                per_accessorial[name]["tp"] += 1
            elif p and not a:
                fp += 1
                per_accessorial[name]["fp"] += 1
            elif not p and a:
                fn += 1
                per_accessorial[name]["fn"] += 1
            else:
                tn += 1
                per_accessorial[name]["tn"] += 1

    precision = tp / (tp + fp) if tp + fp else 0
    recall = tp / (tp + fn) if tp + fn else 0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
    rows = []
    for name, counts in per_accessorial.items():
        p = counts["tp"] / (counts["tp"] + counts["fp"]) if counts["tp"] + counts["fp"] else 0
        r = counts["tp"] / (counts["tp"] + counts["fn"]) if counts["tp"] + counts["fn"] else 0
        f = 2 * p * r / (p + r) if p + r else 0
        rows.append({"accessorial": name, "precision": p, "recall": r, "f1": f, **counts})

    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "avg_latency_ms": sum(latencies) / len(latencies) if latencies else 0,
        "per_accessorial": rows,
    }


def log_audit(payload: Dict) -> None:
    shipment = payload.get("shipment", {})
    with db() as conn:
        conn.execute(
            """
            INSERT INTO audit_log (scenario_id, status, gemma_status, recommendations, metadata)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                shipment.get("scenario_id"),
                payload.get("status"),
                payload.get("gemma_status"),
                json.dumps(payload.get("recommendations", [])),
                json.dumps({k: v for k, v in payload.items() if k != "recommendations"}),
            ),
        )


def audit_rows() -> List[Dict]:
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM audit_log ORDER BY id DESC LIMIT 30"
        ).fetchall()
    output = []
    for row in rows:
        output.append({
            "id": row["id"],
            "scenario_id": row["scenario_id"],
            "status": row["status"],
            "gemma_status": row["gemma_status"],
            "recommendations": json.loads(row["recommendations"] or "[]"),
            "created_at": row["created_at"],
        })
    return output


def gemma_health(model_name: str) -> Dict:
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=4) as response:
            raw = json.loads(response.read().decode("utf-8"))
        models = [item.get("name") for item in raw.get("models", [])]
        gemma_models = [name for name in models if name and "gemma" in name.lower()]
        return {
            "connected": True,
            "requested_model_available": model_name in models,
            "models": models,
            "gemma_models": gemma_models,
            "message": "Connected to local Ollama.",
        }
    except Exception as exc:
        return {
            "connected": False,
            "requested_model_available": False,
            "models": [],
            "gemma_models": [],
            "message": f"Ollama unavailable: {type(exc).__name__}.",
        }


class Handler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, payload: Dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> Dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        if self.path.startswith("/api/shipments"):
            self.send_json({"shipments": shipments()})
            return
        if self.path.startswith("/api/audit"):
            self.send_json({"audit": audit_rows()})
            return
        if self.path.startswith("/api/evaluate"):
            self.send_json(evaluate_dataset())
            return
        if self.path.startswith("/api/health"):
            model_name = "gemma4:latest"
            if "?" in self.path:
                query = self.path.split("?", 1)[1]
                for part in query.split("&"):
                    key, _, value = part.partition("=")
                    if key == "model" and value:
                        model_name = urllib.parse.unquote_plus(value)
            self.send_json(gemma_health(model_name))
            return
        super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/recommend"):
            body = self.read_json()
            if not body.get("agent_enabled", True):
                payload = {
                    "shipment": body.get("shipment", {}),
                    "recommendations": [],
                    "status": "disabled",
                    "reason": "Agent disabled by kill switch. Continue with manual shipment workflow.",
                    "latency_ms": 0,
                    "metadata_completeness": metadata_completeness(body.get("shipment", {})),
                    "guardrails": ["Kill switch is active."],
                    "gemma_status": "not_invoked",
                    "gemma_note": "Gemma skipped because the agent is disabled.",
                }
            else:
                recs, meta = build_recommendations(
                    body.get("shipment", {}),
                    bool(body.get("use_gemma")),
                    body.get("model_name") or "gemma4:latest",
                )
                payload = {"shipment": body.get("shipment", {}), "recommendations": recs, **meta}
            log_audit(payload)
            self.send_json(payload)
            return
        self.send_json({"error": "Not found"}, status=404)


if __name__ == "__main__":
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", 4174), Handler)
    print(f"FreightPOP Edge AI demo running at http://localhost:4174")
    print(f"SQLite database: {DB_FILE}")
    server.serve_forever()
