# Entanglement Swapping Experiment

Study project: run a simple entanglement-swapping experiment on real IBM Quantum hardware with Qiskit 2.5,
and keep a log of every run here.

## Files
- `entanglement_swapping.ipynb`: the whole experiment (theory, circuits, local sim, hardware run, analysis).
- `entanglement_swapping_chain.ipynb`: swap chains of several lengths (n swaps = n+1 Bell pairs = 2n+2 qubits)
  in one job; plots fidelity vs. chain length and fits the decay. Self-contained (its own helpers).
- `entanglement_swapping_nested.ipynb`: nested/doubling swapping (BDCZ 1998 pattern, **without purification**)
  vs parallel, with and without DD, in one job. Self-contained.
- `linear_repeater_throughput.ipynb` (**current focus, since 2026-10-20**): linear repeater chain, n = 1, 2, 4, 8, 16
  links, nested swapping with mid-circuit measurements, Pauli-frame correction; measures F and throughput vs n.
  Optional Part 3 = real-time feed-forward (`if_test`) as a separate job. Self-contained.
- `.env`: IBM credentials (`QISKIT_IBM_TOKEN`, optional `QISKIT_IBM_INSTANCE`, `IBM_BACKEND`). Never commit or print it.
- `.env.example`: template for `.env`.
- `results/`: one `*_job.txt` (job ID, written at submit), `*_results.json` (raw joint counts + summary)
  and `*_fidelity.png` per hardware run. Filenames start with a UTC timestamp and the backend name.
  Chain runs use `*_chain_job.txt`, `*_chain_results.json`, `*_chain_fidelity.png`.
- `requirements.txt`; the virtual env lives in `.venv/` (Python 3.14).

## Setup
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
Select the `.venv` interpreter as the notebook kernel.

## Stack / API notes
- Qiskit 2.5, qiskit-ibm-runtime >= 0.50. Use `QiskitRuntimeService(channel="ibm_quantum_platform", ...)`
  (the old `ibm_quantum` channel no longer exists).
- Primitives V2 only: `SamplerV2(mode=backend)` for hardware, `StatevectorSampler` for the local ideal check.
- Circuits must be transpiled to ISA form with `generate_preset_pass_manager(backend=..., optimization_level=3)` before submitting.
- `qiskit_ibm_runtime.SamplerV2` is deprecated as of 0.50.0 (still works, removal ≥ 3 months later). The
  replacement is `qiskit_ibm_runtime.executor_sampler.Sampler`; check the release notes before upgrading the runtime.
- Qiskit Aer is not installed; the local sim cannot run the dynamic-circuit (Part 3) version.

## Protocol (what the circuits do)
1. Bell pairs on (q0,q1) and (q2,q3).
2. Bell-state measurement on (q1,q2): `cx(1,2); h(1)`, then measure → `bsm[0]=m1` (q1), `bsm[1]=m2` (q2).
3. Measure (q0,q3) in XX / YY / ZZ → `out[0]=q0`, `out[1]=q3`.
4. Outcome m1m2 → state of (q0,q3): 00 Φ+, 01 Ψ+, 10 Φ-, 11 Ψ-. Correction on q3 = Z^m1 X^m2.
5. Fidelity with Φ+: `F = (1 + <XX> - <YY> + <ZZ>) / 4`. **F > 0.5 ⇒ entangled.**
- Software correction signs: XX × (-1)^m1, YY × (-1)^(m1+m2), ZZ × (-1)^m2.
- Control circuit = same but no `cx(1,2); h(1)`. Expect per-outcome F of 0.5 or 0 (classical ZZ only),
  corrected F ≈ 0.25. If control ever exceeds 0.5, something is wrong.
- All circuits of a run use the same physical qubits: the layout chosen for `swap_XX` is passed as
  `initial_layout` to every other circuit (saved as `physical_qubits` in the results JSON).
- No barrier after the BSM in the static circuits: `StatevectorSampler` rejects any op after a measurement.
- Windows: always pass `encoding="utf-8"` to `write_text`/`open` (labels contain Φ/Ψ; default cp1252 fails).
  Run scripts with `PYTHONIOENCODING=utf-8` for the same reason.

