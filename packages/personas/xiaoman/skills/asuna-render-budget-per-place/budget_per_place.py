#!/usr/bin/env python3
"""asuna-render-budget-per-place 的账：随身层每一节，在各场合各占多少。

口径（与程序卡预算的口径一致，不自己发明）：

1. 对家里／线／群／私聊各渲染一份（`visibility.PLACE_CLASS`）；
2. 每一节的数 = 那份渲染去掉这一节少多少（同一节在不同场合可以不同，甚至 0）；
3. 预算卡的是几个场合里**最大的那份**（`render.largest`／`render.render_status`）；
4. 所以放掉一节真正腾出来的是「最大那份 − 去掉它之后最大的那份」——
   放掉只出现在一个场合的节，最大那份会换成另一个场合，可能只腾几格。

只读：读库里的 persona／voice，不写任何东西。

用法：
    python3 budget_per_place.py                  # 四个场合的整份渲染 + 每节的账 + 放掉每节能腾多少
    python3 budget_per_place.py --top 12         # 只列最大的 12 节
    python3 budget_per_place.py --drop persona#某节sid   # 只算「放掉这一节」之后最大那份变成多少
退出码 0 = 账跑出来了（超没超预算写在输出里，不是退出码）。
"""
import argparse
import copy
import os
import re
import sys

PLACE_CN = {"home": "家里", "peer": "线", "group": "群", "dm": "私聊"}


def find_persona(db):
    """库里的 persona 名：从 doc:<persona>:persona 那一格读，别照抄记忆。"""
    from asuna.documents import SCOPE
    for row in db.state_heads.find({"_id": {"$regex": "^doc:"}}, {"_id": 1}):
        match = re.match(r"^doc:([^:]+):persona\|", row["_id"])
        if match and row["_id"].endswith("|" + SCOPE):
            return match.group(1)
    return None


def content_of(db, persona, slug):
    from asuna.documents import SCOPE
    head = db.state_heads.find_one({"_id": "doc:%s:%s|%s" % (persona, slug, SCOPE)})
    if not head:
        return None
    revision = db.state_revisions.find_one({"_id": head["revision_id"]})
    return (revision or {}).get("content")


def store_for_limit():
    """算上限要一个 store：宿主给的库优先，没有就读检出的 config/local.json（和 dbread 同一条退路）。

    返回 (store, 说明)。上限取 max(budget_tokens, 包里种子渲染 ×1.25)，
    这份 config 读不到 persona_contribution 时，种子那一格算不出来——输出里照实写。
    """
    from asuna import state
    uri, name = os.environ.get("ASUNA_MONGO_URI"), os.environ.get("ASUNA_DATABASE")
    if uri and name:
        config = {"mongo_uri": uri, "database": name, "allowed_databases": [name]}
    else:
        from asuna.config import ROOT, load
        config = load(ROOT / "config" / "local.json")
    try:
        return state.Store(config), None
    except Exception as exc:                           # noqa: BLE001 建不了 store 就没上限
        return None, "%s: %s" % (type(exc).__name__, exc)


