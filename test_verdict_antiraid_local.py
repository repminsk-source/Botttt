import asyncio
from types import SimpleNamespace

import ai
from anti_spam import AntiSpamMiddleware


def test_verdict_cards():
    action = ai._compose_action_verdict({
        "success": "partial",
        "headline": "Реформа запущена, но денег не хватило",
        "summary": "Инфраструктурная программа началась в крупных городах, однако масштаб пришлось сократить из-за слабой экономики.",
        "key_factors": ["Низкий бюджет ограничил охват", "Технологический уровень замедлил внедрение"],
        "risks": ["Дефицит бюджета сохранится"],
        "next_actions": ["Сначала укрепить доходы", "Затем расширить цифровую инфраструктуру"],
    })
    assert "ЧАСТИЧНЫЙ УСПЕХ" in action["verdict_text"]
    assert "Почему:" in action["verdict_text"]
    assert "Следующие шаги:" in action["verdict_text"]
    assert len(action["verdict_text"]) < 1400

    war = ai._compose_war_verdict({
        "outcome": "defender_win",
        "headline": "Атака остановлена на приграничном рубеже",
        "summary": "Оборона удержала ключевые позиции и сорвала темп наступления.",
        "key_factors": ["Подготовленные гарнизоны", "Лучшее снабжение обороны"],
        "risks": ["Обеим сторонам потребуется восстановление"],
        "next_actions": {"attacker": ["Отвести потрёпанные части"], "defender": ["Укрепить рубежи"]},
    })
    assert "ПОБЕДА ОБОРОНЯЮЩЕГОСЯ" in war["verdict_text"]
    assert "Атакующему:" in war["verdict_text"]
    assert "Обороняющемуся:" in war["verdict_text"]
    assert len(war["verdict_text"]) < 1400


class FakeEvent:
    def __init__(self, chat_id, user_id):
        self.chat = SimpleNamespace(id=chat_id, type="supergroup")
        self.from_user = SimpleNamespace(id=user_id)
        self.deleted = False

    async def delete(self):
        self.deleted = True


class FakeBot:
    async def get_chat_member(self, chat_id, user_id):
        return SimpleNamespace(status="member")


async def test_group_raid_gate():
    middleware = AntiSpamMiddleware()
    data = {"bot": FakeBot()}
    events = [FakeEvent(-100, user_id) for user_id in range(1, 6)]
    allowed = []
    for event in events:
        allowed.append(await middleware._group_raid_gate(event, data, event.from_user.id))
    assert allowed[:4] == [True, True, True, True]
    assert allowed[4] is False
    assert events[4].deleted is True


if __name__ == "__main__":
    test_verdict_cards()
    asyncio.run(test_group_raid_gate())
    print("VERDICT_FORMAT_OK")
    print("GROUP_ANTIRAID_OK")
