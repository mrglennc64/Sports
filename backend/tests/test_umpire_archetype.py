from app.data.umpire_archetype import TakenPitch, aggregate_csr

PITCHES = [
    # ump A, breaking-heavy pitcher: 2 called strikes, 1 ball -> CSR 0.667
    TakenPitch(umpire="A", archetype="breaking_heavy", called_strike=True),
    TakenPitch(umpire="A", archetype="breaking_heavy", called_strike=True),
    TakenPitch(umpire="A", archetype="breaking_heavy", called_strike=False),
    # ump B, breaking-heavy: 0 of 2 -> CSR 0.0
    TakenPitch(umpire="B", archetype="breaking_heavy", called_strike=False),
    TakenPitch(umpire="B", archetype="breaking_heavy", called_strike=False),
    # ump A, power: 1 of 1
    TakenPitch(umpire="A", archetype="power", called_strike=True),
]


def test_aggregate_counts_and_rates():
    table = aggregate_csr(PITCHES)
    cell = table["A"]["breaking_heavy"]
    assert cell["taken"] == 3
    assert abs(cell["csr"] - 2 / 3) < 1e-9


def test_league_mean_and_delta():
    table = aggregate_csr(PITCHES)
    # league breaking_heavy CSR = 2/5 = 0.4 ; ump A delta = 0.667-0.4
    assert abs(table["A"]["breaking_heavy"]["delta_vs_league"] - (2 / 3 - 0.4)) < 1e-9
    assert abs(table["B"]["breaking_heavy"]["delta_vs_league"] - (0.0 - 0.4)) < 1e-9


def test_min_sample_flag():
    table = aggregate_csr(PITCHES, min_taken=5)
    assert table["A"]["breaking_heavy"]["reliable"] is False