## Swap chain (entanglement_swapping_chain.ipynb)
- Pairs (q0,q1)(q2,q3)...; Bell measurements on (q1,q2)(q3,q4)... all in parallel; ends = q0 and q_last.
  2q-depth stays 2 for any length; only the number of qubits/gates grows.
- `bsm[2k]` = m1 of swap k (qubit 2k+1), `bsm[2k+1]` = m2 (qubit 2k+2). Correction uses parities
  M1 = XOR of all m1, M2 = XOR of all m2, then the same table/signs as the single swap. Verified by ideal sim.
- Default `N_SWAPS = [1, 2, 3, 4, 6, 8, 10]` with controls = 42 circuits × 4000 shots in one job.
- Ideal sim only up to `SIM_MAX_QUBITS = 14`: `StatevectorSampler` needs ~6 GB at 22 qubits (it builds
  string labels for all 2^n outcomes).
- Layout: transpile the longest chain once, then every shorter chain uses a prefix of that physical line.
  The notebook checks 2q-gate count == 2n+1 (no routing SWAPs). On FakeMarrakesh a 22-qubit line is found.
- Decay model: v = (4F-1)/3, fit v(n) = a·r^n; entanglement lost when v < 1/3 (F < 0.5).
- Part 3 = DD test: chain circuits only (no controls), `DD_N_SWAPS = [1, 4, 10]` × `DD_WAITS_NS = [0, 4000]`
  (optional `delay` on all qubits after the Bell pairs = "memory" wait), run as two back-to-back jobs, DD off/on.
  DD is added locally (`ALAPScheduleAnalysis` + `PadDynamicalDecoupling`, X–X per idle gap), not via the
  runtime option, so pulse counts are known: wait 0 → 4 pulses at every length (end qubits only);
  wait 4 µs → 2 per qubit (12 / 24 / 48). Verified: ISA-valid on FakeMarrakesh, ideal F stays 1.000 with DD
  (FakeManilaV2 sim), delays meet timing constraints (Heron: dt = 4 ns, granularity 1).
  Needs sections 0–2b (for `backend`, `LINE`); 2c–2e need not be rerun. Results: `*_dd_jobs.json`,
  `*_dd_results.json`, `*_dd_fidelity.png`.
- `build_chain_circuit(..., wait_ns=0)`: the wait is off by default, so Parts 1–2 are unchanged.

## Nested swapping (entanglement_swapping_nested.ipynb)
- `N_LINKS = [2, 4, 8]` (powers of 2; qubits = 2·links; swaps = links−1). Boundary b joins link b−1 and b via a
  BSM on qubits (2b−1, 2b) → still nearest-neighbour on a line. `swap_rounds()`: level ℓ swaps boundaries with
  b mod 2^ℓ == 2^(ℓ−1) → 8 links: [1,3,5,7], [2,6], [4]. Same bsm register layout/parity correction as chain.
- Hardware circuits (`mid_circuit=True`) measure each round's BSM qubits before the next round (barrier after),
  so stored qubits idle through ~2.6 µs mid-circuit measurements. Ideal sim uses `mid_circuit=False`
  (all measurements at the end; StatevectorSampler cannot do mid-circuit measurement).
- One job, 4 kinds × 3 sizes × 3 bases = 36 circuits: `parallel`, `nested`, `nested + XX` (1 X–X pair per idle
  gap), `nested + XX×4` (4 pairs). DD added locally; X pulses after a qubit's last measurement are removed.
- On FakeMarrakesh: q0 storage 0.19 µs (parallel) vs 2.91 / 5.65 µs (nested, 4 / 8 links). DD pulses
  XX: 4 / 12 / 28, XX×4: 0 / 32 / 96 (8-pulse sequence does not fit the 1-swap short gaps).
  Verified: ISA-valid; compacted ISA+DD circuits (measurements deferred) give ideal F = 1.000 for all kinds.
