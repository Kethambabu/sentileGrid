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
genuinely support one.** As originally built, that safeguard's trigger
condition — cosine similarity below `novel_condition_threshold` in
`backend/config/retrieval.yaml` — essentially never fired, which is why the
false-positive rate was 100%: every negative-control (no-fault) window got
matched to *some* incident in the KB with high confidence instead of being
correctly flagged as novel.

**Root cause of the original (cosine) problem, confirmed by direct
measurement, not guesswork:** `bge-small-en-v1.5` cosine similarity on this
project's templated window-description text compresses into a roughly
1%-wide band near 1.0 regardless of whether the match is correct, wrong, or
there's no real match at all:

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

### Fix implemented: numeric feature-vector similarity channel — real improvement, gap not closed

A supplementary similarity channel computed directly on the raw numeric
window vectors (`backend/rag/chunker.py::compute_feature_vector` +
`backend/rag/numeric_similarity.py`), rather than on text descriptions
embedded by a general-purpose sentence encoder, was implemented and measured
against real held-out data across **three independent sampling passes**
(2026-07-23, `sample_every` = 10, 25, and 40 — different windows sampled
each time, to check the finding wasn't an artifact of one particular
sample):

| group | pass 1 (n) | pass 2 (n) | pass 3 (n) |
| --- | --- | --- | --- |
| fault run, correct top-1 match | 0.227 (33) | 0.262 (8) | 0.193 (9) |
| fault run, wrong top-1 match | 0.174 (67) | 0.156 (34) | 0.206 (16) |
| baseline run (should be "novel") | 0.313 (16) | 0.266 (6) | 0.333 (4) |

**What worked:** unlike cosine similarity, "wrong" matches are measurably
lower than "correct" matches on this channel (a real, if modest, signal —
this metric genuinely helps distinguish a good match from a bad one).

**What didn't:** in **all three** independent passes, the baseline
(negative-control) group's mean similarity **exceeded** the fault-correct
group's mean — the opposite of what novelty detection needs, and consistent
enough across three separately-sampled passes to rule out sampling noise.
**This is a structural limitation of the metric, not a threshold-tuning
problem.** Root cause (confirmed by inspection): a true no-fault window's
deviation-from-baseline vector is near-zero across all 16 summary channels,
and it best-matches against KB chunks from incidents' own early-warning
stages — which are *also* near-zero, since an incident hasn't escalated yet
at that stage. Two near-zero vectors are always numerically close to each
other regardless of whether they represent the same real precedent, while
two genuinely escalated (large, noisy) fault vectors need much closer
alignment to score as similar. This magnitude bias is distinct from the
original cosine boilerplate-dominance problem — a different failure mode,
not the same one recurring.

**Practical consequence, measured directly (not inferred):** every
threshold tested traded one failure mode for another —

- `threshold = 0.5` (initial reasoned guess): `is_novel_condition` fired on
  **100% of both fault and negative-control samples** — universal caution,
  meaning the Compound-Risk Agent would never report a real risk score at
  all under this setting.
- `threshold = 0.20` (first recalibration attempt, chosen to sit just above
  the fault-wrong band): **100% false-positive rate** on the negative
  control (reverting to the original problem) **and** suppressed **58.6%**
  of real fault detections into "novel, no score" — worse than either
  single failure mode alone.
- `threshold = 0.25` (current, documented in `retrieval.yaml` as a
  best-effort compromise sitting between the fault-wrong and fault-correct
  bands): not presented as validated — expect both false positives on true
  negatives and false suppression on genuine faults at rates that vary by
  which window arrives, since no global cutoff on this metric separates the
  groups cleanly.

**Honest bottom line: this fix is a real, partial improvement (the
"wrong-vs-correct" discrimination is genuine signal that didn't exist
before) but it does NOT close the novelty-detection gap required by
CLAUDE.md §9.2.** Report it as "attempted, root cause partially addressed,
new residual limitation discovered and documented" — not as "fixed."

**What would actually fix it (not implemented, flagged as the next concrete
step per this project's own precedent of disclosing scope limits rather
than implying broader coverage than tested):** gate on the *live window's
own* deviation magnitude (its feature vector's norm against a fixed
"is this near baseline at all" bound) as a first-pass filter, independent of
best-match similarity to any KB chunk. That would stop a genuinely flat live
window from ever being compared against early-stage incident chunks in the
first place — recognizing "nothing is happening" on the live window's own
terms, rather than trying to infer it from resemblance to an arbitrary KB
chunk after the fact.
