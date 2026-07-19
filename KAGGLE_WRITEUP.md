# FreightPOP Edge AI Accessorial Recommendation Agent

## Summary

The FreightPOP Edge AI Accessorial Recommendation Agent is an offline-first logistics assistant that helps dispatchers identify required freight accessorial services before a shipment is finalized.

Accessorials such as liftgate delivery, inside delivery, limited access delivery, residential delivery, and appointment-required service are often missed during shipment creation. These misses can lead to carrier rebills, invoice disputes, delivery delays, failed delivery attempts, and lost revenue.

This prototype uses Gemma 4 running locally through Ollama, blended with deterministic business rules, to recommend approved accessorials from shipment metadata and free-text delivery notes. It is designed for edge environments where internet access may be limited or unavailable, such as hospitals, ports, mines, military bases, construction sites, oil-rig supply bases, and remote warehouses.

## Problem

Dispatchers often make accessorial decisions under time pressure while reading a mixture of structured fields and messy delivery notes.

Examples of accessorial-driving signals include:

- No loading dock
- No forklift
- Heavy palletized freight
- Residential destination
- Hospital, school, port, airport, mine, or military facility
- Security, gate, escort, or appointment requirements
- Notes such as "deliver to ICU receiving" or "call before arrival"

The business cost of missing these signals is real:

- Missed billing opportunities
- Carrier rebills
- Customer invoice disputes
- Manual correction work
- Delayed or failed deliveries
- Lower dispatcher confidence

The goal of this POC is not to replace the dispatcher. The goal is to provide a fast, explainable recommendation while preserving human control.

## Solution

The app evaluates each shipment against a fixed, business-approved accessorial list:

- Liftgate Delivery
- Limited Access Delivery
- Residential Delivery
- Inside Delivery
- Appointment Required

For each accessorial, the app returns:

- Confidence score
- Recommended action
- Rollout eligibility
- Explanation
- Supporting evidence
- Contradicting evidence
- Gemma semantic score when local Gemma is enabled
- Deterministic rule score

The prototype includes a kill switch and fallback behavior. If Gemma or Ollama is unavailable, dispatchers can continue using deterministic recommendations or proceed manually.

## Why Gemma 4

Gemma 4 is useful here because shipment notes are often semantic rather than neatly structured. A deterministic rule can easily detect "no dock," but a local language model is better suited to interpreting phrases such as:

- "Deliver to ICU receiving on the third floor"
- "TWIC escort required at gate"
- "Call superintendent before arrival"
- "Mixed-use residential and commercial building"
- "Use the freight elevator"

The app uses Gemma as an offline semantic scoring layer. Gemma scores each approved accessorial from `0.0` to `1.0` using only the shipment fields and notes. The application then blends Gemma's semantic score with deterministic business rules, evidence strength, and conflict penalties.

This keeps the model core to the recommendation while still enforcing operational guardrails:

- Gemma cannot invent unsupported accessorial names.
- Only approved accessorials are displayed.
- Deterministic rules remain available if local inference fails.
- Human review is required below the auto-apply threshold.
- The app runs without a cloud LLM or external API.

## Architecture

```text
Browser UI
   |
   v
Local Python API
   |
   +--> SQLite shipment and audit database
   |
   +--> Deterministic rules engine
   |
   +--> Local Ollama API
          |
          v
       Gemma 4
```

The runtime flow is:

```text
Operator loads or edits shipment
        |
        v
Eligibility and metadata guardrails run
        |
        v
Rules engine scores approved accessorials
        |
        v
Optional local Gemma semantic scoring runs
        |
        v
Scores are blended with evidence and conflict penalties
        |
        v
Recommendations, explanations, and rollout actions are shown
        |
        v
Decision is written to local SQLite audit log
```

## Demo Walkthrough

