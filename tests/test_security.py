from app.security import is_dictionary_word, validate_password_strength


def test_rejects_short_passwords():
    ok, reason = validate_password_strength("Ab1!")
    assert not ok
    assert "10 characters" in reason


def test_rejects_passwords_missing_a_character_class():
    ok, _ = validate_password_strength("alllowercase1!")
    assert not ok

    ok, _ = validate_password_strength("ALLUPPERCASE1!")
    assert not ok

    ok, _ = validate_password_strength("NoDigitsHere!!")
    assert not ok

    ok, _ = validate_password_strength("NoSpecialChars1")
    assert not ok


def test_rejects_plain_dictionary_word_passwords():
    ok, reason = validate_password_strength("Password1!")
    assert not ok
    assert "dictionary" in reason


def test_rejects_dictionary_word_with_decorated_edges():
    # "summer" wrapped in digits/symbols should still be caught.
    ok, _ = validate_password_strength("Summer2025!")
    assert not ok


def test_accepts_a_strong_non_dictionary_password():
    ok, reason = validate_password_strength("Xk7!qzWvLp9Q")
    assert ok
    assert reason is None


def test_is_dictionary_word_matches_case_insensitively():
    assert is_dictionary_word("Cucumber")
    assert is_dictionary_word("CUCUMBER99")
    assert not is_dictionary_word("Xk7qzWvLp9Q")
