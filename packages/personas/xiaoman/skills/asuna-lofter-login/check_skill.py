#!/usr/bin/env python3
"""asuna-lofter-login 的零依赖离线自检。

这份技能是「不开浏览器登 LOFTER」的做法，所以这里查四件事：
1. 文件本身：frontmatter 能解析、name 与目录名一致、只在 home 可用、章节齐、三支探针能编译、换行是 LF（读字节数 CR）；
2. 内容要点：登录两步半与 4071 的正确读法、滑块的四步形状（取图／加密口径／回包两种解／一个 id 只用一次）、
   缺口两条硬口径（1:1 坐标＋四把投票）、登录态在哪与两条只读验通、凭据纪律、未核实清单、配额与停手、
   账号事实（域名与 blogId）只待在本机私有处那一个文件里（值出现在本目录任何文件即红）；
3. 家规：正文无日期与来历叙述；不带别人的个人信息（禁词表、本机私密名单——名单配不上或 0 条记红
   `leak_scan_ran`，「没跑」不许长得像「过了」）；正文不许出现手机号形状的数字串（凭据值不许进文件）；
   提到 TEMP 就必须带上「只活一条命令」那句。
4. 没有占位符残留；CHANGELOG.md 首条是「11-03 新建」。

不联网、不碰数据库、不发 QQ、不花 LOFTER 配额。

用法：
    python3 check_skill.py [SKILL.md 路径]        # 默认取脚本旁边的 SKILL.md
退出码 0 = 全绿；非 0 时最后一行写「N/M 通过，失败：<检查名>」。
"""
import os
import re
import sys

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8")

HERE = os.path.dirname(os.path.abspath(__file__))
EXPECTED_NAME = os.path.basename(HERE)

SECTIONS = [
    "## 什么时候读这一份",
    "## 凭据（先定死这一条）",
    "## 登录（两步半）",
    "## 滑块：纯 HTTP，不用浏览器",
    "## 缺口 xPos 的两条硬口径",
    "## 登录态放在哪、怎么验通",
    "## 探针（同目录，全在一趟沙箱里跑）",
    "## 未核实（别当已核实）",
    "## 配额与停手",
]

# 登录两步半
LOGIN = [
    ("login_endpoint", "lpt/login.do?product=lofter-pc"),
    ("login_body_passport_sha256", "sha256(密码)"),
    ("login_body_fields", "`clientType=0`"),
    ("login_body_target", "Target=www.lofter.com"),
    ("login_answer_4071", "meta.status=4071"),
    ("login_4071_means_gate", "服务端把验证挡在验密之前"),
    ("login_4071_not_password", "不许改成密码重试"),
    ("login_retry_with_ticket", "`capttoken: <票据>`"),
    ("login_success_token_len", "96 位"),
]

# 滑块的 HTTP 形状
CAPTCHA = [
    ("captcha_get_url", "captcha.lofter.com/captcha/get?type=jigsaw"),
    ("captcha_get_parts", "`front`（拼图条 base64）"),
    ("captcha_check_body_raw_bytes", "请求体是密文的原始字节"),
    ("captcha_data_is_string", "`data` 是字符串"),
    ("captcha_aes", "AES-128-CBC"),
    ("captcha_key_shape", "每位 50% 数字 0-8"),
    ("captcha_seckey_header", "X-EncSecKey"),
    ("captcha_rsa", "RSA PKCS#1 v1.5"),
    ("captcha_answer_two_shapes", "外面再套一层 base64"),
    ("captcha_ticket_len", "32 位"),
    ("captcha_id_single_use", "别拿同一个 id 再 check 第二次"),
]

