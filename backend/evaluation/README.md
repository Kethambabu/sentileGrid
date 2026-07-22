# backend/evaluation/

Phase 6 evaluation harness (CLAUDE.md §10). Every number below came from an
actual run of `python -m backend.evaluation.run_eval` against real held-out
scenario runs and real LLM calls — none of it is a placeholder.

## Running it

```bash
python -m backend.evaluation.generate_holdout_runs   # once, to (re)build held-out runs
python -m backend.evaluation.run_eval
```

Writes a timestamped JSON report to `data/evaluation/reports/`.

## What each script measures

| Script | Metric | Notes |
| --- | --- | --- |
| `retrieval_eval.py` | Precision@1, recall@topK, false-positive rate | Held-out scenario runs only (CLAUDE.md §9.3) — never runs used to seed the KB |
| `groundedness_eval.py` | Groundedness score, citation completeness | Checks every claim in an explanation cites a retrieved chunk |
| `judge_eval.py` | Hallucination rate | Cross-tier judged — the judging call always uses the LLM tier that did *not* produce the original answer (CLAUDE.md §9.5), verified structurally, not just by convention |
| `risk_accuracy_eval.py` | Risk accuracy | Against authored ground-truth risk levels per incident stage |
| `latency_eval.py` | Per-agent mean latency | Compound-risk, compliance, explanation agents |

## Latest measured results

From `eval_report_20260722T125112.json` (6 holdout runs — the original 3 fault scenarios + baseline, plus Phase 7's `compressor_feed_pressure_loss` and `separator_cooling_duty_loss` — 17 assessment samples):

- Retrieval precision@1 (fault runs): **29.3%**
- Retrieval recall@topK (fault runs): **37.9%**
- Retrieval false-positive rate (negative control): **100%**
- Groundedness: **100%** · Citation completeness: **100%**
- Hallucination rate (cross-tier judged): **66.7%** (3/17 judged — 14 unavailable, LLM free-tier quota pressure during the run; see note below)
- Risk accuracy: **70.6%**
- Latency (mean ms): compound-risk 4129, compliance 6343, explanation 4054

**Precision/recall dropped from the 3-incident library's 46.1%/57.9%** — expected, not a regression: precision@1 gets structurally harder as more incidents are added, since there are more genuinely-similar candidates for the retriever to confuse a live window with. The false-positive-rate and root-cause findings below are unchanged by the library expansion.

**LLM free-tier quota note:** mid-Phase-7, both configured LLM tiers hit their real limits simultaneously — Hugging Face returned `402` (monthly included credits depleted) and Groq returned `429` (daily token limit, ~99,958/100,000 used). The system's response was exactly what CLAUDE.md §5/§14 require: it failed visibly per checkpoint ("reasoning service unavailable: both LLM tiers failed") and skipped those samples, rather than hanging or silently retrying forever. This is real evidence the fail-visibly requirement works as designed, not just a described behavior — but it's also why 14/17 hallucination-judge calls are marked unavailable in this run rather than judged. Re-running with quota headroom (fresh keys, or after Groq's daily reset) would raise that judged fraction; it does not affect groundedness, citation completeness, or the retrieval numbers, none of which depend on the judge call.

## Known limitation: retrieval novelty detection

**CLAUDE.md §9.2/§14 requires the system to output "novel condition, low
confidence" instead of a forced risk score whenever retrieval doesn't
genuinely support one.** As currently built, that safeguard's trigger
condition — cosine similarity below `novel_condition_threshold` in
`backend/config/retrieval.yaml` — essentially never fires, which is why the
false-positive rate above is 100%: every negative-control (no-fault) window
gets matched to *some* incident in the KB with high confidence instead of
being correctly flagged as novel.

**Root cause, confirmed by direct measurement, not guesswork:** `bge-small-en-v1.5`
cosine similarity on this project's templated window-description text
compresses into a roughly 1%-wide band near 1.0 regardless of whether the
match is correct, wrong, or there's no real match at all:

| group | n | mean similarity | stdev |
| --- | --- | --- | --- |
| fault run, correct top-1 match | 64 | 0.9969 | 0.0012 |
| fault run, wrong top-1 match | 72 | 0.9963 | 0.0015 |
| baseline run (should be "novel") | 31 | 0.9960 | 0.0019 |

These are statistically indistinguishable — no absolute threshold, however
calibrated, can separate them.

**Fixes attempted and shipped** (each independently verified, real
improvement on some dimension): BM25 decimal-tokenization (was fragmenting
numbers like `"2942.076"` into near-unique tokens), leading window
descriptions with deviation-from-published-baseline rather than
within-window trend (raised `reactor_a_feed_loss` precision 41.7%→75%), and
per-channel-type similarity thresholds (actuator/xmv channels vs. passive
xmeas/synthetic channels) to stop normal valve-control noise from reading
as an anomaly. None of these closed the novelty-detection gap, because it
isn't a wording or calibration problem.

**Fix attempted and discarded:** a relative/comparative novelty signal
(flag "novel" when the top match isn't meaningfully better than the rest of
its own retrieved candidate pool), tried four ways — margin vs. pool mean,
rank-1-vs-rank-2 gap, margin vs. best candidate from a different incident,
and z-score vs. pool spread. Tested directly against held-out data before
being adopted, not assumed to work: in every formulation, baseline/novel
windows scored **as distinctive or more distinctive** than genuine fault
matches, the opposite of what's needed. Root cause: with only 3 seed
incidents, a fault window's candidate pool is dominated by near-duplicate
sibling chunks (other stages of the *same* correct incident), which
shrinks its own margin, while a baseline window's pool of unrelated
incidents has more natural — but meaningless — score scatter. This is a
genuine negative result, not an unexplored option.

**What would actually fix it:** a similarity channel computed on the raw
numeric window vectors directly, rather than on text descriptions embedded
by a general-purpose sentence encoder — the boilerplate template structure
of the text is what's drowning out the numeric content in the current
approach. Not implemented; flagged here as the next concrete step if this
is revisited, per CLAUDE.md's own precedent of disclosing scope limits
(e.g. TEP's 20-fault coverage) rather than implying broader coverage than
tested.
