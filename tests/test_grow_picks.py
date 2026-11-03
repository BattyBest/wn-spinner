import types

from wn.api.routes import novels as routes
from wn.learner.coverage import NovelFit


def fit(coverage, money=0.0):
    return NovelFit(coverage, 1000, 10, 2, {"money": money} if money else {})


def test_one_slot_in_five_goes_to_a_grow_pick(monkeypatch):
    monkeypatch.setattr(routes, "domain_strengths", lambda *_: [])
    monkeypatch.setattr(routes, "weakest_domain", lambda _s: "money")
    rows = [{"id": i, "points": 100 - i, "status": "ongoing"} for i in range(10)]
    rows += [{"id": 100 + i, "points": 1, "status": "ongoing"} for i in range(2)]
    fits = {i: fit(0.965 - i * 0.002) for i in range(10)}  # all in the stretch band
    fits[100] = fit(0.99, money=30)  # comfortable, money-heavy
    fits[101] = fit(0.99, money=60)  # comfortable, even more money-heavy
    ordered = routes._rank_for_me(
        types.SimpleNamespace(catalog=None, learner=None), rows, fits, None, best=True
    )

    assert len(ordered) == 12
    grow = [i for i, (_row, is_grow) in enumerate(ordered) if is_grow]
    assert grow == [4, 9]  # every fifth slot
    assert [ordered[i][0]["id"] for i in grow] == [101, 100]  # most money-heavy first
    plain = [row["id"] for row, is_grow in ordered if not is_grow]
    assert plain == sorted(plain)  # the rest stay in score order


def test_without_a_tested_weak_domain_there_are_no_grow_picks(monkeypatch):
    monkeypatch.setattr(routes, "domain_strengths", lambda *_: [])
    monkeypatch.setattr(routes, "weakest_domain", lambda _s: None)
    rows = [{"id": i, "points": 1, "status": "ongoing"} for i in range(6)]
    fits = {i: fit(0.97) for i in range(6)}
    ordered = routes._rank_for_me(
        types.SimpleNamespace(catalog=None, learner=None), rows, fits, None, best=True
    )
    assert not any(is_grow for _row, is_grow in ordered) and len(ordered) == 6
