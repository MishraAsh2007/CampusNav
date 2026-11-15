"""Portable JSON graph storage, separate from OSMnx's build-time dependencies."""

import json
import math
from pathlib import Path

import networkx as nx


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def save_graph(graph: nx.MultiDiGraph, path: Path) -> None:
    write_json(
        path,
        {
            "version": 1,
            "metadata": dict(graph.graph),
            "nodes": [{"id": n, **data} for n, data in graph.nodes(data=True)],
            "edges": [
                {"u": u, "v": v, "key": k, **data}
                for u, v, k, data in graph.edges(keys=True, data=True)
            ],
        },
    )


def load_graph(path: Path) -> nx.MultiDiGraph:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        raise ValueError("Unsupported graph format")
    graph = nx.MultiDiGraph(**payload["metadata"])
    for record in payload["nodes"]:
        record = dict(record)
        node_id = record.pop("id")
        graph.add_node(node_id, **record)
    for record in payload["edges"]:
        record = dict(record)
        u, v, key = (record.pop(field) for field in ("u", "v", "key"))
        if u not in graph or v not in graph:
            raise ValueError("Edge references a missing node")
        length, grade = record["length"], record.get("grade_percent")
        if not math.isfinite(length) or length <= 0:
            raise ValueError("Edge lengths must be finite and positive")
        if grade is not None and (not math.isfinite(grade) or grade < 0):
            raise ValueError("Grades must be nonnegative percentages or null")
        graph.add_edge(u, v, key=key, **record)
    if graph.number_of_edges() == 0:
        raise ValueError("Graph has no edges")
    return graph
