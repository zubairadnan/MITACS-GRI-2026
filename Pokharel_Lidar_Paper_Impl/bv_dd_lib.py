"""
Circuit construction, UR-n dynamical decoupling, transpilation, budget
estimation, execution, and result helpers for replicating the ssBV-n
"guessing game" from Pokharel & Lidar, arXiv:2207.07647.

Bitstring convention: an oracle is labeled by b = "1"*k + "0"*(n-k), matching
the paper's representative oracle family (Methods, "Experimental
implementation"). b[i] refers to data qubit i (0-indexed, left to right).
"""

import math

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister
from qiskit.quantum_info import Operator
from qiskit.transpiler import PassManager
from qiskit.transpiler.passes import ALAPScheduleAnalysis, PadDelay, PadDynamicalDecoupling
from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

# ---------------------------------------------------------------------------
# ssBV-n circuit construction (Fig. 1, top)
# ---------------------------------------------------------------------------


def oracle_label(n: int, k: int) -> str:
    """Representative oracle b = 1^k 0^(n-k) for problem size n, weight k."""
    return "1" * k + "0" * (n - k)


def all_representative_oracles(n: int) -> list[str]:
    """The n+1 representative oracles the paper tests per problem size (one per Hamming weight)."""
    return [oracle_label(n, k) for k in range(n + 1)]


def marked_qubits_from_label(label: str) -> list[int]:
    return [i for i, bit in enumerate(label) if bit == "1"]


def build_bv_circuit(label: str) -> QuantumCircuit:
    """n data qubits + 1 ancilla; X on ancilla, H-layer, CNOTs from marked qubits, H-layer, measure."""
    n = len(label)
    data = QuantumRegister(n, "q")
    ancilla = QuantumRegister(1, "a")
    creg = ClassicalRegister(n, "c")
    qc = QuantumCircuit(data, ancilla, creg, name=f"bv_{label}")

    qc.x(ancilla[0])
    qc.h(data)
    qc.h(ancilla[0])
    for i in marked_qubits_from_label(label):
        qc.cx(data[i], ancilla[0])
    qc.h(data)
    qc.h(ancilla[0])
    qc.measure(data, creg)
    return qc


def expected_output_key(label: str) -> str:
    """Qiskit reports classical bits little-endian (creg[n-1] leftmost); reverse our label to match."""
    return label[::-1]


# ---------------------------------------------------------------------------
# UR-n dynamical decoupling sequence (Appendix F)
# ---------------------------------------------------------------------------


def ur_n_big_phi(n: int) -> float:
    """Phi^(n) from Eq. F1c, piecewise on n mod 4."""
    if n % 4 == 0:
        m = n // 4
        return math.pi / m
    if n % 4 == 2:
        m = (n - 2) // 4
        return 2 * m * math.pi / (2 * m + 1)
    raise ValueError("URn requires even n >= 4")


def ur_n_phases(n: int) -> list[float]:
    """Pulse-axis angles phi_k for k=1..n (Eq. F1b).

    The sequence's net rotation is a phase gate exp(i*chi*Z) with
    chi = n*phi2/2 (Genov et al. 2017, arXiv:1609.09416, discussion after
    their Eq. 3); pure dynamical decoupling (identity, chi=0 mod pi) requires
    phi2 to be an integer multiple of 2*pi/n. For n = 4m this holds
    automatically at phi2 = pi/2 (since n/4 is an integer) -- reproducing the
    paper's stated "phi2 = pi/2, so UR4 = XY4" convention, which we verify
    below. For n = 4m+2 (UR14, UR18 -- what this paper actually uses),
    n/4 is a half-integer, so pi/2 does NOT satisfy closure: multiplying it
    out algebraically shows the sequence would compose to a nonzero Z-rotation,
    not identity. We instead use phi2 = Phi^(n), which is always an integer
    multiple of 2*pi/n for this branch and matches the phase values Genov et
    al.'s own Table 1 gives for UR6 (phi2 = Phi = 2*pi/3).
    """
    if n < 4 or n % 2 != 0:
        raise ValueError("URn requires even n >= 4")
    big_phi = ur_n_big_phi(n)
    phi2 = math.pi / 2 if n % 4 == 0 else big_phi
    return [((k - 1) * (k - 2) / 2) * big_phi + (k - 1) * phi2 for k in range(1, n + 1)]