- Since 2026-10-16 run: `N_LINKS = [2, 4, 8, 16]` (48 circuits, 192k shots). Section 2b: `readout_scan()` measures
  every qubit's readout error live (one job: all-0 / all-1, 1000 shots, whole chip); qubits above
  `READOUT_LIMIT = 0.08` or in `EXCLUDE_QUBITS = [137]` are never used. `choose_line()` then picks the
  lowest-cost line (branch and bound over all simple paths; cost = Σ −ln(1−live readout) + Σ −ln(1−CZ err)
  + Σ STORE_US/T2). If no clean line fits the longest chain, that chain is dropped (16 → 8 → ...) and
  circuits are rebuilt. (Replaced a 3-attempt per-line check that failed on 2026-10-16: it found 39 at 38%,
  63 at 21%, 83/36/77/85/116 at 11–15% while calibration said ~1–2%.) Section 2g flags qubits whose P(1) is
  > 0.10 from 0.5 after the run. DD pulse counts = X gates added by DD only (transpiled circuits can contain
  their own X). 32-qubit logic verified with StabilizerState sampling (F = 1.000, all kinds); ideal statevector
  sim limited to `SIM_MAX_QUBITS = 16`.
  FakeMarrakesh storage of q0 at 16 links (nested): 8.36 µs; DD pulses XX 60, XX×4 224.
- Lesson: calibration data can be stale; the transpiler's layout trusts it. Per-qubit P(1) marginals from the
  raw job result (re-downloadable with `service.job(id).result()`, free) are the fastest way to spot a bad qubit.
- Purification left out: needs two copies of each link side by side; heavy-hex has no ladder connectivity, so
  routing SWAPs would add more error than purification removes.

## Linear repeater throughput (linear_repeater_throughput.ipynb)
- Links (q_{2k}, q_{2k+1}); node j holds (q_{2j−1}, q_{2j}); level ℓ swaps nodes with j mod 2^ℓ == 2^(ℓ−1); barrier
  between levels; BSM qubits measured mid-circuit at the end of their level. `sequential=True` puts barriers between
  link preparations. With the Pauli frame the ends are measured **in the final level's round** (they need not wait);
  with `feedforward=True` they are measured after `if_test(XOR expr)` corrections X^x then Z^z on the last qubit.
- Frame: x = XOR of `bsm[1::2]` (second qubits), z = XOR of `bsm[0::2]` (first qubits). Counts keyed `"xz ab"`
  (note: x first; the older notebooks key `"M1M2 ab"` = z first). n = 1 has no `bsm` register.
- Ideal check: own shot-by-shot `StabilizerState` sampler (`stabilizer_sample`) that supports mid-circuit measurement
  and `if_test` with expressions, works on ISA circuits too (32 qubits OK, ~1 min for 30 circuits × 200 shots).
  **Pitfall:** a StabilizerState's RNG is copied with the state, so without reseeding before every `measure` every
  shot repeats the same outcomes (F still 1, but uncorrected F came out 1.0 instead of 0.25). The notebook reseeds
  and its table shows F uncorrected ≈ 0.25 for n ≥ 2 as proof that the frame does the work. `ideal_check` raises if F < 0.99.
- 2c checks each ISA circuit: exactly 2n−1 two-qubit gates (barriers excluded), all between line neighbours, no SWAP;
  then simulates all ISA circuits ideally. Cycle time T = `estimate_duration` (if_else bodies inlined, ff latency
  not included). FakeMarrakesh: T = 2.76 / 2.86 / 5.59 / 8.31 / 11.05 µs (parallel), sequential up to 13.15 µs at 16.
- Throughput: R_proto = 1/T, R_dev = 1/(T + overhead), overhead = Σ execution-span durations / shots − mean T
  (fallback: `default_rep_delay`, 250 µs). Yield Y = max(0, 1 − H(p)) with p = Bell-diagonal probabilities from the
  corrected correlators (hashing lower bound on distillable entanglement); ebit rate = R × Y; "entangled" = F − 2 SE > 0.5.
- One job = 2 modes × 5 n × 3 bases = 30 circuits × 4000 shots. Results: `*_repeater_job.txt`, `*_repeater_results.json`,
  `*_repeater_fidelity.png`, `*_repeater_throughput.png`; Part 3: `*_repeater_ff_*`.
