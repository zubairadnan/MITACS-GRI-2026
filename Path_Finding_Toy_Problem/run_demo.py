import networkx as nx
import matplotlib.pyplot as plt
from blue_path_baseline import solve, BLUE, RED

# ---------------------------------------------------------------------------
# 1) Hardcoded graph (reproducible) -----------------------------------------
# ---------------------------------------------------------------------------
# 14 nodes. s=0, t=13. There is exactly one guaranteed blue-only path
# (0-1-4-7-10-13, length 5) plus several red decoys and a couple of extra
# blue nodes that are NOT on the shortest path (to show the algorithm won't
# waste queries on them) and one alternate longer all-blue detour
# (0-2-5-8-11-13) to make sure the algorithm still finds the SHORTEST one.

edges = [
    (0, 1), (0, 2), (0, 3),
    (1, 4), (2, 5), (3, 6),
    (4, 7), (5, 8), (6, 9),
    (7, 10), (8, 11), (9, 12),
    (10, 13), (11, 13), (12, 13),
    (1, 2), (4, 5), (7, 8),   # a few cross-links to create extra frontier choices
    (2, 3), (5, 6), (8, 9),
]

G = nx.Graph()
G.add_edges_from(edges)

s, t = 0, 13

# Ground-truth colors (hardcoded, reproducible). s and t are always blue
# per Assumption 5.
colors = {
    0: "blue",   # s
    1: "blue",
    2: "red",
    3: "red",
    4: "blue",
    5: "blue",
    6: "red",
    7: "blue",
    8: "blue",
    9: "red",
    10: "blue",
    11: "blue",
    12: "red",
    13: "blue",  # t
}

assert colors[s] == "blue" and colors[t] == "blue"
assert set(colors.keys()) == set(G.nodes)

# sanity check: verify (offline, for our own confidence only -- the agent
# does NOT get to see this) that a blue-only path exists.
blue_nodes = {n for n, c in colors.items() if c == "blue"}
H_true = G.subgraph(blue_nodes)
true_shortest = nx.shortest_path(H_true, s, t)
print("Ground-truth blue-only shortest path (for verification only):", true_shortest,
      "length =", len(true_shortest) - 1)

# ---------------------------------------------------------------------------
# 2) Run the baseline agent ---------------------------------------------
# ---------------------------------------------------------------------------
cq, cm = 5.0, 1.0
print("\n--- Running value-of-information baseline (cq=%.1f, cm=%.1f) ---\n" % (cq, cm))
result = solve(G, s, t, colors, cq=cq, cm=cm, verbose=True)

print("\n=== RESULT ===")
print("Path walked      :", result.path, " (length =", len(result.path) - 1, "edges)")
print("Queries in order  :", result.queries_in_order)
print("Num queries        :", result.num_queries, " (wasted:", result.num_wasted_queries, ")")
print("Move cost           :", result.move_cost)
print("Query cost          :", result.query_cost)
print("TOTAL COST          :", result.total_cost)

# Compare with a plain "query everything on the shortest-known BFS frontier"
# baseline cost for reference: optimal path length assuming free color info.
print("\nFor reference, true optimal blue-path length (perfect information):",
      len(true_shortest) - 1, "  -> would cost", len(true_shortest) - 1, "if colors were free")

# ---------------------------------------------------------------------------
# 3) Visualize ----------------------------------------------------------
# ---------------------------------------------------------------------------
pos = nx.spring_layout(G, seed=42)  # fixed seed -> reproducible layout

fig, ax = plt.subplots(1, 1, figsize=(11, 8))

path_edges = list(zip(result.path, result.path[1:]))
path_nodes = set(result.path)
queried_nodes = [v for v, _ in result.queries_in_order]

# base edges
nx.draw_networkx_edges(G, pos, ax=ax, edge_color="#cccccc", width=1.5)
# highlight walked path edges
nx.draw_networkx_edges(G, pos, edgelist=path_edges, ax=ax, edge_color="#1f77b4", width=4)

# node colors: true color (for verification), but outline shows whether it
# was queried, and node shape/size shows whether it's on the walked path.
node_face_colors = []
node_edge_colors = []
node_line_widths = []
for n in G.nodes:
    true_c = colors[n]
    node_face_colors.append("#4c86f0" if true_c == "blue" else "#e05c5c")
    if n in queried_nodes:
        node_edge_colors.append("black")
        node_line_widths.append(2.5)
    else:
        node_edge_colors.append("white")
        node_line_widths.append(1.0)

nx.draw_networkx_nodes(G, pos, ax=ax, node_color=node_face_colors,
                        edgecolors=node_edge_colors, linewidths=node_line_widths,
                        node_size=800)
nx.draw_networkx_nodes(G, pos, nodelist=[s, t], ax=ax, node_color=[node_face_colors[list(G.nodes).index(s)],
                                                                     node_face_colors[list(G.nodes).index(t)]],
                        edgecolors="gold", linewidths=4, node_size=900)
nx.draw_networkx_labels(G, pos, ax=ax, font_color="white", font_weight="bold")

# annotate query order
for i, (v, r) in enumerate(result.queries_in_order, start=1):
    x, y = pos[v]
    ax.annotate(f"Q{i}", (x, y), xytext=(12, 12), textcoords="offset points",
                fontsize=9, color="black", fontweight="bold",
                bbox=dict(boxstyle="circle", fc="yellow", ec="black", alpha=0.85))

legend_elems = [
    plt.Line2D([0], [0], marker='o', color='w', label='True Blue node',
               markerfacecolor='#4c86f0', markersize=14),
    plt.Line2D([0], [0], marker='o', color='w', label='True Red node',
               markerfacecolor='#e05c5c', markersize=14),
    plt.Line2D([0], [0], marker='o', color='w', label='s / t (gold outline)',
               markerfacecolor='#4c86f0', markeredgecolor='gold', markeredgewidth=3, markersize=14),
    plt.Line2D([0], [0], marker='o', color='w', label='Queried node (black outline)',
               markerfacecolor='#4c86f0', markeredgecolor='black', markeredgewidth=3, markersize=14),
    plt.Line2D([0], [0], color='#1f77b4', lw=4, label='Path walked by agent'),
    plt.Line2D([0], [0], marker='o', color='w', label='Query order (Q1, Q2, ...)',
               markerfacecolor='yellow', markeredgecolor='black', markersize=12),
]
ax.legend(handles=legend_elems, loc='upper left', bbox_to_anchor=(1.0, 1.0), fontsize=10)

title = (f"Blue-path search: cq={cq}, cm={cm}\n"
         f"Path len={len(result.path)-1} edges | Queries={result.num_queries} "
         f"(wasted={result.num_wasted_queries}) | Total cost={result.total_cost:.1f}")
ax.set_title(title, fontsize=13)
ax.axis("off")
plt.tight_layout()
plt.savefig("/mnt/user-data/outputs/blue_path_result.png", dpi=150, bbox_inches="tight")
print("\nSaved visualization to /mnt/user-data/outputs/blue_path_result.png")