def ur_n_sequence(n: int) -> list:
    """UR-n as native-basis gates: IBM targets don't support a general RGate ('r' is not in
    the target's basis), so each R(pi, phi_k) pulse is decomposed as RZ(phi_k)-X-RZ(-phi_k) --
    a virtual-Z frame change around a physical X pulse, which is also how transmon control
    electronics actually implement an arbitrary-axis pi-pulse in practice. RZ is free (virtual,
    zero duration) on IBM hardware, so this costs the same physical time as a bare X per pulse.
    """
    from qiskit.circuit.library import RZGate, XGate

    sequence = []
    for phi in ur_n_phases(n):
        sequence += [RZGate(phi), XGate(), RZGate(-phi)]
    return sequence


_IBM_BUILTIN_DD_PHASES = {
    # Axis angles for IBM Runtime's built-in SamplerV2 dynamical_decoupling
    # presets (qiskit_ibm_runtime.options.DynamicalDecouplingOptions.sequence_type),
    # expressed in the same RZ-X-RZ pulse-axis convention as ur_n_sequence.
    "XX": [0.0, 0.0],
    "XpXm": [0.0, math.pi],
    "XY4": [0.0, math.pi / 2, math.pi, 3 * math.pi / 2],
}


def ibm_builtin_dd_sequence(sequence_type: str) -> list:
    """Native-basis gate list matching one of IBM Runtime's built-in DD presets.

    Lets the existing local-simulation path (add_dynamical_decoupling,
    verify_dd_sequence_identity, run_ideal, run_noisy_local) exercise the
    same sequences that SamplerV2's options.dynamical_decoupling applies on
    real hardware, even though that option itself is a per-job Runtime
    setting rather than a transpiler pass we control (see
    run_on_hardware_builtin_dd). Note XX and XpXm are unitarily identical up
    to a global phase -- local simulation cannot distinguish them; any real
    difference is a hardware-only effect of the physical pulse phase.
    """
    from qiskit.circuit.library import RZGate, XGate

    if sequence_type not in _IBM_BUILTIN_DD_PHASES:
        raise ValueError(f"Unknown sequence_type {sequence_type!r}; expected one of {sorted(_IBM_BUILTIN_DD_PHASES)}")
    sequence = []
    for phi in _IBM_BUILTIN_DD_PHASES[sequence_type]:
        sequence += [RZGate(phi), XGate(), RZGate(-phi)]
    return sequence


def verify_dd_sequence_identity(sequence: list, atol: float = 1e-9) -> bool:
    """Multiply the sequence's matrices in time order and check the product is I up to global phase.

    This mirrors the check PadDynamicalDecoupling performs internally before
    accepting a custom dd_sequence, so passing this guarantees the pass will
    accept the sequence.
    """
    product = np.eye(2, dtype=complex)
    for gate in sequence:
        product = Operator(gate).data @ product
    return Operator(product).equiv(Operator(np.eye(2, dtype=complex)))


# ---------------------------------------------------------------------------
# Transpilation and DD insertion
# ---------------------------------------------------------------------------


def to_isa_circuit(circuit: QuantumCircuit, backend, optimization_level: int = 1) -> QuantumCircuit:
    """Standard-transpiler ISA circuit (Sabre routing), per the routing decision in the scope log."""
    pm = generate_preset_pass_manager(backend=backend, optimization_level=optimization_level)
    return pm.run(circuit)


def schedule_only(isa_circuit: QuantumCircuit, backend) -> QuantumCircuit:
    """ALAP-schedule the 'free' (bare) variant -- no DD pulses, idle time left as explicit Delays.

    ALAPScheduleAnalysis alone only computes a schedule into the pass
    property set; it doesn't materialize it. PadDelay consumes that analysis
    and inserts the Delay instructions, which is also what sets
    circuit.duration -- without it, .duration stays None.
    """
    pm = PassManager([ALAPScheduleAnalysis(target=backend.target), PadDelay(target=backend.target)])
    return pm.run(isa_circuit)