- First hardware run 2026-10-20 (jobs dbbuaq424mrc73cies10 + ff dbbubj1gv2cc73e95qlg), findings:
  - Entangled up to n = 4 (F 0.555 ± 0.006); distillable (hashing) only up to n = 2. Device rate ~flat 3.58k → 3.47k
    pairs/s (276 µs overhead per shot dominates); protocol rate 350k → 87k pairs/s.
  - **The mid-circuit-measurement wait is the main error**, not readout: ff n=2 is the same circuit as frame n=2 plus one
    wait of the 2 end qubits → F 0.883 → 0.655. Frame n=2 → 4 (one wait, all 8 qubits ≤ 2.4% readout) → 0.555.
    Mostly phase-type (XX/YY drop far more than ZZ; Bell prob. Φ− 0.27 at n=4).
  - Part of it is a coherent common phase: frames that hold a Φ state during the wait lose much more than Ψ frames
    (ff n=2 XX: Φ +0.36 vs Ψ +0.52), same signature as the 2026-10-16 DD test → DD or a compensating virtual rz should recover some.
  - Sequential generation better at n=2 (+0.022, XX/YY only): likely crosstalk between simultaneous CZs on neighbouring pairs.
  - Qubit 58 (end B of n=8) read 1 in only 39% of ZZ shots (≈ 0.48 in XX/YY): relaxation during the wait (short T1 / TLS?).
  - Feed-forward shots took ~10 µs longer than the timing model accounts for (rough estimate of if_test latency).

### Conventions (easy to get wrong)
- Qiskit bitstrings are little-endian. `joint_counts()` reverses them, so result keys are
  `"m1m2 ab"` with a = q0, b = q3, read left to right.
- Keep the register names `bsm` / `out` and the basis order `XX, YY, ZZ` stable; saved JSON files depend on them.
- Each hardware job = 6 circuits: 3 swap (XX, YY, ZZ) then 3 control.

## Experiment log
One row per hardware run (the last cell of Part 2 in the notebook prints a ready-made row).
F = corrected fidelity of (q0,q3) with Φ+, ± 1 standard error.

