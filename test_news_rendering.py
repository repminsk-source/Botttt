import os

os.environ.setdefault("BOT_TOKEN", "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijk")

import bot


def test_news_excerpt_removes_markup_and_unescapes_text():
    value = bot.news_excerpt("<b>ЧАСТИЧНЫЙ УСПЕХ</b>: Россия &amp; Украина")
    assert value == "ЧАСТИЧНЫЙ УСПЕХ: Россия &amp; Украина"
    assert "<b>" not in value


def test_news_excerpt_truncates_on_word_boundary():
    value = bot.news_excerpt("слово " * 100, 40)
    assert value.endswith("…")
    assert len(value) <= 42
    assert not value[:-1].endswith(" ")


def test_news_excerpt_escapes_user_text():
    value = bot.news_excerpt("<script>alert(1)</script> <tag> текст")
    assert "<script>" not in value
    assert "alert(1)" in value


if __name__ == "__main__":
    test_news_excerpt_removes_markup_and_unescapes_text()
    test_news_excerpt_truncates_on_word_boundary()
    test_news_excerpt_escapes_user_text()
    print("NEWS_RENDERING_OK")
