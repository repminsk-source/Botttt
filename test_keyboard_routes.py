from pathlib import Path


SOURCE = Path(__file__).with_name("bot.py").read_text(encoding="utf-8")

MAIN_LABELS = ["📊 Страна", "📥 Сбор", "🏗️ Строить", "⚔️ Армия", "📈 Прогресс", "☰ Ещё"]
MORE_LABELS = ["📰 Новости", "🌍 Рейтинг", "🏛️ Политика", "🤝 Дипломатия", "🏴 ЧВК", "📖 Помощь", "⬅️ Назад"]


def test_all_visible_buttons_have_routes():
    for label in MAIN_LABELS + MORE_LABELS:
        assert label in SOURCE, f"button label missing from bot.py: {label}"
    expected_handler_fragments = [
        'F.text.in_({"📊 Моя страна", "📊 Страна"})',
        'F.text.in_({"📥 Собрать ресурсы", "📥 Сбор"})',
        'F.text.in_({"🏗️ Построить", "🏗️ Строить"})',
        'F.text == "⚔️ Армия"',
        'F.text == "📈 Прогресс"',
        'F.text == "☰ Ещё"',
        'F.text == "📰 Новости"',
        'F.text == "🌍 Рейтинг"',
        'F.text == "🏛️ Политика"',
        'F.text == "🤝 Дипломатия"',
        'F.text.in_({"📖 Что делать?", "📖 Помощь"})',
        'F.text == "⬅️ Назад"',
    ]
    for fragment in expected_handler_fragments:
        assert fragment in SOURCE, f"handler route missing: {fragment}"


def test_unknown_text_restores_menu():
    assert '@dp.message(F.text)' in SOURCE
    assert 'reply_markup=MAIN_INLINE' in SOURCE


if __name__ == "__main__":
    test_all_visible_buttons_have_routes()
    test_unknown_text_restores_menu()
    print("KEYBOARD_ROUTES_OK")