def add_dynamical_decoupling(
    isa_circuit: QuantumCircuit, backend, dd_sequence: list, skip_reset_qubits: bool = True
) -> QuantumCircuit:
    """Schedule + fill idle windows with dd_sequence ('decouple then compute', Fig. 1 bottom).

    skip_reset_qubits=True (Qiskit's default) declines to pad the idle window immediately
    following each qubit's initialization, even if it's otherwise long enough to fit
    dd_sequence -- pass False to pad those windows too. See dd_utilization_report to check
    whether this matters for a given circuit (it can silently zero out DD coverage on qubits
    whose only idle time is that first window).
    """
    pm = PassManager(
        [
            ALAPScheduleAnalysis(target=backend.target),
            PadDynamicalDecoupling(target=backend.target, dd_sequence=dd_sequence, skip_reset_qubits=skip_reset_qubits),
        ]
    )
    return pm.run(isa_circuit)


def build_variant_circuits(
    qc: QuantumCircuit, backend, dd_sequences: dict[str, list], skip_reset_qubits: bool = True
) -> dict[str, QuantumCircuit]:
    """Transpile qc once to ISA, then produce the 'free' (bare, scheduled) variant plus one
    DD-padded variant per entry in dd_sequences (e.g. {"dd": ur14, "XX": ..., "XY4": ...}).

    Returns a dict keyed "routed" (the unscheduled ISA circuit -- what
    run_on_hardware_builtin_dd needs), "free", and one key per dd_sequences entry -- the same
    variant names compare_variants expects. Each circuit's .name is suffixed with "_<variant>"
    so same-oracle variants can be safely batched into one job without colliding.
    """
    isa = to_isa_circuit(qc, backend)
    variants: dict[str, QuantumCircuit] = {"routed": isa}

    free_c = schedule_only(isa, backend)
    free_c.name = f"{qc.name}_free"
    variants["free"] = free_c

    for name, seq in dd_sequences.items():
        padded = add_dynamical_decoupling(isa, backend, seq, skip_reset_qubits=skip_reset_qubits)
        padded.name = f"{qc.name}_{name.lower()}"
        variants[name] = padded

    return variants


# ---------------------------------------------------------------------------
# DD idle-time utilization diagnostics
# ---------------------------------------------------------------------------


def idle_windows_by_qubit(free_circuit: QuantumCircuit) -> dict[int, list[int]]:
    """Per-qubit list of idle-window durations (dt), read off a plain ALAP-scheduled circuit
    (schedule_only's output -- exactly one Delay per idle window, no DD pulses). This is the
    ground-truth idle budget that add_dynamical_decoupling has to work with for the same
    underlying circuit, since DD padding never changes where or how long the idle windows are,
    only what fills them.

    Restricted to qubits the circuit actually routes to (i.e. that carry at least one non-Delay
    instruction) -- same convention as draw(idle_wires=False). An ISA circuit spans the whole
    backend register (127+ qubits), and an untouched qubit's "idle window" is its entire
    duration sitting right after the circuit's start node, which skip_reset_qubits (Qiskit's
    default) always declines to pad regardless of length -- mixing those in would swamp the
    real signal from the handful of qubits the oracle actually uses.
    """
    active = {
        free_circuit.find_bit(q).index
        for instr in free_circuit.data
        if instr.operation.name != "delay"
        for q in instr.qubits
    }
    windows: dict[int, list[int]] = {i: [] for i in sorted(active)}
    for instr in free_circuit.data:
        if instr.operation.name == "delay":
            q = free_circuit.find_bit(instr.qubits[0]).index
            if q in windows:
                windows[q].append(instr.operation.duration)
    return windows


def _sequence_duration_dt(dd_sequence: list, backend, qubit: int) -> int:
    """Total duration (dt) of one application of dd_sequence on physical qubit `qubit`.

    RZ is virtual (zero duration) on IBM hardware, so only the X pulses contribute -- see
    ur_n_sequence. Looked up fresh from backend.target rather than trusting `.duration` on the
    dd_sequence gate objects themselves: PadDynamicalDecoupling mutates and reuses those same
    Gate instances while padding every qubit in turn (see qiskit's
    transpiler.passes.scheduling.padding.dynamical_decoupling._pre_runhook), so by the time
    padding is done, a gate's `.duration` attribute reflects whichever qubit was processed
    last -- not necessarily this one.
    """
    durations = backend.target.durations()
    total = 0
    for gate in dd_sequence:
        try:
            total += durations.get(gate.name, qubit)
        except Exception:
            pass  # not separately listed (e.g. some virtual gates) -- treat as zero duration
    return total


