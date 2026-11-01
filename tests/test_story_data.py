"""Проверка целостности сюжетных данных: переходы, достижимость финалов, длина текста, флаги."""
import random

import pytest

from bot.data.story import CHAPTERS, CHECK_DIVISORS
from bot.emoji import EMOJI
from bot.handlers.story import _node_view
from bot.services import story as story_svc

CLASSES = ("warrior", "mage", "rogue")


def _targets(choice):
    if "check" in choice:
        return [choice["check"]["win"], choice["check"]["lose"]]
    return [choice["goto"]]


@pytest.mark.parametrize("ch", sorted(CHAPTERS))
def test_chapter_graph(ch):
    meta = CHAPTERS[ch]
    nodes = meta["nodes"]
    assert meta["start"] in nodes
    seen, stack = set(), [meta["start"]]
    while stack:
        nid = stack.pop()
        if nid in seen:
            continue
        seen.add(nid)
        node = nodes[nid]
        if node.get("end"):
            assert not node.get("choices") and node.get("reward"), f"{ch}/{nid}: у финала нет награды или есть выборы"
            continue
        assert node.get("choices"), f"{ch}/{nid}: тупик без выбора"
        for c in node["choices"]:
            for t in _targets(c):
                assert t in nodes, f"{ch}/{nid}: переход в несуществующий узел {t!r}"
                stack.append(t)
            if "check" in c:
                assert c["check"]["stat"] in CHECK_DIVISORS
    assert seen == set(nodes), f"глава {ch}: недостижимые узлы {set(nodes) - seen}"
    assert any(nodes[n].get("end") for n in seen)


def test_flags_are_set_before_being_required():
    """Любой флаг из req.flag где-то выставляется (иначе вариант недоступен всегда)."""
    set_flags, needed = set(), set()
    for meta in CHAPTERS.values():
        for node in meta["nodes"].values():
            for c in node.get("choices", []):
                f = (c.get("fx") or {}).get("flag")
                if f:
                    set_flags.add(f)
                r = (c.get("req") or {})
                needed |= {r[k] for k in ("flag", "noflag") if k in r}
    assert needed <= set_flags, f"флаги без источника: {needed - set_flags}"


@pytest.mark.parametrize("ch", sorted(CHAPTERS))
def test_text_fits_caption(ch):
    """Подпись к картинке ограничена 1024 символами: берём худший случай — самый длинный префикс с броском и наградой."""
    EMOJI.custom.clear()
    worst_prefix = ("🎲 d20: 20 + 30 = <b>50</b> против 30 — <b>Успех!</b>\n\n"
                    "<i>Получено: 🪙 +100000 ⭐ +100000 💎 +100 🔮 +1000 🧪 +10\n🎁 Эпический предмет с длинным названием</i>\n\n")
    p = {"cls": "mage", "level": 99, "story": "{}"}
    for nid, node in CHAPTERS[ch]["nodes"].items():
        text, _ = _node_view(p, ch, node, worst_prefix)
        assert len(text) <= 1024, f"{ch}/{nid}: {len(text)} символов"
        if node.get("end"):  # финал: текст + награда за главу
            assert len(text) + 260 <= 1100, f"{ch}/{nid}: финал слишком длинный"


def test_all_chapters_completable_by_random_walk(db):
    """Случайные прохождения всех глав на всех классах доходят до финала без ошибок."""
    from .conftest import make_player, run

    async def go():
        for cls in CLASSES:
            uid = {"warrior": 1, "mage": 2, "rogue": 3}[cls]
            await make_player(db, uid, cls=cls, level=70)
            rng = random.Random(uid)
            for ch in sorted(CHAPTERS):
                for _ in range(3):  # несколько разных маршрутов
                    assert (await story_svc.start_chapter(db, uid, ch))["ok"] or ch > 1
                    for _step in range(80):
                        from bot.services import players
                        p = await players.get(db, uid)
                        cur = story_svc.current(p)
                        if cur is None:
                            break
                        _c, _n, node = cur
                        vis = [i for i, c in enumerate(node["choices"]) if story_svc.choice_visible(c, p)]
                        assert vis, f"{cls} застрял в {ch}/{_n}"
                        res = await story_svc.choose(db, uid, rng.choice(vis), rng)
                        assert res["ok"]
                    else:
                        raise AssertionError(f"{cls}: глава {ch} не закончилась за 80 шагов")

    run(go())