Demo video: [Loom walkthrough](https://www.loom.com/share/b18e3f409c4941c68ad3586dbdcbd0a5)

QA checklist: [QA_CHECKLIST.md](./QA_CHECKLIST.md)

1. Start the app:

   ```bash
   python3 server.py
   ```

2. Open:

   ```text
   http://localhost:4174
   ```

3. Confirm that local Ollama is connected and that a Gemma model is available.

4. Select a shipment scenario, such as:

   - `HOSP-001`: hospital delivery with no dock or forklift
   - `PORT-001`: port terminal delivery with TWIC escort requirement
   - `RES-001`: residential heavy pallet delivery
   - `MISS-001`: incomplete metadata guardrail
   - `FTL-001`: non-LTL eligibility guardrail

5. Click **Run Agent**.

6. Review the recommended accessorials, confidence scores, explanations, evidence, and rollout action.

7. Run **Evaluate Dataset** to compare rules-only predictions against ground truth.

## Example Recommendation

For `HOSP-001`, the shipment notes say:

```text
Deliver to ICU receiving on the third floor. No loading dock or forklift.
Appointment and security check required.
```

The app identifies likely accessorials such as:

- Liftgate Delivery
- Limited Access Delivery
- Inside Delivery
- Appointment Required

The recommendation is explainable because the UI shows the evidence behind each accessorial:

- Destination does not have a loading dock.
- Destination does not have a forklift.
- Shipment weight is 1,200 lb.
- Notes indicate delivery beyond the curb or loading area.
- Notes or facility signals require coordination before arrival.

## Evaluation

The included sample dataset contains 21 scenarios with ground-truth accessorial labels.

Rules-only offline evaluation currently produces:

| Metric | Result |
|---|---:|
| Precision | 94.6% |
| Recall | 85.4% |
| F1 Score | 89.7% |
| True Positives | 35 |
| False Positives | 2 |
| False Negatives | 6 |
| True Negatives | 62 |

Per-accessorial results:

| Accessorial | Precision | Recall | F1 |
|---|---:|---:|---:|
| Liftgate Delivery | 88.9% | 100.0% | 94.1% |
| Limited Access Delivery | 100.0% | 81.8% | 90.0% |
| Residential Delivery | 66.7% | 100.0% | 80.0% |
| Inside Delivery | 100.0% | 80.0% | 88.9% |
| Appointment Required | 100.0% | 80.0% | 88.9% |

For an initial rollout, the system intentionally prioritizes precision. In freight billing workflows, false positives can create customer disputes, so the app favors human review for moderate-confidence recommendations.

## Offline and Edge Readiness

The app is built to run locally:

- Browser UI served from a local Python server
- SQLite database created on the local machine
- Gemma called through local Ollama at `localhost:11434`
- No cloud LLM API required
- No package installation required beyond Python and Ollama/Gemma

This makes the prototype relevant for locations with intermittent or restricted connectivity:

- Hospital basement receiving areas
- Port and marine terminals
- Military bases
- Mines
- Construction sites
- Oil-rig supply bases
- Remote warehouses

## Safety and Guardrails

The app includes operational controls that matter in logistics:

- **Approved list only:** the model cannot display unsupported accessorial names.
- **LTL eligibility:** the recommendation engine only runs for eligible LTL shipments.
- **Metadata completeness:** incomplete shipments abstain instead of producing overconfident output.
- **Kill switch:** operators can disable the agent immediately.
- **Gemma fallback:** if local inference fails, deterministic rules continue.
- **Latency warning:** slow local inference triggers a verification guardrail.
- **Human-in-the-loop:** the POC does not automatically dispatch shipments or modify invoices.

## Innovation and Impact

Many AI demos focus on generic chat workflows. This project applies local generative AI to a narrow operational problem where explainability, latency, auditability, and offline behavior matter.

The impact is practical:

- Reduces missed accessorials
- Reduces rebilling and invoice disputes
- Helps dispatchers make consistent decisions
- Keeps shipment data local
- Supports disconnected freight environments
- Provides measurable offline evaluation
- Creates an audit trail for billing and operations review

## Limitations

This is a proof of concept, not a production deployment.

Known limitations:

- The dataset is small and synthetic.
- Confidence scores are directional, not statistically calibrated probabilities.
- Gemma latency depends on local hardware and model size.
- The app does not integrate with a production TMS or carrier rating engine.
- The POC does not auto-apply charges to invoices.
- More real shipment history is needed before production rollout.

## Future Work

Next steps would include:

- Test against historical shipment and rebill data.
- Calibrate thresholds by customer, carrier, lane, and facility type.
- Add operator feedback capture for accept, reject, and override events.
- Add carrier-specific tariff and accessorial policy logic.
- Add facility memory for recurring delivery locations.
- Add analytics for override rate, false positive rate, and revenue recovery.
- Package the app for edge devices used in warehouses and secure facilities.

## Judging Rubric Alignment

### Gemma Integration

Gemma 4 is used as a local semantic scoring engine through Ollama. It evaluates shipment notes and metadata, returns approved accessorial scores, and is blended into the final confidence calculation.

### Innovation and Impact

The app addresses a real logistics problem: missed accessorials cause rebills, disputes, revenue leakage, and delivery delays. The edge-first design makes the approach relevant in locations where cloud AI is not reliable or allowed.

### Functionality

The prototype runs locally, loads demo shipments, checks Gemma availability, produces recommendations, shows explanations and evidence, logs decisions to SQLite, and evaluates against ground truth.

### Presentation and Writeup

This writeup explains the problem, solution, architecture, Gemma usage, metrics, limitations, and future roadmap so the demo can be understood without requiring code inspection.
