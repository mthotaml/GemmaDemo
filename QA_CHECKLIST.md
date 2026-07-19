# QA Checklist

Demo video: [Loom walkthrough](https://www.loom.com/share/b18e3f409c4941c68ad3586dbdcbd0a5)

QA demo video: [Loom QA walkthrough](https://www.loom.com/share/4ffcf9c919d2435db5206c605c47d9be)

GitHub repo: [mthotaml/GemmaDemo](https://github.com/mthotaml/GemmaDemo)

## Smoke Test

1. Start the local app:

   ```bash
   python3 server.py
   ```

2. Open:

   ```text
   http://localhost:4174
   ```

3. Confirm the app loads with:

   - `Accessorial Recommendation` page title
   - `Powered by Gemma` banner
   - 21 demo shipment scenarios
   - Agent controls in the sidebar

## Gemma Connectivity

1. Confirm Ollama is running locally.
2. Use model `gemma4:latest`.
3. Click **Check Gemma**.
4. Expected result:

   ```text
   Connected to local Ollama.
   ```

The app should list available Gemma models and show that the requested model is available.

## Recommendation Flow

1. Select `HOSP-001`.
2. Keep **Agent enabled** on.
3. Keep **Use local Gemma** on.
4. Click **Run Agent**.
5. Expected result:

   - Status: `completed`
   - Mode: `Rules + Gemma`
   - Recommendations render for approved accessorials only
   - Evidence and explanations are shown
   - SQLite audit log receives a new entry

## Guardrail Tests

### Non-LTL Shipment

1. Select `FTL-001`.
2. Click **Run Agent**.
3. Expected result:

   - Status: `skipped`
   - Guardrail says the agent runs only for eligible LTL shipments

### Incomplete Metadata

1. Select `MISS-001`.
2. Click **Run Agent**.
3. Expected result:

   - Status: `abstained`
   - Guardrail says critical shipment metadata is incomplete

### Kill Switch

1. Turn **Agent enabled** off.
2. Click **Run Agent**.
3. Expected result:

   - Status: `disabled`
   - Gemma is not invoked
   - Dispatcher can continue manually

## Offline Evaluation

1. Click **Evaluate Dataset**.
2. Expected baseline:

   | Metric | Result |
   |---|---:|
   | Precision | 94.6% |
   | Recall | 85.4% |
   | F1 Score | 89.7% |

## Code Checks

Run:

```bash
python3 -m py_compile server.py
node --check app.js
```

Both commands should complete without errors.
