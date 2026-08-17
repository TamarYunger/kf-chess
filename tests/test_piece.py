from board.piece import Color, Kind, Piece, color_of, kind_of, make_piece


def test_piece_color_is_a_color_enum_member():
    assert Piece.from_token("wK").color is Color.WHITE
    assert Piece.from_token("bK").color is Color.BLACK


def test_piece_kind_is_a_kind_enum_member_for_a_standard_kind():
    assert Piece.from_token("wK").kind is Kind.KING
    assert Piece.from_token("bP").kind is Kind.PAWN


def test_piece_compares_and_hashes_equal_to_its_plain_token():
    # A Piece must drop straight into every existing string comparison,
    # dict key, and JSON payload unchanged - see board/piece.py's own
    # docstring for why __eq__/__hash__/__str__ are overridden.
    piece = Piece.from_token("wK")
    assert piece == "wK"
    assert {piece: "value"}["wK"] == "value"
    assert str(piece) == "wK"


def test_color_of_returns_a_color_enum_member_equal_to_the_letter():
    color = color_of("wK")
    assert color is Color.WHITE
    assert color == "w"  # still compares equal to the plain letter


def test_kind_of_returns_a_kind_enum_member_for_a_standard_kind():
    assert kind_of("wK") is Kind.KING


def test_kind_of_is_not_restricted_to_the_standard_six_kinds():
    # Kind is a closed Enum, but kind_of falls back to the raw letter for
    # anything it doesn't recognise - a custom piece kind (registered with
    # rules.rule_registry.PieceRuleRegistry) must still round-trip through
    # kind_of instead of raising.
    assert kind_of("wC") == "C"


def test_make_piece_returns_a_piece_with_the_expected_color_and_kind():
    piece = make_piece("w", "Q")
    assert piece == "wQ"
    assert piece.color is Color.WHITE
    assert piece.kind is Kind.QUEEN


def test_make_piece_accepts_an_existing_color_enum_member():
    piece = make_piece(Color.BLACK, "R")
    assert piece == "bR"


def test_make_piece_with_a_custom_kind_falls_back_to_the_raw_letter():
    piece = make_piece("w", "C")
    assert piece == "wC"
    assert piece.kind == "C"


def test_piece_is_not_equal_to_an_unrelated_type():
    assert Piece.from_token("wK") != 5
