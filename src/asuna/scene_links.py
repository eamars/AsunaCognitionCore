"""跨场景只读联动（A2）：一条有向边 + 一个 canonical person，配置是唯一真相。

依据：《跨场景上下文同步_方案报告_2026-09-25》A2。这里只放宽**读**——写、出站投递、场景成员资格、
历史行上的 author/platform 原始信息都不动；删掉配置键就回到原状（回滚 = 删键）。

配置（写在 config/local.json 或 config/asuna-channel.local.json 顶层；config.load 原样带过，
不新增校验器，形状不对的条目在读的时候照实丢掉）：

  "context_links": {"local-dm": ["qq:3768713357:dm:673225019"]}
      有向边：左边的场景可以**只读**右边那些场景的历史。不做通配、不自动反向。
      通道路由里也可以写 read_scenes，语义等同于给该路由的 scene_id 挂同一条边。

  "canonical_persons": {"qq:673225019": "local-user"}
      同一个人的不同入口：键是别名（历史行里照旧写这个 person_id，不改写），值是 canonical person_id。
      归一只作用在两处——「按人过滤」把同一个人的其他入口算进来；「关系／偏好状态落在哪一份 head」
      用 canonical 那一份。别的都不动。

库里那两个派生投影（scenes.readable_scenes、identities.canonical_person_id）只在宿主启动时写一次，
为的是让人看得见联动到哪；读路径一律现算自配置，配置删掉立刻不联动，不会出现「库里还认、配置已经不认」。
"""
from __future__ import annotations
import re

MAX_LINKS = 8          # 一条边最多带几个场景：写宽了直接推高 token 成本，超了照实截断
MAX_PERSONS = 32       # 一组「同一个人」最多几个人格入口


def _clean(value, limit=90):
    if not isinstance(value, str):
        return ""
    return " ".join(value.replace("\x00", " ").split())[:limit]


def _id_list(value, limit=MAX_LINKS):
    """配置里的场景／person 列表 → 去重、去空、去通配的有序列表（`*` 不当通配用，照实丢掉）。"""
    items = value if isinstance(value, (list, tuple)) else ([value] if isinstance(value, str) else [])
    out = []
    for item in items:
        text = _clean(item)
        if not text or text == "*" or text in out:
            continue
        out.append(text)
    return out[:limit]


def _rows(db, collection, spec=None):
    column = getattr(getattr(db, collection, None), "find", None)
    if not callable(column):
        return []
    try:
        return [row for row in (column(spec or {}) or []) if isinstance(row, dict)]
    except Exception:
        return []


# ── 场景这一侧：谁能读谁 ────────────────────────────────────────────
def context_links(config):
    """{场景: [可只读的场景]}。顶层 context_links 与路由级 read_scenes 都算，两处都不做通配。"""
    out = {}
    raw = (config or {}).get("context_links")
    if isinstance(raw, dict):
        for scene, value in raw.items():
            scene = _clean(scene)
            if scene:
                out.setdefault(scene, []).extend(_id_list(value))
    channels = (config or {}).get("channels")
    if isinstance(channels, dict):
        for channel in channels.values():
            routes = channel.get("routes") if isinstance(channel, dict) else None
            if not isinstance(routes, dict):
                continue
            for route in routes.values():
                if not isinstance(route, dict) or route.get("read_scenes") is None:
                    continue
                scene = _clean(route.get("scene_id"))
                if scene:
                    out.setdefault(scene, []).extend(_id_list(route.get("read_scenes")))
    return {scene: [target for target in dict.fromkeys(targets) if target != scene][:MAX_LINKS]
            for scene, targets in out.items()}


def readable_scenes(config, scene_id):
    """这个场景可以额外只读哪些场景（有序、不含自己）。"""
    return list(context_links(config).get(_clean(scene_id), []))


def read_scope(config, scene_doc):
    """这一轮能读哪些场景／scope_key：本场景永远排第一，联动场景按配置顺序跟在后面。"""
    own = _clean((scene_doc or {}).get("scene_id") or (scene_doc or {}).get("_id"))
    linked = [scene for scene in readable_scenes(config, own) if scene != own]
    return {"scene_id": own, "scene_ids": ([own] if own else []) + linked,
            "linked_scenes": linked,
            "scope_keys": ["scene:" + scene for scene in ([own] if own else []) + linked],
            "linked_scope_keys": ["scene:" + scene for scene in linked]}


def scene_id_filter(parts_or_scene):
    """场景过滤条件：没联动时保持原来的单值形状（查询条件一行都不多写），联动了才换成 $in。"""
    source = parts_or_scene if isinstance(parts_or_scene, dict) else {}
    ids = [scene for scene in (source.get("scene_ids") or []) if _clean(scene)]
    if not ids:
        own = _clean(source.get("scene_id") or source.get("_id"))
        ids = [own] if own else []
    ids = list(dict.fromkeys(ids))
    if not ids:
        return {}
    return {"scene_id": ids[0]} if len(ids) == 1 else {"scene_id": {"$in": ids}}


