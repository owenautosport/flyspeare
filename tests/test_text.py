from flyspeare.text import tokenize, strip_gutenberg


def test_lowercases_and_splits_on_non_letters():
    words = tokenize("From fairest creatures, we-desire")
    assert [w.text for w in words] == ["from", "fairest", "creatures", "we", "desire"]


def test_apostrophes_split_words():
    words = tokenize("’Tis o'er beauty’s rose")
    assert [w.text for w in words] == ["tis", "o", "er", "beauty", "s", "rose"]


def test_spans_point_back_into_display_text():
    display = "  Pity the World, or else!"
    for w in tokenize(display):
        assert display[w.start:w.end].lower() == w.text


def test_accents_fold_and_unknown_letters_split():
    words = tokenize("Café æther naïve")
    assert [w.text for w in words] == ["cafe", "ther", "naive"]


def test_strip_gutenberg_starts_at_the_sonnets_body():
    raw = (
        "header junk\n*** START OF THE PROJECT GUTENBERG EBOOK X ***\n"
        "Title\n    Contents\n    THE SONNETS\n    HAMLET\n\nTHE SONNETS\n\n  1\n\nFrom fairest\n"
        "*** END OF THE PROJECT GUTENBERG EBOOK X ***\nlicence"
    )
    body = strip_gutenberg(raw)
    assert body.startswith("THE SONNETS")
    assert "licence" not in body and "Contents" not in body
