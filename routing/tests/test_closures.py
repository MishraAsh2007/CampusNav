from datetime import datetime, timedelta, timezone

import pytest

from app.routing.closures import resolve_closures
from app.routing.weights import ACCESSIBLE, STANDARD
from app.schemas import Closure

MID_AB = (42.3900, -72.5295)  # midpoint of the A-B edges
MID_CD = (42.3905, -72.5295)  # midpoint of the detour's C-D edge


def closure(id, type, point=MID_AB, radius=10, **kw):
    return Closure(id=id, type=type, lat=point[0], lon=point[1], radius_m=radius, **kw)


def kinds(G, blocked):
    return {G[u][v][k]["kind"] for (u, v, k) in blocked}


def test_elevator_out_blocks_only_elevator_edges_for_accessible(toy_graph):
    idx = resolve_closures(toy_graph, [closure("e1", "elevator_out")])
    assert kinds(toy_graph, idx.blocked_for(ACCESSIBLE)) == {"elevator"}
    assert idx.blocked_for(STANDARD) == {}  # stairs users are unaffected


def test_construction_blocks_everyone(toy_graph):
    idx = resolve_closures(toy_graph, [closure("c1", "construction")])
    assert kinds(toy_graph, idx.blocked_for(STANDARD)) == {"steps", "elevator"}
    assert kinds(toy_graph, idx.blocked_for(ACCESSIBLE)) == {"steps", "elevator"}


def test_ramp_blocked_falls_back_to_any_edge_when_no_ramp_mapped(toy_graph):
    idx = resolve_closures(toy_graph, [closure("r1", "ramp_blocked", point=MID_CD)])
    assert kinds(toy_graph, idx.blocked_for(ACCESSIBLE)) == {"path"}
    assert idx.blocked_for(STANDARD) == {}


def test_radius_limits_the_blast(toy_graph):
    far = (42.3910, -72.5295)
    idx = resolve_closures(toy_graph, [closure("far", "construction", point=far, radius=10)])
    assert idx.blocked_for(ACCESSIBLE) == {}
    assert idx.applied_for(ACCESSIBLE)[0].edges_blocked == 0  # reported, so the demo never fails silently


def test_edge_ids_block_both_directions(toy_graph):
    c = Closure(id="e", type="path_closed", edge_ids=["3_4"])
    idx = resolve_closures(toy_graph, [c])
    assert {(u, v) for (u, v, _k) in idx.blocked_for(STANDARD)} == {(3, 4), (4, 3)}


def test_expired_closures_are_ignored_and_counted(toy_graph):
    now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    old = closure("old", "construction", expires_at=now - timedelta(hours=1))
    live = closure("live", "construction", expires_at=now + timedelta(hours=1))
    idx = resolve_closures(toy_graph, [old, live], now=now)
    assert (idx.active_count, idx.expired_count) == (1, 1)
    assert {a.id for a in idx.applied_for(STANDARD)} == {"live"}


def test_naive_expiry_is_treated_as_utc(toy_graph):
    now = datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
    c = closure("naive", "construction", expires_at=datetime(2026, 11, 13, 11, 0))
    assert resolve_closures(toy_graph, [c], now=now).expired_count == 1


def test_last_confirmed_uses_newest_blocking_closure(toy_graph):
    t1 = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 11, 13, 11, 0, tzinfo=timezone.utc)
    cs = [
        closure("a", "elevator_out", confirmed_at=t1),
        closure("b", "elevator_out", confirmed_at=t2),
    ]
    assert resolve_closures(toy_graph, cs).last_confirmed(ACCESSIBLE) == t2


def test_closure_requires_a_location():
    with pytest.raises(ValueError):
        Closure(id="x", type="construction")
