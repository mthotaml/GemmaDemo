# FreightPOP Edge AI Accessorial Agent POC

This rebuild follows the latest PRD:

- Offline-first edge app
- SQLite-backed local shipment/audit database
- Deterministic accessorial rules
- Optional local Gemma inference through Ollama
- Approved accessorial whitelist only
- LTL eligibility guardrail
- Metadata completeness guardrail
- Kill switch
- Human review rollout thresholds
- Offline evaluation against demo ground truth

## Local Gemma

The app calls Ollama at `http://localhost:11434/api/generate`.

Confirmed available in this environment:

- `gemma4:latest`
- `gemma4:12b`

If Ollama or Gemma is unavailable, the app falls back to deterministic rules.

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