# 缺口两条硬口径
XPOS = [
    ("xpos_definition", "拼图条左边缘在 bg 原图坐标里的 x"),
    ("xpos_1to1", "显示宽 320 ＝ natural 宽"),
    ("xpos_piece_columns", "front` 的 alpha 量"),
    ("xpos_vote_required", "必须多算法投票，单把不许发"),
    ("xpos_algo_edge", "边缘轮廓打分"),
    ("xpos_algo_dark", "洞内暗度"),
    ("xpos_algo_ncc", "模糊 NCC"),
    ("xpos_algo_seam", "接缝色差"),
    ("xpos_take_median", "取一致区间的中值"),
    ("xpos_eye_wrong", "判成 195"),
    ("xpos_true_range", "166–169"),
    ("xpos_wrong_cause", "白色蒸汽的低饱和区"),
    ("xpos_eye_is_reference_only", "不当结论"),
]

# 登录态与验通
STATE = [
    ("state_is_body_token", "服务端不下发登录态 cookie"),
    ("state_only_tracking_cookie", "usertrack"),
    ("state_plant_like_frontend", "LOFTER-PHONE-LOGIN-AUTH"),
    ("state_api_header", "lofter-phone-login-auth"),
    ("verify_logincheck", "loginCheck.do"),
    ("verify_401_to_200", "401→200"),
    ("verify_collection_api", "postCollection.api"),
    ("verify_collection_meta_ok", "`meta.status` 200 为通"),
    ("account_facts_pointer", "lofter-account.txt"),
    ("account_keys_in_body", "`blogId`"),
    ("account_values_stay_private", "不抄进正文"),
]

# 凭据纪律
CRED = [
    ("cred_vault_name", "`xiaoman-lofter`"),
    ("cred_env_phone", "`LOFTER_PHONE`"),
    ("cred_env_pass", "`LOFTER_PASS`"),
    ("cred_token_is_secret", "那枚 96 位 token 本身就是凭据"),
    ("cred_phone_shape_rule", "剥国家码"),
]

# 未核实清单（一条都不许被写成事实）
UNVERIFIED = [
    ("unverified_ttl", "登录态的服务端 TTL 未知"),
    ("unverified_maxage_unit", "864e6"),
    ("unverified_replay", "跨会话重放未实测"),
    ("unverified_next_login", "下次登录还弹不弹滑块未知"),
    ("unverified_egress_sample", "一个样本，没核实"),
    ("unverified_write_path", "发文与写路径没有公开文档"),
    ("unverified_post_not_proven", "「能发帖」这句没验证过"),
]

# 配额与停手
BUDGET = [
    ("budget_one_or_two", "每次一到两次预算"),
    ("budget_no_hammering", "别循环 hammering"),
    ("budget_stop_on_new_shape", "4071 之外的新风控形状"),
    ("budget_stop_immediately", "即停"),
    ("budget_no_variants", "不试第二下"),
    ("stop_report_three", "停在哪一步"),
]

# 探针脚本
PROBES = ["captcha_stage_a.py", "captcha_stage_b.py", "lofter_login_probe.py"]
PROBE_ANCHORS = [
    ("probe_a_four_algos", ("captcha_stage_a.py", ["edge_peak", "dark_min", "ncc_peak", "seam_min"])),
    ("probe_a_vote_gate", ("captcha_stage_a.py", ["return None, \"四把凑不出", "--front"])),
    ("probe_b_encrypt", ("captcha_stage_b.py", ["PKCS7", "PKCS1v15", "X-EncSecKey", "capttoken"])),
    ("probe_b_single_shot", ("captcha_stage_b.py", ["唯一一次登录", "loginCheck.do", "postCollection.api"])),
    ("probe_login_env_only", ("lofter_login_probe.py", ["os.environ.get(\"LOFTER_PHONE\"",
                                                        "os.environ.get(\"LOFTER_PASS\"",
                                                        "loginCheck.do"])),
]

# 别人的个人信息不进技能：称呼与场景词。出现即红（具体人名群名由本机私密名单拦，见下）。
PERSONAL_TOKENS = ["主人", "旧居", "交流群", "姐姐", "金主"]

# 正文不许出现凭据值：手机号形状（11 位、1 开头）的数字串
PHONE_SHAPE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")