def main():
    parser = argparse.ArgumentParser(description="随身层每节在各场合占多少（只读）")
    parser.add_argument("--persona", help="默认从 state_heads 里找")
    parser.add_argument("--top", type=int, help="只列最大的几节")
    parser.add_argument("--drop", help="只算这一节：写成 slug#sid，看放掉它之后最大那份是多少")
    args = parser.parse_args()

    from asuna import dbread, render, visibility

    db = dbread._default().db
    persona = args.persona or find_persona(db)
    if not persona:
        print("state_heads 里没有 doc:<persona>:persona——不知道给谁算。带 --persona 再跑。")
        return 1
    docs = {slug: content_of(db, persona, slug) for slug in ("persona", "voice")}
    if not docs["persona"]:
        print("读不到「%s」的 persona 文档。" % persona)
        return 1
    print("persona =", persona)
    print("随身层：persona %d 节、voice %d 节（inject=always 才算随身）"
          % (len((docs["persona"] or {}).get("sections") or []),
             len((docs["voice"] or {}).get("sections") or [])))

    common = render.common_text({})            # prompt_path 不看 config
    places = list(visibility.PLACE_CLASS.items())

    def tokens(place, cls, drop=None):
        """drop = (slug, sid)：把这一节从文档里拿掉再渲染这个场合。"""
        parts = {}
        for slug, content in docs.items():
            if content is None:
                parts[slug] = None
                continue
            kept = copy.deepcopy(content)
            if drop and drop[0] == slug:
                kept["sections"] = [s for s in kept["sections"] if s["sid"] != drop[1]]
            parts[slug] = kept
        return render.estimate_tokens(render.compose(common, parts["persona"], parts["voice"], cls, place))

    full = {place: tokens(place, cls) for place, cls in places}
    largest_place = max(full, key=full.get)

    # 上限：policy 存储 > persona-model 默认 > 核默认（render.budget_tokens），再和种子渲染 ×1.25 取大
    limit, limit_note, seed_note = None, "", ""
    store, problem = store_for_limit()
    if store is None:
        limit_note = "（上限没算出来：%s）" % problem
    else:
        try:
            limit = render.budget_limit(store, persona)
            if not render.seed_estimate(store, persona):
                seed_note = "，种子那一格读不到（这份 config 没有 persona_contribution），界面那格可能比这里高"
        except Exception as exc:                       # noqa: BLE001 拿不到上限也要给账
            limit_note = "（上限没算出来：%s: %s）" % (type(exc).__name__, exc)

    print("\n各场合整份渲染（token）：")
    for place, cls in places:
        mark = "   <= 预算卡的是这份" if place == largest_place else ""
        print("  %-6s %-16s %6d%s" % (PLACE_CN.get(place, place), place + "/" + cls, full[place], mark))
    print("  上限 %s %s%s%s" % (limit, "超了" if limit and full[largest_place] > limit else "没超",
                                limit_note, seed_note))

    always = [(slug, s) for slug in ("persona", "voice")
              for s in ((docs[slug] or {}).get("sections") or []) if s.get("inject") == "always"]

    rows = []
    for slug, section in always:
        drop = (slug, section["sid"])
        deltas = {place: full[place] - tokens(place, cls, drop) for place, cls in places}
        seen = [place for place in full if deltas[place]]
        after = max(tokens(place, cls, drop) for place, cls in places)
        rows.append({"slug": slug, "sid": section["sid"], "heading": section.get("heading") or "",
                     "visibility": section.get("visibility"), "places": visibility.section_places(section),
                     "deltas": deltas, "seen": seen, "largest_after": after,
                     "freed": full[largest_place] - after})

    if args.drop:
        try:
            want_slug, want_sid = args.drop.split("#", 1)
        except ValueError:
            print("--drop 写成 slug#sid")
            return 1
        hit = [row for row in rows if row["slug"] == want_slug and row["sid"] == want_sid]
        if not hit:
            print("%s 不在随身层里（inject 不是 always，或 sid 抄错了）" % args.drop)
            return 1
        row = hit[0]
        print("\n放掉 %s#%s（%s）之后：" % (row["slug"], row["sid"], row["heading"][:30]))
        for place, cls in places:
            print("  %-6s %6d -> %6d" % (PLACE_CN.get(place, place), full[place],
                                         tokens(place, cls, (row["slug"], row["sid"]))))
        print("  最大那份：%d -> %d，真正腾出来 %d（这一节本身占 %d）"
              % (full[largest_place], row["largest_after"], row["freed"], max(row["deltas"].values())))
        return 0

    print("\n每一节的账（数 = 那份渲染去掉这一节少多少）")
    print("%-36s %-16s %-14s %s   %s" % ("节", "可见／场合", "在哪出现",
                                        " ".join("%6s" % PLACE_CN.get(p, p) for p, _ in places), "放掉它腾多少"))
    ordered = sorted(rows, key=lambda row: -max(row["deltas"].values()))
    if args.top:
        ordered = ordered[:args.top]
    for row in ordered:
        tag = row["visibility"] or ""
        if row["places"]:
            tag += "/" + ",".join(row["places"])
        where = "、".join(PLACE_CN.get(p, p) for p in row["seen"]) or "哪都不在"
        print("%-36s %-16s %-14s %s   %5d（这节本身 %d）"
              % ((row["slug"] + "#" + row["sid"])[:36], tag, where,
                 " ".join("%6d" % row["deltas"][place] for place, _ in places),
                 row["freed"], max(row["deltas"].values())))

    single = [row for row in rows if len(row["seen"]) == 1]
    everywhere = [row for row in rows if len(row["seen"]) == len(places)]
    print("\n只出现在一个场合的节 %d 节：放掉它们，最大那份会换成另一个场合，腾出来的不是那一节的字数。" % len(single))
    for row in sorted(single, key=lambda row: -row["freed"]):
        print("  %-38s 只在 %s（那节 %d），放掉只腾 %d"
              % ((row["slug"] + "#" + row["sid"])[:38], "、".join(PLACE_CN.get(p, p) for p in row["seen"]),
                 max(row["deltas"].values()), row["freed"]))
    print("\n处处都出现的节 %d 节：要真腾地方只能动这些（动它得重写正文，别在赶时间时动）。" % len(everywhere))
    for row in sorted(everywhere, key=lambda row: -row["deltas"][largest_place]):
        print("  %-38s 最大那份里 %d" % ((row["slug"] + "#" + row["sid"])[:38], row["deltas"][largest_place]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
