"""
Baseline solver for: shortest blue-only path from s to t with unknown node
colors, revealed only via a paid Query(v) action.

This implements the "value-of-information" Canadian-Traveller-Problem-style
baseline discussed:

  - Maintain a set of known-blue nodes (K_blue) and known-red nodes (K_red).
  - At each step, check whether a blue-only path from the current node to t
    already exists using only confirmed-blue nodes. If so, just walk it
    (no more queries needed).
  - Otherwise, look at the "frontier": unknown nodes adjacent to the
    blue-confirmed component that contains the current node. For each
    frontier candidate v, compute an *optimistic* total path cost if v
    turns out to be blue (treating all still-unknown nodes as passable).
    Combine this with the best already-known finite path cost to get an
    expected value of information for querying v:

        EV(v) = 0.5 * (best_known - optimistic_via_v) - cq

    (0.5 because P(blue)=0.5 under assumption 7; if v turns out red the
    only "loss" is the cq already paid, which is a sunk cost baked into
    the EV formula as the constant term.)

  - Query the frontier candidate with the highest EV (ties broken by
    smallest optimistic distance). If nothing has positive EV but we still
    have no confirmed path, we relax and just query the most promising
    (smallest optimistic distance) candidate anyway -- we are guaranteed
    (Assumption 8) that a blue path exists, so exploration must continue.
  - Repeat until t is reached.

Costs: moving along an edge costs `cm`, querying a node costs `cq`.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import networkx as nx


UNKNOWN, BLUE, RED = "unknown", "blue", "red"


@dataclass
class RunResult:
    path: list          # sequence of nodes actually walked, s..t
    queries_in_order: list   # sequence of (node, result) queries made
    total_cost: float
    move_cost: float
    query_cost: float
    num_queries: int
    num_wasted_queries: int  # queries for nodes that never end up on the final path
    known_colors: dict       # final knowledge state


def blue_subgraph_distance(G: nx.Graph, known: dict, src, dst) -> Optional[list]:
    """Shortest path from src to dst using only nodes known BLUE (src/dst included
    even if not explicitly marked, since caller guarantees they're safe)."""
    allowed = {n for n, c in known.items() if c == BLUE}
    allowed.add(src)
    allowed.add(dst)
    H = G.subgraph(allowed)
    if src not in H or dst not in H:
        return None
    try:
        return nx.shortest_path(H, src, dst)
    except nx.NetworkXNoPath:
        return None


def optimistic_distance(G: nx.Graph, known: dict, src, dst) -> Optional[int]:
    """Shortest path length from src to dst treating UNKNOWN and BLUE nodes as
    passable, and only excluding known-RED nodes. This is a lower bound on the
    true remaining cost if src's color turns out blue."""
    blocked = {n for n, c in known.items() if c == RED}
    if src in blocked or dst in blocked:
        return None
    H = G.subgraph([n for n in G.nodes if n not in blocked])
    if src not in H or dst not in H:
        return None
    try:
        return nx.shortest_path_length(H, src, dst)
    except nx.NetworkXNoPath:
        return None


def solve(G: nx.Graph, s, t, colors: dict, cq: float = 5.0, cm: float = 1.0,
          verbose: bool = True) -> RunResult:
    """
    colors: ground-truth dict {node: 'blue'/'red'} -- the oracle the agent may
            query. Only used inside Query(); the algorithm never reads it directly.
    """
    known = {s: BLUE, t: BLUE}
    current = s
    path_walked = [s]
    queries_in_order = []
    move_cost_total = 0.0
    query_cost_total = 0.0

    def log(msg):
        if verbose:
            print(msg)

    def query(v):
        nonlocal query_cost_total
        query_cost_total += cq
        result = colors[v]
        known[v] = BLUE if result == "blue" else RED
        queries_in_order.append((v, result))
        log(f"  QUERY {v} -> {result.upper()}  (cost so far: queries={query_cost_total})")
        return known[v]

    steps = 0
    max_steps = 10_000  # safety valve
    while current != t and steps < max_steps:
        steps += 1

        # 1) Can we already walk a fully-confirmed-blue path from here to t?
        confirmed_path = blue_subgraph_distance(G, known, current, t)
        if confirmed_path is not None:
            log(f"[Step {steps}] Confirmed blue path found from {current} to {t}: {confirmed_path}")
            # Walk it (skip current, already there)
            for nxt in confirmed_path[1:]:
                move_cost_total += cm
                path_walked.append(nxt)
                current = nxt
            break

        best_known_len = None  # None == infinity (no confirmed path yet)

        # 2) Build frontier: unknown neighbors of the blue-confirmed component
        #    that contains `current`.
        blue_nodes = {n for n, c in known.items() if c == BLUE}
        blue_nodes.add(current)
        comp_subgraph = G.subgraph(blue_nodes | {current})
        # nodes reachable from current using only blue nodes (current included)
        try:
            reachable_blue = nx.node_connected_component(G.subgraph(blue_nodes), current)
        except KeyError:
            reachable_blue = {current}

        frontier = set()
        for b in reachable_blue:
            for nb in G.neighbors(b):
                if nb not in known:
                    frontier.add((b, nb))  # (blue anchor, unknown neighbor)

        if not frontier:
            raise RuntimeError("No frontier left to explore but no path found -- "
                                "contradicts Assumption 8 (a blue path must exist).")

        # dist from s (start of walk) to each blue anchor along the walked/confirmed
        # path is just "how many hops to get there from current position" --
        # since current sits inside reachable_blue, use BFS within blue subgraph.
        dist_from_current = nx.single_source_shortest_path_length(
            G.subgraph(reachable_blue), current
        )

        best_candidate = None
        best_ev = float("-inf")
        best_optimistic = float("inf")

        for anchor, v in frontier:
            d_to_anchor = dist_from_current.get(anchor)
            if d_to_anchor is None:
                continue
            tail = optimistic_distance(G, known, v, t)
            if tail is None:
                continue  # v is a dead end even optimistically, not worth it
            optimistic_total = d_to_anchor + 1 + tail
            ev = 0.5 * ((best_known_len if best_known_len is not None else float("inf"))
                        - optimistic_total) - cq
            # best_known_len is inf here (we already returned early if finite),
            # so ev is effectively "how good is this shortcut", dominated by
            # -optimistic_total; we just want the candidate with smallest
            # optimistic_total (that's the true tie-breaker/EV driver when
            # best_known is infinite).
            if optimistic_total < best_optimistic:
                best_optimistic = optimistic_total
                best_candidate = v
                best_ev = ev

        if best_candidate is None:
            raise RuntimeError("Frontier nonempty but no viable candidate -- "
                                "contradicts Assumption 8.")

        log(f"[Step {steps}] No confirmed path yet. Querying most promising frontier "
            f"node {best_candidate} (optimistic total dist={best_optimistic}).")
        query(best_candidate)
        # loop again: re-check confirmed path / frontier

    if current != t:
        raise RuntimeError("Failed to reach t within step budget.")

    total_cost = move_cost_total + query_cost_total
    on_path = set(path_walked)
    wasted = sum(1 for (v, r) in queries_in_order if v not in on_path)

    return RunResult(
        path=path_walked,
        queries_in_order=queries_in_order,
        total_cost=total_cost,
        move_cost=move_cost_total,
        query_cost=query_cost_total,
        num_queries=len(queries_in_order),
        num_wasted_queries=wasted,
        known_colors=dict(known),
    )
