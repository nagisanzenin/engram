# 05 · The Affective Layers: Motivation and Wisdom, Compiled for an Agent

This document extends the theoretical constitution (`docs/01-foundations.md`) with two layers that the first four pillars implied but never made explicit: **why the learner shows up tomorrow**, and **how a wise tutor carries them through the part where learning is supposed to hurt**. It exists because a founder — learning system design, a subject he does not (yet) find fun — noticed the machine was correct and complete and still, some evenings, boring. The engine was verified. The *will to run it* was left to chance.

The instinct behind this document is right, and the evidence is unusually clear about how to honor it *without* breaking anything. The short version, stated before the argument so it can be checked against it:

> **The dopamine Engram was missing is not the dopamine of a slot machine. It is the dopamine of competence, curiosity, and visible progress — which Engram already *generates* and then *throws away*. The fix is to surface what is already true, never to manufacture what is not.**

Everything below is either (a) making a real, already-computed signal visible at the moment it happens, or (b) the tutor saying out loud, at the moment of felt difficulty, something Engram already believes. Neither adds a game. Both were adversarially checked against the literature that says motivation layers backfire — and they survive precisely because they are not that.

A note on method: the claims here were assembled by a fan-out research pass (100+ web searches, sources fetched, every load-bearing number verified against the primary paper by an adversarial voter that was told to *refute* it). Effect sizes are given where they exist; where a canonical idea failed replication or was never tested on adults, that is said plainly. This document prefers a small verified claim to a large inspiring one.

---

## The unifying frame, extended: prediction error is also a *reward* signal

`01-foundations.md` opens on one computational idea — brains update on prediction error — and uses it to justify generation-first encoding. That same dopaminergic signal (Schultz et al., 1997) is not only how memory *encodes*; it is how motivation *is felt*. The two layers in this document are the motivational face of the same coin the engine already spends:

- **Curiosity** is the *appetite* for a prediction to be resolved. Gruber, Gelman & Ranganath (2014, *Neuron*) showed states of high curiosity both improve memory (70.6% vs 54.1% immediate recall; 45.9% vs 28.1% at ~24h) *and* light up the dopaminergic reward circuit (NAcc, SN/VTA) — "a link between the mechanisms supporting extrinsic reward motivation and intrinsic curiosity," in their words. Engram's curiosity-gap session openings are already this. The layer just protects and repeats the move.
- **Competence** is the *satisfaction* of a prediction resolved in your favor. Successful retrieval is a reward-prediction-error event with a number attached — the FSRS stability jump. Engram computes that number on every review and discards it. Surfacing it is the single highest-leverage change in this document.

So the two new pillars are not bolted on. They are the reward side of the prediction-error engine that was already the theory.

---

## Pillar 13 — Competence salience: the honest reward

**Claim.** Making *real* progress visible at the moment it happens sustains motivation, and does so without any of the risks that sink gamification — because it is information, not a token.

**Evidence.**
- **Progress monitoring causally improves goal attainment.** Harkin et al. (2016, *Psychological Bulletin*), meta-analysis of **138 randomized studies, N = 19,951**: prompting people to monitor progress toward a goal raised attainment **d+ = 0.40 [0.32, 0.48]**, and — critically — the effect was *larger when progress was physically recorded or reported* rather than left implicit. This is the direct warrant for surfacing the stability jump and for micro-session completion structure. (Caveat: the corpus is health-behavior-heavy; extension to learning is domain transfer, though the mechanism is domain-general.)
- **Competence feedback enhances adult intrinsic motivation — specifically adults.** Deci, Koestner & Ryan (1999, *Psychological Bulletin*), the 128-experiment meta-analysis usually cited *against* rewards, found the opposite for informational verbal feedback: free-choice intrinsic motivation **d = +0.33**, interest **d = +0.31**, and the free-choice effect was **college-student-specific (d = 0.43 [0.27, 0.58]) and null for children (d = 0.11, ns)**. Engram's users are adults. This is the one point where the rival behaviorist meta-analyses (Cameron & Pierce) *agree*.
- **The hard boundary.** The *same* paper: informational-vs-controlling praise composite **d = −0.78 [−1.02, −0.54]**. "When positive feedback is administered controllingly, the negative effect of the control counteracts the positive effects of the information." Competence data delivered as *information* ("this memory now holds ~4× longer") is a reward; the *same* data delivered as *pressure* ("great — keep it up, don't slip!") is a net negative. The line is not what you show; it is whether it steers.

