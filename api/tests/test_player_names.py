from app.services.player_names import complexity


def test_plain_beats_decorated():
    assert complexity("Northwar") < complexity("Anemo main")  # a space
    assert complexity("rozax") < complexity("RozaX")  # a capital after a small letter
    assert complexity("koshmar") < complexity("koshmar.3")
    assert complexity("DzeN") < complexity("😈DzeN😈")


def test_all_caps_and_capitalized_are_plain():
    assert complexity("KOSHMAR") == complexity("koshmar") == complexity("Koshmar") == 0


def test_length_doesnt_count():
    assert complexity("ab") == complexity("abcdefgh")


def test_surrounding_spaces_count():
    assert complexity(" peudan") > complexity("peudan")
