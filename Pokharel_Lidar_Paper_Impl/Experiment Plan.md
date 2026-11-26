# Experiment Plan

Running log of experiments performed and planned for the ssBV-*n* DD
replication (see `CLAUDE.md` for project scope), plus the design decisions
behind `bv_dd_lib.py` and the per-experiment notebooks. This is the
canonical record `bv_dd_replication.ipynb`'s markdown cells refer to as
"the design-decisions log" -- update it as experiments run rather than
letting findings live only in notebook cell outputs.

Each experiment gets its own notebook (`bv_dd_replication.ipynb`,
`bv_dd_experiment2_n_sweep.ipynb`, ...); `bv_dd_lib.py` is the one shared
library all of them import.

## Design decisions

- **Standard Sabre routing, not the paper's Appendix D custom ancilla-swap
  router.** `to_isa_circuit` uses Qiskit's default preset pass manager.
  Deferred -- revisit once N-scaling (Experiment 2) is validated and we can
  see how much routing overhead actually costs at higher N.
- **UR-*n* phase formula for `n = 4m+2` (UR14, UR18) uses `phi_2 = Phi^(n)`,
  not the paper's stated `phi_2 = pi/2`.** The sequence's net rotation is a
  phase gate `exp(i*chi*Z)` with `chi = n*phi_2/2` (Genov et al. 2017,
  arXiv:1609.09416); pure DD needs `chi = 0 mod pi`, which only holds at
  `phi_2 = pi/2` when `n` is a multiple of 4. UR14/UR18 are `n = 4m+2`, so
  `phi_2 = Phi^(n)` is used instead (verified against Genov's own UR6
  worked example). See `bv_dd_lib.ur_n_phases` docstring for the full
  derivation.
- **Representative-oracle trick**: test the `n+1` bitstrings
  `b = 1^k 0^(n-k)` (one per Hamming weight) rather than all `2^n` oracles,
  since same-weight oracles are identical up to qubit relabeling.
- **Counts are positionally aligned, not name-keyed**, across
  `run_ideal`/`run_noisy_local`/`counts_from_sampler_result`. `free` and DD
  variants of the same oracle share a name (both derive from the same
  source circuit), so name-keyed lookup would silently collide when both
  are batched into one call.
- **IBM Runtime's built-in DD presets (`XX`/`XpXm`/`XY4`,
  `SamplerV2.options.dynamical_decoupling`) are a per-job Runtime setting,
  not a per-circuit transpiler pass.** Unlike UR-14 (inserted via our own
  `PadDynamicalDecoupling` + custom `dd_sequence`), each built-in preset
  needs its own hardware job -- it can't be mixed with other presets or
  "free" in one batched job. For local simulation we reconstruct the
  equivalent native gate lists (`ibm_builtin_dd_sequence`) so the
  correctness gate/dress rehearsal/budget estimate can still treat them
  like any other DD variant. XX and XpXm are unitarily identical up to a
  global phase, so local simulation cannot distinguish them -- any real
  difference is a hardware-only pulse-phase effect.