**Design consequence.** Engram surfaces competence as fact, at three grains:
1. **Per-review (the moment):** on a genuine stability gain, the tutor may state the real jump from the engine's own `s_before → s_after` output — *"that went from holding ~2 days to ~9 days; it'll survive the week now"* — as one informational line, never a score, never a should-statement. Silence when there was no real gain (see Pillar 14 on when *not* to speak).
2. **Per-session (the close):** the receipt strip already exists; it gains an honest momentum line drawn from real receipts (nodes moved to retained, stability added), never a streak count.
3. **Per-week (the coach):** a `momentum` readout computed by `engram.py` — not the model — from the last seven days of receipts: reviews cleared, total days of durability added, most-durable memory now. Deterministic core does the math (Article 10); the coach only narrates it.

**Anti-patterns (this pillar is a leash as much as a license):**
- **No invented reward tokens.** No XP, points, badges, or levels. The number must be a real memory-stability or retention figure the engine computed, or it is not shown.
- **No streak counters by default.** (Pillar 14 handles why, with evidence.)
- **Never controlling.** Growth is reported the way a good lab notebook reports a result — flatly, because the result is good. If a line would survive being read by a skeptic as "the tutor is trying to make me feel a certain way," it is cut.

---

## Pillar 14 — The mentor stance: wisdom at the point of difficulty

**Claim.** Learning that is worth anything is effortful, and the effort *feels like failure* even when it is working. A wise tutor names this at the moment it is felt — reframing struggle as encoding, absolving lapses, and holding high standards *with* the assurance the learner can meet them — and stays silent, or terse, everywhere else. This is a *stance*, deployed at specific moments, not a personality of constant warmth.

This is the layer with the most seductive literature and the most failed replications, so it is stated conservatively: each move below is kept only because it is either (a) evidence-supported at adult scale, or (b) free — it costs nothing, aligns with an existing anti-sycophancy rule, and the *downside* case is what's ruled out by evidence.

**Evidence, move by move.**

- **Struggle is the encoding signal — and learners systematically misread it.** Bjork's desirable-difficulties program (already Pillar 3) plus **Kirk-Johnson, Galla & Fraundorf (2019)**: learners abandon effortful strategies precisely *because* effort feels like poor learning (the "fluency illusion" as a motivational trap, not just a metacognitive one). The mentor move — *"this friction is the memory forming; easy review would mean nothing stuck"* — is Engram's own P3 thesis, voiced at the instant the learner would otherwise quit. **Supported mechanism.**
- **Confusion helps — when it resolves — and comfort offered too early hurts.** D'Mello, Lehman, Pekrun & Graesser (2014), "Confusion can be beneficial for learning": induced confusion improved learning *when subsequently resolved*. The authors' own design rule is the load-bearing quote: **"don't be supportive until the students need support."** So the mentor does not rush to soothe a productive struggle; it lets the confusion sit inside the struggle budget and arrives at the point of genuine need. **Supported, with a boundary.**
- **Wise feedback: use the framing, don't claim the effect.** Yeager, Purdie-Vaughns et al.'s "wise feedback" (high standards + explicit assurance the learner can meet them) produced striking gains in the original (K-12, minority students: **71% vs 17% revision**). But a preregistered **university replication (n = 94) failed** — both conditions had high baseline trust, so there was nothing to move. Verdict: **mixed at adult scale.** Engram adopts the *framing* ("I'm holding this to a real standard because you can meet it") because it costs nothing and it *is* the anti-sycophancy stance already in the constitution — but it is not sold as a lever with an effect size.
- **After a bad grade: absolve, never pity.** Two findings converge. **Breines & Chen (2012):** self-compassion after failure *increased* self-improvement motivation and subsequent study time. But **Graham (1984):** expressed sympathy/pity and unsolicited help after failure function as **low-ability cues** — "there, there" tells the learner you think they *can't*. And **Brummelman et al. (2014, *Psychological Science*):** *inflated* praise **decreases** challenge-seeking in low-self-esteem children — over-encouragement backfires on exactly the vulnerable learner it targets. The synthesis is sharp: the response to a lapse is **absolution + high standards** ("nothing lost, this is normal, here's the re-derivation"), never sympathy, never inflation.
- **Relevance must be self-generated, not preached.** Utility-value interventions work (Hulleman & Harackiewicz 2009, N = 262: gains for low-expectation students), **but** Canning & Harackiewicz (2015), "Teach It, Don't Preach It": *directly communicating* why material matters **backfires for low-confidence learners**, lowering interest — while having them *generate* the relevance themselves works. So when motivation sags, the mentor **asks** ("where does this touch the thing you're actually trying to build?") and never **lectures** relevance. **Supported, with a strict how.**
- **Return-after-absence absolution — the strongest Layer-2 evidence.** Silverman & Barasch (2022/23, *JCR*, 7 studies, ~5,000 participants): a *broken* streak depresses subsequent engagement, self-attributed lapses depress it *more* (48% vs 60% continuation), and a **repair/amnesty option causally restores it (+14.5 pp)**. Duolingo's measured forgiveness mechanics agree (Weekend Amulet +4% return, −5% streak loss; Streak Wager +14% D7 retention). And habit science removes the guilt's basis entirely: **Lally et al. (2010)** — a single missed day "did not materially affect" habit formation. So a returning learner with a wall of due reviews is met with **amnesty and load renegotiation**, framed as normal, never as debt owed. **Directly supported.**