| UTC timestamp | Backend | Job ID | Mode | Shots/circuit | F swap | F control | Notes |
|---|---|---|---|---|---|---|---|
| 2026-10-15 | StatevectorSampler (seed 1234) | n/a | ideal sim | 4000 | 1.000 ± 0.000 | 0.245 ± 0.007 | baseline; uncorrected swap F = 0.259 |
| 20261016T044018Z | ibm_marrakesh | db8qlcgb3g5c73egqkp0 | post-processed | 4000 | 0.921 ± 0.003 | 0.247 ± 0.007 | qubits [149,148,147,146]; per-outcome F 0.915–0.925; <XX>,<YY>,<ZZ> = +0.909, −0.866, +0.909; uncorrected 0.265. JSON save failed (cp1252 bug, since fixed); results.json is empty, so re-save via 2d |
| 20261016T044714Z | ibm_marrakesh | db8qokdckpjs73b1hp90 | post-processed | 4000 | 0.928 | 0.260 | repeat run, same qubits [149,148,147,146]; per-outcome F 0.922–0.932; <XX>,<YY>,<ZZ> = +0.908, −0.881, +0.925; uncorrected 0.252 |
| 20261016T052334Z | ibm_marrakesh | db8r9lheukqs73ar6110 | chain, 1 swap (4 q) | 4000 | 0.927 ± 0.003 | 0.263 | line starts [92,91,98,111] |
| 20261016T052334Z | ibm_marrakesh | db8r9lheukqs73ar6110 | chain, 2 swaps (6 q) | 4000 | 0.785 ± 0.005 | 0.247 | big drop: adds 110 (2.4% readout) + 109 (3.1%) as end |
| 20261016T052334Z | ibm_marrakesh | db8r9lheukqs73ar6110 | chain, 3 swaps (8 q) | 4000 | 0.779 ± 0.005 | 0.240 | ZZ recovers (0.73→0.80) as 109 becomes an m1 bit |
| 20261016T052334Z | ibm_marrakesh | db8r9lheukqs73ar6110 | chain, 4 swaps (10 q) | 4000 | 0.721 ± 0.005 | 0.256 | |
| 20261016T052334Z | ibm_marrakesh | db8r9lheukqs73ar6110 | chain, 6 swaps (14 q) | 4000 | 0.650 ± 0.006 | 0.251 | |
| 20261016T052334Z | ibm_marrakesh | db8r9lheukqs73ar6110 | chain, 8 swaps (18 q) | 4000 | 0.573 ± 0.006 | 0.252 | |
| 20261016T052334Z | ibm_marrakesh | db8r9lheukqs73ar6110 | chain, 10 swaps (22 q) | 4000 | 0.553 ± 0.006 | 0.244 | still entangled (~9 SE above 0.5); full line [92 … 149] in results JSON |
| 20261016T053914Z | ibm_marrakesh | db8rh0dckpjs73b1ilr0 / db8rh0m94fic73etvka0 | DD test, 1 swap, no wait | 4000 | off 0.933 ± 0.003 / on 0.935 ± 0.003 | - | +0.002 (0.5 SE): no effect; same line as chain run |
| 20261016T053914Z | ibm_marrakesh | db8rh0dckpjs73b1ilr0 / db8rh0m94fic73etvka0 | DD test, 4 swaps, no wait | 4000 | off 0.732 ± 0.005 / on 0.752 ± 0.005 | - | +0.020 (2.7 SE): small gain, XX/YY up; only 4 pulses on end qubits |
| 20261016T053914Z | ibm_marrakesh | db8rh0dckpjs73b1ilr0 / db8rh0m94fic73etvka0 | DD test, 10 swaps, no wait | 4000 | off 0.547 ± 0.006 / on 0.555 ± 0.006 | - | +0.008 (0.9 SE): no significant effect |
| 20261016T053914Z | ibm_marrakesh | db8rh0dckpjs73b1ilr0 / db8rh0m94fic73etvka0 | DD test, 1 swap, 4 µs wait | 4000 | off 0.724 ± 0.005 / on 0.810 ± 0.005 | - | +0.086 (12.4 SE): DD works; off shows Φ outcomes 0.64 vs Ψ 0.81 = coherent phase drift, DD equalises |
| 20261016T053914Z | ibm_marrakesh | db8rh0dckpjs73b1ilr0 / db8rh0m94fic73etvka0 | DD test, 4 swaps, 4 µs wait | 4000 | off 0.374 ± 0.007 / on 0.394 ± 0.007 | - | +0.020 (2.1 SE): entanglement lost either way |
| 20261016T053914Z | ibm_marrakesh | db8rh0dckpjs73b1ilr0 / db8rh0m94fic73etvka0 | DD test, 10 swaps, 4 µs wait | 4000 | off 0.288 ± 0.007 / on 0.294 ± 0.007 | - | ≈ noise; T1 + T2 over 22 qubits |
| 20261016T192613Z | ibm_marrakesh | db97kl424mrc7383job0 | nested job: parallel 1 / 3 / 7 swaps | 4000 | 0.765 / 0.357 / 0.378 | - | INVALID LINE: physical 137 (q7) read 1 in 82–83% of shots (calibration 35 min earlier said 2.3% readout) |
| 20261016T192613Z | ibm_marrakesh | db97kl424mrc7383job0 | nested (no DD) 1 / 3 / 7 swaps | 4000 | 0.778 / 0.304 / 0.294 | - | same broken line; line [141,142,143,144,145,146,147,137,127,…,98] |
| 20261016T192613Z | ibm_marrakesh | db97kl424mrc7383job0 | nested + XX 1 / 3 / 7 swaps | 4000 | 0.805 / 0.318 / 0.314 | - | DD +0.027 (4.0 SE) at 1 swap, ≤ 2 SE otherwise |
| 20261016T192613Z | ibm_marrakesh | db97kl424mrc7383job0 | nested + XX×4 1 / 3 / 7 swaps | 4000 | 0.786 / 0.311 / 0.288 | - | XX×4 inserts 0 pulses at 1 swap (gaps too short) |
| 20261020T220425Z | ibm_marrakesh | dbbuaq424mrc73cies10 | repeater parallel, 1 / 2 / 4 / 8 / 16 links | 4000 | 0.943 / 0.883 / 0.555 / 0.351 / 0.260 (± 0.003–0.007) | - | line [105,106,107,…,41,42] (live readout scan, 24 qubits excluded); yield 0.598 / 0.300 / 0 / 0 / 0; R_dev 3580 → 3473 pairs/s; ebit_dev 2140 / 1074 / 0 /s |
| 20261020T220425Z | ibm_marrakesh | dbbuaq424mrc73cies10 | repeater sequential, 1 / 2 / 4 / 8 / 16 links | 4000 | 0.940 / 0.905 / 0.549 / 0.347 / 0.262 | - | n=2 beats parallel by +0.022 (4.6 SE), only in XX/YY; ebit_dev 2063 / 1440 / 0 /s; overhead 276.5 µs/shot measured |
| 20261020T220605Z | ibm_marrakesh | dbbubj1gv2cc73e95qlg | repeater feed-forward (if_test), 1 / 2 / 4 / 8 / 16 links | 4000 | 0.939 / 0.655 / 0.510 / 0.323 / 0.263 | - | same line; n=2 −0.228 vs Pauli frame (34 SE); 295.5 vs 283.2 µs per shot |

