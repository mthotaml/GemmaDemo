# FreightPOP Edge AI Accessorial Agent POC

An offline-first logistics assistant that uses deterministic rules plus local Gemma 4 inference to recommend freight accessorial services before shipment execution.

Full Kaggle-style writeup: [KAGGLE_WRITEUP.md](./KAGGLE_WRITEUP.md)

Demo video: [Loom walkthrough](https://www.loom.com/share/b18e3f409c4941c68ad3586dbdcbd0a5)

QA checklist: [QA_CHECKLIST.md](./QA_CHECKLIST.md)

## What It Demonstrates

- Offline-first edge app
- SQLite-backed local shipment/audit database
- Deterministic accessorial rules
- Local Gemma 4 inference through Ollama
- Approved accessorial whitelist only
- LTL eligibility guardrail
- Metadata completeness guardrail
- Kill switch
- Human review rollout thresholds
- Offline evaluation against demo ground truth

## Current Evaluation

Rules-only offline evaluation on the included 21-scenario sample dataset:

| Metric | Result |
|---|---:|
| Precision | 94.6% |
| Recall | 85.4% |
| F1 Score | 89.7% |

## Local Gemma

The app calls Ollama at `http://localhost:11434/api/generate`.

Confirmed available in this environment:

- `gemma4:latest`
- `gemma4:12b`

If Ollama or Gemma is unavailable, the app falls back to deterministic rules.

Gemma is used as a semantic scoring layer for delivery notes and shipment context. The final score blends Gemma's output with deterministic rules, evidence strength, and conflict penalties while restricting output to approved accessorials.

## Run

```bash
python3 server.py
```

Then open:

```text
http://localhost:4174
```

The SQLite file is created at:

```text
freightpop_edge_agent.sqlite
```

## Reviewer Links

- Demo video: [https://www.loom.com/share/b18e3f409c4941c68ad3586dbdcbd0a5](https://www.loom.com/share/b18e3f409c4941c68ad3586dbdcbd0a5)
- QA checklist: [QA_CHECKLIST.md](./QA_CHECKLIST.md)
- Kaggle writeup: [KAGGLE_WRITEUP.md](./KAGGLE_WRITEUP.md)
