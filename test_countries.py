import countries


def test_common_entries_match():
    assert countries.match_country("Тайвань") == "Тайвань"
    assert countries.match_country("Taiwan") == "Тайвань"
    assert countries.match_country("китайская республика") == "Тайвань"
    assert countries.match_country("Косово") == "Косово"
    assert countries.match_country("kosovo") == "Косово"


def test_normalization_and_unknowns():
    assert countries.match_country("  тайвань  ") == "Тайвань"
    assert countries.match_country("Несуществующая страна") is None


if __name__ == "__main__":
    test_common_entries_match()
    test_normalization_and_unknowns()
    print("COUNTRY_MATCHING_OK")
