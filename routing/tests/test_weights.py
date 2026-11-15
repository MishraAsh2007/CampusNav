from app.routing.weights import ACCESSIBLE, STANDARD, Prefs, edge_cost, make_weight_fn

ACC = Prefs(ACCESSIBLE, 5.0, True)
STD = Prefs(STANDARD, 5.0, False)


def edge(kind="path", length=50.0, grade=0.0, **kw):
    return {"kind": kind, "length": length, "grade": grade, "grade_abs": abs(grade), **kw}


def test_standard_ignores_steps_and_grade():
    assert edge_cost(edge("steps"), STD) == 50.0
    assert edge_cost(edge(grade=15), STD) == 50.0


def test_accessible_blocks_steps():
    assert edge_cost(edge("steps"), ACC) is None


def test_accessible_can_allow_steps_with_penalty():
    cost = edge_cost(edge("steps"), Prefs(ACCESSIBLE, 5.0, avoid_steps=False))
    assert cost is not None and cost > 50.0 * 10


def test_grade_over_limit_is_blocked_both_directions():
    assert edge_cost(edge(grade=6.0), ACC) is None
    assert edge_cost(edge(grade=-6.0), ACC) is None  # downhill steepness counts too


def test_grade_limit_is_adjustable():
    e = edge(grade=6.0)
    assert edge_cost(e, Prefs(ACCESSIBLE, 8.0, True)) is not None
    assert edge_cost(e, Prefs(ACCESSIBLE, 5.0, True)) is None


def test_short_steep_edge_is_penalized_not_blocked():
    cost = edge_cost(edge(length=4.0, grade=12.0), ACC)  # likely DEM noise
    assert cost is not None and cost > 4.0


def test_cost_grows_as_grade_approaches_limit_and_never_below_length():
    flat = edge_cost(edge(grade=0.5), ACC)
    mild = edge_cost(edge(grade=4.0), ACC)
    near = edge_cost(edge(grade=4.9), ACC)
    assert flat == 50.0
    assert flat < mild < near
    assert near >= 50.0  # heuristic admissibility: cost >= length


def test_ground_truth_inaccessible_flag_blocks_accessible_only():
    e = edge(accessible=False)
    assert edge_cost(e, ACC) is None
    assert edge_cost(e, STD) == 50.0


def test_weight_fn_picks_cheapest_parallel_edge_and_respects_blocked():
    parallel = {0: edge("steps", 40.0), 1: edge("elevator", 90.0)}
    w = make_weight_fn(ACC, {})
    assert w(1, 2, parallel) == 90.0  # stairs impassable, elevator used
    assert make_weight_fn(ACC, {(1, 2, 1): {"c1"}})(1, 2, parallel) is None
    assert make_weight_fn(STD, {})(1, 2, parallel) == 40.0
