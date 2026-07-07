# Model Routing Guide

Two routing tables live here: **(A)** which model tier a development agent
should be for a given task class, and **(B)** which runtime AI/CV model each
production task uses. Both were set by the July 2026 principal review
([`PROJECT-REVIEW-2026-07.md`](PROJECT-REVIEW-2026-07.md)) and informed by the
measured April 2026 multi-model round (`Project Review/`).

Route by **tier**, not by brand name — model names age fast. Tier definitions:

| Tier | Meaning | Examples (as of mid-2026) |
|------|---------|---------------------------|
| Frontier reasoning | Best available reasoning/coding model | Claude 5 (Fable/Mythos), Claude Opus 4.8, GPT-5.x top tier, Gemini Pro top tier |
| Mid-tier agentic coder | Fast, capable, spec-following coder | Claude Sonnet 5, Composer-class IDE agents |
| Fast/cheap | Low-latency, low-cost | Claude Haiku 4.5 class |

---

## A. Development-agent routing

Lessons from the April 2026 round that this table encodes:

- Three-frontier-model review panels produced duplicate signal (GPT 5.4 ≈ Gemini 3.1 Pro) — **family diversity matters more than model count**.
- The most imaginative reviewer (Opus 4.7, Apr 16) was also the only one factually wrong on a verifiable claim — **verification passes must check citations against the code**.
- Composer 2 implemented `P0`–`P2` cleanly **because the specs were prescriptive** (todo.md format). Spec quality is what makes cheaper implementation safe.
- The independent corrections pass (Opus 4.7, Apr 22) caught real production bugs at trivial cost — **always route verification to a different model than the implementer**.

| Task class | Tier | Rationale / rules |
|------------|------|-------------------|
| Architecture arbitration, quarterly reassessment, consensus synthesis | **One** frontier reasoning model, plus at most one from a *different* family | Panels of 3+ are overkill (measured). Reserve for checkpoints, not per-task. |
| Roadmap items with written acceptance criteria (todo.md style) | Mid-tier agentic coder | Frontier here is overkill; the spec carries the correctness. If no spec exists, escalate to "spec writing" first. |
| Spec writing for new roadmap items | Frontier reasoning | The spec is the highest-leverage artifact in this repo's process. |
| Cross-cutting correctness work: merge semantics, dwell model, occupancy metric, concurrency, auth | Frontier coder | These embed subtle invariants (event-log ordering, writer precedence). The April bug list is exactly the defect class mid-tier models introduce. Mid-tier is **too weak** here. |
| Post-merge verification review | One frontier model, **different from the implementer** | Verifier must run `pytest` + `npm run lint` + `npm run build` itself before filing findings, and must cite file/line evidence. One verifier, not a panel; rotate family occasionally. |
| Tests-from-spec, docs sync, lint/CI chores, dependency bumps | Fast/cheap tier | Frontier for docs sync is pure overkill. |
| Fine-tuning scripts, benchmark plumbing | Mid-tier | Mechanical work against existing `benchmark.py` / `fine_tune_yolo11.py` patterns. |
| Interpreting benchmark results; go/no-go on model or metric swaps | Frontier + human | Judgment calls with product consequences — never delegate fully. |
| Large-file decomposition (e.g., `HybridStreetMapView.tsx`) | Frontier writes the decomposition plan; mid-tier executes it | Plan/execute split buys frontier judgment at mid-tier cost. |

### Process rules (binding)

1. Any agent proposing a stack, model, or transport change must cite a measured
   benchmark **from this repo** (`detector/benchmark.py` on labeled parking
   footage). External benchmarks and release notes are not evidence.
2. Verification agents run the full verification gate themselves before filing
   findings; findings without reproduced evidence are marked speculative.
3. Implementer and verifier are never the same model for roadmap-item work.
4. Every completed item ticks its checkboxes in `todo.md` and updates docs in
   the same change set.

---

## B. Runtime model routing (the CV pipeline)

Verdicts: ✅ right-sized · ⬆ upgrade path defined · ⛔ do not do.

| Task | Current | Verdict + rule |
|------|---------|----------------|
| Per-frame vehicle detection | YOLO11n, CPU, frame-skip | ✅ Right-sized for 1–2 fixed cameras. ⬆ Move to `yolo11s` **only** if fine-tuned `11n` measurably misses on the pilot benchmark. Family swaps (YOLO12, RF-DETR) require benchmark evidence per process rule 1. |
| Occupancy decision | Slot-bbox IoU (until `R1.1`) | ⬆ Being replaced by polygon coverage ratio (`R1.1`) — a geometry fix, not a model upgrade. Do not attempt to fix occupancy accuracy with a bigger model before `R1.1` lands. |
| Occupancy (alternative to evaluate) | Per-slot patch classifier (CNRPark/mAlexNet style) | ⬆ `R2.1` runs it head-to-head against fine-tuned YOLO on pilot footage. For fixed cameras it is often more accurate *and* cheaper than detection+overlap. Decision by benchmark, not preference. |
| Motion → "soon" | ByteTrack centroid displacement | ✅ Right-sized. BoT-SORT/OC-SORT add cost with no measured gain on a fixed camera. |
| Dwell → "soon" | Per-spot mean × `SOON_THRESHOLD` | ✅ Right for MVP; statistically weak long-term (dwell is time-of-day dependent and right-skewed). ⬆ `R2.2`: time-bucketed medians/quantiles, then optionally a survival model. ⛔ No ML/LLM model here — overkill. |
| Street geometry lines | Canny + HoughLinesP | ✅ Classical CV is correct for a demo overlay. ⛔ Segmentation models are overkill. |
| Pixel → map coordinates | OpenCV homography (Python) | ✅ Right. ⛔ The TS inverse-distance-weighting copy is a defect, removed in `R1.3`. ⛔ Learned depth/geo models are overkill. |
| VLM (Gemma family) | Excluded from hot path | ✅ Correct. Event-triggered adjunct use only (operator summaries, incident review, privacy flows). ⛔ Per-frame VLM occupancy is overkill in cost and too weak in latency/determinism. Phone-as-detector remains R&D contingent on locally reproduced throughput. |
| Vehicle make/model classification | Disabled extension point in `detector/detector/server.py` | ✅ Keep off until a product need exists. |
