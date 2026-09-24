"""ADR-005 P1-c 离线用例：整理逻辑用假集合真算一遍。

这里不依赖 Mongo 也不依赖 pytest：假集合真实现 $in/$gte/$lte/$lt/$ne/$regex/$and/$or、
点号键、projection、多键排序与 count_documents，所以过滤、分页、整理结果都是算出来的，
不是断言出来的。操作员在隔离宿主跑 pytest 时，这些用例也会跟着跑（见
 test_discussion_digest.py::test_offline_cases_all_pass）；本机用
 python3 tools/p1c_offline_check.py 直接跑同一套。
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(os.path.dirname(HERE), "src", "asuna")
for _path in (SRC, HERE):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import discussion_digest as dd                       # noqa: E402
import history_query as hq                           # noqa: E402

BOT = "3768713357"
GID = "905393941"
SCENE_ID = "qq:%s:group:%s" % (BOT, GID)
OTHER_SCENE = "qq:%s:group:54369546" % BOT
EPOCH = 7
A_ID, A_ACC, A_CARD = "qq:458658853", "458658853", "雾灯修理工"
B_ID, B_ACC, B_CARD = "qq:7777777", "7777777", "路人甲"
FULL = {"since": "2000-01-01", "until": "2999-12-31T23:59:59Z"}


def peer_block(person_id, account, card, role="member"):
    return {"person_id": person_id, "account_id": account, "scene": "group:%s" % GID,
            "group_id": GID, "display": card, "nickname": card, "card": card, "role": role,
            "verified": True, "aliases": []}


PEER_A = peer_block(A_ID, A_ACC, A_CARD, "admin")
PEER_B = peer_block(B_ID, B_ACC, B_CARD)


def inbound(mid, seq, at, text, author=A_ID, peer=PEER_A, reply_to=None, scene=SCENE_ID):
    doc = {"_id": mid, "scene_id": scene, "scope_key": "scene:" + scene, "policy_epoch": EPOCH,
           "scene_seq": seq, "text": text, "author": author, "direction": "inbound",
           "delivery_state": "RECEIVED", "occurred_at": at,
           "adapter_id": "p1c-fixture", "platform_event_id": "pe-" + mid}
    if peer is not None:
        doc["event"] = {"raw": {"asuna_peer": dict(peer)},
                        "channel": {"sender_id": author.split(":")[-1],
                                    "target": {"type": "group", "id": scene.rsplit(":", 1)[-1]}}}
        if reply_to:
            doc["event"]["group_context"] = {"reply_to": "pe-" + reply_to,
                                             "reply_message_id": reply_to,
                                             "mentioned_account_ids": [], "wake_reason": None,
                                             "topic_id": reply_to}
    return doc


def outbound(mid, seq, text, reply_to=None, receipt_at="2026-09-22T12:20:00Z",
             phase="SPEAK", delivery="DELIVERED", scene=SCENE_ID):
    doc = {"_id": mid, "scene_id": scene, "scope_key": "scene:" + scene, "policy_epoch": EPOCH,
           "scene_seq": seq, "text": text, "author": "xiaoman", "direction": "outbound",
           "phase": phase, "delivery_state": delivery, "adapter_id": "p1c-fixture"}
    if receipt_at:
        doc["receipt_at"] = receipt_at
    if reply_to:
        doc["reply_to"] = reply_to
    return doc


def scene_row(scene_id=SCENE_ID):
    return {"_id": scene_id, "scene_id": scene_id, "kind": "group",
            "scope_key": "scene:" + scene_id, "policy_epoch": EPOCH, "sequence": 0}


def task_row(scene_id=SCENE_ID, scope=None, epoch=EPOCH):
    return {"_id": "task-p1c", "scene_id": scene_id, "scope_key": scope or ("scene:" + scene_id),
            "policy_epoch": epoch, "requester_id": A_ID}


# ── 假集合：真算过滤与排序 ────────────────────────────────────────
def _lookup(doc, key):
    value = doc
    for part in key.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return False, None
    return True, value


def _match(doc, flt):
    for key, cond in flt.items():
        if key == "$or":
            if not any(_match(doc, sub) for sub in cond):
                return False
        elif key == "$and":
            if not all(_match(doc, sub) for sub in cond):
                return False
        elif isinstance(cond, dict) and not cond:
            found, value = _lookup(doc, key)
            if not (found and value == {}):
                return False
        elif isinstance(cond, dict):
            found, value = _lookup(doc, key)
            for op, arg in cond.items():
                if op == "$in" and value not in arg:
                    return False
                elif op == "$exists" and found is not bool(arg):
                    return False
                elif op == "$ne" and found and value == arg:
                    return False
                elif op == "$gte" and (value is None or value < arg):
                    return False
                elif op == "$lte" and (value is None or value > arg):
                    return False
                elif op == "$lt" and (value is None or value >= arg):
                    return False
                elif op == "$regex" and not (isinstance(value, str) and re.search(
                        arg, value, re.IGNORECASE if cond.get("$options") == "i" else 0)):
                    return False
        else:
            found, value = _lookup(doc, key)
            if not found or not (value == cond or (isinstance(value, list) and cond in value)):
                return False
    return True


def _project(doc, projection):
    if not projection:
        return dict(doc)
    out = {"_id": doc.get("_id")}
    for key in projection:
        if key == "_id":
            continue
        found, value = _lookup(doc, key)
        if not found:
            continue
        cursor = out
        parts = key.split(".")
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    return out


class FakeCollection:
    def __init__(self, rows, boom=False):
        self.rows, self.boom, self.finds = rows, boom, []

    def find(self, flt=None, projection=None, sort=None, limit=0):
        self.finds.append((flt, projection, sort, limit))
        if self.boom:
            raise RuntimeError("mongo down")
        out = [_project(doc, projection) for doc in self.rows if _match(doc, flt or {})]
        for key, direction in reversed(list(sort or [])):
            out.sort(key=lambda d: (d.get(key) is None, d.get(key)), reverse=direction < 0)
        return out[:limit] if limit else out

    def find_one(self, flt, projection=None):
        rows = self.find(flt, projection)
        return rows[0] if rows else None

    def count_documents(self, flt):
        return len([doc for doc in self.rows if _match(doc, flt or {})])


class FakeStore:
    def __init__(self, rows, sink=None, scenes=None, boom=False):
        class DB:
            pass
        self.db = DB()
        self.db.messages = FakeCollection(rows, boom=boom)
        self.db.scenes = FakeCollection(scenes if scenes is not None else [scene_row()])
        if sink is not None:
            self.db.sink_receipts = FakeCollection(sink)


def digest_of(rows, args=None, **kwargs):
    store = FakeStore(rows, **kwargs)
    service = dd.DiscussionDigestService(store, None)
    return service.digest_for_task(task_row(), dict(FULL, **(args or {}))), store


# ── 一段真实形状的群讨论：参与者、更正、意见、未决混在一起 ──────────────
def discussion_rows():
    return [
        inbound("i1", 1, "2026-09-22T12:00:00Z", "雾灯坏了，明天去修"),
        inbound("i2", 2, "2026-09-22T12:01:00Z", "我觉得周末再去更稳", author=B_ID, peer=PEER_B),
        inbound("i3", 3, "2026-09-22T12:02:00Z", "不同意，明天必须修", reply_to="i2"),
        inbound("i4", 4, "2026-09-22T12:03:00Z", "更正一下：不是明天，是周三", reply_to="i1"),
        inbound("i5", 5, "2026-09-22T12:04:00Z", "那工具谁带？", author=B_ID, peer=PEER_B),
        outbound("o1", 6, "我周三上午去看看", reply_to="i1", receipt_at="2026-09-22T12:05:00Z"),
        inbound("i6", 7, "2026-09-22T12:06:00Z", "时间还没定"),
        outbound("o2", 8, "工具我来带", reply_to="i5", receipt_at="2026-09-22T12:07:00Z"),
        # 下面两条不算讨论内容，但覆盖范围要能说出它们被排除了：
        outbound("o-ready", 9, "没送达的不进讨论", receipt_at=None, delivery="READY"),
        outbound("o-react", 10, "不是 SPEAK 的出站", receipt_at="2026-09-22T12:08:00Z",
                 phase="REACT"),
    ]


def case_participants_and_coverage():
    value, _store = digest_of(discussion_rows())
    assert value["degraded"] is False, value
    people = dict((person["display"], person) for person in value["participants"])
    assert sorted(people) == sorted([A_CARD, B_CARD, "xiaoman"]), people
    assert people[A_CARD]["identity"] == "peer" and people[A_CARD]["role"] == "管理员"
    assert people[A_CARD]["messages"] == 4 and people[A_CARD]["person_id"] == A_ID
    assert people[B_CARD]["messages"] == 2 and people[B_CARD]["role"] == "成员"
    assert people["xiaoman"]["identity"] == "author" and people["xiaoman"]["side"] == "我说"
    cov = value["coverage"]
    assert (cov["read"], cov["inbound"], cov["outbound"]) == (8, 6, 2), cov
    assert cov["covered_from"] == "2026-09-22T12:00:00Z"
    assert cov["covered_to"] == "2026-09-22T12:07:00Z"
    assert cov["time_sources"] == {"messages.occurred_at": 6, "messages.receipt_at": 2}, cov
    assert cov["identity_fallback"] == 2          # 两条出站没有身份块，按记录作者
    assert cov["excluded"] == {"undelivered_outbound": 1, "non_speak_outbound": 1}, cov
    assert cov["complete"] is True and value["more"] is False
    assert value["source_ids"] == ["i1", "i2", "i3", "i4", "i5", "o1", "i6", "o2"]
    assert "o-ready" not in value["source_ids"] and "o-react" not in value["source_ids"]
    assert value["readback"]["tool"] == hq.HISTORY_TOOL_NAME
    assert value["readback"]["example_args"]["since"] == "2026-09-22T12:02:58Z"


def case_correction_opinion_open_are_separate():
    value, _store = digest_of(discussion_rows())
    correction = value["corrections"][0]
    assert len(value["corrections"]) == 1 and correction["message_id"] == "i4"
    assert correction["basis"] == "reply_link" and correction["confidence"] == "high"
    assert correction["corrects"] == "i1" and correction["target_author"] == A_CARD
    assert correction["self_correction"] is True and correction["later_than_target"] is True
    assert correction["cue"] == "更正"
    opinions = dict((item["message_id"], item) for item in value["opinions"])
    assert set(opinions) == {"i2", "i3"}, opinions
    assert opinions["i2"]["subtype"] == "opinion" and opinions["i2"]["cue"] == "我觉得"
    assert opinions["i3"]["subtype"] == "dissent" and opinions["i3"]["target_in_scope"] is True
    assert [item["message_id"] for item in value["open_items"]] == ["i6"]
    assert value["open_items"][0]["kind"] == "undecided"
    assert value["open_items"][0]["undecided_cue"] == "还没定"
    assert "reply 链" in value["open_items"][0]["note"]
    assert [item["message_id"] for item in value["resolved"]] == ["i5"]
    assert value["resolved"][0]["answered_by"] == "o2"
    assert value["resolved"][0]["answer_confirms"] is True
    assert sorted((reply["message_id"], reply["in_reply_to"]) for reply in value["replies"]) == [
        ("i3", "i2"), ("i4", "i1"), ("o1", "i1"), ("o2", "i5")]


def case_correction_without_link_does_not_invent_target():
    rows = [inbound("i1", 1, "2026-09-22T12:00:00Z", "明天去修"),
            inbound("i2", 2, "2026-09-22T12:01:00Z", "我打错字了，不说错了")]
    value, _store = digest_of(rows)
    item = value["corrections"][0]
    assert item["basis"] == "cue_only" and item["confidence"] == "low"
    assert item["corrects"] == "" and item["target_in_scope"] is False
    rows2 = [inbound("i1", 1, "2026-09-22T12:00:00Z", "明天去修"),
             inbound("i2", 2, "2026-09-22T12:01:00Z", "上面那条我说错了")]
    item = digest_of(rows2)[0]["corrections"][0]
    assert item["basis"] == "self_reference" and item["confidence"] == "medium"
    # reply 链指向本次没读到的一行：照实说对象不在范围内，不拿时间最近的那条冒充
    rows3 = [inbound("i2", 2, "2026-09-22T12:01:00Z", "更正：是周三", reply_to="i1")]
    item = digest_of(rows3)[0]["corrections"][0]
    assert item["basis"] == "reply_link_out_of_scope" and item["corrects"] == "i1"
    assert item["target_in_scope"] is False


def case_answer_only_counts_real_reply_link():
    """没有 reply 链的后续表态不能自动当成回答——那是猜。"""
    rows = [inbound("i1", 1, "2026-09-22T12:00:00Z", "工具谁带？"),
            inbound("i2", 2, "2026-09-22T12:01:00Z", "我已经买好了", author=B_ID, peer=PEER_B)]
    value, _store = digest_of(rows)
    assert [item["message_id"] for item in value["open_items"]] == ["i1"]
    assert value["resolved"] == []
    assert "reply 链" in value["open_items"][0]["note"]


def case_sink_receipt_time_is_carried_through():
    """本机 Web 出站的时间在 sink_receipts 上：P1-c 不另造一套时间口径，跟着 P1-b 走。"""
    rows = [inbound("i1", 1, "2026-09-22T12:04:00Z", "那工具谁带？", author=B_ID, peer=PEER_B),
            outbound("o1", 2, "工具我来带", reply_to="i1", receipt_at=None)]
    rows[1]["receipt"] = "sr-1"
    value, _store = digest_of(rows, sink=[{"_id": "sr-1", "received_at": "2026-09-22T12:07:00Z",
                                           "sink": "web"}])
    assert value["resolved"][0]["answered_by"] == "o1"
    assert value["coverage"]["time_sources"] == {"messages.occurred_at": 1,
                                                "sink_receipts.received_at": 1}, value["coverage"]


def case_partial_coverage_and_continuation():
    """more=true 时覆盖范围一定 partial；续页不重不漏，跨页的链不猜。"""
    rows = discussion_rows()
    first, _store = digest_of(rows, dict(FULL, limit=3))
    assert first["more"] is True and first["coverage"]["complete"] is False
    assert first["source_ids"] == ["o1", "i6", "o2"], first["source_ids"]
    assert first["coverage"]["covered_from"] == "2026-09-22T12:05:00Z"
    assert first["next_cursor"] and first["next_cursor"] in first["text"]
    assert [item["message_id"] for item in first["open_items"]] == ["i6"]
    assert first["resolved"] == []            # 回答 o2 在本页，但被回答的 i5 还没读到
    second, _store = digest_of(rows, dict(FULL, limit=3, cursor=first["next_cursor"]))
    assert second["source_ids"] == ["i3", "i4", "i5"], second["source_ids"]
    assert second["corrections"][0]["basis"] == "reply_link_out_of_scope"
    assert [item["message_id"] for item in second["open_items"]] == ["i5"]
    third, _store = digest_of(rows, dict(FULL, limit=3, cursor=second["next_cursor"]))
    assert third["more"] is False and third["coverage"]["complete"] is True
    seen = first["source_ids"] + second["source_ids"] + third["source_ids"]
    assert sorted(seen) == sorted(["i1", "i2", "i3", "i4", "i5", "o1", "i6", "o2"])
    assert len(seen) == len(set(seen))


def case_cursor_and_argument_fences():
    rows = discussion_rows()
    page, store = digest_of(rows, dict(FULL, limit=1))
    assert page["next_cursor"] and page["more"], page["coverage"]
    try:
        digest_of(rows, dict(FULL, limit=1, topic="雾灯", cursor=page["next_cursor"]))
        raise AssertionError("换 topic 复用游标应该被拒")
    except ValueError as exc:
        assert "DIGEST_CURSOR_FILTER_MISMATCH" in str(exc), exc
    try:
        digest_of(rows, dict(FULL, limit=1, topic="雾灯", cursor="not-a-real-cursor"))
        raise AssertionError("乱写的游标应该被拒")
    except ValueError as exc:
        assert "DIGEST_CURSOR_INVALID" in str(exc), exc
    # P1-b 的游标不能拿到 P1-c 用：信封里没有 kind='digest'
    p1b = hq.HistoryQueryService(store, None).query_for_task(task_row(), dict(FULL, limit=1))
    assert p1b["next_cursor"]
    try:
        digest_of(rows, dict(FULL, limit=1, cursor=p1b["next_cursor"]))
        raise AssertionError("P1-b 游标拿到 P1-c 应该被拒")
    except ValueError as exc:
        assert "DIGEST_CURSOR_INVALID" in str(exc), exc
    for args, wanted in ((dict(FULL, scene_id=OTHER_SCENE), "DIGEST_ARGUMENT_DENIED:scene_id"),
                         (dict(FULL, topic="雾灯", query="周三"), "DIGEST_ARGUMENT_CONFLICT"),
                         (dict(FULL, since="昨天"), "INVALID_DIGEST_SINCE"),
                         (dict(FULL, limit=0), "INVALID_DIGEST_LIMIT"),
                         (dict(FULL, window_days=900), "INVALID_DIGEST_WINDOW_DAYS")):
        try:
            digest_of(rows, args)
            raise AssertionError("%s 应该被拒" % wanted)
        except ValueError as exc:
            assert wanted in str(exc), (wanted, exc)
    service = dd.DiscussionDigestService(FakeStore(rows), None)
    try:
        service.digest_for_task(task_row(scope="scene:some-other-binding"), dict(FULL))
        raise AssertionError("场景围栏不同步应该拒查")
    except dd.Denied as exc:
        assert "DIGEST_SCENE_FENCE_MISMATCH" in str(exc), exc


def case_degraded_and_no_match_are_different_states():
    broken, _store = digest_of(discussion_rows(), boom=True)
    assert broken["degraded"] is True and broken["why"].startswith("messages_search_failed")
    assert broken["participants"] == [] and "没查成" in broken["text"]
    empty, _store = digest_of(discussion_rows(), {"topic": "不存在的词"})
    assert empty["degraded"] is False and empty["coverage"]["read"] == 0
    assert empty["participants"] == [] and empty["more"] is False
    assert empty["coverage"]["complete"] is True      # 读完了，只是没匹配
    assert any("字面匹配" in note for note in empty["notes"]), empty["notes"]
    assert "没读到任何发言" in empty["text"]


def case_identity_fallback_is_labelled_not_hidden():
    rows = [inbound("i1", 1, "2026-09-22T12:00:00Z", "雾灯坏了", peer=None)]
    value, _store = digest_of(rows)
    person = value["participants"][0]
    assert person["identity"] == "author" and person["display"] == A_ID
    assert value["coverage"]["identity_fallback"] == 1
    assert any("身份块" in note for note in value["notes"]), value["notes"]


def case_render_shows_categories_and_honesty_notes():
    text = digest_of(discussion_rows())[0]["text"]
    for wanted in ("参与者：", "后续更正 1 条", "个人意见 2 条", "未决事项 1 条", "已被回应 1 条",
                   "message_id", "机械标注", "query_authorized_history"):
        assert wanted in text, (wanted, text)
    assert "覆盖完整" in text and "续页 cursor" not in text


def case_budget_guard_keeps_ids_and_counts():
    payload = {"coverage": {"budget_trimmed": 0}, "notes": [], "source_ids": ["a", "b"],
               "corrections": [{"message_id": "a", "text": "长" * 40000, "at": "", "who": "",
                                "person_id": "", "cue": "", "confidence": "", "corrects": "",
                                "target_author": "", "target_in_scope": False,
                                "self_correction": False, "later_than_target": False},
                               {"message_id": "b", "text": "长" * 40000, "at": "", "who": "",
                                "person_id": "", "cue": "", "confidence": "", "corrects": "",
                                "target_author": "", "target_in_scope": False,
                                "self_correction": False, "later_than_target": False}],
               "opinions": [], "open_items": [], "resolved": [], "replies": []}
    fitted = dd._fit_budget(payload)
    assert len(__import__("json").dumps(fitted, ensure_ascii=False).encode("utf-8")) \
        <= dd.DIGEST_RESULT_BUDGET
    assert fitted["source_ids"] == ["a", "b"]
    assert any("预算" in note for note in fitted["notes"]), fitted["notes"]


def thread_rows():
    """Q2 等价形状：线缆主题首句 + 不含“线缆”字样的 reply 更正，中间交错一段相机讨论。

    相机那两条跟线缆没有任何 reply 链关系，只是时间上交错；它们不得冒充线缆讨论的结论。
    """
    return [
        inbound("c1", 1, "2026-09-22T12:00:00Z", "线缆得换一根两米的"),
        inbound("cam1", 2, "2026-09-22T12:01:00Z", "相机我先借走了", author=B_ID, peer=PEER_B),
        inbound("c2", 3, "2026-09-22T12:02:00Z", "更正一下：是一米五，不是两米", reply_to="c1"),
        inbound("cam2", 4, "2026-09-22T12:03:00Z", "我觉得那台更稳", author=B_ID,
                peer=PEER_B, reply_to="cam1"),
        inbound("c3", 5, "2026-09-22T12:04:00Z", "那谁去买？", reply_to="c2"),
        outbound("o1", 6, "我去买", reply_to="c3", receipt_at="2026-09-22T12:05:00Z"),
    ]


def case_topic_filter_keeps_thread_continuations():
    """按主题整理必须带上不含主题词的链内后续；交错话题不得被拉进来。"""
    value, store = digest_of(thread_rows(), {"topic": "线缆"})
    assert value["source_ids"] == ["c1", "c2", "c3", "o1"], value["source_ids"]
    assert "cam1" not in value["source_ids"] and "cam2" not in value["source_ids"]
    correction = value["corrections"][0]
    assert correction["message_id"] == "c2" and "线缆" not in correction["text"]
    assert correction["basis"] == "reply_link" and correction["corrects"] == "c1"
    assert correction["thread"] is True
    assert value["open_items"] == []
    assert [item["message_id"] for item in value["resolved"]] == ["c3"]
    assert value["resolved"][0]["answered_by"] == "o1"
    assert value["resolved"][0]["answer_confirms"] is True
    cov = value["coverage"]
    assert (cov["read"], cov["matched"], cov["thread_extra"]) == (4, 1, 3), cov
    assert cov["complete"] is True and cov["thread"]["extra"] == 3
    assert cov["covered_from"] == "2026-09-22T12:00:00Z"
    assert cov["covered_to"] == "2026-09-22T12:05:00Z"
    assert any("同一 reply 链后续" in note for note in value["notes"]), value["notes"]
    assert "线程内后续" in value["text"] and "相机" not in value["text"]
    assert "我觉得那台更稳" not in value["text"]
    # 回读参数不能再带 topic：这条更正不含主题词，带了就会被 query_authorized_history 筛掉
    args = value["readback"]["example_args"]
    assert value["readback"]["topic_omitted"] is True and "query" not in args, value["readback"]
    assert value["readback"]["thread_source_ids"] == ["c2", "c3"], value["readback"]
    scene = {"scene_id": SCENE_ID, "scope_key": "scene:" + SCENE_ID, "policy_epoch": EPOCH}
    back = hq.query_history(None, store, scene, args.get("query", ""), person=args["person"],
                            since=args["since"], until=args["until"], limit=50)
    assert "c2" in [hit["message_id"] for hit in back["hits"]], back["hits"]
    # 不带 topic 时本来就会读到全部六条：补齐逻辑不改变无筛选那条路径
    plain, _store = digest_of(thread_rows())
    assert plain["coverage"]["read"] == 6 and plain["coverage"]["thread_extra"] == 0
    assert "cam2" in plain["source_ids"]


def case_thread_rows_outside_the_window_are_reported_not_invented():
    """链内后续落在请求窗口外：不假装读到，但要说有多少在窗口外。"""
    value, _store = digest_of(thread_rows(), {"topic": "线缆",
                                              "since": "2000-01-01",
                                              "until": "2026-09-22T12:03:00Z"})
    assert value["source_ids"] == ["c1", "c2"], value["source_ids"]
    assert value["coverage"]["thread"]["out_of_window"] == 2, value["coverage"]["thread"]
    assert any("窗口外" in note for note in value["notes"]), value["notes"]
    assert value["coverage"]["covered_to"] == "2026-09-22T12:02:00Z"



def seed_and_continuation_rows():
    """既是种子又是链上环节的形状：s1←x←s2，只有 s1/s2 含主题词，x 不含。"""
    return [inbound("s1", 1, "2026-09-22T12:00:00Z", "线缆初稿"),
            inbound("x", 2, "2026-09-22T12:01:00Z", "更正一下：日期改了", reply_to="s1"),
            inbound("s2", 3, "2026-09-22T12:02:00Z", "线缆新方案", reply_to="x")]


def person_scope_rows():
    """A 的首句含主题词，B 的 reply 更正不含：person=A 时 B 只能以链内上下文出现。"""
    return [inbound("a1", 1, "2026-09-22T12:00:00Z", "线缆初稿", author=A_ID, peer=PEER_A),
            inbound("b1", 2, "2026-09-22T12:01:00Z", "更正：第二格", author=B_ID, peer=PEER_B,
                    reply_to="a1")]


def long_thread_rows():
    """11 环连续 reply，只有首句含主题词：比 MAX_THREAD_ROUNDS 能走完的还长。"""
    rows = [inbound("m1", 1, "2026-09-22T12:00:00Z", "线缆走线图")]
    for n in range(2, 12):
        rows.append(inbound("m%d" % n, n, "2026-09-22T12:%02d:00Z" % n, "补充说明 %d" % n,
                            reply_to="m%d" % (n - 1)))
    return rows


def _pages(rows, args, cap=12):
    seen, cursor, pages = [], None, 0
    while True:
        value, _store = digest_of(rows, dict(args, cursor=cursor))
        seen += value["source_ids"]
        pages += 1
        assert pages < cap, "pagination must terminate"
        if not value["more"]:
            return value, seen
        cursor = value["next_cursor"]


def case_seed_and_continuation_are_not_delivered_twice():
    """跳页不重不漏：既是主题命中项又是链上环节的行只送一遍。"""
    rows = [inbound("i1", 1, "2026-09-22T12:00:00Z", "线缆初稿"),
            inbound("i2", 2, "2026-09-22T12:01:00Z", "线缆新方案", reply_to="i1")]
    last, seen = _pages(rows, dict(FULL, topic="线缆", limit=1))
    assert sorted(seen) == ["i1", "i2"], seen
    assert len(seen) == len(set(seen)), seen
    assert last["coverage"]["complete"] is True
    assert last["coverage"]["thread"]["skipped_seed_eligible"] == 1, last["coverage"]["thread"]
    # 链上环节被两页都链到：上一页送过的靠游标携带的去重集合跳过
    last, seen = _pages(seed_and_continuation_rows(), dict(FULL, topic="线缆", limit=1))
    assert sorted(seen) == ["s1", "s2", "x"], seen
    assert len(seen) == len(set(seen)), seen
    assert last["coverage"]["thread"]["skipped_carried"] == 1, last["coverage"]["thread"]
    assert any("不重复送" in note for note in last["notes"]), last["notes"]


def case_long_thread_reports_partial_not_fake_completeness():
    """链比上限还长：不能只因为主题命中项读完了就声称覆盖完整。"""
    value, _store = digest_of(long_thread_rows(), dict(FULL, topic="线缆"))
    assert value["source_ids"] == ["m%d" % n for n in range(1, 10)], value["source_ids"]
    assert "m10" not in value["source_ids"] and "m11" not in value["source_ids"]
    thread = value["coverage"]["thread"]
    assert thread["rounds"] == dd.MAX_THREAD_ROUNDS and thread["truncated"] is True
    assert thread["why"] == "thread_rounds_exhausted", thread
    assert value["more"] is True                       # 链没走完也算还有未读
    assert value["next_cursor"], "截断后必须有原筛选下的续页入口"
    assert thread["pending"] == ["m9"], thread         # 待走环节随游标带下去
    assert value["coverage"]["complete"] is False      # 整条讨论流没走完
    honest = [note for note in value["notes"] if "讨论流没完全展开" in note]
    assert honest and "部分完成" in honest[0] and "续页" in honest[0], value["notes"]
    assert "部分覆盖（讨论流没走完）" in value["text"]
    assert "覆盖完整" not in value["text"]


def case_long_thread_continues_to_the_end():
    """截断不是终点：带 cursor 沿同一筛选续读，能拿到 m10/m11（DECISIONS §3 部分结果可续）。"""
    rows = long_thread_rows()
    first, _store = digest_of(rows, dict(FULL, topic="线缆"))
    assert first["source_ids"] == ["m%d" % n for n in range(1, 10)], first["source_ids"]
    assert first["more"] is True and first["next_cursor"]
    second, _store = digest_of(rows, dict(FULL, topic="线缆", cursor=first["next_cursor"]))
    assert second["source_ids"] == ["m10", "m11"], second["source_ids"]
    assert second["more"] is False and second["next_cursor"] is None
    assert second["coverage"]["complete"] is True, second["coverage"]
    assert second["coverage"]["thread"]["resumed"] is True
    assert second["coverage"]["window"] == first["coverage"]["window"]   # 时间窗不随现在漂
    assert sorted(first["source_ids"] + second["source_ids"]) == sorted(
        ["m%d" % n for n in range(1, 12)]), "不重不漏"
    assert any("续读" in note for note in second["notes"]), second["notes"]
    assert "覆盖完整" in second["text"]


def case_person_scope_labels_thread_context():
    """person 只限定主题命中项是谁说的：链上带进来的别人要标出来，不冒充“只看 A”。"""
    value, _store = digest_of(person_scope_rows(), dict(FULL, topic="线缆", person=A_CARD))
    assert value["source_ids"] == ["a1", "b1"], value["source_ids"]
    assert value["coverage"]["person"] == A_CARD
    assert value["coverage"]["person_scope"] == "seed"
    assert value["coverage"]["person_context_rows"] == 1, value["coverage"]
    item = next(x for x in value["corrections"] if x["message_id"] == "b1")
    assert item["thread"] is True and item["person_match"] is False, item
    marks = dict((person["display"], person) for person in value["participants"])
    assert marks[A_CARD]["outside_person"] == 0 and marks[B_CARD]["outside_person"] == 1
    assert any("person 只限定主题命中项" in note for note in value["notes"]), value["notes"]
    assert "非 person 指定" in value["text"] and "thread_context" in value["text"]


def case_linkage_read_stays_inside_the_scene_fence():
    """链与身份块的批量读也带场景围栏：不拿别的场景的行来解释本场景的讨论。"""
    _value, store = digest_of(discussion_rows())
    reads = [flt for flt, _proj, _sort, _limit in store.db.messages.finds
             if isinstance(flt, dict) and "$in" in (flt.get("_id") or {})]
    assert reads, "没看到按 _id $in 的批量链读"
    for flt in reads:
        assert flt.get("scene_id") == SCENE_ID and flt.get("policy_epoch") == EPOCH, flt


CASES = [name for name in sorted(globals()) if name.startswith("case_")]


def run_all():
    results = []
    for name in CASES:
        try:
            globals()[name]()
            results.append((name, True, ""))
        except Exception as exc:
            results.append((name, False, "%s: %s" % (type(exc).__name__, exc)))
    return results


if __name__ == "__main__":
    failed = 0
    for name, ok, why in run_all():
        print("%s %s%s" % ("PASS" if ok else "FAIL", name, "" if ok else " -> " + why))
        failed += 0 if ok else 1
    print("%d/%d 通过" % (len(CASES) - failed, len(CASES)))
    sys.exit(1 if failed else 0)