def sync_scene_docs(store, config, scene_ids=None):
    """把派生出来的 readable_scenes 写进 scenes 文档（只为可观察；读路径现算自配置）。"""
    links = context_links(config)
    wanted = {scene: links.get(scene, []) for scene in (scene_ids or sorted(links))}
    column = getattr(getattr(store, "db", None), "scenes", None)
    if column is None:
        return {"updated": [], "readable": wanted, "why": "no_scenes_collection"}
    updated = []
    for scene, targets in wanted.items():
        if not targets:
            continue                      # 没这条边就不往文档里塞空键：保持原形状
        doc = column.find_one({"_id": scene})
        if not isinstance(doc, dict) or doc.get("readable_scenes") == targets:
            continue
        try:
            store.put("scenes", {**doc, "readable_scenes": list(targets)},
                      expected=doc.get("revision"), stream="scene-links")
            updated.append(scene)
        except Exception:
            continue                      # 同一轮里别人推了 revision：下次启动再补，不影响本轮读
    return {"updated": updated, "readable": wanted}


# ── 人这一侧：同一个人的不同入口 ────────────────────────────────────
def canonical_map(config):
    """{别名 person_id: canonical person_id}；自指与非字符串条目照实丢掉。"""
    raw = (config or {}).get("canonical_persons")
    out = {}
    if isinstance(raw, dict):
        for alias, canonical in raw.items():
            alias, canonical = _clean(alias, 60), _clean(canonical, 60)
            if alias and canonical and alias != canonical:
                out[alias] = canonical
    return out


def _normalize_person(value):
    """归一成 person_id：已带 `qq:` 这类前缀的不再拼第二次（与 history_query 同一口径）。"""
    text = _clean(value, 60)
    if not text:
        return ""
    head, sep, _rest = text.partition(":")
    if sep and head and len(head) <= 12 and re.match(r"^[a-z][a-z0-9_]*$", head):
        return text.lower()
    return "qq:%s" % text.lower()


def canonical_person_id(config, db, person_id):
    """别名 → canonical；配置优先，其次库里那份派生投影。没配映射就返回本人 id。"""
    person_id = _clean(person_id, 60)
    if not person_id:
        return ""
    mapping = canonical_map(config)
    if person_id in mapping:
        return mapping[person_id]
    if not mapping:
        return person_id                  # 没配映射就不查库：不引入新的隐式行为
    for row in _rows(db, "identities"):
        if _clean(row.get("person_id"), 60) == person_id:
            return _clean(row.get("canonical_person_id"), 60) or person_id
    return person_id


def person_classes(config, db):
    """{person_id: [同一个人的全部 person_id]}：只包含真的不止一个人的那几组，含本人。"""
    classes = {}
    for alias, canonical in canonical_map(config).items():
        classes.setdefault(canonical, set()).update({alias, canonical})
    mapping = canonical_map(config)
    if mapping:                           # 库里的投影只在配置还认这条边时才参与
        for row in _rows(db, "identities"):
            person = _clean(row.get("person_id"), 60)
            canonical = _clean(row.get("canonical_person_id"), 60)
            if person and canonical in classes:
                classes[canonical].add(person)
    out = {}
    for members in classes.values():
        members = sorted(members)[:MAX_PERSONS]
        for person in members:
            out[person] = list(members)
    return out


def extra_person_values(config, db, person):
    """按人过滤时要一起算进来的其他 person_id（同一个人的其他入口）；没有就空。"""
    text = _clean(person, 60).lower()
    if not text:
        return []
    wanted = {text, _normalize_person(text)}
    out = []
    for members in person_classes(config, db).values():
        if wanted & {member.lower() for member in members}:
            for member in members:
                if member.lower() not in wanted and member not in out:
                    out.append(member)
    return out


def relationship_target(config, db, scene, person_id):
    """这个人在这一轮的关系／偏好状态该落在哪一份 head。

    没配 canonical 映射时返回的就是原来那一份（entity=relationship:<本人>，scope=本场景）——一个字段都不变。
    配了映射、且两个场景之间确实有联动边时，同一个人只用 canonical 那一份：别名场景不再另起一条关系记录，
    否则「同一个人在两边被理解成两个人」只是换了个地方继续分叉。找不到归属场景就只归一 entity、
    scope 仍按本场景（宁可少统一，不猜哪份才是正的）。
    """
    own = _clean((scene or {}).get("scene_id") or (scene or {}).get("_id"))
    own_scope = _clean((scene or {}).get("scope_key")) or ("scene:" + own)
    person_id = _clean(person_id, 60)
    canonical = canonical_person_id(config, db, person_id)
    if not canonical or canonical == person_id:
        return {"entity": "relationship:" + person_id, "scope": own_scope,
                "canonical": person_id, "shared": False, "linked_scopes": []}
    home = _canonical_home_scene(config, db, canonical, own)
    if not home:
        return {"entity": "relationship:" + canonical, "scope": own_scope,
                "canonical": canonical, "shared": False, "linked_scopes": []}
    scope = "scene:" + home
    return {"entity": "relationship:" + canonical, "scope": scope, "canonical": canonical,
            "shared": scope != own_scope, "linked_scopes": [own_scope] if scope != own_scope else []}


