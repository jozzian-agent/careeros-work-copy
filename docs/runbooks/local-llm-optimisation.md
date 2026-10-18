# Local-LLM optimisation: what we measured and what to keep

Findings from the CAREER-57 follow-up timing work (2026-10-18), so the
lessons are not lost. Host: **ideaai** (Lenovo IdeaPad Pro 5, CPU-only,
Ollama at `http://192.168.1.10:11434`, default model `qwen3:30b-a3b`).
All numbers below are measured on that box, not estimated.

## The one finding that matters most: use the native API, not /v1

qwen3 is a *reasoning-capable* model. Thinking mode must be switched off
per request, and **Ollama's OpenAI-compatible `/v1/chat/completions`
endpoint silently ignores the `think` parameter** (verified on Ollama
0.34.4). The native `/api/chat` endpoint honours it.

Same realistic classification prompt (395 prompt tokens, JSON out):

| Path | Latency | Result |
|---|---|---|
| `/v1/chat/completions`, `think=False` sent | **105.9 s** | model spent ~100 s thinking, then answered; would hit the 120 s client timeout on longer prompts |
| `/api/chat`, `think:false`, `format:json` | **9.3 s** | correct JSON, same quality |

That is a **>10x difference** and it is invisible: no error, no warning,
just slow answers. The classify pipeline therefore has a
`CLASSIFY_LLM_NATIVE=1` env switch (`careeros.classify.llm.Config`),
which routes `careeros.llm_client.LLMClient` to the native endpoint and
translates only the keys that survive the trip (`model`, `messages`,
`stream`, `temperature`, `format`, `think`). **Every scheduled or manual
LLM-layer run must set it**; `scripts/nightly_pipeline.sh` exports it.

Corollary: never assume an OpenAI-compatible shim forwards
vendor-specific parameters. If a setting is load-bearing, test that the
shim passes it (compare against the native endpoint once) and record the
answer here.

## What was already right (keep it)

- **JSON in, JSON out.** The client sends `format: json` (native) /
  `response_format: {"type":"json_object"}` (/v1). The model answers
  strict JSON; `_parse` still defends against fenced or prose-wrapped
  output. Zero parse failures in the 10-call measured run.
- **Constrained answer space.** The prompt lists the *only* allowed
  codes per field ("One of: code (label), …, unknown") instead of the
  whole taxonomy. Shorter prompt, fewer hallucinated codes, and
  `unknown` is always an allowed answer so the model can decline.
- **One call per posting, all open fields at once.** Fields share the
  posting text; asking per field would re-send it per dimension.
- **temperature 0** and **per-call metrics** (`latency_ms`,
  prompt/completion tokens, `ok`, error) recorded into every run YAML —
  that is how the numbers in this file were produced and how regressions
  will be caught.
- **Trimmed subject text**: title + department + employer + place +
  description capped at `TEXT_LIMIT` chars — the prompt is ~1.7 KB, not
  the full posting.

## Measured performance (2026-10-18, native path)

- 10-posting live run, `--layer llm`: mean **19.0 s/call** (min 15.5,
  max 27.0), mean 1 106 tokens/call. The 19 s mean is higher than the
  9.3 s single-shot probe because the real prompt asks more fields and
  includes evidence strings.
- Model reload is not a factor mid-run (calls are back-to-back, Ollama
  keeps the model resident); the first call after idle pays a load, the
  run does not.
- 204-posting pool ⇒ ~65 min expected, ~92 min worst case. Fits the
  overnight window with hours of margin.

## Knobs not yet used (try in this order if speed becomes a problem)

1. **Smaller model.** `qwen3:14b` is resident on the same box; on
   CPU-only hardware roughly 2x faster per token. Gate: re-run the
   golden-set accuracy report and only switch if the fields it answers
   do not regress. Speed is not worth accuracy we measured a gate for.
2. **Fewer prompt tokens.** Prompt eval was 5.8 s of the 9.3 s probe —
   most of the cost is *reading*, not writing. The taxonomy option lists
   are the bulk; if a field has >15 candidates, send only the 2-3
   families the rules layer already narrowed to.
3. **`num_predict` cap.** Answers are small JSON; capping output at
   ~400 tokens prevents a runaway generation from eating the night.
   (The 10-call run never exceeded ~200.)
4. **`num_ctx` floor.** Default context is far larger than a 400-token
   prompt needs; a smaller `num_ctx` reduces KV-cache allocation on a
   CPU box.
5. **Batching.** One call already covers all open fields for a posting.
   Batching several *postings* per call trades isolation (one bad answer
   poisons the batch) for throughput — only worth it if 1-4 are not
   enough.

## Anti-patterns (do not do these)

- Do not "optimise" by dropping `think:false` because it looks
  redundant — it is the single most load-bearing parameter in the
  request (see table above).
- Do not raise the ATS fetch rate limit to make the night shorter; the
  1 req/s cap is politeness, not performance tuning.
- Do not treat a failed model call as fatal: it lands in `needs_review`
  with a reason, which is the designed behaviour. A night with a few
  failed calls is a successful night.
- Do not benchmark with a toy prompt ("say PONG"): qwen3's thinking
  behaviour differs per prompt shape, and only realistic prompts
  (option lists + evidence requirements) reproduce the 19 s figure.

## Re-verify after any change

```bash
cd /root/work/careeros-dashboard
CLASSIFY_LLM_NATIVE=1 .venv/bin/python scripts/run_classification.py \
    --pool data/ats/exports/golden_set_pool_2026-10-18.yaml \
    --layer llm --limit 10 --dry-run
# then: scripts/classification_report.py for the accuracy gate
```

Compare mean `latency_ms` against the 19.0 s baseline above; compare
accuracy against `data/classification_accuracy_2026-10-18.md`. Record
the new numbers here, dated — this file is the memory of what the box
can do.
