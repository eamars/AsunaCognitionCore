/* Native DSH Client contribution. React and controls come from the Host bundle.
 *
 * Every word this UI shows comes from the `asuna` locale namespace (zh, en) and follows DSH's
 * language setting; only her own content (what she says and thinks, her documents, her persona's
 * names and words) is shown in the persona's language (ADR-011 §2.8). */
window.__ModuleLoader__.load({ id: '@asuna/cognition-core', factory: require => {
  const React = require('react');
  const primitives = require('@deepseek-ai/dsh-client-ui-primitives');
  const { Button, Input, Menu, Pill, IconChevronDownOutlineRegular, DisclosureRow, MarkdownText, SettingsForm,
    SettingsFormModel, SettingsValueField, SettingsSecretField } = primitives;
  const h = React.createElement;
  const NS = 'asuna';

  // ── words ───────────────────────────────────────────────────────────
  const DICTIONARY = {
    zh: {
      'date.locale': 'zh-CN',
      'brain.character': '角色脑', 'brain.executor': '行动脑',
      'trigger.message': '收到消息', 'trigger.task_result': '行动脑交回了结果', 'trigger.question': '行动脑在问她',
      'trigger.internal': '她的内部时间', 'trigger.visit': '她自己来看看', 'trigger.note': '她自己留的便条', 'trigger.schedule': '到了安排的时间', 'trigger.brief': '她的交代',
      'trigger.follow-up': '她的补充',
      'collab.header': '{character} ⇄ {action}', 'collab.untitled': '一件事',
      'collab.state.queued': '排队中', 'collab.state.running': '进行中', 'collab.state.waiting': '等她回答',
      'collab.state.done': '已完成', 'collab.state.failed': '没做成', 'collab.state.stopped': '已叫停',
      'collab.state.paused': '已暂停', 'collab.paused': '宿主重启时暂停了；要接着做，在本机私聊里请她继续。',
      'workspace.local': '本机', 'session.group': '群聊', 'session.dm': '私聊',
      'collab.state.continued': '下面接着', 'collab.working': '正在做 {duration}', 'collab.watch': '展开看实时过程',
      'collab.stopped': '已叫停：{reason}', 'collab.open': '在侧栏打开完整过程',
      'collab.work': '工作了 {duration}', 'collab.call': '{n} 次工具调用', 'collab.calls': '{n} 次工具调用', 'collab.loading': '读取行动脑记录…',
      'collab.more': '展开全文', 'collab.less': '收起', 'collab.progress': '进展',
      'duration.seconds': '{n} 秒', 'duration.minutes': '{n} 分钟', 'duration.hours': '{h} 小时 {m} 分钟',
      'tool.think': '心里话', 'tool.recall': '回想', 'tool.delegate': '交给行动脑', 'tool.message_action': '给行动脑补话',
      'tool.stop_action': '叫停', 'tool.answer_action': '回答行动脑', 'tool.stay_silent': '不说话',
      'tool.attach_image': '配图', 'tool.write_document': '写文档', 'tool.update_self': '更新自我',
      'tool.understand_person': '理解这个人', 'tool.set_policy': '调参数', 'tool.pin_memory': '置顶记忆',
      'tool.feel': '心情', 'tool.plan': '安排', 'tool.group_action': '群管理', 'tool.promote_memory': '沉淀记忆',
      'tool.visit': '出门', 'tool.note_idea': '记想法', 'tool.read_ideas': '读想法本', 'tool.review_idea': '处理想法', 'tool.ask_character': '问她', 'tool.report_progress': '报进展',
      'tool.refused': '被退回', 'tool.preparing': '正在写…', 'repair.title': '草稿退回重写',
      'input.checking': '正在确认会话输入权限…', 'input.internal': '这是内部工作会话，请回到本地私聊。',
      'input.readOnly': '{platform} 会话仅供查看，请在 {platform} 中回复。', 'input.readOnlyLocal': '这个会话仅供查看。',
      'markdown.copy': '复制', 'markdown.copied': '已复制', 'markdown.footnotes': '来源',
      'memory.tab': '记忆', 'memory.guide': '当前角色、场景与授权来源', 'memory.aria': 'Asuna 记忆',
      'memory.category': '记忆类型', 'memory.search': '搜索记忆', 'memory.searchPlaceholder': '搜索当前类型的全部记录',
      'memory.refresh': '刷新记忆', 'memory.subject': '当前交谈对象：{name}', 'memory.linked': '也能读到：{titles}',
      'memory.notBound': '当前会话尚无 Asuna 场景绑定。完成角色交互后可查看。', 'memory.loading': '读取当前场景…',
      'memory.detailLoading': '读取详情…', 'memory.revision': '版本 {n}', 'memory.compiled': '整理于 {time}',
      'memory.sourcesTruncated': '以下显示前 12 条来源。', 'memory.noMatch': '未找到匹配的记录。',
      'memory.empty': '当前范围暂无记录。', 'memory.previous': '上一页', 'memory.next': '下一页',
      'memory.corrected': '这条记录之后出现了更正；请结合后续原话查看。', 'memory.separator': '、',
      'memory.kind.all': '全部', 'memory.kind.documents': '文档', 'memory.kind.affect': '情感', 'memory.kind.jobs': '作业报告',
      'memory.kind.ideas': '改进想法', 'memory.category.idea': '改进想法',
      'memory.idea.state.open': '待处理', 'memory.idea.state.adopted': '已采纳', 'memory.idea.state.deferred': '暂缓',
      'memory.idea.state.dropped': '已放弃', 'memory.idea.why': '为什么：{text}', 'memory.idea.from.character': '她自己记下的 · {where}',
      'memory.idea.from.action': '行动脑做事时记下的 · {where}', 'memory.idea.decision.adopt': '采纳：{why}',
      'memory.idea.decision.defer': '暂缓：{why}', 'memory.idea.decision.drop': '放弃：{why}',
      'memory.status.idea.open': '待处理', 'memory.status.idea.adopted': '已采纳', 'memory.status.idea.deferred': '暂缓',
      'memory.status.idea.dropped': '已放弃',
      'memory.kind.self': '自我', 'memory.kind.relation': '对人的认识', 'memory.kind.summary': '交流摘要',
      'memory.kind.interpretation': '当时的理解', 'memory.kind.source': '原始来源',
      'memory.category.self': '自我', 'memory.category.relation': '对人的认识', 'memory.category.derived_summary': '交流摘要',
      'memory.category.character_interpretation': '当时的理解', 'memory.category.public_statement': '角色的发言',
      'memory.category.reported_speech': '他人的原话', 'memory.category.observed_fact': '事实记录',
      'memory.category.source': '原始消息', 'memory.category.document': '文档', 'memory.category.affect': '情感',
      'memory.category.affect_event': '情感', 'memory.category.persona_job_report': '作业报告', 'memory.category.other': '记忆',
      'memory.status.empty': '还没有写过', 'memory.status.recorded': '已记录',
      'memory.hint.self': '她只在每天一次的内部自省时间里决定要不要写下或改写。',
      'memory.hint.relation': '她在对话中觉得对这个人的理解有了变化时才会写下。',
      'memory.title.character_core': '核心自我', 'memory.title.current_self': '当前自我', 'memory.title.relation': '关系与偏好',
      'memory.title.peer': '对方身份资料', 'memory.title.mood': '此刻的心情', 'memory.title.moved': '触动 · {feeling}',
      'memory.title.job': '作业报告', 'memory.title.said': '原话 · {speaker}', 'memory.title.blank': '无正文的记忆',
      'memory.title.document': '{kind}', 'memory.title.documentNamed': '{kind} · {name}',
      'memory.doc.persona': '人格设定', 'memory.doc.voice': '说话方式', 'memory.doc.ledger': '承诺与挂账',
      'memory.doc.working': '工作笔记', 'memory.doc.other': '文档',
      'memory.doc.sections': '{label} {n} 节', 'memory.doc.overBudget': '超出渲染预算',
      'memory.visibility.public': '公开', 'memory.visibility.owner_private': '仅主人可见',
      'memory.inject.always': '每轮都用', 'memory.inject.on_demand': '相关时才用', 'memory.inject.never': '不放进对话',
      'memory.mood.calm': '平静', 'memory.mood.line': '{label} · 心情 {val} · 激动 {arl}{open}', 'memory.mood.open': ' · {n} 件事还挂着',
      'memory.mood.head': '**{label}**（心情 {val}，范围 −100～100；激动 {arl}，范围 0～100）',
      'memory.mood.policy': '此刻的倾向：{text}', 'memory.mood.tendencies': '主要的情绪带来：{text}', 'memory.mood.from': '来自：',
      'memory.mood.contribution': '- {feeling} · 心情 {val} · 激动 {arl} · {ago}{held}：{why}', 'memory.mood.held': '（还挂着，不会淡去）',
      'memory.mood.fade': '每件触动会随时间淡去（各种情绪淡得快慢不同）；还挂着的事要等了结后才开始淡。',
      'memory.event.line': '心情 {val} · 激动 {arl}{held} · {why}', 'memory.event.held': ' · 还挂着',
      'memory.event.kind': '种类：{feeling} · 心情 {val} · 激动 {arl}', 'memory.event.cost': '代价：{text}',
      'memory.event.open': '这是一件还挂着的事：了结之前不会淡去。', 'memory.event.noReason': '（未写原因）',
      'memory.amendment.close': '已了结：{why}', 'memory.amendment.void': '作废（前提不成立）：{why}', 'memory.amendment.fix_ts': '更正时间：{why}',
      'memory.amendment.fix_kind': '更正种类：{why}', 'memory.doc.meta': '*{visibility} · {inject}{date}*',
      'memory.report.status': '状态：{status} · 作业 {job} · {run}',
      'memory.ago.now': '刚才', 'memory.ago.minutes': '{n} 分钟前', 'memory.ago.hours': '{n} 小时前', 'memory.ago.days': '{n} 天前',
      'memory.scene.shared': '所有对话共用', 'memory.scene.local': '本地聊天', 'memory.scene.group': '群聊 · {name}',
      'memory.scene.dm': '私聊 · {name}',
      'memory.usage.none': '这个对话还没有可核对的一轮', 'memory.usage.used': '最近一轮（{time}）用到了这一版',
      'memory.usage.older': '最近一轮（{time}）用的还是旧版本', 'memory.usage.formed': '最近一轮形成的理解，保存在该轮原生会话中',
      'memory.usage.input': '是最近一轮（{time}）的输入', 'memory.usage.unused': '最近一轮（{time}）没有用到',
      'memory.readback': '——回读（{path} 第 {from}–{to} 行，导入时快照）——',
      'settings.loading': '读取设置…', 'settings.unavailable': '配置暂不可用。', 'settings.aria': 'Asuna 设置',
      'settings.persona': '当前角色', 'settings.channelAdmission': '外部渠道接入策略', 'settings.python': 'Python',
     
      'settings.route': '{brain} · {field}', 'settings.route.provider': '模型服务', 'settings.route.model': '模型',
      'settings.route.reasoningEffort': '推理强度', 'settings.route.maxTokens': '最大输出 token',
      'settings.newSecrets': '新增或更新凭据（JSON）', 'settings.overridden': '已覆盖', 'settings.reset': '恢复默认',
      'settings.choose': '请选择', 'settings.unavailableValue': '{value}（当前不可用）',
      'settings.admission.automatic': '自动接入私聊、群及新成员', 'settings.admission.explicit': '仅接入已配置身份',
      'settings.providerDefault': '使用模型服务默认值', 'settings.routeHint': '选项来自 DSH 已配置的模型服务及其能力。',
      'settings.secretMapHint': '例如 {"ASUNA_CHANNELS_NEW_TOKEN":"值"}：存进凭据库，设置里只写引用。只更新列出的名称；留空不修改。', 'settings.secretHint': '留空保留现有凭据。',
      'settings.secretAdd': '可添加凭据引用', 'settings.secretSet': '已配置', 'settings.secretUnset': '未配置',
      'settings.jsonHint': 'JSON 配置；凭据使用 {"$secret":"名称"} 引用。', 'settings.pythonHint': '留空：首次启动时在数据目录里按包里的锁文件建好 Python 环境（需要 uv 或 Python 3.12+）。', 'settings.invalidNumber': '请输入正整数',
      'settings.invalidJson': '请输入有效的 JSON 值', 'settings.form.unavailable': '配置暂不可用', 'settings.form.readOnly': '当前配置只读',
      'settings.form.saveFailed': '保存失败，草稿已保留。', 'settings.form.save': '保存设置', 'settings.form.saving': '保存中…',
      'settings.status': '业务 worker：{state} · Mongo：{database}', 'settings.disconnected': '未连接',
      'settings.restartWaiting': '{project} 的已发布改动（{time}）要重启宿主后才生效；在那之前夜里的自我开发会跳过。',
      'settings.readingStatus': '读取状态…',
      'settings.note': '配置由 DSH 保存；凭据只写不回显。模型与 API key 在 DSH 原生 provider 设置管理。会话中的模型选择优先于下方默认路由。',
      'settings.savedPending': '已保存，尚未应用。', 'settings.savedApplied': '已保存，与当前应用配置一致。',
      'settings.activated': '已应用到业务 worker 与后续模型请求。',
      'settings.selfSource': '自我来源：{source}', 'settings.waiting': '等待连接', 'settings.channelsFallback': '外部渠道',
      'settings.channels': '{titles}：{state}', 'settings.channelOn': '本机入口已启动；适配器 {state}；平台连接未验证',
      'settings.channelOff': '未启用', 'settings.schedule': '定时：{state}', 'settings.sandbox': '沙箱：{state}', 'settings.sandboxNone': '无（{reason}）：跑代码、自开发与集成已关闭', 'settings.scheduleOn': '原生调度',
      'settings.pending': '已保存的配置尚未应用。', 'settings.applied': '保存配置与当前应用配置一致。',
      'settings.apply': '应用已保存设置', 'settings.refresh': '刷新状态',
      'persona.aria': '人格数据', 'persona.title': '人格数据 · {persona}',
      'persona.render': '人格渲染估算 {estimate} / 上限 {limit}', 'persona.unlimited': '未设', 'persona.overBudget': '超出预算',
      'persona.sources': '源根：{list}', 'persona.source': '{id}（{state}，{path}）', 'persona.noSources': '未配置源根（本机配置 persona_sources）。',
      'persona.job': '作业 {id} · 源根 {sources}', 'persona.dryRun': '试运行', 'persona.run': '运行',
      'persona.runs': '最近运行：{list}', 'persona.runDry': '（试）', 'persona.export': '导出文档',
      'persona.exportUnset': '导出（未配置 export_dir）', 'persona.exported': '已导出 {n} 份文档。',
      'persona.jobResult': '作业 {job}{dry}：{status}{code}{reason} · 报告在「记忆 → 作业报告」中查看。',
      'persona.exitCode': ' · 退出码 {code}',
    },
    en: {
      'date.locale': 'en-US',
      'brain.character': 'Character brain', 'brain.executor': 'Action brain',
      'trigger.message': 'Message received', 'trigger.task_result': 'The action brain reported back',
      'trigger.question': 'The action brain asks her', 'trigger.internal': 'Her inner time', 'trigger.visit': 'Her own visit', 'trigger.note': 'A note from herself', 'trigger.schedule': 'A plan came due',
      'trigger.brief': 'Her brief', 'trigger.follow-up': 'Her follow-up',
      'collab.header': '{character} ⇄ {action}', 'collab.untitled': 'A task',
      'collab.state.queued': 'Queued', 'collab.state.running': 'In progress', 'collab.state.waiting': 'Waiting for her answer',
      'collab.state.done': 'Done', 'collab.state.failed': 'Not finished', 'collab.state.stopped': 'Stopped',
      'collab.state.paused': 'Paused', 'collab.paused': 'Paused when the Host restarted; ask her in the local chat to continue.',
      'workspace.local': 'Local', 'session.group': 'Group chat', 'session.dm': 'Direct message',
      'collab.state.continued': 'Continued below', 'collab.working': 'Working {duration}', 'collab.watch': 'Expand to watch it live',
      'collab.stopped': 'Stopped: {reason}', 'collab.open': 'Open the full record in the sidebar',
      'collab.work': 'Worked {duration}', 'collab.call': '{n} tool call', 'collab.calls': '{n} tool calls', 'collab.loading': 'Loading the action brain’s record…',
      'collab.more': 'Show all', 'collab.less': 'Show less', 'collab.progress': 'Progress',
      'duration.seconds': '{n}s', 'duration.minutes': '{n} min', 'duration.hours': '{h} h {m} min',
      'tool.think': 'Thought', 'tool.recall': 'Recall', 'tool.delegate': 'Hand to the action brain',
      'tool.message_action': 'Message the action brain', 'tool.stop_action': 'Stop a task', 'tool.answer_action': 'Answer the action brain',
      'tool.stay_silent': 'Stay silent', 'tool.attach_image': 'Attach a picture', 'tool.write_document': 'Write document',
      'tool.update_self': 'Update self', 'tool.understand_person': 'Understand this person', 'tool.set_policy': 'Adjust a setting',
      'tool.pin_memory': 'Pin a memory', 'tool.feel': 'Feeling', 'tool.plan': 'Plan', 'tool.group_action': 'Group action',
      'tool.promote_memory': 'Keep a memory', 'tool.visit': 'Go and see a group', 'tool.note_idea': 'Note an idea', 'tool.read_ideas': 'Read her ideas', 'tool.review_idea': 'Review an idea', 'tool.ask_character': 'Ask her',
      'tool.report_progress': 'Report progress', 'tool.refused': 'Refused', 'tool.preparing': 'Writing…',
      'repair.title': 'Draft sent back',
      'input.checking': 'Checking who may write here…', 'input.internal': 'This is an internal work conversation; go back to the local chat.',
      'input.readOnly': '{platform} conversations are read-only here; reply in {platform}.', 'input.readOnlyLocal': 'This conversation is read-only.',
      'markdown.copy': 'Copy', 'markdown.copied': 'Copied', 'markdown.footnotes': 'Sources',
      'memory.tab': 'Memory', 'memory.guide': 'The character, this scene and its authorized sources', 'memory.aria': 'Asuna memory',
      'memory.category': 'Kind of memory', 'memory.search': 'Search memory', 'memory.searchPlaceholder': 'Search every record of this kind',
      'memory.refresh': 'Refresh', 'memory.subject': 'Talking with: {name}', 'memory.linked': 'Also reads: {titles}',
      'memory.notBound': 'This conversation has no Asuna scene yet. It appears after she has taken part.',
      'memory.loading': 'Loading this scene…', 'memory.detailLoading': 'Loading…', 'memory.revision': 'Revision {n}',
      'memory.compiled': 'Compiled {time}', 'memory.sourcesTruncated': 'Showing the first 12 sources.',
      'memory.noMatch': 'No matching records.', 'memory.empty': 'Nothing here yet.', 'memory.previous': 'Previous', 'memory.next': 'Next',
      'memory.corrected': 'This record was corrected later; read it with the later messages.', 'memory.separator': ', ',
      'memory.kind.all': 'All', 'memory.kind.documents': 'Documents', 'memory.kind.affect': 'Feelings', 'memory.kind.jobs': 'Job reports',
      'memory.kind.ideas': 'Improvement ideas', 'memory.category.idea': 'Improvement idea',
      'memory.idea.state.open': 'Open', 'memory.idea.state.adopted': 'Adopted', 'memory.idea.state.deferred': 'Deferred',
      'memory.idea.state.dropped': 'Dropped', 'memory.idea.why': 'Why: {text}', 'memory.idea.from.character': 'Noted by her · {where}',
      'memory.idea.from.action': 'Noted by the action brain while working · {where}', 'memory.idea.decision.adopt': 'Adopted: {why}',
      'memory.idea.decision.defer': 'Deferred: {why}', 'memory.idea.decision.drop': 'Dropped: {why}',
      'memory.status.idea.open': 'Open', 'memory.status.idea.adopted': 'Adopted', 'memory.status.idea.deferred': 'Deferred',
      'memory.status.idea.dropped': 'Dropped',
      'memory.kind.self': 'Self', 'memory.kind.relation': 'People', 'memory.kind.summary': 'Summaries',
      'memory.kind.interpretation': 'Her readings', 'memory.kind.source': 'Sources',
      'memory.category.self': 'Self', 'memory.category.relation': 'People', 'memory.category.derived_summary': 'Summary',
      'memory.category.character_interpretation': 'Her reading', 'memory.category.public_statement': 'What she said',
      'memory.category.reported_speech': 'What others said', 'memory.category.observed_fact': 'Recorded fact',
      'memory.category.source': 'Original message', 'memory.category.document': 'Document', 'memory.category.affect': 'Feelings',
      'memory.category.affect_event': 'Feelings', 'memory.category.persona_job_report': 'Job report', 'memory.category.other': 'Memory',
      'memory.status.empty': 'Not written yet', 'memory.status.recorded': 'Recorded',
      'memory.hint.self': 'She decides whether to write or rewrite this only in her daily time for reflection.',
      'memory.hint.relation': 'She writes this when, in a conversation, her understanding of the person changes.',
      'memory.title.character_core': 'Core self', 'memory.title.current_self': 'Current self', 'memory.title.relation': 'Relationship and preferences',
      'memory.title.peer': 'Their profile', 'memory.title.mood': 'Her mood now', 'memory.title.moved': 'Moved · {feeling}',
      'memory.title.job': 'Job report', 'memory.title.said': 'Said · {speaker}', 'memory.title.blank': 'A memory without text',
      'memory.title.document': '{kind}', 'memory.title.documentNamed': '{kind} · {name}',
      'memory.doc.persona': 'Persona', 'memory.doc.voice': 'Voice', 'memory.doc.ledger': 'Promises and open items',
      'memory.doc.working': 'Working notes', 'memory.doc.other': 'Document',
      'memory.doc.sections': '{label}: {n} sections', 'memory.doc.overBudget': 'over the render budget',
      'memory.visibility.public': 'Public', 'memory.visibility.owner_private': 'Owner only',
      'memory.inject.always': 'used every turn', 'memory.inject.on_demand': 'used when relevant', 'memory.inject.never': 'never in conversation',
      'memory.mood.calm': 'Calm', 'memory.mood.line': '{label} · mood {val} · stirred {arl}{open}', 'memory.mood.open': ' · {n} things still open',
      'memory.mood.head': '**{label}** (mood {val}, from −100 to 100; stirred {arl}, from 0 to 100)',
      'memory.mood.policy': 'Leaning now: {text}', 'memory.mood.tendencies': 'Her main feelings bring: {text}', 'memory.mood.from': 'From:',
      'memory.mood.contribution': '- {feeling} · mood {val} · stirred {arl} · {ago}{held}: {why}', 'memory.mood.held': ' (still open, not fading)',
      'memory.mood.fade': 'Each thing that moved her fades with time (some feelings faster than others); open things fade only once settled.',
      'memory.event.line': 'mood {val} · stirred {arl}{held} · {why}', 'memory.event.held': ' · still open',
      'memory.event.kind': 'Kind: {feeling} · mood {val} · stirred {arl}', 'memory.event.cost': 'Cost: {text}',
      'memory.event.open': 'This is still open: it does not fade until settled.', 'memory.event.noReason': '(no reason written)',
      'memory.amendment.close': 'Settled: {why}', 'memory.amendment.void': 'Voided (its premise was wrong): {why}', 'memory.amendment.fix_ts': 'Time corrected: {why}',
      'memory.amendment.fix_kind': 'Kind corrected: {why}', 'memory.doc.meta': '*{visibility} · {inject}{date}*',
      'memory.report.status': 'Status: {status} · job {job} · {run}',
      'memory.ago.now': 'just now', 'memory.ago.minutes': '{n} min ago', 'memory.ago.hours': '{n} h ago', 'memory.ago.days': '{n} days ago',
      'memory.scene.shared': 'Shared by every conversation', 'memory.scene.local': 'Local chat', 'memory.scene.group': 'Group · {name}',
      'memory.scene.dm': 'Direct · {name}',
      'memory.usage.none': 'This conversation has no turn to check against yet', 'memory.usage.used': 'Used in the latest turn ({time})',
      'memory.usage.older': 'The latest turn ({time}) still used an older revision', 'memory.usage.formed': 'Formed in the latest turn; kept in that turn’s native conversation',
      'memory.usage.input': 'The input of the latest turn ({time})', 'memory.usage.unused': 'Not used in the latest turn ({time})',
      'memory.readback': '— read back ({path}, lines {from}–{to}, snapshot taken at import) —',
      'settings.loading': 'Loading settings…', 'settings.unavailable': 'Settings are unavailable.', 'settings.aria': 'Asuna settings',
      'settings.persona': 'Character', 'settings.channelAdmission': 'Channel admission', 'settings.python': 'Python',
     
      'settings.route': '{brain} · {field}', 'settings.route.provider': 'Model service', 'settings.route.model': 'Model',
      'settings.route.reasoningEffort': 'Reasoning effort', 'settings.route.maxTokens': 'Max output tokens',
      'settings.newSecrets': 'Add or update credentials (JSON)', 'settings.overridden': 'Overridden', 'settings.reset': 'Reset to default',
      'settings.choose': 'Choose', 'settings.unavailableValue': '{value} (unavailable now)',
      'settings.admission.automatic': 'Admit direct chats, groups and new members automatically', 'settings.admission.explicit': 'Admit configured identities only',
      'settings.providerDefault': 'Model service default', 'settings.routeHint': 'Choices come from the model services configured in DSH and what they offer.',
      'settings.secretMapHint': 'For example {"ASUNA_CHANNELS_NEW_TOKEN":"value"}: stored in the credential store; the settings keep only the reference. Only the listed names change; leave empty for no change.',
      'settings.secretHint': 'Leave empty to keep the current credential.',
      'settings.secretAdd': 'Credential references can be added', 'settings.secretSet': 'Configured', 'settings.secretUnset': 'Not configured',
      'settings.jsonHint': 'JSON; refer to credentials as {"$secret":"name"}.', 'settings.pythonHint': 'Leave empty to build a Python environment from the package lock in the data folder on first start (needs uv or Python 3.12+).', 'settings.invalidNumber': 'Enter a positive whole number',
      'settings.invalidJson': 'Enter a valid JSON value', 'settings.form.unavailable': 'Settings are unavailable', 'settings.form.readOnly': 'Settings are read-only',
      'settings.form.saveFailed': 'Saving failed; your draft is kept.', 'settings.form.save': 'Save settings', 'settings.form.saving': 'Saving…',
      'settings.status': 'Business worker: {state} · Mongo: {database}', 'settings.disconnected': 'not connected',
      'settings.restartWaiting': 'A published change to {project} ({time}) takes effect after a Host restart; until then her night self-development stages are skipped.',
      'settings.readingStatus': 'Reading status…',
      'settings.note': 'DSH stores these settings; credentials are write-only. Models and API keys are managed in DSH’s own provider settings. A model chosen in a conversation takes precedence over the routes below.',
      'settings.savedPending': 'Saved, not applied yet.', 'settings.savedApplied': 'Saved; matches what is running.',
      'settings.activated': 'Applied to the business worker and later model requests.',
      'settings.selfSource': 'Self from: {source}', 'settings.waiting': 'waiting for connection', 'settings.channelsFallback': 'Channels',
      'settings.channels': '{titles}: {state}', 'settings.channelOn': 'local entry running; adapter {state}; platform connection not verified',
      'settings.channelOff': 'off', 'settings.schedule': 'Schedules: {state}', 'settings.sandbox': 'Sandbox: {state}', 'settings.sandboxNone': 'none ({reason}): running code, self-development and integration are off', 'settings.scheduleOn': 'native scheduler',
      'settings.pending': 'Saved settings are not applied yet.', 'settings.applied': 'Saved settings match what is running.',
      'settings.apply': 'Apply saved settings', 'settings.refresh': 'Refresh status',
      'persona.aria': 'Persona data', 'persona.title': 'Persona data · {persona}',
      'persona.render': 'Persona render estimate {estimate} / limit {limit}', 'persona.unlimited': 'none', 'persona.overBudget': 'over budget',
      'persona.sources': 'Source roots: {list}', 'persona.source': '{id} ({state}, {path})', 'persona.noSources': 'No source roots (configure persona_sources locally).',
      'persona.job': 'Job {id} · sources {sources}', 'persona.dryRun': 'Dry run', 'persona.run': 'Run',
      'persona.runs': 'Recent runs: {list}', 'persona.runDry': ' (dry)', 'persona.export': 'Export documents',
      'persona.exportUnset': 'Export (export_dir not configured)', 'persona.exported': 'Exported {n} documents.',
      'persona.jobResult': 'Job {job}{dry}: {status}{code}{reason} · the report is under Memory → Job reports.',
      'persona.exitCode': ' · exit code {code}',
    },
  };

  const stack = { display: 'flex', flexDirection: 'column', gap: 12, padding: 16, minWidth: 0,
    overflowWrap: 'anywhere', fontSize: 14, lineHeight: 1.6 };
  const small = { fontSize: 12, color: 'var(--dsw-alias-label-tertiary)' };
  const markdownLabels = t => ({ code: { copyLabel: t('markdown.copy'), copiedLabel: t('markdown.copied') }, footnotes: t('markdown.footnotes') });
  const formatDate = (t, value, compact = false) => {
    const date = new Date(value);
    return value && Number.isFinite(date.getTime()) ? date.toLocaleString(t('date.locale'), {
      ...(compact ? {} : { year: 'numeric' }), month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    }) : '';
  };
  const duration = (t, ms) => {
    const seconds = Math.max(0, Math.round(ms / 1000));
    if (seconds < 60) return t('duration.seconds', { n: seconds });
    const minutes = Math.round(seconds / 60);
    return minutes < 60 ? t('duration.minutes', { n: minutes })
      : t('duration.hours', { h: Math.floor(minutes / 60), m: minutes % 60 });
  };
  const ago = (t, hours) => hours * 60 < 5 ? t('memory.ago.now') : hours < 1 ? t('memory.ago.minutes', { n: Math.round(hours * 60) })
    : hours < 48 ? t('memory.ago.hours', { n: Math.round(hours) }) : t('memory.ago.days', { n: Math.round(hours / 24) });
  const signed = value => (value >= 0 ? '+' : '') + Math.round(Number(value) || 0);
  // A platform person id (qq:<account>) reads as `QQ · <account>`; local ids read as themselves.
  const memoryAuthor = value => typeof value === 'string'
    ? value.replace(/^([a-z][a-z0-9_]{0,15}):/, (_, kind) => kind.toUpperCase() + ' · ') : '';
  // A server label: a locale key with its parameters, or content text shown as it is.
  // A list of parts is concatenated (the server puts its own paragraph breaks in).
  const say = (t, label) => !label ? '' : typeof label === 'string' ? label
    : Array.isArray(label) ? label.map(part => say(t, part)).join('')
    : t(label.key, Object.fromEntries(Object.entries(label.params ?? {}).map(([name, value]) =>
      [name, value && typeof value === 'object' ? say(t, value) : value])));

  // ── which brain ─────────────────────────────────────────────────────
  const stageLabel = (t, stage) => ['character', 'executor'].includes(stage?.lane) ? t('brain.' + stage.lane) : null;
  const brainClass = lane => ['character', 'executor'].includes(lane) ? 'asuna-brain-' + lane : undefined;

  function subscribeInputPolicies(ctx, rpc, t) {
    let controller, previous = '', owned = new Map();
    const unconfirmed = new Set();
    const clear = id => {
      if (ctx.conversation.blocks.storeFor(id).getSnapshot() === owned.get(id))
        ctx.conversation.blocks.set(id, undefined);
      owned.delete(id);
      unconfirmed.delete(id);
    };
    const reasonOf = policy => policy.key === 'internal' ? t('input.internal')
      : policy.platform ? t('input.readOnly', { platform: policy.platform }) : t('input.readOnlyLocal');
    const update = () => {
      const list = ctx.sessions.list.getSnapshot();
      const ids = Object.keys(list.byId).filter(id => list.byId[id]?.retainedBy.mainView > 0);
      const key = ids.join('\n');
      if (key === previous) return;
      previous = key; controller?.abort(); controller = new AbortController();
      const signal = controller.signal;
      for (const id of owned.keys()) if (!ids.includes(id)) clear(id);
      if (!ids.length) return;
      // Resolve policy before enabling the shipped composer on a cold selection.
      // Confirmed blocks survive request failure; temporary ones do not prevent
      // ordinary DSH or the independent recovery preset from being used.
      for (const id of ids) if (!owned.has(id) && !ctx.conversation.blocks.storeFor(id).getSnapshot()) {
        const block = { reason: t('input.checking') };
        owned.set(id, block); unconfirmed.add(id); ctx.conversation.blocks.set(id, block);
      }
      rpc('inputPolicies', { sessionIds: ids }, signal).then(policies => {
        if (signal.aborted) return;
        for (const id of ids) {
          const policy = policies[id];
          if (!policy) { if (owned.has(id)) clear(id); continue; }
          unconfirmed.delete(id);
          const block = { reason: reasonOf(policy) }; owned.set(id, block); ctx.conversation.blocks.set(id, block);
        }
      }).catch(() => {
        if (signal.aborted) return;
        for (const id of ids) if (unconfirmed.has(id)) clear(id);
        previous = '';
      });
    };
    const unsubscribe = ctx.sessions.list.subscribe(update); update();
    return () => { unsubscribe(); controller?.abort(); for (const id of owned.keys()) clear(id); };
  }
  // Pill's static branch forwards className, but not style. Scope just the
  // palette to these existing labels; native Pill still owns their geometry.
  const brainPalette = `
    body .asuna-brain-character { color: #7e22ce; background: color-mix(in srgb, #7e22ce 10%, var(--dsw-alias-bg-base)); }
    body .asuna-brain-executor { color: var(--dsw-static-blue-600); background: color-mix(in srgb, var(--dsw-static-blue-600) 10%, var(--dsw-alias-bg-base)); }
    body[data-ds-dark-theme] .asuna-brain-character { color: #c4b5fd; background: color-mix(in srgb, #c4b5fd 10%, var(--dsw-alias-bg-base)); }
    body[data-ds-dark-theme] .asuna-brain-executor { color: var(--dsw-static-blue-300); background: color-mix(in srgb, var(--dsw-static-blue-300) 10%, var(--dsw-alias-bg-base)); }
    body .asuna-collab { border: .5px solid var(--dsw-alias-border-l1); border-radius: var(--dsw-radius-lg, 12px);
      padding: 10px 12px; margin: 8px 0; display: flex; flex-direction: column; gap: 8px; min-width: 0; }
    body .asuna-collab-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; font-size: 13px;
      color: var(--dsw-alias-label-secondary); }
    body .asuna-collab-title { font-weight: 500; color: var(--dsw-alias-label-primary); min-width: 0; overflow-wrap: anywhere; }
    body .asuna-collab-bubble { border-left: 3px solid; border-radius: 4px; padding: 4px 10px; min-width: 0;
      background: color-mix(in srgb, currentColor 4%, transparent); }
    body .asuna-collab-character { border-color: #7e22ce; }
    body .asuna-collab-executor { border-color: var(--dsw-static-blue-600); }
    body[data-ds-dark-theme] .asuna-collab-character { border-color: #c4b5fd; }
    body[data-ds-dark-theme] .asuna-collab-executor { border-color: var(--dsw-static-blue-300); }
    body .asuna-collab-bubble .asuna-collab-text { color: var(--dsw-alias-label-primary); }
    body .asuna-collab-clipped { max-height: 9.6em; overflow: hidden; }
  `;
  // Palette only (pinned DSH version's class): DSH's meter is the character-brain purple, the second
  // instance of the same meter (the action session) the action-brain blue.
  const meterPalette = `
    .JObwrW_fill { stroke: #7e22ce; }
    body[data-ds-dark-theme] .JObwrW_fill { stroke: #c4b5fd; }
    .asuna-action-meter { display: contents; }
    .asuna-action-meter .JObwrW_fill { stroke: var(--dsw-static-blue-600); }
    body[data-ds-dark-theme] .asuna-action-meter .JObwrW_fill { stroke: var(--dsw-static-blue-300); }
  `;
  /** DSH's own ContextMeter, read from the meter it already renders next to this dock. DSH does not
   * export it; when the lookup fails (another DSH revision) the action meter is simply absent. */
  function shippedContextMeter(anchor) {
    for (const element of anchor?.parentElement?.parentElement?.children ?? []) {
      const key = Object.keys(element).find(name => name.startsWith('__reactFiber$'));
      for (let fiber = key && element[key], depth = 0; fiber && depth < 4; fiber = fiber.return, depth++)
        if (typeof fiber.type === 'function' && fiber.type.name === 'ContextMeter' && fiber.memoizedProps?.t)
          return { Meter: fiber.type, t: fiber.memoizedProps.t };
    }
    return null;
  }
  function stageIdentity(source) {
    if (typeof source?.phase !== 'string' || !source.phase) return null;
    // Older source notices have phase but no lane. Infer only documented
    // business phases, never a brain from the selected provider/model.
    const lane = source.lane ?? (['execution', 'execution-repair', 'EXECUTE'].includes(source.phase) ? 'executor'
      : source.phase === 'dialogue-summary' ? 'summary'
      : ['MONOLOGUE', 'DECIDE', 'REFLECT', 'SELF', 'CONSULT', 'SPEAK', 'TURN', 'REPAIR'].includes(source.phase) ? 'character' : undefined);
    return ['character', 'executor', 'summary'].includes(lane) ? { lane, phase: source.phase, operation: source.operation } : null;
  }
  function stageDefinitions() {
    const matchStep = event => ['asuna/stage', 'asuna/stage-result', 'assistant/live-chunk', 'assistant/message'].includes(event.type)
      && Number.isInteger(event.data.turn) && Number.isInteger(event.data.step);
    const stageState = (match, reader) => {
      const { event } = match;
      const prior = reader.previous('asuna-stage-source')?.state;
      return { stage: event.type.startsWith('asuna/') ? stageIdentity(event.data)
        : prior?.turn === event.data.turn ? prior.stage : null,
        turn: event.data.turn, step: event.data.step, anchor: event.seq,
        sourceSeq: prior?.turn === event.data.turn ? prior.seq : undefined };
    };
    // Words a reader sees, not only thinking or tool calls: a Turn that ends in a tool (her answer to the
    // action brain, stay_silent) shows only its folded process, so the brain label waits for text.
    const hasText = event => event.type === 'assistant/message'
      ? (event.data.message?.content ?? []).some(block => block.type === 'text' && block.text?.trim())
      : event.type === 'assistant/live-chunk' && event.data.chunk?.type === 'text-delta' && !!event.data.chunk.text?.trim();
    const markerState = (match, reader) => {
      const state = stageState(match, reader);
      const responseSeen = match.event.type.startsWith('assistant/');
      return { ...state, responseSeen, textSeen: hasText(match.event),
        anchor: responseSeen ? state.sourceSeq ?? state.anchor - 0.2 : state.anchor, markerLocation: { kind: 'session' } };
    };
    return [{ kind: 'asuna-stage-source',
      match: event => event.type === 'user/message' && event.data.source?.kind === 'asuna'
        ? { id: String(event.seq), role: 'start' } : null,
      start: (_context, match) => ({ stage: stageIdentity(match.event.data.source),
        turn: match.location.turn?.turn, seq: match.event.seq }),
      update: context => context.state,
    }, { kind: 'asuna-stage',
      match: event => matchStep(event)
        ? { id: event.data.turn + ':' + event.data.step, role: 'start' } : null,
      start: (_context, match, reader) => stageState(match, reader),
      update: (context, match) => match.event.type === 'asuna/stage'
        ? { ...context.state, stage: stageIdentity(match.event.data) } : context.state,
      // No token buffer: subscribe to native events only for their placement.
      publication: match => match.event.type === 'assistant/live-chunk' ? 'animation-frame' : 'immediate',
      buildLocationData: (context, scope, previous) => {
        if (scope !== 'step' || !context.state?.stage) return null;
        if (previous?.value === context.state.stage) return previous;
        return { kind: 'step', turn: context.state.turn, step: context.state.step,
          key: 'asuna-stage', value: context.state.stage };
      },
    }, { kind: 'asuna-brain-marker', target: 'chat',
      match: event => matchStep(event) ? { id: String(event.data.turn), role: 'start' } : null,
      start: (_context, match, reader) => markerState(match, reader),
      update: (context, match) => {
        const state = context.state, stage = state.stage ?? stageIdentity(match.event.data);
        // The explicit notice precedes native input materialization. Place
        // identity immediately before the first response/process control,
        // after user input, rather than anchoring it to that early notice.
        const textSeen = state.textSeen || hasText(match.event);
        if (!state.responseSeen && match.event.type.startsWith('assistant/')) return { ...state,
          stage, textSeen, responseSeen: true, anchor: match.event.seq - 0.2 };
        return stage === state.stage && textSeen === state.textSeen ? state : { ...state, stage, textSeen };
      },
      publication: match => match.event.type === 'assistant/live-chunk' ? 'animation-frame' : 'immediate',
      buildViewNode: context => {
        // Keep one brain label with a native Turn's records, outside its
        // disclosure. Attribute every step separately, but never repeat the
        // label for tool followups. A cold partial Turn can use its first
        // loaded explicit notice without guessing unloaded attribution.
        const nativeStep = context.matches.some(match => match.location.kind === 'step');
        if (!['character', 'executor'].includes(context.state?.stage?.lane) || !nativeStep || !context.state.responseSeen
            || !context.state.textSeen) return null;
        const location = context.state.markerLocation;
        const previous = context.current.get('chat');
        if (previous?.data === context.state.stage && previous.location === location
            && previous.anchorSeq === context.state.anchor) return previous;
        return { key: context.key, kind: 'asuna-stage',
          id: context.id, target: 'chat', anchorSeq: context.state.anchor, location,
          visibility: 'visible', data: context.state.stage };
      },
    }, { kind: 'asuna-stage-finish',
      // How the Turn's last stage ended. DSH keeps a Turn's end at max-tokens once any step hit the
      // cap, even when the platform retried that stage in the same Turn and the retry finished.
      match: event => event.type === 'asuna/stage-result' && Number.isInteger(event.data.turn)
        ? { id: String(event.data.turn), role: 'start' } : null,
      start: (_context, match) => ({ turn: match.event.data.turn, finish: match.event.data.finish_reason }),
      update: (_context, match) => ({ turn: match.event.data.turn, finish: match.event.data.finish_reason }),
      buildLocationData: (context, scope, previous) => {
        if (scope !== 'turn' || !context.state) return null;
        if (previous?.value === context.state.finish) return previous;
        return { kind: 'turn', turn: context.state.turn, key: 'asuna-stage-finish', value: context.state.finish };
      },
    }];
  }

  /** The program's note that sends her final text back to be rewritten in the same Turn (ADR-011 §3.5).
   * DSH draws a mid-Turn message only when a person sent it, so without this row the rejected draft and
   * the rewrite read as two answers. It sits where the note was given, between the two. Like the brain
   * label it is placed in the session, not the Turn: DSH folds a Turn's unknown process rows into the next
   * reasoning group, which would hide it a level deeper; so it also shows above the answer when folded. */
  function repairDefinitions() {
    return [{ kind: 'asuna-repair', target: 'chat',
      match: event => event.type === 'user/message' && event.data.source?.kind === 'asuna' && event.data.source.phase === 'REPAIR'
        ? { id: String(event.seq), role: 'start' } : null,
      start: (_context, match) => ({ seq: match.event.seq,
        text: (match.event.data.content ?? []).filter(part => part.type === 'text').map(part => part.text).join('\n').trim() }),
      update: context => context.state,
      buildViewNode: context => !context.state ? null : ({ key: context.key, kind: 'asuna-repair', id: context.id,
        target: 'chat', anchorSeq: context.state.seq, location: { kind: 'session' }, visibility: 'visible',
        data: { text: context.state.text } }),
    }];
  }

  // ── the two brains' thread (ADR-011 §7.1) ───────────────────────────
  /** One node per block of a task thread (collab.js: an entry after the conversation moved on starts a new
   * block where it happens), from her session's `asuna/collab` entries, anchored at the block's first. */
  function collabDefinitions() {
    return [{ kind: 'asuna-collab', target: 'chat',
      match: event => event.type === 'asuna/collab' && event.data?.thread
        ? { id: String(event.data.block ?? event.data.thread), role: 'start' } : null,
      start: (_context, match) => ({ anchor: match.event.seq, entries: [match.event.data] }),
      update: (context, match) => context.state.entries.some(entry => entry.id === match.event.data.id) ? context.state
        : { ...context.state, entries: [...context.state.entries, match.event.data] },
      buildViewNode: context => !context.state ? null : ({ key: context.key, kind: 'asuna-collab', id: context.id,
        target: 'chat', anchorSeq: context.state.anchor, location: { kind: 'session' }, visibility: 'visible',
        data: context.state }),
    }];
  }
  /** What a block of a thread reads as: its title, its sessions, its state, how long it has run, and the
   * action brain's work still going on (`live`: the range after its last work row). */
  function threadOf(entries) {
    const open = entries.findLast(entry => entry.kind === 'open');
    const title = entries.find(entry => entry.title)?.title;
    const statuses = entries.filter(entry => entry.kind === 'status');
    const last = entries.at(-1);
    const asked = entries.findLast(entry => entry.kind === 'question');
    const answered = asked && entries.slice(entries.indexOf(asked)).some(entry => entry.kind === 'answer');
    let state = statuses.at(-1)?.state ?? (open ? 'running' : 'queued');
    if (asked && !answered && !['done', 'failed', 'stopped', 'paused'].includes(state)) state = 'waiting';
    // A continuation runs again after a finished or paused run.
    if (['done', 'failed', 'paused'].includes(state) && last && last !== statuses.at(-1) && ['message', 'open'].includes(last.kind)) state = 'queued';
    // The thread went on in a later block, below.
    if (entries.some(entry => entry.kind === 'continued')) state = 'continued';
    const started = Date.parse(entries[0]?.at), ended = Date.parse(last?.at);
    const child = open?.child_session_id ?? entries.findLast(entry => entry.child_session_id)?.child_session_id;
    const work = open && entries.slice(entries.indexOf(open)).findLast(entry => entry.kind === 'work');
    const live = state === 'running' && child && (work?.through_seq ?? open?.after_seq) !== undefined
      ? { child, after: work?.through_seq ?? open.after_seq, since: Date.parse(work?.at ?? open.at) } : null;
    return { title, open, child, live, state, stopped: statuses.findLast(entry => entry.state === 'stopped'),
      elapsed: Number.isFinite(started) ? (['done', 'failed', 'stopped', 'paused', 'continued'].includes(state) && Number.isFinite(ended) ? ended : Date.now()) - started : null };
  }

  // ── her tool rows (ADR-011 §7.2) ────────────────────────────────────
  const TOOL_ICONS = { think: 'IconThinkOutlineRegular', recall: 'IconSearchOutlineRegular', delegate: 'IconSendOutlineRegular',
    message_action: 'IconPaperPlaneOutlineRegular', stop_action: 'IconPauseOutlineRegular', answer_action: 'IconQuestionOutlineRegular',
    stay_silent: 'IconMicrophoneOutlineRegular', attach_image: 'IconPaperclipOutlineRegular', write_document: 'IconEditOutlineRegular',
    update_self: 'IconPersonalizationOutlineRegular', understand_person: 'IconUserOutlineRegular', set_policy: 'IconSlidersTwoOutlineRegular',
    pin_memory: 'IconPinOutlineRegular', feel: 'IconLikeOutlineRegular', plan: 'IconAlarmClockOutlineRegular',
    group_action: 'IconUsersOutlineRegular', promote_memory: 'IconArchiveOutlineRegular', note_idea: 'IconLightOutlineRegular',
    read_ideas: 'IconListPenOutlineRegular', review_idea: 'IconChecklistOutlineRegular', visit: 'IconRightUpOutlineRegular',
    ask_character: 'IconQuestionOutlineRegular', report_progress: 'IconInfoOutlineRegular' };
  // The argument that says what a call was about (her own words), and the one shown in full when opened.
  const TOOL_SUMMARY = { think: 'thought', recall: 'query', delegate: 'title', message_action: 'message', stop_action: 'reason',
    answer_action: 'answer', stay_silent: 'reason', attach_image: 'why', write_document: 'doc', update_self: 'target',
    understand_person: 'body', set_policy: 'key', pin_memory: 'memory_id', feel: 'why', plan: 'intent', group_action: 'who',
    promote_memory: 'fact', note_idea: 'idea', review_idea: 'why', ask_character: 'question', report_progress: 'note',
    visit: 'topic' };
  const TOOL_BODY = { think: 'thought', delegate: 'brief', message_action: 'message', answer_action: 'answer',
    write_document: 'body', update_self: 'body', understand_person: 'body', note_idea: 'idea', ask_character: 'question',
    report_progress: 'note', promote_memory: 'fact' };
  const parseArgs = raw => { try { const value = JSON.parse(raw ?? ''); return value && typeof value === 'object' ? value : {}; } catch { return {}; } };
  const firstSentence = text => String(text ?? '').split(/(?<=[。！？!?.\n])/)[0].trim();
  const resultText = block => (block?.content ?? []).filter(part => part.type === 'text').map(part => part.text).join('\n');
  const ROLE_TOOLS = Object.keys(TOOL_ICONS);

  function apply(ctx) {
    ctx.effect(() => ctx.locale.register(NS, DICTIONARY));
    const t = ctx.locale.bind(NS);
    const rpc = async (method, payload = {}, signal) => {
      const result = await ctx.connection.rpc.call('/api', 'asunaApi/' + method, { args: payload }, signal);
      if (!result.ok) throw new Error(result.error.message);
      return result.value;
    };
    const describe = ctx.configForms.describe();
    // Host validation callbacks cannot travel in a serialized schema. Read
    // the native mirror's redacted value, as DSH's cross-namespace editors do.
    // The shipped form model still owns drafts, revisions and save recovery.
    describe.ensure();
    const subscribe = fn => describe.subscribe(fn);
    let described, describedValue;
    const snapshot = () => {
      const next = describe.getSnapshot();
      if (next !== described) {
        described = next;
        const view = next.view?.namespaces.find(row => row.ns === 'asuna-cognition-core');
        describedValue = { status: view ? 'ready' : next.view ? 'unavailable' : 'loading',
          writable: next.view?.writable ?? false, ...view };
      }
      return describedValue;
    };

    // Use the shipped composer's block service, including blank/cold platform
    // sessions. This is a service subscription, not a new UI slot/component.
    ctx.effect(() => subscribeInputPolicies(ctx, rpc, t));

    // Same anchored Menu/Button primitives used by DSH's own preference rows.
    // The native form model still owns the staged value, reset and save.
    function Select({ id, label, value, options, onChange, disabled, overridden, onReset, hint, t }) {
      const [open, setOpen] = React.useState(false);
      const selected = options.find(option => option[0] === value);
      return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } },
        h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
          h('label', { htmlFor: id }, label), overridden && h(Pill, null, t('settings.overridden')),
          overridden && h(Button, { size: 'sm', disabled, onClick: onReset }, t('settings.reset'))),
        h(Menu, { open: open && !disabled, portal: true, selectedId: value,
          items: options.map(([id, label]) => ({ id, label })), onClose: () => setOpen(false),
          onSelect: value => { onChange(value); setOpen(false); },
          anchor: h(Button, { id, variant: 'outline', 'aria-label': label, 'aria-haspopup': 'menu',
            'aria-expanded': open && !disabled, disabled: disabled || !options.length,
            onClick: () => setOpen(value => !value) },
          selected?.[1] ?? (value ? t('settings.unavailableValue', { value }) : t('settings.choose')),
          h(IconChevronDownOutlineRegular, null)) }),
        hint && h('p', { style: small }, hint));
    }

    // ── memory ────────────────────────────────────────────────────────
    const categoryLabel = (t, category) => t('memory.category.' + (DICTIONARY.en['memory.category.' + category] ? category : 'other'));
    function Memory(props) {
      const t = props.t;
      const visible = props.useTabInfo().tab.visible;
      const [category, setCategory] = React.useState('summary'), [offset, setOffset] = React.useState(0);
      const [search, setSearch] = React.useState(''), [query, setQuery] = React.useState('');
      const [composing, setComposing] = React.useState(false);
      const [page, setPage] = React.useState(null), [error, setError] = React.useState('');
      const [selected, setSelected] = React.useState(null), [detail, setDetail] = React.useState(null);
      const [refresh, setRefresh] = React.useState(0);
      React.useEffect(() => {
        if (!visible || composing) return;
        const timer = setTimeout(() => { setQuery(search.trim()); setOffset(0); }, 250);
        return () => clearTimeout(timer);
      }, [visible, search, composing]);
      React.useEffect(() => {
        if (!visible) return;
        const controller = new AbortController(); setPage(null); setError(''); setSelected(null); setDetail(null);
        rpc('memory', { request: { session_id: props.sessionId, category, offset, search: query } }, controller.signal)
          .then(value => { if (!controller.signal.aborted) setPage(value); })
          .catch(error => { if (!controller.signal.aborted) setError(error.message); });
        return () => controller.abort();
      }, [visible, props.sessionId, category, offset, query, refresh]);
      React.useEffect(() => {
        setDetail(null);
        if (!visible || !selected) return;
        const controller = new AbortController();
        rpc('memory', { request: { session_id: props.sessionId, id: selected } }, controller.signal)
          .then(value => { if (!controller.signal.aborted) setDetail(value); })
          .catch(error => { if (!controller.signal.aborted) setError(error.message); });
        return () => controller.abort();
      }, [visible, props.sessionId, selected]);
      const labels = markdownLabels(t);
      const usage = detail => detail.usage && t('memory.usage.' + detail.usage, { time: formatDate(t, detail.context_at, true) });
      return h('section', { style: { ...stack, height: '100%', minHeight: 0, overflow: 'hidden' }, 'aria-label': t('memory.aria') },
        h('div', { style: { display: 'flex', flexDirection: 'column', gap: 8, flexShrink: 0 } },
        h(Select, { t, label: t('memory.category'), value: category,
          options: ['all', 'documents', 'affect', 'jobs', 'ideas', 'self', 'relation', 'summary', 'interpretation', 'source']
            .map(kind => [kind, t('memory.kind.' + kind)]),
          onChange: value => { setCategory(value); setOffset(0); } }),
        h(Input, { 'aria-label': t('memory.search'), placeholder: t('memory.searchPlaceholder'), value: search, maxLength: 160,
          onChange: event => setSearch(event.target.value),
          onCompositionStart: () => setComposing(true), onCompositionEnd: () => setComposing(false) }),
        h(Button, { size: 'sm', onClick: () => setRefresh(x => x + 1) }, t('memory.refresh')),
        page && h('p', { style: { ...small, margin: 0 } }, say(t, page.scene_title),
          category === 'relation' ? ' · ' + t('memory.subject', { name: page.subject_name }) : '',
          page.linked_scene_titles?.length ? ' · ' + t('memory.linked', { titles: page.linked_scene_titles.map(title => say(t, title)).join(t('memory.separator')) }) : '')),
        h('div', { style: { display: 'flex', flexDirection: 'column', gap: 12, flex: 1, minHeight: 0, overflowY: 'auto' } },
        error && h('p', { role: 'alert' }, error.includes('NOT_BOUND') ? t('memory.notBound') : error),
        !page && !error && h('p', null, t('memory.loading')),
        page?.rows.map(row => h('article', { key: row.id },
          h(DisclosureRow, { icon: h(IconChevronDownOutlineRegular), previewChevron: false,
            title: formatDate(t, row.updated_at, true) || (row.status ? t('memory.status.' + row.status) : categoryLabel(t, row.kind)),
            collapsedContent: h('span', { style: { marginLeft: 8, minWidth: 0, overflow: 'hidden',
              textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--dsw-alias-label-primary)' } }, say(t, row.title)),
            keepContentWhenOpen: true,
            open: selected === row.id, expandable: true,
            expandOnRowClick: true, onToggle: () => setSelected(selected === row.id ? null : row.id) },
            selected === row.id && (detail ? h('div', { style: { padding: '8px 0', color: 'var(--dsw-alias-label-primary)' } },
              h('p', { style: small }, [categoryLabel(t, detail.category), detail.status && t('memory.status.' + detail.status)].filter(Boolean).join(' · ')),
              h(MarkdownText, { text: say(t, detail.body), labels }),
              usage(detail) && h('p', { style: small }, usage(detail)),
              detail.corrected && h('p', null, t('memory.corrected')),
              h('p', { style: small }, [typeof detail.revision === 'number' ? t('memory.revision', { n: detail.revision }) : '',
                memoryAuthor(detail.speaker || detail.author),
                detail.generated_at ? t('memory.compiled', { time: formatDate(t, detail.generated_at) }) : formatDate(t, detail.occurred_at)].filter(Boolean).join(' · ')),
              detail.sources_truncated && h('p', { style: small }, t('memory.sourcesTruncated')),
              ...detail.sources.map(source => h('blockquote', { key: source._id },
                h('p', { style: small }, [categoryLabel(t, source.category ?? 'source'), memoryAuthor(source.author), say(t, source.scene_title),
                  formatDate(t, source.occurred_at)].filter(Boolean).join(' · ')),
                h(MarkdownText, { text: source.text, labels })))) : h('p', null, t('memory.detailLoading')))),
          selected !== row.id && row.excerpt && h('p', { style: { margin: '4px 0', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } }, say(t, row.excerpt)),
          (category === 'all' || (row.scene_title && say(t, row.scene_title) !== say(t, page.scene_title))) && h('p', { style: { ...small, margin: 0 } },
            [category === 'all' ? categoryLabel(t, row.kind) : '',
              row.scene_title && say(t, row.scene_title) !== say(t, page.scene_title) ? say(t, row.scene_title) : ''].filter(Boolean).join(' · ')))),
        page && !page.rows.length && h('p', null, query ? t('memory.noMatch') : t('memory.empty'))),
        page && h('div', { style: { display: 'flex', gap: 8, flexShrink: 0 } },
          h(Button, { disabled: offset === 0, onClick: () => setOffset(Math.max(0, offset - 24)) }, t('memory.previous')),
          h(Button, { disabled: page.next_offset === null, onClick: () => setOffset(page.next_offset) }, t('memory.next'))));
    }

    // ── settings ──────────────────────────────────────────────────────
    function Settings(props) {
      const saved = React.useSyncExternalStore(subscribe, snapshot);
      return saved.value ? h(SettingsEditor, { initial: saved.value, t: props.t })
        : h('p', null, saved.status === 'unavailable' ? props.t('settings.unavailable') : props.t('settings.loading'));
    }

    function SettingsEditor({ initial, t }) {
      const [status, setStatus] = React.useState(null);
      // Whether each credential the card shows has a value: asked of DSH's credential store, never the value.
      const [credentialState, setCredentialState] = React.useState({});
      const describeCredentials = async refs => {
        if (!refs.length) return {};
        const response = await ctx.remote.credentials.describe(refs);
        const states = response?.ok ? Object.fromEntries(refs.map(ref => [ref, response.value[ref]?.configured === true])) : {};
        setCredentialState(previous => ({ ...previous, ...states }));
        return states;
      };
      const [notice, setNotice] = React.useState(''), [busy, setBusy] = React.useState(false);
      const [persona, setPersona] = React.useState(null);
      const loadPersona = () => rpc('personaSources').then(setPersona).catch(() => setPersona(null));
      React.useEffect(() => { loadPersona(); }, []);
      const runJob = async (job, dryRun) => { setBusy(true); setNotice('');
        try { const result = await rpc('personaJob', { request: { job, dry_run: dryRun } });
          setNotice(t('persona.jobResult', { job, dry: dryRun ? t('persona.runDry') : '', status: result.status,
            code: result.exit_code !== undefined ? t('persona.exitCode', { code: result.exit_code }) : '',
            reason: result.reason ? ' · ' + result.reason : '' }));
          loadPersona(); } catch (error) { setNotice(error.message); } finally { setBusy(false); } };
      const exportDocs = async () => { setBusy(true); setNotice('');
        try { const result = await rpc('personaExport'); setNotice(t('persona.exported', { n: result.exported.length })); }
        catch (error) { setNotice(error.message); } finally { setBusy(false); } };
      const [editor] = React.useState(() => {
        // Labels are read at render (the language may change); fields carry keys and parameters.
        const fields = [], add = (path, label, type = 'text') => fields.push({ path, label, type, field: JSON.stringify(path) });
        for (const key of ['persona', 'channelAdmission', 'python'])
          add([key], { key: 'settings.' + key }, ['persona', 'channelAdmission'].includes(key) ? 'choice' : 'text');
        for (const lane of ['character', 'action']) for (const key of ['provider', 'model', 'reasoningEffort', 'maxTokens'])
          add(['routes', lane, key], { key: 'settings.route', params: { brain: { key: 'brain.' + (lane === 'character' ? 'character' : 'executor') },
            field: { key: 'settings.route.' + key } } }, key === 'maxTokens' ? 'number' : 'choice');
        // Business values use the shipped settings fields. Structured settings
        // retain their JSON type; no second schema editor or settings store.
        for (const [key, value] of Object.entries(initial.deployment ?? {}))
          add(['deployment', key], key, typeof value === 'string' ? 'text' : 'json');
        // A new profile has no deployment yet: its required sections appear with a starting value staged
        // (the Mongo URI already pointing at a credential), so the page alone can configure it (ADR-010 M1).
        const starters = [];
        for (const [key, type, text] of [['database', 'text', ''], ['mongo_uri', 'json', '{"$secret":"ASUNA_MONGO_URI"}'],
          ['embedding', 'json', '{"base_url":"","model":""}']]) {
          if (initial.deployment?.[key] !== undefined) continue;
          add(['deployment', key], key, type);
          if (text) starters.push([JSON.stringify(['deployment', key]), text]);
        }
        const secretNames = new Set(initial.deployment?.mongo_uri === undefined ? ['ASUNA_MONGO_URI'] : []);
        const collect = value => { if (!value || typeof value !== 'object') return;
          if (typeof value.$secret === 'string') secretNames.add(value.$secret);
          else Object.values(value).forEach(collect); };
        collect(initial.deployment);
        // Credentials are write-only controls into DSH's credential store, never settings (ADR-010 D6): one per
        // reference the settings name, and one that stores values for references a new section names.
        for (const key of secretNames) add(['credentials', key], key, 'secret');
        add(['credentials'], { key: 'settings.newSecrets' }, 'secret-map');
        const byId = new Map(fields.map(field => [field.field, field]));
        const flatten = value => Object.fromEntries(fields.flatMap(field => {
          const entry = field.path.reduce((value, key) => value?.[key], value);
          return entry === undefined || field.type.startsWith('secret') ? [] : [[field.field, entry]];
        }));
        const scope = { subscribe, getSnapshot: () => {
          const saved = snapshot();
          return { ...saved, value: flatten(saved.value), base: flatten(saved.base), user: flatten(saved.user) };
        }, mutate: async (ops, revision) => {
          try {
            const edits = ops.map(op => ({ ...op, path: byId.get(op.path[0]).path }));
            await rpc('saveSettings', { ops: edits, revision });
            const response = await ctx.remote.settings.describe();
            if (response.ok) {
              const view = response.value.namespaces.find(row => row.ns === 'asuna-cognition-core');
              if (view) ctx.configForms.describe().acceptView(view);
            }
            const current = await rpc('status');
            setStatus(current); setNotice(current.pending ? t('settings.savedPending') : t('settings.savedApplied')); return true;
          } catch (error) { setNotice(error.message); return false; }
        } };
        const store = async values => {
          for (const [ref, value] of Object.entries(values)) {
            const response = await ctx.remote.credentials.set(ref, value);
            if (response && response.ok === false) throw new Error(response.error?.message ?? 'CREDENTIAL_NOT_STORED');
          }
          const states = await describeCredentials(Object.keys(values));
          return Object.keys(values).every(ref => states[ref]);
        };
        const secrets = fields.filter(field => field.type.startsWith('secret')).map(field => ({ field: field.field,
          write: async text => { try {
            if (field.type === 'secret') return await store({ [field.path[1]]: text });
            const value = JSON.parse(text);
            if (!value || Array.isArray(value) || typeof value !== 'object' || Object.entries(value).some(([ref, item]) =>
              typeof item !== 'string' || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(ref))) throw new Error(t('settings.secretMapHint'));
            return await store(value);
          } catch (error) { setNotice(error.message); return false; } } }));
        const model = new SettingsFormModel(scope, fields.filter(field => !field.type.startsWith('secret')).map(field => ({ field: field.field,
          format: value => value === undefined ? '' : field.type === 'json' ? JSON.stringify(value) : String(value),
          parse: text => { try {
            // An empty reasoning choice explicitly uses the provider default;
            // clearing an override would instead re-inherit a previous effort.
            if (field.path[2] === 'reasoningEffort') return { kind: 'set', value: text };
            if (field.type === 'choice') return text ? { kind: 'set', value: text } : undefined;
            if (!text.trim()) return { kind: 'clear' };
            const value = ['json', 'number'].includes(field.type) ? JSON.parse(text) : text;
            if (field.type === 'number' && (!Number.isSafeInteger(value) || value < 1)) return undefined;
            return { kind: 'set', value };
          } catch { return undefined; } } })), secrets);
        return { fields, model, starters, actions: model.actions(), store: model.bind(() => ({ shell: model.shell(),
          fields: Object.fromEntries(fields.map(field => [field.field, model.field(field.field)])) })) };
      });
      const state = React.useSyncExternalStore(editor.store.subscribe, editor.store.getSnapshot);
      const routeValue = (lane, key) => state.fields[JSON.stringify(['routes', lane, key])].text;
      const choices = field => {
        if (field.path[0] === 'channelAdmission') return [['automatic', t('settings.admission.automatic')], ['explicit', t('settings.admission.explicit')]];
        if (field.path[0] === 'persona') return (status?.personas ?? []).map(persona => [persona.id, persona.name || persona.id]);
        const [, lane, key] = field.path, providers = status?.providers ?? [];
        if (key === 'provider') return providers.map(provider => [provider.id, provider.name || provider.id]);
        const provider = providers.find(provider => provider.id === routeValue(lane, 'provider'));
        if (key === 'model') return (provider?.models ?? []).map(model => [model.id, model.name || model.id]);
        const model = provider?.models.find(model => model.id === routeValue(lane, 'model'));
        return model ? [['', t('settings.providerDefault')], ...(model.reasoning?.efforts ?? []).map(effort => [effort.id, effort.name])] : [];
      };
      const choose = (field, value) => {
        editor.actions.edit(field.field, value);
        const [, lane, key] = field.path;
        if (field.path[0] !== 'routes' || !['provider', 'model'].includes(key)) return;
        const provider = status?.providers.find(provider => provider.id === (key === 'provider' ? value : routeValue(lane, 'provider')));
        let model = provider?.models.find(model => model.id === (key === 'model' ? value : routeValue(lane, 'model')));
        if (key === 'provider') {
          if (!model && provider?.models.length === 1) model = provider.models[0];
          editor.actions.edit(JSON.stringify(['routes', lane, 'model']), model?.id ?? '');
        }
        if (!model?.reasoning?.efforts.some(effort => effort.id === routeValue(lane, 'reasoningEffort')))
          editor.actions.edit(JSON.stringify(['routes', lane, 'reasoningEffort']), '');
      };
      React.useEffect(() => () => editor.model.dispose(), [editor]);
      React.useEffect(() => {
        const refs = editor.fields.filter(field => field.type === 'secret').map(field => field.path[1]);
        describeCredentials(refs).catch(error => setNotice(error.message));
        return ctx.remote.$on('credentials/reference-updated', ref => {
          if (refs.includes(ref)) describeCredentials([ref]).catch(() => {});
        });
      }, [editor]);
      React.useEffect(() => { for (const [field, text] of editor.starters) editor.actions.edit(field, text); }, [editor]);
      React.useEffect(() => { const controller = new AbortController();
        rpc('status', {}, controller.signal).then(setStatus).catch(error => { if (!controller.signal.aborted) setNotice(error.message); });
        return () => controller.abort(); }, []);
      const activate = async () => { setBusy(true); setNotice('');
        try { setStatus(await rpc('applySettings')); setNotice(t('settings.activated')); }
        catch (error) { setNotice(error.message); } finally { setBusy(false); } };
      const worker = status?.worker;
      return h('section', { style: stack, 'aria-label': t('settings.aria') },
        h('h3', null, 'Asuna'),
        h('p', null, status ? t('settings.status', { state: status.lifecycle.state + (status.lifecycle.step ? ' · ' + status.lifecycle.step : ''), database: worker?.database || t('settings.disconnected') })
          : t('settings.readingStatus')),
        status?.lifecycle.error && h('p', { role: 'alert' }, status.lifecycle.error),
        // A publication that only a Host restart puts into effect is said, never left silent (ADR-021 D4).
        ...(status?.publications ?? []).filter(p => p.state === 'HOST_RESTART_REQUIRED').map(p => h('p', { key: 'restart-' + p.project,
          role: 'status' }, t('settings.restartWaiting', { project: p.project,
            time: p.published_at ? new Date(p.published_at).toLocaleString() : '?' }))),
        h('p', { style: small }, t('settings.note')),
        h(SettingsForm, { state: state.shell, onSave: editor.actions.save, onDiscard: editor.actions.discard,
          labels: { unavailable: t('settings.form.unavailable'), readOnly: t('settings.form.readOnly'),
            saveFailed: t('settings.form.saveFailed'), save: t('settings.form.save'), saving: t('settings.form.saving') } },
          ...editor.fields.map(field => {
            // A valid element id (the field key is JSON, which no selector or label-for can address).
            const props = { key: field.field, id: 'asuna-setting-' + field.path.join('-').replace(/[^A-Za-z0-9_-]/g, '_'), label: say(t, field.label),
              ...state.fields[field.field], disabled: busy || state.shell.saving || !state.shell.writable,
              overriddenLabel: t('settings.overridden'), resetLabel: t('settings.reset'),
              invalidLabel: field.type === 'number' ? t('settings.invalidNumber') : t('settings.invalidJson'),
              onEdit: text => editor.actions.edit(field.field, text), onReset: () => editor.actions.resetField(field.field) };
            if (field.type === 'choice') return h(Select, { ...props, t, value: props.text, options: choices(field),
              onChange: value => choose(field, value),
              hint: field.path[0] === 'routes' ? t('settings.routeHint') : undefined });
            return field.type.startsWith('secret') ? h(SettingsSecretField, { ...props, configured: credentialState[field.path[1]] ?? false,
              hint: field.type === 'secret-map' ? t('settings.secretMapHint') : t('settings.secretHint'),
              stateLabel: field.type === 'secret-map' ? t('settings.secretAdd') : credentialState[field.path[1]] ? t('settings.secretSet') : t('settings.secretUnset') })
              : h(SettingsValueField, { ...props, numeric: field.type === 'number',
                hint: field.type === 'json' ? t('settings.jsonHint') : field.path[0] === 'python' ? t('settings.pythonHint') : undefined });
          })),
        status && h('p', { style: small }, [
          t('settings.selfSource', { source: worker?.self_source || t('settings.waiting') }),
          t('settings.channels', { titles: worker?.channel_titles?.join(t('memory.separator')) || t('settings.channelsFallback'),
            state: worker?.channels_active ? t('settings.channelOn', { state: worker.integration_state }) : t('settings.channelOff') })
            + (worker?.integration_error ? ' · ' + worker.integration_error : ''),
          t('settings.schedule', { state: worker?.schedules_active ? t('settings.scheduleOn') : t('settings.channelOff') }),
          ...(worker?.sandbox ? [t('settings.sandbox', { state: worker.sandbox.backend === 'none'
            ? t('settings.sandboxNone', { reason: worker.sandbox.reason }) : worker.sandbox.backend })] : [])].join(' · ')),
        status && h('p', { role: 'status' }, status.pending ? t('settings.pending') : t('settings.applied')),
        h('div', { style: { display: 'flex', gap: 8, flexWrap: 'wrap' } },
          h(Button, { disabled: busy || state.shell.dirty || state.shell.saving, onClick: activate, variant: 'outline' }, t('settings.apply')),
          h(Button, { disabled: busy, onClick: () => rpc('status').then(setStatus).catch(error => setNotice(error.message)) }, t('settings.refresh'))),
        persona && h('section', { style: stack, 'aria-label': t('persona.aria') },
          h('h4', null, t('persona.title', { persona: persona.persona })),
          persona.render && h('p', { role: persona.render.over_budget ? 'alert' : 'status',
            style: persona.render.over_budget ? { color: 'var(--dsw-alias-status-danger, #c00)' } : small },
            t('persona.render', { estimate: persona.render.estimate_tokens, limit: persona.render.limit_tokens ?? t('persona.unlimited') })
              + (persona.render.over_budget ? ' · ' + t('persona.overBudget') : '')),
          h('p', { style: small }, persona.sources.length
            ? t('persona.sources', { list: persona.sources.map(source => t('persona.source', source)).join(t('memory.separator')) })
            : t('persona.noSources')),
          ...persona.jobs.map(job => h('div', { key: job.id, style: { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' } },
            h('span', null, t('persona.job', { id: job.id, sources: job.sources.join(t('memory.separator')) })),
            h(Button, { size: 'sm', disabled: busy, onClick: () => runJob(job.id, true) }, t('persona.dryRun')),
            h(Button, { size: 'sm', disabled: busy, variant: 'outline', onClick: () => runJob(job.id, false) }, t('persona.run')))),
          persona.runs.length > 0 && h('p', { style: small }, t('persona.runs', { list: persona.runs.map(run =>
            run.job + ' ' + run.status + (run.dry_run ? t('persona.runDry') : '')).join(t('memory.separator')) })),
          h(Button, { size: 'sm', disabled: busy || !persona.export_configured, onClick: exportDocs },
            persona.export_configured ? t('persona.export') : t('persona.exportUnset'))),
        notice && h('p', { role: 'status' }, notice));
    }

    ctx.effect(() => ctx.sidebarRightTabs.register({ id: '@asuna/memory', kind: 'asuna-memory', title: () => t('memory.tab'),
      guide: [{ id: 'asuna-memory', order: 50, title: () => t('memory.tab'), description: () => t('memory.guide') }] }));
    ctx.slots.inject('sidebar.right.pane.tab', () => ctx.slots.register({ name: 'sidebar.right.pane.tab', key: '@asuna/memory', locale: NS }, Memory));
    ctx.slots.inject('plugins.bundle.config', () => ctx.slots.register({ name: 'plugins.bundle.config', key: '@asuna/cognition-core', locale: NS }, Settings));

    // Two context wheels in a character conversation (owner-approved, 2026-10-04): DSH's own meter is
    // the character brain (purple); a second instance of that same meter, fed the latest action
    // session's projections, is the action brain (blue). Nothing is shown in other sessions.
    function BrainMeters({ sessionId }) {
      const [state, setState] = React.useState(null), [shipped, setShipped] = React.useState(null);
      const anchor = React.useRef(null);
      React.useEffect(() => {
        if (!sessionId) return undefined;
        let alive = true;
        const load = () => rpc('brainContext', { sessionId }).then(value => {
          if (!alive) return;
          setState(value);
          setShipped(current => current ?? shippedContextMeter(anchor.current));
        }).catch(() => {});
        load();
        const timer = setInterval(load, 5000);
        return () => { alive = false; clearInterval(timer); setState(null); };
      }, [sessionId]);
      const action = state?.action;
      return h('span', { ref: anchor, className: 'asuna-action-meter' },
        state && h('style', null, meterPalette),
        action && shipped && h(shipped.Meter, { useProjection: key => action[key], t: shipped.t }));
    }
    ctx.slots.inject('conversation.composer.dock', () => ctx.slots.register({
      name: 'conversation.composer.dock', id: 'asuna-brain-meters', order: 100 }, BrainMeters));

    // Add only Asuna business attribution in public extension points. Never
    // shadow assistant-step or replace the native Chat grouping definition.
    ctx.effect(() => {
      const style = document.createElement('style');
      style.textContent = brainPalette;
      document.head.append(style);
      return () => style.remove();
    });
    for (const definition of [...stageDefinitions(), ...collabDefinitions(), ...repairDefinitions()])
      ctx.effect(() => ctx.uiConversation.events.register(definition));

    // ── the collaboration thread ──────────────────────────────────────
    // The action brain's records render inline only where DSH's Chat offers its fragment factory (the local
    // rendering extension, ADR-010 D7); elsewhere a work row opens the action session in DSH's own subagent view.
    const inlineChat = () => ctx.slots.snapshot('factory:conversation.chat.content').length > 0;
    const openSubagent = (child, parent) => ctx.sidebarRight.openResource('dsh-resource://subagentchat/session/'
      + encodeURIComponent(child) + '?' + new URLSearchParams({ parent, mode: 'one-shot' }),
      { kind: 'subagentchat', preferNewPane: true });
    function Work(props) {
      if (inlineChat()) return h(InlineWork, props);
      const { entry, parent, t } = props;
      return h(Button, { size: 'sm', variant: 'ghost', onClick: () => openSubagent(entry.child_session_id, parent) },
        t('collab.open'));
    }
    /** The action session's own records for one stretch of work, as DSH renders them (a fragment). */
    function InlineWork(props) {
      const { entry, parent } = props;
      const [reference, setReference] = React.useState(null), [error, setError] = React.useState('');
      React.useEffect(() => {
        const controller = new AbortController();
        const target = { parentSessionId: parent, childSessionId: entry.child_session_id, mode: 'unknown' };
        const ref = ctx.sessions.retain(target, { source: 'asunaCollab', signal: controller.signal });
        ref.ready.then(() => { if (!controller.signal.aborted) setReference(ref); })
          .catch(error => { if (!controller.signal.aborted) setError(error.message); });
        return () => { controller.abort(); ref.release(); };
      }, [entry.child_session_id, parent]);
      return reference ? h(props.SessionProvider, { session: reference },
        props.renderSlot('asuna.collab.work', { owner: { node: { data: entry } } }))
        : h('p', { role: error ? 'alert' : 'status', style: small }, error || props.t('collab.loading'));
    }
    const workKinds = ['turn-process', 'assistant-step', 'tool-call', 'turn-error', 'turn-max-tokens',
      'model-retry', 'compaction', 'manual-compaction', 'command'];
    function WorkFragment(props) {
      const range = props.owner.node.data;
      return props.renderFactorySlot('conversation.chat.content', { variant: 'fragment', kinds: workKinds,
        after: range.after_seq, through: range.through_seq });
    }
    function Bubble({ entry, t }) {
      const lane = entry.from === 'action' ? 'executor' : 'character';
      const [all, setAll] = React.useState(false);
      const text = String(entry.text ?? '');
      const long = text.split('\n').length > 6 || text.length > 360;
      return h('div', { className: 'asuna-collab-bubble asuna-collab-' + lane },
        h('div', { style: { display: 'flex', alignItems: 'center', gap: 6 } },
          h(Pill, { className: brainClass(lane) }, t('brain.' + lane)),
          entry.kind === 'progress' && h('span', { style: small }, t('collab.progress'))),
        h('div', { className: 'asuna-collab-text' + (long && !all ? ' asuna-collab-clipped' : '') },
          h(MarkdownText, { text, labels: markdownLabels(t) })),
        long && h(Button, { size: 'sm', variant: 'ghost', onClick: () => setAll(value => !value) },
          all ? t('collab.less') : t('collab.more')));
    }
    function WorkRow(props) {
      const { entry, t } = props;
      const [open, setOpen] = React.useState(false);
      return h(DisclosureRow, { icon: h(IconChevronDownOutlineRegular), previewChevron: false,
        title: t('collab.work', { duration: duration(t, entry.duration_ms ?? 0) }),
        collapsedContent: h('span', { style: { marginLeft: 8, ...small } },
          t(entry.tool_calls === 1 ? 'collab.call' : 'collab.calls', { n: entry.tool_calls ?? 0 })),
        keepContentWhenOpen: true, open, expandable: true, expandOnRowClick: true, onToggle: () => setOpen(value => !value) },
        open && h(Work, { ...props }));
    }
    /** The action brain's work still going on: its native records after the last work row, as they come. */
    function LiveWorkRow(props) {
      const { live, t } = props;
      const [open, setOpen] = React.useState(false), now = Date.now();      // the thread re-renders while running
      return h(DisclosureRow, { icon: h(IconChevronDownOutlineRegular), previewChevron: false,
        title: t('collab.working', { duration: duration(t, Math.max(0, now - (Number.isFinite(live.since) ? live.since : now))) }),
        collapsedContent: h('span', { style: { marginLeft: 8, ...small } }, t('collab.watch')),
        keepContentWhenOpen: true, open, expandable: true, expandOnRowClick: true, onToggle: () => setOpen(value => !value) },
        open && h(Work, { ...props, entry: { child_session_id: live.child, after_seq: live.after } }));
    }
    function CollabThread(props) {
      const t = props.t, { entries } = props.node.data;
      const thread = threadOf(entries);
      // While the thread goes on, its clock and the live work row's tick together.
      const [, tick] = React.useState(0);
      React.useEffect(() => {
        if (!['running', 'queued', 'waiting'].includes(thread.state)) return undefined;
        const timer = setInterval(() => tick(count => count + 1), 15000);
        return () => clearInterval(timer);
      }, [thread.state]);
      const parent = thread.open?.parent_session_id ?? props.sessionId;
      const child = thread.child;
      const openAside = child && parent ? () => openSubagent(child, parent) : null;
      return h('section', { className: 'asuna-collab', 'aria-label': t('collab.header', {
        character: t('brain.character'), action: t('brain.executor') }) },
        h('div', { className: 'asuna-collab-head' },
          h('span', null, t('collab.header', { character: t('brain.character'), action: t('brain.executor') }), ' · '),
          h('span', { className: 'asuna-collab-title' }, thread.title || t('collab.untitled')),
          h(Pill, null, t('collab.state.' + thread.state)),
          thread.elapsed !== null && h('span', { style: small }, duration(t, thread.elapsed)),
          openAside && h(Button, { size: 'sm', variant: 'ghost', onClick: openAside }, t('collab.open'))),
        ...entries.filter(entry => entry.kind !== 'open' && entry.kind !== 'continued').map(entry =>
          entry.kind === 'work' ? h(WorkRow, { key: entry.id, entry, t, parent, SessionProvider: props.SessionProvider,
              renderSlot: props.renderSlot })
            : entry.kind === 'status' ? (entry.state === 'stopped' ? h('p', { key: entry.id, style: small },
              t('collab.stopped', { reason: entry.reason ?? '' }))
              : entry.state === 'paused' && entry === entries.at(-1) && h('p', { key: entry.id, style: small }, t('collab.paused')))
            : h(Bubble, { key: entry.id, entry, t })),
        thread.live && h(LiveWorkRow, { key: 'live:' + thread.live.after, live: thread.live, t, parent,
          SessionProvider: props.SessionProvider, renderSlot: props.renderSlot }));
    }
    ctx.slots.inject('conversation.chat.node', () => ctx.slots.register({
      name: 'conversation.chat.node', key: 'asuna-collab', locale: NS, children: {
        'asuna.collab.work': { kind: 'single', scope: 'session' },
      },
    }, CollabThread));
    ctx.slots.inject('asuna.collab.work', () => ctx.slots.register({ name: 'asuna.collab.work' }, WorkFragment));

    // ── her tool rows and the action brain's ways to reach her ────────
    function RoleToolRow(props) {
      const t = props.t, name = props.toolName;
      const disclosure = props.useDisclosure();
      const raw = props.phase === 'start' ? props.block.argsRaw : props.phase === 'result' ? props.block.call?.argsRaw : '';
      const args = parseArgs(raw);
      const refused = props.phase === 'result' && props.block.isError;
      const said = args[TOOL_SUMMARY[name]];
      const summary = name === 'think' ? firstSentence(said) : typeof said === 'string' ? said : said === undefined ? '' : JSON.stringify(said);
      // A call whose only text is its summary (stay_silent's reason, feel's why…) still opens to that text in
      // full when the one-line row would cut it off; a call with a body opens to the body.
      const body = typeof args[TOOL_BODY[name]] === 'string' ? args[TOOL_BODY[name]]
        : name !== 'think' && typeof said === 'string' && said.length > 40 ? said : '';
      const result = props.phase === 'result' ? resultText(props.block) : '';
      const Icon = primitives[TOOL_ICONS[name]] ?? primitives.IconInfoOutlineRegular;
      const detail = [body && h(MarkdownText, { key: 'body', text: body, labels: markdownLabels(t) }),
        refused && h('p', { key: 'refused', style: { ...small, color: 'var(--dsw-alias-state-error-primary)' } }, t('tool.refused') + ' · ' + result)]
        .filter(Boolean);
      return h(DisclosureRow, { icon: h(Icon), previewChevron: false,
        title: t('tool.' + name),
        // DSH's own row text: the secondary size, a dot between the title and what the call was about.
        collapsedContent: h('span', { style: { minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          fontSize: 'var(--dsh-content-font-size-secondary, 13px)',
          ...(refused ? { color: 'var(--dsw-alias-state-error-primary)' } : {}) } },
          h('span', { 'aria-hidden': true, style: { margin: '0 6px', opacity: .6 } }, '·'),
          props.phase === 'preparing' ? t('tool.preparing') : refused ? t('tool.refused') : summary),
        keepContentWhenOpen: true, open: disclosure.expanded, expandable: detail.length > 0,
        expandOnRowClick: true, onToggle: disclosure.toggle }, ...detail);
    }
    for (const name of ROLE_TOOLS) ctx.slots.inject('tool.call.toolview', () => ctx.slots.register({
      name: 'tool.call.toolview', key: name, locale: NS }, RoleToolRow));
    // The program's note between a rejected draft and her rewrite, drawn like her tool rows.
    function RepairNote(props) {
      const t = props.t, text = props.node.data.text;
      const [open, setOpen] = React.useState(false);
      const long = text.length > 80;
      return h(DisclosureRow, { icon: h(primitives.IconInfoOutlineRegular), previewChevron: false,
        title: t('repair.title'),
        collapsedContent: h('span', { style: { minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
          fontSize: 'var(--dsh-content-font-size-secondary, 13px)' } },
          h('span', { 'aria-hidden': true, style: { margin: '0 6px', opacity: .6 } }, '·'), text),
        keepContentWhenOpen: true, open, expandable: long, expandOnRowClick: true, onToggle: () => setOpen(value => !value) },
        ...(long ? [h('p', { key: 'note', style: { ...small, whiteSpace: 'pre-wrap' } }, text)] : []));
    }
    ctx.slots.inject('conversation.chat.node', () => ctx.slots.register({
      name: 'conversation.chat.node', key: 'asuna-repair', locale: NS }, RepairNote));

    // ── where a conversation is: the local workspace's name, a group or a DM ──
    // DSH stores workspace titles as plain text: the client gives the words it shows, again on a switch.
    let titledIn;
    const titleWorkspaces = () => {
      const active = ctx.locale.getSnapshot().active;
      if (!active || active === titledIn) return;       // empty while the page is still resolving its language
      titledIn = active;
      rpc('workspaceTitles', { titles: { Local: t('workspace.local') } }).catch(() => { titledIn = undefined; });
      // The names the program gives in the task page and the scheduler session follow this language too.
      rpc('uiLanguage', { locale: active }).catch(() => { titledIn = undefined; });
    };
    ctx.effect(() => ctx.locale.subscribe(titleWorkspaces)); titleWorkspaces();
    // A small mark before each of her platform conversations in the sidebar (DSH's leading row slot).
    const sceneKinds = { value: {}, listeners: new Set(), asked: new Set() };
    const subscribeKinds = listener => { sceneKinds.listeners.add(listener); return () => sceneKinds.listeners.delete(listener); };
    const askKinds = () => {
      const ids = Object.keys(ctx.sessions.list.getSnapshot().byId).filter(id => !sceneKinds.asked.has(id)).slice(0, 500);
      if (!ids.length) return;
      for (const id of ids) sceneKinds.asked.add(id);
      rpc('sessionKinds', { sessionIds: ids }).then(kinds => {
        sceneKinds.value = { ...sceneKinds.value, ...kinds }; for (const listener of sceneKinds.listeners) listener();
      }).catch(() => { for (const id of ids) sceneKinds.asked.delete(id); });
    };
    ctx.effect(() => ctx.sessions.list.subscribe(askKinds)); askKinds();
    function SceneKindMark({ sessionId, t }) {
      const kind = React.useSyncExternalStore(subscribeKinds, () => sceneKinds.value)[sessionId];
      if (kind !== 'group' && kind !== 'dm') return null;
      const Icon = kind === 'group' ? primitives.IconUsersOutlineRegular : primitives.IconUserOutlineRegular;
      const label = t(kind === 'group' ? 'session.group' : 'session.dm');
      return h('span', { title: label, 'aria-label': label, role: 'img',
        style: { display: 'inline-flex', color: 'var(--dsw-alias-label-tertiary)' } }, Icon ? h(Icon, { size: 12 }) : null);
    }
    ctx.slots.inject('sidebar.session.row.leading', () => ctx.slots.register({
      name: 'sidebar.session.row.leading', id: 'asuna-scene-kind', order: 0, locale: NS }, SceneKindMark));

    // ── DSH's permission picker, only where it does something ─────────
    // It sets DSH's shell sandbox and approval policy; her two brains use neither (api.js brainPresets).
    // In their sessions it is not shown; every other session renders DSH's own picker, given the same
    // injection and locale DSH gives it, so nothing about it changes there.
    const brainPresets = { value: new Set(), listeners: new Set() };
    rpc('brainPresets').then(list => {
      brainPresets.value = new Set(list); for (const listener of brainPresets.listeners) listener();
    }).catch(error => ctx.logger?.warn?.(String(error)));
    const subscribePresets = listener => { brainPresets.listeners.add(listener); return () => brainPresets.listeners.delete(listener); };
    const shippedPermission = () => ctx.slots.entries('conversation.input.permission')
      .find(entry => entry.component !== PermissionPicker);
    function PermissionPicker(props) {
      const presets = React.useSyncExternalStore(subscribePresets, () => brainPresets.value);
      const preset = props.useSessions(state => state.byId[props.sessionId]?.projectionValues?.agentPreset);
      if (typeof preset === 'string' && presets.has(preset)) return null;
      const shipped = shippedPermission();
      return shipped ? h(shipped.component, props) : null;
    }
    ctx.slots.inject('conversation.input.permission', () => ctx.slots.register({
      name: 'conversation.input.permission', priority: -1, locale: 'permission.access',
      inject: sessionId => shippedPermission()?.options.inject?.(sessionId) ?? {},
    }, PermissionPicker));

    // ── a turn's trigger, titled in the viewer's language ─────────────
    // DSH titles a turn started by a notice "execution requested"; an Asuna notice says what started it.
    function AsunaTrigger(props) {
      const source = props.node?.data?.source;
      const shipped = ctx.slots.entries('conversation.chat.node')
        .find(entry => entry.options.key === 'turn-trigger' && entry.component !== AsunaTrigger);
      if (!shipped) return null;
      if (source?.kind !== 'asuna' || !source.trigger) return h(shipped.component, props);
      const title = t('trigger.' + source.trigger);
      return h(shipped.component, { ...props, t: (key, params) => key === 'message.trigger.request' ? title : props.t(key, params) });
    }
    ctx.slots.inject('conversation.chat.node', () => ctx.slots.register({
      name: 'conversation.chat.node', key: 'turn-trigger', priority: -1, locale: 'chat',
    }, AsunaTrigger));

    // DSH's max-tokens notice says the reply was cut off and asks for "continue". A Turn whose last
    // stage finished (the platform retried the cut-off attempt itself) was not cut off, so it has no
    // notice; every other Turn, in any session, renders DSH's own notice unchanged.
    function MaxTokensNotice(props) {
      const finish = props.useTurnData('asuna-stage-finish');
      if (finish === 'stop') return null;
      const shipped = ctx.slots.entries('conversation.chat.node')
        .find(entry => entry.options.key === 'turn-max-tokens' && entry.component !== MaxTokensNotice);
      return shipped ? h(shipped.component, props) : null;
    }
    ctx.slots.inject('conversation.chat.node', () => ctx.slots.register({
      name: 'conversation.chat.node', key: 'turn-max-tokens', priority: -1, locale: 'chat',
    }, MaxTokensNotice));
    ctx.slots.inject('conversation.chat.node', () => ctx.slots.register({
      name: 'conversation.chat.node', key: 'asuna-stage', locale: NS,
    }, props => stageLabel(props.t, props.node.data)
      ? h(Pill, { className: brainClass(props.node.data.lane) }, stageLabel(props.t, props.node.data)) : null));
    const injectChat = sessionId => ({ hooks: { chat: ctx.uiConversation.binding(ctx.sessions.binding(sessionId)).target('chat') } });
    function ActiveStage(props) {
      const stage = props.useChat(snapshot => {
        const timeline = snapshot?.timeline;
        const turn = timeline?.turns.get(timeline.turnOrder.at(-1));
        return turn?.status === 'open' ? turn.steps.at(-1)?.data.get('asuna-stage') : undefined;
      });
      return stageLabel(props.t, stage) ? h(Pill, { className: brainClass(stage.lane) }, stageLabel(props.t, stage)) : null;
    }
    ctx.slots.inject('conversation.session.header.actions', () => ctx.slots.register({
      name: 'conversation.session.header.actions', id: 'asuna-active-stage', order: 50, inject: injectChat, locale: NS,
    }, ActiveStage));

  }
  return { apply, stageDefinitions, collabDefinitions, repairDefinitions, threadOf, stageIdentity, stageLabel, subscribeInputPolicies, DICTIONARY,
    inject: ['slots', 'locale', 'sidebarRight', 'sidebarRightTabs', 'connection', 'remote', 'remote.settings', 'remote.credentials', 'configForms',
      'sessions', 'conversation', 'uiConversation', 'uiWorkspace'] };
} });