def _canonical_home_scene(config, db, canonical, own_scene):
    """canonical 那份关系记录该挂在哪个场景：宿主自己的聊天场景优先，其次任何「成员含 canonical
    且与本场景有联动边」的场景；多个候选按场景名排序取第一个，保证同一份配置每次算出同一个结果。"""
    links = context_links(config)
    chat = _clean((config or {}).get("chat", {}).get("scene_id")) \
        if isinstance((config or {}).get("chat"), dict) else ""
    candidates = []
    for row in _rows(db, "scenes"):
        scene = _clean(row.get("scene_id") or row.get("_id"))
        if not scene or scene == own_scene or canonical not in (row.get("members") or []):
            continue
        if own_scene in links.get(scene, []) or scene in links.get(own_scene, []):
            candidates.append(scene)
    candidates = list(dict.fromkeys(candidates))
    if chat in candidates:
        return chat
    return sorted(candidates)[0] if candidates else ""


def sync_identity_docs(store, config):
    """把 canonical 映射写进 identities（只加 canonical_person_id／alias_of 两个派生字段）。

    历史消息行不在这里动：author、platform、身份块原样留着，归一只在查询与状态落点上生效。
    """
    mapping = canonical_map(config)
    out = {"updated": [], "classes": {}}
    if not mapping:
        return out
    column = getattr(getattr(store, "db", None), "identities", None)
    if column is None:
        return {**out, "why": "no_identities_collection"}
    for row in _rows(store.db, "identities"):
        person = _clean(row.get("person_id"), 60)
        canonical = canonical_person_id(config, store.db, person)
        if not canonical:
            continue
        wanted = {"canonical_person_id": canonical}
        if person in mapping:
            wanted["alias_of"] = mapping[person]
        if all(row.get(key) == value for key, value in wanted.items()):
            continue
        try:
            store.put("identities", {**row, **wanted}, expected=row.get("revision"),
                      stream="scene-links")
            out["updated"].append(person)
        except Exception:
            continue
    out["classes"] = person_classes(config, store.db)
    return out


# ── 归并用：一条消息行的有效时间 ────────────────────────────────────
TIME_RECEIPT_AT = "messages.receipt_at"            # 平台 ack
TIME_SINK = "sink_receipts.received_at"            # 本机送达回执，不是平台 ack
TIME_OCCURRED = "messages.occurred_at"             # 入站自带时刻
TIME_RECEIVED = "messages.received_at"             # 落库时间：只在前面几个都没有时兜底


def _stamp(value):
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return _clean(value, 32)


def message_times(store, rows):
    """{消息 id: (时间, 时间来源)}：出站行内 receipt_at ＞ 关联出来的 sink_receipts.received_at
    ＞ 入站 occurred_at ＞ 落库 received_at。

    优先级与 history_query 一致（那边对「没时间戳」要照实报告，这里只是给跨场景归并找一个可比的键，
    所以最后兜到落库时间，并把来源写清楚，不冒充平台 ack）。同一次调用只发一条 sink_receipts 查询。
    """
    docs = [row for row in (rows or []) if isinstance(row, dict)]
    refs = set()
    for row in docs:
        if _clean(row.get("direction"), 16) == "outbound" and not _stamp(row.get("receipt_at")):
            ref = row.get("receipt")
            if isinstance(ref, str) and _clean(ref):
                refs.add(ref)
    sinks = {}
    column = getattr(getattr(store, "db", None), "sink_receipts", None)
    if refs and column is not None:
        try:
            for row in (column.find({"_id": {"$in": sorted(refs)}}) or []):
                if isinstance(row, dict) and _stamp(row.get("received_at")):
                    sinks[_clean(row.get("_id"), 60)] = _stamp(row.get("received_at"))
        except Exception:
            sinks = {}
    out = {}
    for row in docs:
        mid = _clean(row.get("_id"), 80)
        if not mid:
            continue
        at, source = _stamp(row.get("receipt_at")), TIME_RECEIPT_AT
        if not at and _clean(row.get("direction"), 16) == "outbound":
            at, source = sinks.get(_clean(row.get("receipt"), 60), ""), TIME_SINK
        if not at:
            at, source = _stamp(row.get("occurred_at")), TIME_OCCURRED
        if not at:
            at, source = _stamp(row.get("received_at")), TIME_RECEIVED
        out[mid] = (at, source if at else "")
    return out