# 日期与来历：正文只写做法，日期与来路进 CHANGELOG
DATE_SHAPES = [
    (r"20\d{2}-\d{1,2}-\d{1,2}", "ISO 日期"),
    (r"20\d{2}年", "年份"),
    (r"(?<![\d.])\d{1,2}月\d{1,2}日", "几月几日"),
    (r"(?<![\d.])\d{1,2}月[初中下旬底]", "几月上旬"),
    (r"(?<![\d.])\d{1,2}[-/]\d{1,2}[日号]", "几号"),
]
PROVENANCE = ["来路", "实测于", "本次任务", "task-"]

LITERAL_ID = re.compile(r"(?<!PKCS)#\d")           # PKCS#1 这类密码学名字不算字面编号
PLACEHOLDER = re.compile(r"\bTODO\b|\bTBD\b|\bFIXME\b")


def private_list():
    """本机私密名单（private_words 工具维护，不进仓库）。返回 (路径或候选, [(行号, 类别, 词)])。"""
    named = os.environ.get("ASUNA_PRIVATE_WORDS")
    data = os.environ.get("ASUNA_DATA_ROOT")
    if not data:
        try:
            from asuna import config as asuna_config
            data = str(asuna_config.DATA)
        except Exception:                                   # noqa: BLE001 没装 asuna 也要能跑
            data = None
    candidates = []
    if named:
        candidates.append(named)
    if data:
        candidates.append(os.path.join(data, "private", "personal-words.txt"))
    here = HERE                                             # 兜底：往上找 <部署根>/.runtime/private/
    for _ in range(12):
        here = os.path.dirname(here)
        if not here:
            break
        candidates.append(os.path.join(here, ".runtime", "private", "personal-words.txt"))
    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        entries = []
        with open(path, encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                parts = line.strip().split("|", 2)
                if line.strip() and not line.startswith("#") and len(parts) == 3 and parts[1].strip():
                    entries.append((number, parts[0].strip(), parts[1].strip()))
        return path, entries
    return [c for c in candidates if c] or None, None


def listed_hits(entries, text):
    hits = []
    for number, category, word in entries:
        if all(ch.isascii() for ch in word):
            found = re.search(r"(?<![A-Za-z0-9_])" + re.escape(word) + r"(?![A-Za-z0-9_])", text, re.IGNORECASE)
        else:
            found = word in text
        if found:
            hits.append("%s（名单第 %d 行）" % (category, number))
    return hits


# 账号事实（域名与 blogId）不进正文与脚本，待在本机私有处这一个文件里；定位口径同私密名单。
ACCOUNT_FILE = "lofter-account.txt"
ACCOUNT_ENV = "ASUNA_LOFTER_ACCOUNT"
DOMAIN_SHAPE = re.compile(r"^[a-z0-9][a-z0-9-]*\.lofter\.com$")
BLOGID_SHAPE = re.compile(r"^\d{6,12}$")


def account_file():
    """本机私有处的账号事实文件（key=value，不进仓库）。返回 (路径或候选, {键: 值})。"""
    named = os.environ.get(ACCOUNT_ENV)
    data = os.environ.get("ASUNA_DATA_ROOT")
    if not data:
        try:
            from asuna import config as asuna_config
            data = str(asuna_config.DATA)
        except Exception:                                   # noqa: BLE001 没装 asuna 也要能跑
            data = None
    candidates = []
    if named:
        candidates.append(named)
    if data:
        candidates.append(os.path.join(data, "private", ACCOUNT_FILE))
    here = HERE                                             # 兜底：往上找 <部署根>/.runtime/private/
    for _ in range(12):
        here = os.path.dirname(here)
        if not here:
            break
        candidates.append(os.path.join(here, ".runtime", "private", ACCOUNT_FILE))
    for path in candidates:
        if not path or not os.path.isfile(path):
            continue
        values = {}
        with open(path, encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip()
        return path, values
    return [c for c in candidates if c] or None, None


def read_frontmatter(text):
    if not text.startswith("---"):
        return None, text
    end = text.find("\n---", 3)
    if end == -1:
        return None, text
    head, body = text[3:end].strip("\n"), text[end + 4:]
    fields = {}
    for line in head.splitlines():
        m = re.match(r"^([A-Za-z_][A-Za-z0-9_-]*):\s?(.*)$", line)
        if m:
            fields[m.group(1)] = m.group(2).strip()
    return fields, body


def dir_files():
    return sorted(os.path.join(HERE, f) for f in os.listdir(HERE)
                  if f.endswith((".md", ".py")) and os.path.isfile(os.path.join(HERE, f)))


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "SKILL.md")
    results = []

    def check(name, ok, detail=""):
        results.append((name, bool(ok), detail))

    try:
        text = open(path, encoding="utf-8").read()
    except OSError as exc:                                  # noqa: BLE001
        print("读不到 SKILL.md：%s" % exc)
        print("0/1 通过，失败：read_skill")
        return 1

    fields, body = read_frontmatter(text)
    check("frontmatter_parses", fields is not None, "缺 frontmatter 或没收尾")
    check("name_matches_dir", fields and fields.get("name") == EXPECTED_NAME,
          "name=%r 目录=%s" % (fields.get("name") if fields else None, EXPECTED_NAME))
    desc = (fields or {}).get("description", "")
    check("description_present", len(desc) >= 80, "description 太短：只有 %d 字" % len(desc))
    check("description_says_4071", "4071" in desc)
    check("description_says_vote", "投票" in desc)
    check("description_says_unverified", "未核实" in desc)
    check("scene_kinds_home_only", fields and fields.get("scene_kinds") == "[home]",
          "scene_kinds=%r（这份要用保险箱，只在 home）" % ((fields or {}).get("scene_kinds")))

    for section in SECTIONS:
        check("section_" + section.replace(" ", "_")[:40], section in text, "少了这一节：" + section)

    for name, token in LOGIN + CAPTCHA + XPOS + STATE + CRED + UNVERIFIED + BUDGET:
        check(name, token in body, "少了这一条：%s" % token)

    # 探针：文件在、能编译、关键形状在
    for probe in PROBES:
        p = os.path.join(HERE, probe)
        check("probe_exists_" + probe.replace(".py", ""), os.path.isfile(p), "少了探针 " + probe)
        if os.path.isfile(p):
            src = open(p, encoding="utf-8").read()
            try:
                compile(src, p, "exec")
                ok, why = True, ""
            except SyntaxError as exc:
                ok, why = False, "编译不过：%s" % exc
            check("probe_compiles_" + probe.replace(".py", ""), ok, why)
    for name, (probe, tokens) in PROBE_ANCHORS:
        p = os.path.join(HERE, probe)
        src = open(p, encoding="utf-8").read() if os.path.isfile(p) else ""
        missing = [t for t in tokens if t not in src]
        check(name, not missing, "%s 里少了：%s" % (probe, "、".join(missing)))

    # 家规：正文无日期无来历；无手机号形状的数字；禁词表
    for pattern, label in DATE_SHAPES:
        hit = re.search(pattern, body)
        check("no_date_" + label, not hit, "正文出现%s（%r）——日期写进 CHANGELOG" % (label, hit.group(0) if hit else ""))
    for word in PROVENANCE:
        check("no_provenance_" + word, word not in body, "正文写了来历词「%s」——挪进 CHANGELOG" % word)
    phone = PHONE_SHAPE.search(body)
    check("no_phone_shape_digits", not phone, "正文有手机号形状的数字串：%r（凭据值不许进文件）"
          % (phone.group(0) if phone else ""))
    for token in PERSONAL_TOKENS:
        check("no_personal_" + token, token not in body, "正文出现「%s」" % token)
    check("no_literal_ids", not LITERAL_ID.search(body), "正文用了字面编号 #N（只该写占位的「#编号」）")
    check("no_placeholders", not PLACEHOLDER.search(text), "有 TODO／TBD／FIXME 残留")
    check("temp_rule_present_when_temp_mentioned", ("TEMP" not in body) or ("只活一条命令" in body),
          "正文提到 TEMP 却没写「只活一条命令」那句")

    # 换行必须是 LF（读字节数 CR，文本模式看不见 CR）
    cr_files = []
    for f in dir_files():
        count = open(f, "rb").read().count(b"\r")
        if count:
            cr_files.append("%s（%d 个 CR）" % (os.path.basename(f), count))
    check("no_crlf", not cr_files, "有 CR：" + "、".join(cr_files))

    # CHANGELOG 首条
    notes_path = os.path.join(HERE, "CHANGELOG.md")
    notes = open(notes_path, encoding="utf-8").read() if os.path.isfile(notes_path) else ""
    check("changelog_first_entry", notes.startswith("# CHANGELOG · asuna-lofter-login")
          and "- 11-03 新建" in notes[:1200], "CHANGELOG.md 缺首条「- 11-03 新建」")

    # 账号事实：值只许待在本机私有处那一个文件里，技能目录任何文件带上值就红
    acct_source, acct = account_file()
    if isinstance(acct_source, list):                     # 候选路径一个都没落上
        why_missing = "私有文件没落：本机账号事实文件一个都没找到（试了 %s）" % "、".join(acct_source)
    else:                                                 # 文件在，但里面没那两个键
        why_missing = "私有文件没落：读到了 %s，但里面没读到 blogdomain／blogId 两个键" % acct_source
    check("account_file_found", bool(acct),
          why_missing + "——这一格不许「没跑」长得像「过了」")
    if acct:
        domain, blog_id = acct.get("blogdomain", ""), acct.get("blogId", "")
        check("account_domain_shape", bool(DOMAIN_SHAPE.match(domain)),
              "blogdomain 形状不对：%d 段、%d 字（应为 <标签>.lofter.com）" % (domain.count(".") + 1, len(domain)))
        check("account_blogid_shape", bool(BLOGID_SHAPE.match(blog_id)),
              "blogId 不是 6-12 位纯数字：%d 字" % len(blog_id))
        leaked = []
        for f in dir_files():
            one = open(f, encoding="utf-8", errors="ignore").read()
            hit = [k for k, v in acct.items() if v and v in one]
            if hit:
                leaked.append("%s：%s" % (os.path.basename(f), "、".join(hit)))
        check("account_values_not_in_skill_text", not leaked,
              "账号事实的值出现在技能目录：" + "；".join(leaked))

    # 泄露扫描：本目录每个文件都扫本机私密名单（名单配不上或空 → leak_scan_ran 红）
    source, entries = private_list()
    check("leak_scan_ran", bool(entries),
          "读不到本机私密名单（试了 %s）——这一格不许「没跑」长得像「过了」"
          % ("、".join(source) if isinstance(source, list) else repr(source)))
    leak_note = ""
    if entries:
        bad = []
        for f in dir_files():
            hits = listed_hits(entries, open(f, encoding="utf-8", errors="ignore").read())
            if hits:
                bad.append("%s：%s" % (os.path.basename(f), "、".join(hits)))
        check("no_listed_words", not bad, "命中本机私密名单：" + "；".join(bad))
        leak_note = "，泄露扫描真扫（名单 %d 条）" % len(entries)
    else:
        leak_note = "（泄露扫描没跑：名单读不到）"

    notes_extra = []
    if any(d == "__pycache__" for d in os.listdir(HERE)):
        notes_extra.append("NOTE 技能目录里有 __pycache__，发布前清掉")

    total = len(results)
    failed = [name for name, ok, _ in results if not ok]
    for name, ok, detail in results:
        if not ok and detail:
            print("FAIL %s  <- %s" % (name, detail))
    for line in notes_extra:
        print(line)
    if failed:
        print("%d/%d 通过，失败：%s" % (total - len(failed), total, ", ".join(failed)))
        return 1
    print("%d/%d 通过：登录两步半、滑块形状、缺口两条硬口径、登录态与验通、凭据纪律、未核实、配额停手齐全，"
          "三支探针能编译，正文无日期无来历无凭据值%s。" % (total, total, leak_note))
    return 0


if __name__ == "__main__":
    sys.exit(main())