- **`PadDynamicalDecoupling` silently falls back to a bare, unprotected
  `Delay` when an idle window is shorter than one full application of the
  sequence** -- no warning. `dd_utilization_report`/`dd_utilization_summary`
  (added after Experiment 1) recompute that pass/fail check from calibrated
  gate durations and cross-check it against actual remaining `Delay` time,
  specifically to catch this silently. `skip_reset_qubits=True` (Qiskit's
  default, and `add_dynamical_decoupling`'s default) additionally declines
  to pad each qubit's very first idle window regardless of length --
  Experiment 2 checks directly whether disabling this recovers meaningful
  coverage before committing the N-sweep to a setting.

- **Aer noise models match a gate by its *label* when it has one.** A labelled
  `XGate(label="P1")` gets no noise from a model keyed on `"x"`, so it runs
  noiseless in `AerSimulator.from_backend` (verified: 400 labelled X on Q111
  of FakeFez gave 17/4000 errors vs. 239/4000 unlabelled). Hardware ignores
  labels. `bv6_ldd_comparison.ipynb` strips labels before every simulation
  (`unlabelled`). `bv_dd_lib.py`'s sequences are unlabelled, so Experiment 1 and 2
  are unaffected. `bv6_fig1_walkthrough.ipynb` labels its UR-14 pulses `P1`…`P14`,
  so its **noisy-simulation** numbers treat those pulses as perfect. Its
  hardware numbers are unaffected.

## Experiment log

### Experiment 1 -- DONE

- **Notebook**: `bv_dd_replication.ipynb`
- **Question**: Does UR-14 (and, as an add-on, IBM's built-in XX/XpXm/XY4
  presets) improve BV-6 success probability over a bare ("free") circuit?
- **Config**: N=6, 5 variants (`free`, `dd`=UR-14, `xx`, `xpxm`, `xy4`),
  `ibm_fez` (156 qubits), 2000 shots.
- **Hardware job IDs**: `dapdo9gr7bnc73b38qeg` (free+dd, batched),
  `dapdo9ic505c73ci1a70` (XX), `dapdo9sak42c73cidgk0` (XpXm),
  `dapdoa2c505c73ci1a80` (XY4).
- **Result**: all 5 variants statistically indistinguishable on real
  hardware -- avg success probability free 0.849, dd 0.848, XX 0.839,
  XpXm 0.853, XY4 0.847. Success probability decreases monotonically with
  Hamming weight (0.92 at weight 0 down to ~0.68-0.73 at weight 6),
  matching the paper's qualitative expectation, but no DD variant clearly
  beats "free" at any weight.
- **Key finding**: the idle-time-utilization diagnostic
  (`dd_utilization_summary`, added after this run) explains why -- idle
  windows at N=6 are mostly too short for these sequences to do anything.
  UR-14 covers only 16.5% of total idle time and is silently skipped
  outright on 5 of 7 active qubits; the built-in presets cover 4.7-8.3%.
  Three qubits also show "predicted covered, actually skipped" mismatches
  consistent with `skip_reset_qubits` suppressing the first idle window.
  **The N=6 comparison was underpowered by construction, not just by shot
  count.**
- **Follow-up**: Experiment 2 (N-sweep) -- test whether longer circuits
  (longer idle windows) let DD actually apply and show a real effect.

### Experiment 1b -- Fig. 1 (bottom) walkthrough -- BUILT, NOT YET ON HARDWARE

- **Notebook**: `bv6_fig1_walkthrough.ipynb`. Standalone: it does not import
  `bv_dd_lib.py`, so it can be read top to bottom as a teaching walkthrough.
- **Question**: Does UR-14 help BV-6 when it is scheduled the way the paper's
  Fig. 1 (bottom) draws it: every H at t=0, every final H at the end, and data
  qubits waiting *in superposition* before and after their CNOT?
- **Config**: all 64 oracles x 4 variants (`paper_free`, `paper_ur14`,
  `alap_free`, `alap_ur14`) = 256 circuits in one `SamplerV2` job, with
  Runtime's DD explicitly disabled. The default is 1000 shots, estimated at
  ~70 s QPU (budget 240 s). All circuits use one fixed 7-qubit layout, taken
  from transpiling `b=111111` (seed 7); on FakeFez this is physical qubits
  107, 97, 109, 110, 111, 118 and 108.
- **Design decisions**:
  - The "paper" schedule is implemented as **barriers around the oracle plus
    ALAP**, not ASAP. ASAP would move each final H and measurement to right
    after that qubit's CNOT, which is not what Fig. 1 shows.
  - Coverage is measured as the **% of superposition idle time with a UR-14
    repetition inserted**, classifying each idle window as |0>, superposition
    or unmeasured tail. Experiment 1's utilization % is a pulse duty cycle over
    all idle time, including |0> windows DD doesn't need to protect.
  - Gaps shorter than one UR-14 (84 dt on Fez) are left bare, as in the paper,
    and reported in the coverage table.
- **Offline results (FakeFez)**:
  - Superposition idle time covered by UR-14: paper 85.9% (b=111111) / 78.3%
    (mean over 64 oracles); alap 74.8% / 48.1%. The paper schedule has ~3x
    more superposition idle time to protect.
  - Toy static-detuning demo at 400 kHz, mean p_s: paper_free 0.29,
    paper_ur14 0.84, alap_free 0.87, alap_ur14 0.99.
  - Aer noisy sim: paper_free 0.901, paper_ur14 0.917, alap_free 0.925,
    alap_ur14 0.931.
- **Findings**: _(fill in after the hardware run: job ID, and whether
  paper_ur14 > paper_free on ibm_fez)_.

### Experiment 2 -- IN PROGRESS

- **Notebook**: `bv_dd_experiment2_n_sweep.ipynb`
- **Question**: Does DD idle-window utilization, and DD's benefit over
  "free", improve as N grows? (`build_bv_circuit`'s marked qubits all CNOT
  sequentially onto one shared ancilla, so larger N directly lengthens the
  idle windows other data qubits sit in while waiting their turn.)
- **Config**: N in {6, 10, 14, 18} (6 kept as a continuity check against
  Experiment 1), same 5 variants, cumulative-budget-gated before hardware
  submission. Also A/B-tests `skip_reset_qubits` at N=6 before picking a
  setting for the sweep.
- **Status**: notebook built and locally validated (`SUBMIT = False`);
  hardware run not yet submitted.
- **Findings**: _(fill in once the hardware run completes: the
  `skip_reset_qubits` decision, job IDs per N, and whether the
  success-probability/utilization-vs-N trends match the hypothesis)_.

### Experiment 3 -- PLANNED (not yet designed)

- **Question**: Do Pauli twirling and/or readout error mitigation
  (`SamplerV2` options: `twirling`, `resilience_level`) improve success
  probability on top of whichever N/variant combination Experiment 2 finds
  most informative?
- **Notebook**: not yet created.

### Experiment 4 -- PLANNED (not yet designed)

- **Question**: Does a custom `initial_layout` -- physical qubits chosen
  from `backend.properties()` error rates instead of Sabre's default
  choice -- reduce routing overhead or error, as a partial stand-in for the
  paper's Appendix D ancilla-swap router?
- **Notebook**: not yet created.

### Experiment 5 -- Learned DD (LDD) comparison -- BUILT, NOT YET ON HARDWARE

- **Notebook**: `bv6_ldd_comparison.ipynb` (standalone, like the walkthrough).
- **Question**: On BV-6 under the paper (barrier) schedule, how do free, XX,
  XpXm, XY4, UR-14 and a *learned* DD sequence compare? The learned sequence
  follows Rahman, Egger & Arenz, arXiv:2405.08689.
- **Method (LDD)**:
  - **Sequence**: R(θ,φ,λ)–R–R†–R† per idle gap, with R = U(θ,φ,λ) =
    rz(λ) sx rz(θ+π) sx rz(φ+π). That is 8 √X pulses; only the virtual-Z
    angles depend on x.
  - **Parameters**: 3, shared by every qubit and every gap.
  - **Cost**: J(x) = 1 − mean p_s over the 7 oracles of weight ≥ 5
    (250 shots each per point). BV's output is a basis state, so no
    tomography is needed.
  - **Optimizer**: SPSA as in the paper. x0 = (0,0,0), c = 0.2, α = 0.602,
    γ = 0.101, and the learning rate is calibrated to a first step of 2π/10
    from 10 ± pairs.
  - **Control**: an `ldd_x0` variant (the same pulses at x0) separates
    "learning helped" from "extra pulses helped".
- **Config**:
  - One fixed layout for everything: the walkthrough's hardware layout
    [111, 98, 109, 108, 107, 118, 110].
  - All DD is inserted by our own `PadDynamicalDecoupling`, so all 7 variants
    × 64 oracles go in **one** final job.
  - Budget 240 s: learning ≤ 110 s, final ≤ 130 s (1000 shots ≈ 118 s).
  - Hardware learning runs one job per SPSA iteration on the Open Plan.
    Every job is logged to `results/bv6_ldd_train_<backend>.json`, and a rerun
    replays or resumes from that log. A ledger based on `job.usage()` stops the
    loop at the budget.
  - `SPSA_MAXITER = 100`, the paper's count. Run 1 derived the count from
    the cost model instead, which allowed 31. The budget check now projects
    from the usage actually billed in the training log, and the ledger still
    stops the loop at `LEARN_BUDGET_SECONDS`.
  - Rerunning §11 for an x\* that already has a final job re-attaches to it
    instead of paying for the job again.
- **Design decisions**:
  - Pulse axes use the time order rz(−φ) x rz(φ), so the axis really is +φ.
    The walkthrough's order gives −φ, the mirror image, which is harmless
    for UR-14.
  - Spacing is τ/2–τ–…–τ/2 *between* pulse units and zero inside them, so
    each R stays two back-to-back √X pulses.
  - Gaps must be strictly longer than one sequence (the pass needs
    slack > 0).
  - The learnable angles are written in after padding: the circuit is padded
    with placeholder angles, then the labelled rz gates are swapped in place
    for `ParameterExpression`s. This keeps the schedule, and gives one
    parameterized circuit per oracle (K points per PUB).
  - An offline testbed adds toy coherent noise (quasi-static detuning,
    σ = 150 kHz, plus 3% X/√X over-rotation). The FakeFez Markovian model
    gives a *flat* LDD landscape, so it can't test the learning loop.
- **Offline results (FakeFez)**:
  - % of superposition idle time protected (mean over oracles): XX/XpXm 98.6,
    XY4 98.3, LDD 86.8, UR-14 78.3.
  - Toy model, the loop learns: J falls from 0.57 at x0 to 0.04 in about
    5 iterations. The learned R is a 167° rotation about an xy-plane axis
    (+0.66, −0.75, 0), i.e. it found an echo.
  - Toy model, all 64 oracles: free 0.609, XX 0.980, XpXm 0.984, XY4 0.983,
    UR-14 0.965, LDD 0.970, LDD@x0 0.678. LDD can't beat XX here: its family
    contains R = X, and its 48 dt minimum leaves more gaps bare.
  - Noisy (Markovian) rehearsal: every variant within ±0.003 of free (0.887),
    as expected when there is no coherent error to echo.
  - The mocked-hardware tests of the resume, budget-stop and final-job paths
    pass.
- **Hardware run 1 (ibm_fez, 2026-10-02 UTC; 31 SPSA iterations)**:
  - **Training log**: `results/bv6_ldd_train_ibm_fez.json`, calibration job
    `davhuklj371s73dmu35g`.
  - **Billed learning usage**: 29 s in total. That is 14 s for calibration,
    and 0 or 3 s per iteration (0.48 s on average), against 3.1 s
    estimated per iteration.
  - **Calibration-job baselines** (J on the training oracles): free 0.217,
    XX 0.183, XpXm 0.186, XY4 0.165, UR-14 0.199. LDD around x0 was 0.213.
  - **Learning curve**: J stayed near 0.21 for about 20 iterations, then
    drifted to about 0.18–0.19 by iteration 30. **It had not converged.**
  - **Learned x\***: (θ, φ, λ)/π = (−0.84, −0.28, −0.41), wrapped. R is a 167°
    rotation about (+0.20, −0.95, −0.23), close to a π pulse about −Y.
  - **Final job `davi3g84oijs73e7j66g`** (64 oracles × 7 variants × 1000 shots),
    mean p_s: free 0.831, XX 0.866, XpXm 0.865, XY4 0.859, UR-14 0.856,
    **LDD 0.840**, LDD@x0 0.829.
  - **Conclusion**: after 31 iterations LDD barely beats its untrained control
    and stays below every fixed sequence.
- **Run 1b: an accidental repeat.** Final job `davibkk92g1c7398uqog`
  (2026-10-02 03:32 UTC) used the same x\* as run 1. The editor ran a stale
  in-memory copy of the notebook that still had the 40-iteration cap, which
  allowed 31, and no protection against resubmitting. Its mean p_s matches
  run 1 to within 0.004 for every variant (free 0.832, XX 0.869, XpXm 0.867,
  XY4 0.863, UR-14 0.853, LDD 0.840, LDD@x0 0.830), so the run-1 numbers are
  reproducible on this layout.
  - At b = 111111, runs 1 / 1b gave: free 0.765 / 0.788, XX 0.805 / 0.803,
    XpXm 0.809 / 0.817, XY4 0.821 / 0.836, UR-14 0.795 / 0.799,
    LDD 0.795 / 0.803, LDD@x0 0.772 / 0.775.
- **Run 2 (planned): b = 111111 only.**
  - **Oracles**: `ORACLES = [HEADLINE]` for both training and the final job,
    to save QPU time. `ALL_ORACLES` restores the 64-oracle sweep.
  - **Training**: 1750 shots per parameter point, all on 111111. That keeps
    σ_J ≈ 0.01 and the same billed cost per job as run 1.
  - **SPSA**: `SPSA_MAXITER = 100`, starting fresh from x0. The cost function
    changed, so run 1's 7-oracle log can't be continued. The new log is
    `results/bv6_ldd_train_ibm_fez_b111111.json`.
  - **Learning cost**: about 62 s projected, from run 1's billed usage per job.
  - **Final job**: 7 circuits × 10 000 shots, 70k shots, about 23 s estimated,
    against 448k shots and about 118 s before.
- **Run 2 results (ibm_fez, 2026-10-02 UTC; b = 111111; 100 SPSA iterations)**:
  - **Training log**: `results/bv6_ldd_train_ibm_fez_b111111.json`,
    calibration job `davjgfo4oijs73e7m3hg`.
  - **Billed learning usage**: 56 s for 101 jobs. Calibration was billed 14 s;
    iterations averaged 0.42 s.
  - **Wall clock**: the calibration job queued about 65 min, then the 100
    iterations ran in 38 min.
  - **Learning curve**: training p_s went from 0.70 at x0 to 0.79 (mean of the
    last 20 iterations), non-monotonically. The device also drifted: free was
    0.707 in the calibration job and 0.764 in the final job.
  - **Learned x\***: (θ, φ, λ)/π = (−0.90, +0.76, −0.45), wrapped. R is a
    164° rotation about (0.94, 0.32, 0.07): a near-π pulse about an xy-plane
    axis 19° from X. SPSA rediscovered an X-type echo from x0.
  - **Final job `davl135j371s73dn40v0`** (7 × 10 000 shots), p_s:
    free 0.764, XX 0.799, XpXm 0.804, **XY4 0.810**, UR-14 0.794,
    **LDD 0.800**, LDD@x0 0.760.
  - **Gain over free** (95% CI ±1.1 pp): XY4 +4.6, XpXm +4.0, LDD +3.6,
    XX +3.4, UR-14 +2.9, LDD@x0 −0.4.
  - **Conclusion**: learning works. LDD beats its untrained control by
    +4.0 ± 1.1 pp in the same job, and it ties XX. It does not beat the fixed
    sequences: XY4 − LDD = 1.0 ± 1.1 pp, which is not significant. XY4 has the
    highest p_s at b = 111111 in all three final jobs (runs 1, 1b and 2).
  - **Slide figures**: `figures/bv6_ldd_slide_gain.png` and
    `figures/bv6_ldd_slide_learning.png`.