**Evidence that this layer must respect (the adversarial backbone).** These are why the mentor is a *stance at moments*, not a warm personality:
- **Over-helpful AI tutoring harms.** Bastani et al. (2025, *PNAS*), "Generative AI without guardrails can harm learning": high-schoolers with an unguarded GPT-4 tutor did *better* during practice and *worse* on exams once it was removed; a guardrailed version avoided the harm. The mentor layer must **never** become a crutch that dissolves the generation-first discipline. Warmth is not more help; it is the same withheld help, more kindly framed.
- **Most feedback is not automatically good.** Kluger & DeNisi (1996): across 607 effect sizes, feedback averaged d ≈ 0.41 but **over one-third of interventions *decreased* performance** — the ones that directed attention to the *self* rather than the *task*. This is the empirical spine of Engram's existing "feedback about the work, not the person."
- **Growth-mindset framing is small and context-specific — do not build on it.** Honest replication status: Sisk et al. (2018) intervention **d = 0.08 overall, 0.19 at-risk**; Yeager et al. (2019, *Nature*, NSLM) **d = 0.05 average, 0.10 for lower-achievers only**, concentrated in specific school climates. Real, but seasoning — exactly as `01-foundations.md` already ruled. The mentor never delivers mindset homilies.
- **Sycophancy is the failure mode to fear most.** An LLM's default is to agree, flatter, and inflate. Every move above is one keystroke from becoming that. The separation of powers (blind assessor) is what keeps warmth from leaking into the *grade*; the rules below keep it from leaking into the *dialogue*.

**Design consequence.** The mentor register is a small, bounded vocabulary in the dialogue grammar, fired only at specific telemetry moments:

| Moment (signal) | Mentor move | Never |
|---|---|---|
| Learner hits real difficulty inside the struggle budget | Name struggle as encoding (P3, voiced); hold the budget | Rush to comfort or resolve early (D'Mello) |
| Bad grade / lapse | Absolution + high standard + re-derivation path | Sympathy, "don't worry," inflated praise (Graham; Brummelman) |
| Returns after an absence to a large queue | Amnesty + load renegotiation, framed as normal | "You have 213 reviews overdue" (Silverman & Barasch; Lally) |
| Motivation visibly sagging | *Elicit* the goal-connection ("where does this touch what you're building?") | *Preach* relevance (Canning & Harackiewicz) |
| Genuine competence gain | One informational growth line (Pillar 13) | A score, a streak, or a should-statement |
| Everything else | Silence, or terse task-feedback | Ambient warmth for its own sake |

---

## The ADHD question: a profile, not a foundation

The founder has ADHD; most users do not. The honest and evidence-aligned resolution — and the one the founder asked for — is: **the theory stays universal; ADHD is an opt-in profile that turns *up* existing dials, adding no new pedagogy and, above all, no gamification.**

This is not a compromise; it is what the evidence says. Every mechanism that measurably helps ADHD adults persist is the *same* lever the two pillars above already pull, only with a steeper slope:

| ADHD mechanism | Evidence | It is the **same** universal lever, amplified |
|---|---|---|
| Steeper **delay discounting** | Jackson & MacKillop (2016) meta-analysis, **d = 0.43, k = 25, N = 3,913, p < 10⁻¹⁵** | Pillar 13 (competence *now*): make progress visible immediately, not "due in 12 days" |
| **Incentive/immediacy sensitivity** | Luman et al. (2005): reinforcement improves ADHD task performance *more* than controls; immediate reward can normalize on-task behavior | Pillar 13: surface the stability jump *at the moment*, not deferred |
| **Time blindness** | Zheng et al. (2022) meta-analysis, time-perception **Hedges g = 0.66**, 27 studies | Existing minute-sized sessions + explicit visible time boxes |
| Retrieval works, encoding lags | Minear et al. (2023): testing benefit equal for ADHD (ηp² = 0.13, no group interaction) but does **not** fix weaker encoding | Engram's generation-first backbone is *already* the right treatment; pair retrieval with encoding scaffolds |
| **Implementation intentions** | Gollwitzer & Sheeran (2006) **d = 0.65** (general pop; preliminary ADHD support) | Optional if-then session plan ("when I open the terminal, I clear one review") |
| Micro-goals / subgoals | Bandura & Schunk (1981) proximal subgoals — but **no ADHD-adult RCT exists** (honesty flag) | Tighter node/session granularity as a default override |

And — the point that keeps the profile honest — the things ADHD-marketed tools *add* mostly **do not work**:
- **Gamification is not rescued for ADHD.** Even FDA-cleared EndeavorRx (Kollins et al. 2020, N = 348) moved the *trained metric* (TOVA) but showed **no separation from control on actual ADHD symptom ratings**. Points and badges carry the same overjustification risk here as everywhere.
- **Body doubling, novelty-for-retention, working-memory training:** thin, pilot-level, or null on far transfer (Melby-Lervåg et al. 2016). Do not build on them.
- What *does* have the strongest ADHD-adult evidence is **structure and skills** (CBT for adult ADHD, Young et al. 2020, **SMD 0.76** vs waitlist) — i.e. *more* of Engram's structure, not more stimulation.

**So the "Focus" profile** (`settings.profile = "adhd"`, also recorded as a declared need in `accessibility` — a *need*, honored, never a "learning style" — see `01-foundations.md` rejections) changes only defaults the skills already read:
- default session mode → **Sprint** (one node; protects against the mid-task drift);
- competence-salience surfacing → **on and immediate** (Pillar 13, every review, not just the weekly coach);
- novelty-injection sensitivity → **raised** (react earlier to boredom signals — short answers, latency, mode-switching — by changing *activity type*, per the existing adaptation policy, not by adding a game);
- optional **if-then session plan** offered at intake;
- amnesty framing → **always on** (returning to a backlog is the ADHD failure mode most worth disarming).

No new command. The constitution's three-verb cap holds (`/learn`, `/review`, `/coach`); the profile is a setting the existing verbs honor, toggled in natural language or at intake. A dedicated *command* would be a fourth verb and a taxonomy to memorize — the opposite of what helps an ADHD user. A dedicated *default-set* is invisible and always-on. The second is correct.

---

## What this does not change (the invariants)

Stated so the implementation can be checked against them:

1. **The engine is untouched.** FSRS math, state machine, receipts, separation of powers — all identical. Momentum is *read* from receipts; nothing new is *scheduled*.
2. **No mastery without a receipt.** Growth lines report the assessor-verified stability the engine already produced; they never assert learning the assessor didn't grade.
3. **The deterministic core still owns every number.** `engram.py` computes momentum; the model narrates it. No LLM arithmetic (Article 10).
4. **Everything is default-safe and off-switchable.** `momentum` and `profile` are settings; a self-healed model without them behaves exactly as v0.3. A user can set `settings.momentum = "off"` and Engram is byte-for-byte its old self.
5. **Retention is still the north star.** These layers exist to keep the learner *returning* to the instrument that produces retention. If a future A/B shows a mentor move or a growth line does not improve consistency or retention, it loses its place — same rule as everything else (Article 7).

## The founding question, answered

**Q: Engram is correct and complete, and some evenings still boring. Is there a missing dopamine layer, and a missing wisdom layer — without breaking what works?**

**A: Yes to both, and they were already latent in the system.** The missing dopamine is *competence made visible* — the stability jump the engine computes and discards, plus the curiosity gap it already opens — not the manufactured dopamine of streaks and points, which the evidence shows backfires on exactly Engram's already-motivated adult user. The missing wisdom is the tutor *saying, at the moment of difficulty, what Engram already believes*: that struggle is the memory forming, that a lapse is normal and owed nothing, that the standard is high because you can meet it — delivered as a bounded stance at specific moments, never as ambient warmth, and never as sympathy, which reads as doubt. Both layers are surfacing and voicing what is already true. That is why they can be added without breaking a thing: **they invent nothing.**

Slogan version, to sit beside the engine's: *surface the competence you already earned, name the struggle for what it is, forgive the absence, and never once pretend.*