## Ideas / next steps
- Turn on error suppression: `sampler.options.dynamical_decoupling.enable = True`,
  `sampler.options.twirling.enable_measure = True`, and compare against the plain run.
- Try Part 3 (real-time feed-forward with `if_test`) and compare its F with the post-processed F.
- Pick a specific qubit chain with low CX / readout error (`initial_layout=`) and compare with the transpiler's choice.
- Show a CHSH violation on (q0,q3) after swapping (needs rotated measurement bases).
- ~~Chain the swap~~: done as `entanglement_swapping_chain.ipynb`, run 20261016T052334Z.
  Findings: entangled up to 10 swaps / 22 qubits; visibility kept ≈ 0.92 per swap (fit a=0.906, r=0.917,
  predicted limit ≈ 11–12 swaps). Decay is uneven and tracks specific bad qubits (calibration at job time:
  109 readout 3.1%, 110 2.4%, 125 3.7%; 108 T1/T2 ≈ 25 µs). Per-swap decay of |corr| for n ≥ 2:
  ZZ 0.943, XX 0.924, YY 0.899 (YY hit by both bit- and phase-type errors).
- Longer chains (12–16 swaps) to see where F actually crosses 0.5.
- Hand-pick a line avoiding high-readout-error qubits (109, 110, 125) and compare the decay rate.
- DD result (run 20261016T053914Z): prediction confirmed for normal circuits (gain ≤ 0.02, ≤ 2.7 SE). With a 4 µs
  wait, DD gives +0.086 at 1 swap: without DD the Φ outcomes (00, 10) drop to ~0.63 while Ψ outcomes (01, 11)
  stay ~0.81, the signature of a coherent, similar phase drift on the waiting qubits (simulated: equal Rz on
  every qubit hurts only Φ outcomes); DD's echo removes it. With DD, 1-swap XX ≈ 0.75 matches the echo-T2
  prediction from calibration (0.93 × e^(−4 µs·Σ1/T2) ≈ 0.76). DD cannot fix T1 (ZZ also drops) or true T2.
  Next: more pulses per long gap (e.g. [X, X] × 4) to beat the echo-T2 limit.
- Dynamical decoupling: analysed, predicted to give ~no gain. Scheduled on FakeMarrakesh the circuits are ~280 ns of
  gates + 2.6 µs measurement; idle time is ≤140 ns and only on the two end qubits (inner qubits idle 36 ns, too
  short for an X–X pair), so DD adds the same 4 pulses at every chain length and cannot change the decay rate.
  Estimated idle dephasing loss: 0.2–0.4%. (Sampler has DD off by default, so past runs had none.)
- Error budget at 10 swaps (calibration at job time): in visibility v, readout errors alone explain ~40% of the
  log-loss, isolated CZ errors ~9%, ~50% unexplained (suspects: crosstalk between simultaneous CZs/readouts,
  calibration drift). Readout mitigation of the parities (measure flip rates, divide each correlator by
  ∏(1 − 2ε)) is the most promising improvement; report mitigated F next to the raw F, since only raw F
  is a strict entanglement proof.
