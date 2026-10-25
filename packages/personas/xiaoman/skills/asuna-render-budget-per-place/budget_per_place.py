#!/usr/bin/env python3
"""asuna-render-budget-per-place 的账：随身层每一节，在各场合各占多少。

口径（与程序卡预算的口径一致，不自己发明）：

1. 对家里／线／群／私聊各渲染一份（`visibility.PLACE_CLASS`）；
2. 每一节的数 = 那份渲染去掉这一节少多少（同一节在不同场合可以不同，甚至 0）；
3. 预算卡的是几个场合里**最大的那份**（`render.largest`／`render.render_status`）；
4. 所以放掉一节真正腾出来的是「最大那份 − 去掉它之后最大的那份」——
   放掉只出现在一个场合的节，最大那份会换成另一个场合，可能只腾几格。

v2（2026-10-25）：同一份库有**两种口径**，并排打，不替哪一种说话：

- 预算口径：`render.largest`／`render_status`／`report_budget` 直接吃 doc 里的 `inject`（raw）；
- 带出门口径：`render_system` 先过 `memory_tiers.placed()`，每节的 `inject` 改成跟着 tier 里排的那一档
  （随身→always、手边→on_demand、收着→never）再渲染。

两份口径的差逐节报：每节给出 doc 里的 inject／visibility／tags 对 memory_tiers 里的档，再给各场合 ±token。
**自我层**（`self`、`core` 两份文档）不进 render.compose，不受 6144 管，单独一格计。
自证锚点是跨场合的**形状**（哪些场合有、哪些场合是 0），不是绝对 token 数——绝对数跟着文档改，只当旁注。

只读：读库里的 persona／voice／self／core 与 memory_tiers 行，不写任何东西，也不调 render_system
（它在超预算时会写一行审计，这里不碰）。

用法：
    python3 budget_per_place.py                  # 两份口径 + 逐节差异 + 自我层 + 锚点形状 + 每节的账
    python3 budget_per_place.py --top 12         # 每节的账只列最大的 12 节
    python3 budget_per_place.py --drop persona#某节sid   # 只算「放掉这一节」之后最大那份变成多少（预算口径）
退出码 0 = 账跑出来了（超没超预算写在输出里，不是退出码）；锚点形状不对只写在输出里。
"""
import argparse
import copy
import os
import re
import sys
import types

# 宿主普通 Windows 控制台默认码页是 cp1252：中文一 print 就 UnicodeEncodeError 整段崩
# （2026-10-15 实测）。我的沙箱 env 带 PYTHONUTF8=1／PYTHONIOENCODING=utf-8，自检撞不到这一族。
# 输出字节固定成 UTF-8：那种控制台顶多显示成乱码，不再崩；stderr 同理，报错才看得见。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

PLACE_CN = {"home": "家里", "peer": "线", "group": "群", "dm": "私聊"}

# 自证锚点（形状，不是数）：这一节只在家里／线出现，群里必须是 0。
# 形状 = 跨场合的分布；绝对 token 数每次改文档都变（那节改短之后旧绝对数就作废了），所以只当旁注、带 revision 号打出来。
ANCHOR = ("persona", "我自己的源码在哪儿")


def find_persona(db):
    """库里的 persona 名：从 doc:<persona>:persona 那一格读，别照抄记忆。"""
    from asuna.documents import SCOPE
    for row in db.state_heads.find({"_id": {"$regex": "^doc:"}}, {"_id": 1}):
        match = re.match(r"^doc:([^:]+):persona\|", row["_id"])
        if match and row["_id"].endswith("|" + SCOPE):
            return match.group(1)
    return None


def content_of(db, persona, slug):
    """(内容, head 的 revision 号)；读不到返回 (None, None)。"""
    from asuna.documents import SCOPE
    head = db.state_heads.find_one({"_id": "doc:%s:%s|%s" % (persona, slug, SCOPE)})
    if not head:
        return None, None
    revision = db.state_revisions.find_one({"_id": head["revision_id"]})
    return (revision or {}).get("content"), head.get("revision")


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


def signed(n):
    return "%+d" % n if n else "0"


