import sys
from pathlib import Path

import networkx as nx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.utils.geo import haversine_m  # noqa: E402

A = (42.3900, -72.5300)
B = (42.3900, -72.5290)
C = (42.3905, -72.5300)
D = (42.3905, -72.5290)
NODES = {1: A, 2: B, 3: C, 4: D}


def _add(G, u, v, kind, length=None, grade=0.0, **extra):
    """Add a directed edge pair (u->v with +grade, v->u with -grade)."""
    length = length or haversine_m(*NODES[u], *NODES[v])
    for a, b, g in ((u, v, grade), (v, u, -grade)):
        G.add_edge(a, b, kind=kind, length=length, grade=g, grade_abs=abs(g), name=None, **extra)


@pytest.fixture
def toy_graph():
    """A -(stairs, short)- B, A -(elevator)- B, and a longer flat detour A-C-D-B.

        C ---- D
        |      |
        A ---- B     (A-B has parallel: stairs and elevator)
    """
    G = nx.MultiDiGraph()
    for n, (lat, lon) in NODES.items():
        G.add_node(n, y=lat, x=lon, elevation=0.0)
    _add(G, 1, 2, "steps", step_count=12)
    _add(G, 1, 2, "elevator", length=90.0)
    _add(G, 1, 3, "path")
    _add(G, 3, 4, "path")
    _add(G, 4, 2, "path")
    return G


@pytest.fixture
def steep_detour_graph(toy_graph):
    """Same as toy_graph but the detour's A->C leg is 8% grade."""
    for u, v in ((1, 3), (3, 1)):
        for d in toy_graph[u][v].values():
            d["grade"] = 8.0 if u == 1 else -8.0
            d["grade_abs"] = 8.0
    return toy_graph
