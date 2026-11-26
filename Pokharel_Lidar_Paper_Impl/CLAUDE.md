# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A replication of the dynamical-decoupling (DD) experiment from Pokharel & Lidar, "Demonstration of Algorithmic Quantum Speedup" (arXiv:2207.07647, PDF included at `2207.07647v1.pdf`) — the "ssBV-n" (structured/scalable Bernstein-Vazirani) guessing game run on real IBM Quantum hardware, comparing bare ("free") circuits against DD-protected ones.

Two independent pieces live side by side:
- **This project's own work** (repo root): `bv_dd_lib.py` + `bv_dd_replication.ipynb` — the actual replication pipeline being built.
- **`bv6_fig1_walkthrough.ipynb`** — a deliberately *standalone* (does not import `bv_dd_lib`) teaching walkthrough of Fig. 1 (bottom). It covers: BV-6 across all 64 oracles; UR-14; a custom dt-timeline plot of the pulse insertion; paper-style barrier scheduling vs. compact ALAP; a protected-coverage table; correctness gates; and one batched hardware job. `USE_FAKE_BACKEND = True` runs it fully offline on `FakeFez`. It writes `figures/*.png` and `results/bv6_fig1_*.json`.
- **`bv6_ldd_comparison.ipynb`** — also standalone (Experiment 5). It runs BV-6 under the paper (barrier) schedule with
  free / XX / XpXm / XY4 / UR-14 / LDD, plus an untrained `ldd_x0` control. LDD is the *learned* DD sequence of Rahman,
  Egger & Arenz (arXiv:2405.08689, PDF `Learning_How_to_Dynamically_Decouple_2405.08689v1.pdf`): R(θ,φ,λ)–R–R†–R†, with 3
  shared virtual-Z angles learned by SPSA on hardware. Things to know:
  - `ORACLES` (§1) selects the oracles used everywhere. It is currently `[HEADLINE]` (b = 111111 only); `ALL_ORACLES` gives
    the 64-oracle sweep.
  - Hardware learning is resumable: one job per iteration, logged to
    `results/bv6_ldd_train_<backend>_<training set>.json` and replayed on rerun. Run 1's 7-oracle log is
    `results/bv6_ldd_train_ibm_fez.json`.
  - An offline toy coherent-noise testbed (§8) checks that the loop learns. The FakeFez Markovian model gives a flat LDD landscape.
  - `SUBMIT_LEARN` / `SUBMIT_FINAL` gate all QPU use.
- **`bv-quantum-speedup/`** — a separate, independently git-tracked clone of the original paper's authors' repo, kept as reference data/analysis code (not part of this project's own logic). Its own `README.md` explains its `data/` (external, Dropbox-hosted, gitignored), `results/`, `plots/`, and `analysis/` layout. Don't conflate its `.git` with the top-level project — there is no git repo at `E:\Study\BV-Paper-Impl` itself.

## Environment / running the notebook

- Python 3.14 venv at `.venv/`. Key packages: `qiskit` 2.5, `qiskit-aer`, `qiskit-ibm-runtime`, `numpy`, `pandas`, `matplotlib`. No `requirements.txt` exists — check `.venv` installed versions directly if you need to confirm compatibility.
- Run the notebook with the `.venv` kernel: `.venv/Scripts/jupyter-lab.exe` (or select the `.venv` kernel in an editor).
- IBM Quantum credentials are read from environment variables `MY_TOKEN` and `MY_INSTANCE` (see `.env` — **do not print or commit its contents**; it holds a live API token). The notebook's connect cell falls back to a previously saved `QiskitRuntimeService` account if these aren't set.
- There is no test suite, lint config, or build step. Validation happens by running notebook cells in order (see Pipeline below) — the "Correctness gate" and "Dress rehearsal" stages are the closest thing to tests, executed via ideal/noisy simulation before any hardware submission.

## Pipeline structure (`bv_dd_replication.ipynb`)

The notebook is a linear, numbered pipeline; each stage depends on state from the previous cells (labels, circuit dicts, backend object). In order:

1. Connect to IBM Quantum, pick a backend from `PREFERRED_BACKENDS` (`ibm_fez`, `ibm_marrakesh`).
2. Build ssBV-6 oracle circuits — one per Hamming weight (see `bv.all_representative_oracles`), not all 2^n oracles.
3. Construct the UR-14 DD sequence (Appendix F of the paper).
4. Transpile each oracle circuit into paired "free" (bare, ALAP-scheduled) and "dd" (DD-padded) ISA variants.
5. Correctness gate: noiseless `AerSimulator` run — success probability must be 1.0 regardless of DD (DD should be logically transparent).
6. Dress rehearsal: noisy local simulation seeded from a live calibration snapshot of the target backend, no QPU quota used.
7. QPU budget check (`bv.check_budget`) — estimates total QPU-seconds for the whole batch against `QPU_BUDGET_SECONDS`; hardware submission is gated on this passing.
8. Real-hardware run via a single batched `SamplerV2` job (`SUBMIT` flag controls whether this actually fires).
9. Results: free vs. DD success-probability comparison on real hardware.

Stage 2+ (multi-*n* sweep, time-to-solution scaling, bootstrapped confidence intervals, the worst-case speedup exponent λ) is explicitly deferred — see the notebook's final "Next steps" cell.

## `bv_dd_lib.py` — key conventions

- **Bitstring convention**: an oracle is labeled `b = "1"*k + "0"*(n-k)`, matching the paper's representative-oracle family. `b[i]` is data qubit `i`, 0-indexed left to right. Qiskit reports classical bits little-endian, so `expected_output_key()` reverses the label — always go through this helper rather than comparing raw labels to measured bitstrings.
- **UR-n DD sequence** (`ur_n_phases`, `ur_n_sequence`): implements the universally-robust sequence from Appendix F. Each `R(pi, phi_k)` pulse is decomposed as `RZ(phi_k)-X-RZ(-phi_k)` because IBM targets don't expose a general `RGate` in their basis; `RZ` is virtual/zero-duration on IBM hardware so this costs the same as a bare X per pulse. The phase-closure math (why `phi2 = pi/2` works for `n = 4m` but not `n = 4m+2`, i.e. UR14/UR18) is worked out in the docstring — read it before changing the phase formula.
- **Counts are positionally aligned, not name-keyed**: `run_ideal`, `run_noisy_local`, and `counts_from_sampler_result` all return lists aligned by position with the input `circuits` list. This is deliberate — the "free" and "dd" variants of the same oracle share a `circuit.name`, so a name-keyed dict would silently collide.
- **Duration/budget functions require scheduled circuits**: `estimate_qpu_seconds` raises if `circuit.duration is None`; circuits must go through `schedule_only` or `add_dynamical_decoupling` first (both ALAP-schedule via `PassManager`).
- `plot_output_distributions` renders one row per representative oracle (Hamming weight), not the full 2^n-oracle grid the paper's Fig. 2 uses — reproducing that would need the qubit-permutation-symmetry expansion from Appendix B, which is out of scope here.
