"""Симулятор баланса боёв: python tools/balance_sim.py

Прогоняет по 150 боёв на каждый класс/уровень/набор экипировки и печатает процент побед,
длину боя и потерю здоровья. Крути числа в bot/services/formulas.py и bot/data/balance.py
и смотри, как меняется кривая сложности.
"""
import sys, random, statistics as S
sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(__import__("os").path.abspath(__file__))))
from bot.services import combat, formulas, items as it
from bot.data.monsters import LOCATIONS

def gear_stats(cls, level, rarities):
    st = formulas.base_stats(cls, level); rng = random.Random(level)
    for slot, r in zip(("weapon","armor","ring","amulet"), rarities):
        i = it.roll_item(level, rarity=r, slot=slot, rng=rng)
        st["atk"] += i["atk"]; st["def"] += i["def"]; st["hp"] += i["hp"]
    return st

def fight(cls, level, loc, boss, st, rng):
    p = {"user_id":1,"level":level,"cls":cls,"potions":3}
    s = combat.new_state(p, st, loc, boss, rng)
    for _ in range(300):
        if s["done"]: break
        if s["p"]["hp"] < s["p"]["max"]*0.35 and s["potions_have"]-s["potions_used"]>0: act="potion"
        elif s["cd"]==0: act="skill"
        else: act="attack"
        combat.step(s, act, rng)
    return s["done"]=="win", s["round"], 1 - max(0, s["p"]["hp"])/s["p"]["max"], s["potions_used"]

N=150
gears = {"слабая":("common","common","common","common"), "средняя":("rare","uncommon","uncommon","common"), "хорошая":("epic","rare","rare","rare")}
print("          |   ОБЫЧНЫЙ БОЙ: победы / раундов / потеряно HP |   БОСС: победы / раундов / зелий")
for loc in LOCATIONS[:5]:
    lv = [loc["min"], min(loc["max"], loc["min"]+9)]
    for level in lv:
        for gname, gset in gears.items():
            nw=[];nr=[];nl=[];bw=[];br=[];bp=[]
            for cls in ("warrior","mage","rogue"):
                st = gear_stats(cls, level, gset); rng = random.Random(level*13+len(cls))
                for _ in range(N):
                    w,r,l,_ = fight(cls, level, loc["key"], False, st, rng); nw.append(w); nr.append(r); nl.append(l)
                    w,r,_,pu = fight(cls, level, loc["key"], True, st, rng); bw.append(w); br.append(r); bp.append(pu)
            print(f"{loc['key']:7}{level:3d} {gname:8}| {100*sum(nw)//len(nw):3d}%  {S.mean(nr):5.1f} р.  -{100*S.mean(nl):3.0f}% HP        | {100*sum(bw)//len(bw):3d}%  {S.mean(br):5.1f} р.  {S.mean(bp):.1f}")
