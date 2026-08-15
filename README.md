# ВПИ ГАВАНЬ

Telegram-бот для геополитической стратегии и RP. Игрок основывает реальную страну, развивает экономику и инфраструктуру, собирает ресурсы, мобилизует армию, вступает в альянсы, заключает торговые договоры и получает подробные вердикты ИИ по действиям и войнам.

## Быстрый запуск

Установите зависимости и скопируйте шаблон окружения:

```bash
pip install -r requirements.txt
cp .env.example .env
python bot.py
```

В `.env` обязательны `BOT_TOKEN`, `ADMIN_IDS` и `OLLAMA_API_KEY`, если используется Ollama Cloud. Основной режим по умолчанию — `AI_PROVIDER=ollama`, модель — `gpt-oss:20b-cloud`, адрес — `https://ollama.com/v1`.

## Игровой цикл

После `/start` игрок выполняет `/founding Название`. Затем интерфейс ведёт его через четыре базовых шага: открыть страну, выполнить первый сбор, построить ферму или шахту и открыть прогресс. Первый успешный `/collect` выдаёт одноразовый стартовый бонус денег. Дальше сбор работает по таймеру, а производство зависит от зданий и национальной политики.

Кнопки интерфейса работают через inline callbacks, поэтому основные разделы доступны и в группах. Для каждого игрока бот хранит последнее интерфейсное сообщение и старается удалить старую карточку при переходе на новую. Если у бота нет права удаления, игра продолжает работать без падения.

## Основные команды

| Раздел | Команды |
|---|---|
| Страна | `/founding`, `/country`, `/progress`, `/top`, `/history`, `/myid` |
| Экономика | `/collect`, `/build`, `/upgrade`, `/market`, `/buy`, `/policy` |
| Армия и войны | `/mobilize`, `/build_base`, `/spy`, `/action`, `/attack`, `/wars` |
| Дипломатия | `/alliances`, `/alliance_create`, `/alliance_join`, `/alliance_leave`, `/alliance_info` |
| Торговля и мир | `/trade`, `/trade_offer`, `/trade_accept`, `/trade_reject`, `/world`, `/news`, `/year` |
| Помощь | `/help`, `/guide` |

Подробная подсказка доступна через `/help`. В группах можно использовать форму `/команда@имя_бота`.

## AI и безопасность

Пользовательские описания действий передаются модели как данные, а не как инструкции. Ответ модели извлекается из JSON, изменения характеристик ограничиваются кодом, HTML-опасные значения экранируются, а ошибки провайдера очищаются от API-ключей. При `AI_PROVIDER=ollama` бот не переключается самовольно на другой сервис; резервный режим включается отдельно значением `AI_PROVIDER=fallback`.

## Render

Для polling-бота используется **Background Worker**. Blueprint подхватывает `render.yaml`; вручную укажите `pip install -r requirements.txt` как build command и `python bot.py` как start command. Добавьте `BOT_TOKEN`, `ADMIN_IDS` и `OLLAMA_API_KEY`. SQLite-файл на бесплатном Render не является надёжным постоянным хранилищем: для реального сервера нужен Persistent Disk или перенос базы на внешнюю PostgreSQL-инфраструктуру.

## Проверка перед деплоем

```bash
python3 check_handlers.py
python3 test_command_registry.py
python3 test_keyboard_dispatch.py
python3 test_keyboard_routes.py
python3 test_config_edge_cases.py
python3 test_message_cleanup.py
python3 test_world_trade.py
python3 test_stats.py
python3 test_antispam.py
python3 test_ai_safety.py
python3 playtest_beginner.py
python3 playtest_advanced.py
python3 -m py_compile *.py
```

Все тесты должны завершаться сообщениями `OK`, а `git diff --check` не должен находить ошибок форматирования.
