from app.model.selection import input_completeness, select_card


def _row(pitcher, edge, *, game_pk, bet=True, kelly=0.03, completeness=1.0):
    return {
        "pitcher": pitcher,
        "edge": edge,
        "kelly": kelly,
        "bet": bet,
        "game_pk": game_pk,
        "completeness": completeness,
    }


def test_completeness_weights():
    assert input_completeness(starts_ok=True, has_umpire=True, has_whiff=True, has_pitch_mix=True) == 1.0
    assert input_completeness(starts_ok=False, has_umpire=False, has_whiff=False, has_pitch_mix=False) == 0.0
    # starts alone clears the default 0.5 gate; every enricher without starts does not.
    assert input_completeness(starts_ok=True, has_umpire=False, has_whiff=False, has_pitch_mix=False) >= 0.5
    assert input_completeness(starts_ok=False, has_umpire=True, has_whiff=True, has_pitch_mix=True) < 0.5


def test_picks_top_edges_capped_at_max_bets():
    rows = [
        _row("A", 0.18, game_pk=1),
        _row("B", 0.15, game_pk=2),
        _row("C", 0.12, game_pk=3),
        _row("D", 0.09, game_pk=4),
        _row("E", 0.07, game_pk=5),
    ]
    card = select_card(rows, max_bets=4)
    assert [r["pitcher"] for r in card] == ["A", "B", "C", "D"]
    assert [r["card_rank"] for r in card] == [1, 2, 3, 4]
    assert rows[-1]["selected"] is False
    assert "card full" in rows[-1]["card_excluded"]


def test_caps_implausible_high_edge():
    rows = [_row("Huge", 0.30, game_pk=1), _row("Sane", 0.12, game_pk=2)]
    card = select_card(rows, max_bets=4, max_edge=0.20)
    assert [r["pitcher"] for r in card] == ["Sane"]
    assert "above cap" in rows[0]["card_excluded"]


def test_excludes_below_floor():
    rows = [_row("Low", 0.04, game_pk=1), _row("Ok", 0.08, game_pk=2)]
    card = select_card(rows, min_edge=0.05)
    assert [r["pitcher"] for r in card] == ["Ok"]
    assert "below select floor" in rows[0]["card_excluded"]


def test_diversifies_one_bet_per_game():
    rows = [
        _row("A", 0.18, game_pk=1),
        _row("B", 0.15, game_pk=1),  # same game as A — should be skipped
        _row("C", 0.12, game_pk=2),
    ]
    card = select_card(rows, max_bets=4, max_per_game=1)
    assert [r["pitcher"] for r in card] == ["A", "C"]
    assert "game already has" in rows[1]["card_excluded"]


def test_max_per_game_allows_two_when_raised():
    rows = [
        _row("A", 0.18, game_pk=1),
        _row("B", 0.15, game_pk=1),
        _row("C", 0.12, game_pk=2),
    ]
    card = select_card(rows, max_bets=4, max_per_game=2)
    assert [r["pitcher"] for r in card] == ["A", "B", "C"]


def test_completeness_gate_excludes_thin_inputs():
    rows = [
        _row("Thin", 0.18, game_pk=1, completeness=0.3),
        _row("Full", 0.10, game_pk=2, completeness=1.0),
    ]
    card = select_card(rows, min_completeness=0.5)
    assert [r["pitcher"] for r in card] == ["Full"]
    assert "inputs incomplete" in rows[0]["card_excluded"]


def test_ignores_non_bet_rows():
    rows = [_row("NotBet", 0.18, game_pk=1, bet=False), _row("Bet", 0.10, game_pk=2)]
    card = select_card(rows)
    assert [r["pitcher"] for r in card] == ["Bet"]
    assert rows[0]["selected"] is False
    assert "card_excluded" not in rows[0]  # non-bets aren't "excluded", just not bets