def main():
    parser = argparse.ArgumentParser(description="随身层每节在各场合占多少（只读）")
    parser.add_argument("--persona", help="默认从 state_heads 里找")
    parser.add_argument("--top", type=int, help="每节的账只列最大的几节")
    parser.add_argument("--drop", help="只算这一节：写成 slug#sid，看放掉它之后最大那份是多少（预算口径）")
    args = parser.parse_args()

    from asuna import dbread, memory_tiers, render, visibility

    db = dbread._default().db
    persona = args.persona or find_persona(db)
    if not persona:
        print("state_heads 里没有 doc:<persona>:persona——不知道给谁算。带 --persona 再跑。")
        return 1
    raw, revs = {}, {}
    for slug in ("persona", "voice"):
        raw[slug], revs[slug] = content_of(db, persona, slug)
    if not raw["persona"]:
        print("读不到「%s」的 persona 文档。" % persona)
        return 1
    print("persona =", persona)
    print("随身层：persona %d 节、voice %d 节（预算口径下 inject=always 才算随身）；doc revision：persona#%s／voice#%s"
          % (len((raw["persona"] or {}).get("sections") or []),
             len((raw["voice"] or {}).get("sections") or []), revs["persona"], revs["voice"]))

    # 带出门口径：同一个函数 render_system 走的那条（memory_tiers.placed）。
    # placed 只读 store.db['memory_tiers']，给它一个只带 db 的壳就够，不建 store、不写。
    shim = types.SimpleNamespace(db=db)
    placed = {slug: (memory_tiers.placed(shim, persona, slug, content) if content else content)
              for slug, content in raw.items()}
    print("memory_tiers.ENABLED = %s%s" % (memory_tiers.ENABLED, "" if memory_tiers.ENABLED else "（关着：两份口径应当相等）"))

    common = render.common_text({})            # prompt_path 不看 config
    places = list(visibility.PLACE_CLASS.items())

    def tokens(place, cls, drop=None, base=None):
        """base = 用哪份文档（默认 raw）；drop = (slug, sid)：把这一节从文档里拿掉再渲染这个场合。"""
        base = raw if base is None else base
        parts = {}
        for slug, content in base.items():
            if content is None:
                parts[slug] = None
                continue
            kept = copy.deepcopy(content)
            if drop and drop[0] == slug:
                kept["sections"] = [s for s in kept["sections"] if s["sid"] != drop[1]]
            parts[slug] = kept
        return render.estimate_tokens(render.compose(common, parts["persona"], parts["voice"], cls, place))

    full = {place: tokens(place, cls) for place, cls in places}                  # 预算口径（raw inject）
    gone = {place: tokens(place, cls, base=placed) for place, cls in places}     # 带出门口径（tier 排的档）
    largest_place = max(full, key=full.get)
    gone_largest = max(gone, key=gone.get)

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

    print("\n两份口径并排（token；persona＋voice 的整份渲染，两边都是同一个 compose）：")
    print("  %-6s %-18s %10s %10s %7s" % ("场合", "场合/可见级", "预算口径", "带出门", "差"))
    for place, cls in places:
        print("  %-6s %-18s %10d %10d %7s%s" % (
            PLACE_CN.get(place, place), place + "/" + cls, full[place], gone[place], signed(gone[place] - full[place]),
            "   <= 预算口径最大" if place == largest_place else ""))
    print("  预算口径：render.largest／render_status／report_budget／budget_gate 吃的就是这一列"
          "（它们直接读 doc 的 inject，没过 memory_tiers.placed；读 render.py 得来）。")
    print("  带出门：render_system 过 placed() 再渲染，是那一拍真进提示词的字。")
    if limit:
        def verdict(value):
            return "超了 %d" % (value - limit) if value > limit else "没超"
        print("  上限 %d：预算口径最大 %d（%s）%s；带出门最大 %d（%s）%s%s%s" % (
            limit, full[largest_place], PLACE_CN[largest_place], verdict(full[largest_place]),
            gone[gone_largest], PLACE_CN[gone_largest], verdict(gone[gone_largest]), limit_note, seed_note))
        if gone[gone_largest] > limit and full[largest_place] <= limit:
            print("  ↑ 带出门那份已越线而预算口径没超：程序对带出门那份没有报警（读 report_budget 得来：它吃的是 doc 原文）。")
    else:
        print("  上限 None%s%s" % (limit_note, seed_note))
    print("  闸该卡哪一份（预算口径还是带出门，inject 当申请、tier 当权威）：这是别处 05:24 传来的读法，"
          "没核到是不是开发本人拍的板，待读码——这里只并排打，不替哪一份说话。")

    # ── 逐节：doc 怎么说 vs tier 怎么排 ──
    to_inject = memory_tiers.TO_INJECT
    tier_places = {}
    for slug in ("persona", "voice"):
        for row in db["memory_tiers"].find({"row": "item", "persona": persona, "doc": slug}, {"sid": 1, "place": 1}):
            tier_places[(slug, row["sid"])] = row["place"]
    diverge, untiered = [], 0
    for slug in ("persona", "voice"):
        for section in (raw[slug] or {}).get("sections") or []:
            tier = tier_places.get((slug, section["sid"]))
            if tier is None:
                untiered += 1                      # 没有 tier 行：placed 原样放过，跟 doc 一致
                continue
            after = to_inject.get(tier)
            if after == section.get("inject"):
                continue
            variant = copy.deepcopy(raw)
            for s in variant[slug]["sections"]:
                if s["sid"] == section["sid"]:
                    s["inject"] = after
            deltas = {place: tokens(place, cls, base=variant) - full[place] for place, cls in places}
            diverge.append({"slug": slug, "section": section, "tier": tier, "after": after, "deltas": deltas})

    print("\n逐节：doc 里怎么说 vs memory_tiers 排成哪一档（只列两边对不上的节；±token 是只改这一节的 inject、"
          "其余按 doc 原样，在各场合渲染比预算口径多／少多少）")
    if not diverge:
        print("  没有对不上的节：两份口径逐节一致。")
    for row in sorted(diverge, key=lambda r: -max(abs(v) for v in r["deltas"].values())):
        s = row["section"]
        print("  %s#%s" % (row["slug"], s["sid"][:40]))
        print("    doc：inject=%s／visibility=%s／tags=%s" % (s.get("inject"), s.get("visibility"), s.get("tags") or []))
        print("    tier：%s（→ placed 后 inject=%s）" % (row["tier"], row["after"]))
        print("    ±token：%s" % "  ".join("%s %s" % (PLACE_CN.get(p, p), signed(row["deltas"][p])) for p, _ in places))
    print("  没有 tier 行、placed 原样放过的节：%d；对不上的节：%d" % (untiered, len(diverge)))
    sums = {place: sum(r["deltas"][place] for r in diverge) for place, _ in places}
    whole = {place: gone[place] - full[place] for place, _ in places}
    print("  各场合：逐节之和 %s；整份实差 %s；没解释掉的 %s（逐节单独算再相加，估 token 的向上取整不是线性的，"
          "差几格属于取整；差得大才说明还有别的原因）" % (
              "  ".join("%s %s" % (PLACE_CN.get(p, p), signed(sums[p])) for p, _ in places),
              "  ".join("%s %s" % (PLACE_CN.get(p, p), signed(whole[p])) for p, _ in places),
              "  ".join("%s %s" % (PLACE_CN.get(p, p), signed(whole[p] - sums[p])) for p, _ in places)))

    # ── 自我层：不进 6144 那把尺 ──
    print("\n自我层（单独一格，**不受 %s 管**）：" % (limit or "6144"))
    print("  render.compose 只吃 persona＋voice；`self`、`core` 两本走 context 里的 self_state（current_self／character_core 那一块），"
          "放不放得下不看 render.budget_tokens（它有没有别的上限我没查）。所以「自我层省了 N」≠「预算省了 N」：预算那把尺（上限见上面「上限 N」那行）只认上面两列。")
    self_docs, self_revs = {}, {}
    for slug in (memory_tiers.SELF_DOC, memory_tiers.CORE_DOC):
        content, rev = content_of(db, persona, slug)
        self_docs[slug], self_revs[slug] = content, rev
    print("  doc revision：self#%s／core#%s；估法 = estimate_tokens(各随身条目的标题＋正文)，是我自己的量法，不是程序报的数"
          % (self_revs[memory_tiers.SELF_DOC], self_revs[memory_tiers.CORE_DOC]))
    for slug, content in self_docs.items():
        if not content:
            print("  %-5s 读不到" % slug)
            continue
        own = memory_tiers.placed(shim, persona, slug, content)

        def cells_of(doc):
            out = []
            for place, cls in places:
                kept = render.readable_sections(doc, cls)
                out.append("%s %d" % (PLACE_CN.get(place, place), render.estimate_tokens(
                    "\n".join("%s\n%s" % (s.get("heading") or "", s.get("body") or "") for s in kept))))
            return "  ".join(out)
        n_doc = sum(1 for s in content["sections"] if s.get("inject") == "always")
        n_tier = sum(1 for s in own["sections"] if s.get("inject") == "always")
        print("  %-5s doc 口径：随身 %d／共 %d 节；%s" % (slug, n_doc, len(content["sections"]), cells_of(content)))
        print("  %-5s tier 口径：随身 %d／共 %d 节；%s（context 里真带的是这份）" % (slug, n_tier, len(content["sections"]), cells_of(own)))
    print("  （这一格和上面两列相加没有意义：不同的尺。）")

    # ── 每节的账（预算口径，原来那张）──
    def section_rows(base):
        always = [(slug, s) for slug in ("persona", "voice")
                  for s in ((base[slug] or {}).get("sections") or []) if s.get("inject") == "always"]
        out = []
        top = max(full if base is raw else gone, key=(full if base is raw else gone).get)
        ref = full if base is raw else gone
        for slug, section in always:
            drop = (slug, section["sid"])
            deltas = {place: ref[place] - tokens(place, cls, drop, base) for place, cls in places}
            after = max(tokens(place, cls, drop, base) for place, cls in places)
            out.append({"slug": slug, "sid": section["sid"], "heading": section.get("heading") or "",
                        "visibility": section.get("visibility"), "places": visibility.section_places(section),
                        "tags": section.get("tags") or [],
                        "deltas": deltas, "seen": [place for place in ref if deltas[place]],
                        "largest_after": after, "freed": ref[top] - after})
        return out

    rows = section_rows(raw)
    rows_placed = section_rows(placed)

    if args.drop:
        try:
            want_slug, want_sid = args.drop.split("#", 1)
        except ValueError:
            print("--drop 写成 slug#sid")
            return 1
        hit = [row for row in rows if row["slug"] == want_slug and row["sid"] == want_sid]
        if not hit:
            print("%s 不在随身层里（预算口径下 inject 不是 always，或 sid 抄错了）" % args.drop)
            return 1
        row = hit[0]
        print("\n放掉 %s#%s（%s）之后（预算口径）：" % (row["slug"], row["sid"], row["heading"][:30]))
        for place, cls in places:
            print("  %-6s %6d -> %6d" % (PLACE_CN.get(place, place), full[place],
                                         tokens(place, cls, (row["slug"], row["sid"]))))
        print("  最大那份：%d -> %d，真正腾出来 %d（这一节本身占 %d）"
              % (full[largest_place], row["largest_after"], row["freed"], max(row["deltas"].values())))
        return 0

    # ── 锚点：形状，不是数 ──
    print("\n自证锚点（形状）：")
    anchor = [r for r in rows if (r["slug"], r["sid"]) == ANCHOR]
    anchor_placed = [r for r in rows_placed if (r["slug"], r["sid"]) == ANCHOR]
    if not anchor:
        print("  %s#%s：预算口径下不在随身层里（改名了、收起来了或 inject 变了）——锚点失效，先换锚点再信别的。" % ANCHOR)
    else:
        for label, found in (("预算口径", anchor), ("带出门", anchor_placed)):
            if not found:
                print("  %s#%s（%s）：这一口径下不在随身层" % (ANCHOR + (label,)))
                continue
            d = found[0]["deltas"]
            ok = d["group"] == 0 and d["home"] > 0
            print("  %s#%s（%s）分布：%s → 形状%s（要求：群=0、家里有）"
                  % (ANCHOR + (label, "  ".join("%s=%s" % (PLACE_CN.get(p, p), "有" if d[p] else "0") for p, _ in places),
                               "对" if ok else "不对")))
        content = (raw["persona"] or {})
        sec = next((s for s in content.get("sections", []) if s["sid"] == ANCHOR[1]), {})
        print("  旁注（绝对数只当旁注，跟着文档变）：persona doc revision#%s、该节 body_sha256 前 8 位 %s、"
              "预算口径下家里 %d token" % (revs["persona"], (sec.get("body_sha256") or "")[:8], anchor[0]["deltas"]["home"]))
    for label, group in (("预算口径", rows), ("带出门", rows_placed)):
        single = [r for r in group if len(r["seen"]) == 1]
        print("  只出现在一个场合的节数（%s）：%d" % (label, len(single)))

    print("\n每一节的账（预算口径；数 = 那份渲染去掉这一节少多少）")
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
    print("\n只出现在一个场合的节 %d 节（预算口径）：放掉它们，最大那份会换成另一个场合，腾出来的不是那一节的字数。" % len(single))
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