def dd_utilization_report(free_circuit: QuantumCircuit, padded_circuit: QuantumCircuit, backend, dd_sequence: list) -> pd.DataFrame:
    """Per-qubit accounting of a DD-padded circuit's idle time: how much of the idle budget
    (from the paired `free` circuit's plain Delay windows) ended up pulse-covered by
    dd_sequence, versus left as buffer/skipped Delay.

    PadDynamicalDecoupling inserts dd_sequence into an idle window only if the window is at
    least as long as the sequence's total pulse duration; otherwise it silently falls back to
    one bare Delay for that window, with no warning. `predicted_skipped_windows` recomputes
    that same pass/fail check per window directly from calibrated gate durations
    (window_dt >= sequence_duration_dt), so silent fallbacks show up here instead of only being
    visible by diffing circuit.draw() output. `actual_pulse_covered_dt` is an independent
    cross-check: total idle budget minus whatever Delay time genuinely remains in the padded
    circuit, which should agree with the per-window prediction (small discrepancies can come
    from Qiskit's skip_reset_qubits default, which also declines DD right after a reset/circuit
    start regardless of window length).
    """
    free_windows = idle_windows_by_qubit(free_circuit)

    remaining_delay: dict[int, int] = {}
    for instr in padded_circuit.data:
        if instr.operation.name == "delay":
            q = padded_circuit.find_bit(instr.qubits[0]).index
            if q in free_windows:
                remaining_delay[q] = remaining_delay.get(q, 0) + instr.operation.duration

    rows = []
    for q, windows in free_windows.items():
        if not any(windows):
            continue
        seq_dt = _sequence_duration_dt(dd_sequence, backend, q)
        total_idle = sum(windows)
        predicted_covered = sum(seq_dt for w in windows if w > 0 and w >= seq_dt)
        n_skipped = sum(1 for w in windows if w > 0 and w < seq_dt)
        actual_covered = total_idle - remaining_delay.get(q, 0)
        rows.append(
            {
                "qubit": q,
                "n_windows": sum(1 for w in windows if w > 0),
                "total_idle_dt": total_idle,
                "predicted_pulse_covered_dt": predicted_covered,
                "predicted_skipped_windows": n_skipped,
                "actual_pulse_covered_dt": actual_covered,
                "buffer_or_skipped_dt": remaining_delay.get(q, 0),
                "utilization_pct": 100 * actual_covered / total_idle if total_idle else 0.0,
            }
        )
    return pd.DataFrame(rows).set_index("qubit").sort_index()


def dd_utilization_summary(
    free_circuit: QuantumCircuit,
    padded_circuits: dict[str, QuantumCircuit],
    dd_sequences: dict[str, list],
    backend,
) -> pd.DataFrame:
    """One row per DD variant: aggregate idle time, how much of it is pulse-covered vs. left as
    buffer/skipped, and how many idle windows (if any) were too short for the sequence and fell
    back to a bare, unprotected Delay. See dd_utilization_report for the per-qubit breakdown
    behind these totals.
    """
    rows = []
    for name, padded in padded_circuits.items():
        report = dd_utilization_report(free_circuit, padded, backend, dd_sequences[name])
        total_idle = report["total_idle_dt"].sum()
        covered = report["actual_pulse_covered_dt"].sum()
        rows.append(
            {
                "variant": name,
                "total_idle_dt": total_idle,
                "pulse_covered_dt": covered,
                "buffer_or_skipped_dt": total_idle - covered,
                "utilization_pct": 100 * covered / total_idle if total_idle else 0.0,
                "windows_skipped": int(report["predicted_skipped_windows"].sum()),
                "qubits_with_skips": int((report["predicted_skipped_windows"] > 0).sum()),
            }
        )
    return pd.DataFrame(rows).set_index("variant")


# ---------------------------------------------------------------------------
# QPU budget estimation
# ---------------------------------------------------------------------------


def estimate_qpu_seconds(circuits: list[QuantumCircuit], shots: int, backend, per_job_overhead_s: float = 2.0) -> float:
    """Sum scheduled circuit durations x shots across a batch; circuits must already be scheduled."""
    dt = backend.target.dt
    total = 0.0
    for c in circuits:
        if c.duration is None:
            raise ValueError(f"Circuit {c.name!r} has no scheduled duration; run schedule_only/add_dynamical_decoupling first.")
        total += c.duration * dt * shots
    return total + per_job_overhead_s


def check_budget(circuits: list[QuantumCircuit], shots: int, backend, budget_seconds: float = 240.0) -> bool:
    estimate = estimate_qpu_seconds(circuits, shots, backend)
    ok = estimate <= budget_seconds
    print(f"Estimated QPU time: {estimate:.2f}s  (budget: {budget_seconds:.0f}s)  -> {'OK' if ok else 'OVER BUDGET'}")
    return ok


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


def connect_and_pick_backend(preferred_backends: list[str], token_env: str = "MY_TOKEN", instance_env: str = "MY_INSTANCE"):
    """Connect to IBM Quantum Platform and pick the first available backend from preferred_backends.

    Reads credentials from the token_env/instance_env environment variables; falls back to a
    previously saved QiskitRuntimeService account if the token var isn't set (or still holds a
    "PASTE_" placeholder). Returns (service, backend).
    """
    import os

    from qiskit_ibm_runtime import QiskitRuntimeService

    token = os.environ.get(token_env)
    instance = os.environ.get(instance_env)

    if token and not token.startswith("PASTE_"):
        service = QiskitRuntimeService(
            channel="ibm_quantum_platform",
            token=token,
            instance=instance if instance and not instance.startswith("PASTE_") else None,
        )
    else:
        service = QiskitRuntimeService()  # falls back to a previously saved account

    available = {b.name for b in service.backends()}
    backend_name = next((name for name in preferred_backends if name in available), None)
    if backend_name is None:
        raise RuntimeError(f"None of {preferred_backends} is available on this account. Available backends: {sorted(available)}")

    backend = service.backend(backend_name)
    print(f"Using backend: {backend.name}  ({backend.num_qubits} qubits)")
    return service, backend


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def run_on_simulator(circuits: list[QuantumCircuit], sim, shots: int = 2000) -> list[dict]:
    """Run circuits on an already-built AerSimulator instance.

    Returns counts as a list aligned by position with `circuits`, not keyed by
    circuit.name -- the 'free' and 'dd' variant of the same oracle share a
    name (both derive from the same source circuit), so name-based lookup
    would silently collide when both variants are batched in one call.

    Building a noisy simulator (AerSimulator.from_backend) is expensive, so callers running many
    batches against the same backend calibration -- e.g. one sweep across several problem sizes --
    should build it once with build_noisy_simulator and reuse it here, rather than going through
    run_noisy_local (which rebuilds it on every call) once per batch.
    """
    result = sim.run(circuits, shots=shots).result()
    return [result.get_counts(i) for i in range(len(circuits))]


def run_ideal(circuits: list[QuantumCircuit], shots: int = 2000) -> list[dict]:
    """No-noise AerSimulator run; DD should be logically transparent here (success prob = 1.0)."""
    from qiskit_aer import AerSimulator

    return run_on_simulator(circuits, AerSimulator(), shots=shots)


def build_noisy_simulator(backend):
    """AerSimulator seeded from a live calibration snapshot of `backend` -- no QPU quota consumed.

    Build once and reuse across multiple run_on_simulator calls against the same backend
    (e.g. across an N-sweep) rather than rebuilding it per call via run_noisy_local.
    """
    from qiskit_aer import AerSimulator

    return AerSimulator.from_backend(backend)


def run_noisy_local(circuits: list[QuantumCircuit], backend, shots: int = 2000) -> list[dict]:
    """Convenience one-shot wrapper: build_noisy_simulator(backend) + run_on_simulator.

    Rebuilds the noise model on every call -- fine for a single batch, wasteful if called
    repeatedly against the same backend (use build_noisy_simulator + run_on_simulator directly
    instead, see run_on_simulator's docstring).
    """
    return run_on_simulator(circuits, build_noisy_simulator(backend), shots=shots)


def run_on_hardware(circuits: list[QuantumCircuit], backend, shots: int = 2000):
    """Submit one batched SamplerV2 job. Returns the Job; call .result() once it completes."""
    from qiskit_ibm_runtime import SamplerV2

    sampler = SamplerV2(mode=backend)
    return sampler.run(circuits, shots=shots)


def run_on_hardware_builtin_dd(circuits: list[QuantumCircuit], backend, shots: int = 2000, sequence_type: str = "XY4"):
    """Submit one batched SamplerV2 job using IBM Runtime's built-in DD option instead of our own
    PadDynamicalDecoupling pass. `circuits` must be routed-but-unscheduled ISA circuits (to_isa_circuit
    output) -- scheduling and DD padding happen inside the Runtime service when this option is enabled,
    so pre-scheduling them ourselves (schedule_only/add_dynamical_decoupling) would be redundant.
    Returns the Job; call .result() once it completes.
    """
    from qiskit_ibm_runtime import SamplerV2

    sampler = SamplerV2(mode=backend)
    sampler.options.dynamical_decoupling.enable = True
    sampler.options.dynamical_decoupling.sequence_type = sequence_type
    return sampler.run(circuits, shots=shots)


def counts_from_sampler_result(result, num_circuits: int, creg_name: str = "c") -> list[dict]:
    """Extract per-circuit counts from a SamplerV2 PrimitiveResult, positionally aligned (see run_ideal)."""
    return [getattr(result[i].data, creg_name).get_counts() for i in range(num_circuits)]


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def success_probabilities(counts_by_label: dict[str, dict], labels: list[str]) -> pd.DataFrame:
    rows = []
    for label in labels:
        counts = counts_by_label[label]
        total = sum(counts.values())
        target = expected_output_key(label)
        ps = counts.get(target, 0) / total if total else float("nan")
        rows.append({"oracle": label, "weight": label.count("1"), "success_probability": ps})
    return pd.DataFrame(rows).set_index("oracle")


def split_counts_by_variant(counts: list[dict], labels: list[str], variant_cols: list[str]) -> dict[str, dict[str, dict]]:
    """Split a combined, positionally-aligned counts list (as run_ideal/run_noisy_local return for
    a concatenated multi-variant circuit list) back into one {label: counts} dict per variant.

    Assumes the combined circuit list was built as
    `[c for col in variant_cols for c in variant_lists[col]]` -- i.e. all of one variant's
    circuits, then all of the next, each block in `labels` order.
    """
    n = len(labels)
    return {col: dict(zip(labels, counts[i * n : (i + 1) * n])) for i, col in enumerate(variant_cols)}


def compare_free_vs_dd(free_counts: dict[str, dict], dd_counts: dict[str, dict], labels: list[str]) -> pd.DataFrame:
    return compare_variants({"free": free_counts, "dd": dd_counts}, labels)


def compare_variants(counts_by_variant: dict[str, dict[str, dict]], labels: list[str]) -> pd.DataFrame:
    """Success-probability table with a 'weight' column plus one column per variant (e.g. free, dd, xx, xpxm, xy4)."""
    result = pd.DataFrame({"oracle": labels, "weight": [label.count("1") for label in labels]}).set_index("oracle")
    for variant, counts in counts_by_variant.items():
        df = success_probabilities(counts, labels)[["success_probability"]].rename(columns={"success_probability": variant})
        result = result.join(df)
    return result


# ---------------------------------------------------------------------------
# Plotting
# ---------------------------------------------------------------------------


def plot_output_distributions(counts_by_label: dict[str, dict], labels: list[str], n: int, title: str, ax=None):
    """Fig. 2-style heatmap, compressed to one row per representative oracle (Hamming weight) rather
    than all 2**n oracles -- see the notebook's note on the qubit-permutation-symmetry expansion
    (Appendix B) that would be needed to reproduce the paper's full per-bitstring grid."""
    grid = np.zeros((len(labels), 2**n))
    for row, label in enumerate(labels):
        counts = counts_by_label[label]
        total = sum(counts.values())
        for bitstring, count in counts.items():
            grid[row, int(bitstring, 2)] = count / total

    if ax is None:
        _, ax = plt.subplots(figsize=(8, 3))
    im = ax.imshow(grid, aspect="auto", cmap="viridis", vmin=0, vmax=1)
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels([f"k={label.count('1')}" for label in labels])
    ax.set_xlabel("Detected state")
    ax.set_title(title)
    return ax.figure, im
