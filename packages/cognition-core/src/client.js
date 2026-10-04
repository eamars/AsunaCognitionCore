/* Native DSH Client contribution. React and controls come from the Host bundle. */
window.__ModuleLoader__.load({ id: '@asuna/cognition-core', factory: require => {
  const React = require('react');
  const { Button, Input, Menu, Pill, IconChevronDownOutlineRegular, DisclosureRow, MarkdownText, CodeBlock, SettingsForm, SettingsFormModel,
    SettingsValueField, SettingsSecretField, Tooltip } = require('@deepseek-ai/dsh-client-ui-primitives');
  const h = React.createElement;
  const labels = { code: { copyLabel: '复制', copiedLabel: '已复制' }, footnotes: '来源' };
  const stack = { display: 'flex', flexDirection: 'column', gap: 12, padding: 16, minWidth: 0,
    overflowWrap: 'anywhere', fontSize: 14, lineHeight: 1.6 };
  const small = { fontSize: 12, color: 'var(--dsw-alias-label-tertiary)' };
  const memoryDate = (value, compact = false) => {
    const date = new Date(value);
    return value && Number.isFinite(date.getTime()) ? date.toLocaleString('zh-CN', {
      ...(compact ? {} : { year: 'numeric' }), month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit', hour12: false,
    }) : '';
  };
  const memoryAuthor = value => typeof value === 'string' ? value.replace(/^qq:/, 'QQ · ') : '';
  const stageLabel = stage => ({ character: '角色脑', executor: '行动脑' })[stage?.lane] ?? null;
  const brainClass = lane => ['character', 'executor'].includes(lane) ? 'asuna-brain-' + lane : undefined;
  function subscribeInputPolicies(ctx, rpc) {
    let controller, previous = '', owned = new Map();
    const unconfirmed = new Set();
    const clear = id => {
      if (ctx.conversation.blocks.storeFor(id).getSnapshot() === owned.get(id))
        ctx.conversation.blocks.set(id, undefined);
      owned.delete(id);
      unconfirmed.delete(id);
    };
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
        const block = { reason: '正在确认会话输入权限…' };
        owned.set(id, block); unconfirmed.add(id); ctx.conversation.blocks.set(id, block);
      }
      rpc('inputPolicies', { sessionIds: ids }, signal).then(policies => {
        if (signal.aborted) return;
        for (const id of ids) {
          const reason = policies[id];
          if (!reason) { if (owned.has(id)) clear(id); continue; }
          unconfirmed.delete(id);
          const block = { reason }; owned.set(id, block); ctx.conversation.blocks.set(id, block);
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
  `;
  // DSH's meter (pinned DSH version's class) takes the character-brain purple; the action ring matches its geometry.
  const characterMeterTint = `
    .JObwrW_fill { stroke: #7e22ce; }
    body[data-ds-dark-theme] .JObwrW_fill { stroke: #c4b5fd; }
    .asuna-action-meter { display: inline-flex; align-items: center; gap: 6px; padding: 1px 8px; flex: none;
      color: var(--dsw-alias-label-tertiary); font-size: var(--dsh-content-font-size-secondary, 13px);
      font-variant-numeric: tabular-nums; line-height: calc(20px + var(--dsh-content-font-delta-secondary, 0px)); white-space: nowrap; }
    .asuna-meter-track { fill: none; stroke: var(--dsw-alias-border-l3); stroke-width: 2px; }
    .asuna-meter-fill { fill: none; stroke: var(--dsw-static-blue-600); stroke-width: 2px; stroke-linecap: round; }
    body[data-ds-dark-theme] .asuna-meter-fill { stroke: var(--dsw-static-blue-300); }
  `;
  function stageIdentity(source) {
    if (typeof source?.phase !== 'string' || !source.phase) return null;
    // Older source notices have phase but no lane. Infer only documented
    // business phases, never a brain from the selected provider/model.
    const lane = source.lane ?? (['execution', 'execution-repair', 'EXECUTE'].includes(source.phase) ? 'executor'
      : source.phase === 'dialogue-summary' ? 'summary'
      : ['MONOLOGUE', 'DECIDE', 'REFLECT', 'SELF', 'CONSULT', 'SPEAK'].includes(source.phase) ? 'character' : undefined);
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
    const markerState = (match, reader) => {
      const state = stageState(match, reader);
      const responseSeen = match.event.type.startsWith('assistant/');
      return { ...state, responseSeen, anchor: responseSeen ? state.sourceSeq ?? state.anchor - 0.2 : state.anchor,
        markerLocation: { kind: 'session' } };
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
        if (!state.responseSeen && match.event.type.startsWith('assistant/')) return { ...state,
          stage, responseSeen: true, anchor: match.event.seq - 0.2 };
        return stage === state.stage ? state : { ...state, stage };
      },
      publication: match => match.event.type === 'assistant/live-chunk' ? 'animation-frame' : 'immediate',
      buildViewNode: context => {
        // Keep one brain label with a native Turn's records, outside its
        // disclosure. Attribute every step separately, but never repeat the
        // label for tool followups. A cold partial Turn can use its first
        // loaded explicit notice without guessing unloaded attribution.
        const nativeStep = context.matches.some(match => match.location.kind === 'step');
        if (!stageLabel(context.state?.stage) || !nativeStep || !context.state.responseSeen) return null;
        const location = context.state.markerLocation;
        const previous = context.current.get('chat');
        if (previous?.data === context.state.stage && previous.location === location
            && previous.anchorSeq === context.state.anchor) return previous;
        return { key: context.key, kind: 'asuna-stage',
          id: context.id, target: 'chat', anchorSeq: context.state.anchor, location,
          visibility: 'visible', data: context.state.stage };
      },
    }];
  }
  function actionDefinitions() {
    return [{ kind: 'asuna-action-records', target: 'chat',
      match: event => event.type === 'asuna/action-linked'
        ? { id: event.data.segment_id ?? event.data.session_id, role: 'start' }
        : event.type === 'asuna/action-range' ? { id: event.data.segment_id, role: 'update' } : null,
      start: (_context, match) => ({ ...match.event.data, anchor: match.event.seq,
        location: { kind: 'session' } }),
      update: (context, match) => match.event.type === 'asuna/action-range'
        ? { ...context.state, ...match.event.data } : context.state,
      buildViewNode: context => !context.state?.location ? null : ({ key: context.key, kind: 'asuna-action-records',
        id: context.id, target: 'chat', anchorSeq: context.state.anchor,
        location: context.state.location, visibility: 'visible', data: context.state }),
    }];
  }
  // Same anchored Menu/Button primitives used by DSH's own preference rows.
  // The native form model still owns the staged value, reset and save.
  function Select({ id, label, value, options, onChange, disabled, overridden, onReset, hint }) {
    const [open, setOpen] = React.useState(false);
    const selected = options.find(option => option[0] === value);
    return h('div', { style: { display: 'flex', flexDirection: 'column', gap: 8 } },
      h('div', { style: { display: 'flex', alignItems: 'center', gap: 8 } },
        h('label', { htmlFor: id }, label), overridden && h(Pill, null, '已覆盖'),
        overridden && h(Button, { size: 'sm', disabled, onClick: onReset }, '恢复默认')),
      h(Menu, { open: open && !disabled, portal: true, selectedId: value,
        items: options.map(([id, label]) => ({ id, label })), onClose: () => setOpen(false),
        onSelect: value => { onChange(value); setOpen(false); },
        anchor: h(Button, { id, variant: 'outline', 'aria-label': label, 'aria-haspopup': 'menu',
          'aria-expanded': open && !disabled, disabled: disabled || !options.length,
          onClick: () => setOpen(value => !value) },
        selected?.[1] ?? (value ? value + '（当前不可用）' : '请选择'),
        h(IconChevronDownOutlineRegular, null)) }),
      hint && h('p', { style: small }, hint));
  }

  function apply(ctx) {
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

    // Use the shipped composer's block service, including blank/cold QQ
    // sessions. This is a service subscription, not a new UI slot/component.
    ctx.effect(() => subscribeInputPolicies(ctx, rpc));

    function Memory(props) {
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
      return h('section', { style: { ...stack, height: '100%', minHeight: 0, overflow: 'hidden' }, 'aria-label': 'Asuna 记忆' },
        h('div', { style: { display: 'flex', flexDirection: 'column', gap: 8, flexShrink: 0 } },
        h(Select, { label: '记忆类型', value: category, options: [['all', '全部'], ['documents', '文档'], ['affect', '情感'], ['jobs', '作业报告'], ['self', '自我'],
          ['relation', '对人的认识'], ['summary', '交流摘要'],
          ['interpretation', '当时的理解'], ['source', '原始来源']],
          onChange: value => { setCategory(value); setOffset(0); } }),
        h(Input, { 'aria-label': '搜索记忆', placeholder: '搜索当前类型的全部记录', value: search, maxLength: 160,
          onChange: event => setSearch(event.target.value),
          onCompositionStart: () => setComposing(true), onCompositionEnd: () => setComposing(false) }),
        h(Button, { size: 'sm', onClick: () => setRefresh(x => x + 1) }, '刷新记忆'),
        page && h('p', { style: { ...small, margin: 0 } }, page.scene_title,
          category === 'relation' ? ' · 当前交谈对象：' + page.subject_name : '',
          page.linked_scene_titles?.length ? ' · 也能读到：' + page.linked_scene_titles.join('、') : '')),
        h('div', { style: { display: 'flex', flexDirection: 'column', gap: 12, flex: 1, minHeight: 0, overflowY: 'auto' } },
        error && h('p', { role: 'alert' }, error.includes('NOT_BOUND') ? '当前会话尚无 Asuna 场景绑定。完成角色交互后可查看。' : error),
        !page && !error && h('p', null, '读取当前场景…'),
        page?.rows.map(row => h('article', { key: row.id },
          h(DisclosureRow, { icon: h(IconChevronDownOutlineRegular), previewChevron: false,
            title: memoryDate(row.updated_at, true) || row.status_label || row.category_label,
            collapsedContent: h('span', { style: { marginLeft: 8, minWidth: 0, overflow: 'hidden',
              textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--dsw-alias-label-primary)' } }, row.title),
            keepContentWhenOpen: true,
            open: selected === row.id, expandable: true,
            expandOnRowClick: true, onToggle: () => setSelected(selected === row.id ? null : row.id) },
            selected === row.id && (detail ? h('div', { style: { padding: '8px 0', color: 'var(--dsw-alias-label-primary)' } },
              h('p', { style: small }, [detail.category_label, detail.status_label].filter(Boolean).join(' · ')),
              h(MarkdownText, { text: detail.body, labels }),
              detail.usage && h('p', { style: small }, detail.usage.replace('{time}', memoryDate(detail.context_at, true))),
              detail.correction_note && h('p', null, detail.correction_note),
              h('p', { style: small }, [typeof detail.revision === 'number' ? '版本 ' + detail.revision : '',
                memoryAuthor(detail.speaker || detail.author),
                detail.generated_at ? '整理于 ' + memoryDate(detail.generated_at) : memoryDate(detail.occurred_at)].filter(Boolean).join(' · ')),
              detail.levels && Object.keys(detail.levels).length > 0 && h('p', { style: small },
                '已有关系档位（0–4）：' + Object.entries(detail.levels).map(([name, value]) => name + ' ' + value).join(' · ')),
              detail.sources_truncated && h('p', { style: small }, '以下显示前 12 条来源。'),
              ...detail.sources.map(source => h('blockquote', { key: source._id },
                h('p', { style: small }, [source.category_label || '原始消息', memoryAuthor(source.author), source.scene_title,
                  memoryDate(source.occurred_at)].filter(Boolean).join(' · ')),
                h(MarkdownText, { text: source.text, labels })))) : h('p', null, '读取详情…'))),
          selected !== row.id && row.excerpt && h('p', { style: { margin: '4px 0', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' } }, row.excerpt),
          (category === 'all' || (row.scene_title && row.scene_title !== page.scene_title)) && h('p', { style: { ...small, margin: 0 } },
            [category === 'all' ? row.category_label : '',
              row.scene_title && row.scene_title !== page.scene_title ? row.scene_title : ''].filter(Boolean).join(' · ')))),
        page && !page.rows.length && h('p', null, query ? '未找到匹配的记录。' : '当前范围暂无记录。')),
        page && h('div', { style: { display: 'flex', gap: 8, flexShrink: 0 } },
          h(Button, { disabled: offset === 0, onClick: () => setOffset(Math.max(0, offset - 24)) }, '上一页'),
          h(Button, { disabled: page.next_offset === null, onClick: () => setOffset(page.next_offset) }, '下一页')));
    }

    function Settings() {
      const saved = React.useSyncExternalStore(subscribe, snapshot);
      return saved.value ? h(SettingsEditor, { initial: saved.value })
        : h('p', null, saved.status === 'unavailable' ? '配置暂不可用。' : '读取设置…');
    }

    function SettingsEditor({ initial }) {
      const [status, setStatus] = React.useState(null);
      const [notice, setNotice] = React.useState(''), [busy, setBusy] = React.useState(false);
      const [persona, setPersona] = React.useState(null);
      const loadPersona = () => rpc('personaSources').then(setPersona).catch(() => setPersona(null));
      React.useEffect(() => { loadPersona(); }, []);
      const runJob = async (job, dryRun) => { setBusy(true); setNotice('');
        try { const result = await rpc('personaJob', { request: { job, dry_run: dryRun } });
          setNotice('作业 ' + job + (dryRun ? '（试运行）' : '') + '：' + result.status + (result.exit_code !== undefined ? ' · 退出码 ' + result.exit_code : '')
            + (result.reason ? ' · ' + result.reason : '') + ' · 报告在「记忆 → 作业报告」中查看。');
          loadPersona(); } catch (error) { setNotice(error.message); } finally { setBusy(false); } };
      const exportDocs = async () => { setBusy(true); setNotice('');
        try { const result = await rpc('personaExport'); setNotice('已导出 ' + result.exported.length + ' 份文档。'); }
        catch (error) { setNotice(error.message); } finally { setBusy(false); } };
      const [editor] = React.useState(() => {
        const fields = [], add = (path, label, type = 'text') => fields.push({ path, label, type, field: JSON.stringify(path) });
        for (const [key, label] of [['persona', '当前角色'], ['qqAdmission', 'QQ 接入策略'],
          ['python', 'Python'], ['workspace', '工作目录'], ['configPath', '旧配置迁移来源']])
          add([key], label, ['persona', 'qqAdmission'].includes(key) ? 'choice' : 'text');
        for (const lane of ['character', 'action']) for (const key of ['provider', 'model', 'reasoningEffort', 'maxTokens'])
          add(['routes', lane, key], (lane === 'character' ? '角色脑 · ' : '行动脑 · ')
            + ({ provider: '模型服务', model: '模型', reasoningEffort: '推理强度', maxTokens: '最大输出 token' })[key],
            key === 'maxTokens' ? 'number' : 'choice');
        // Business values use the shipped settings fields. Structured settings
        // retain their JSON type; no second schema editor or settings store.
        for (const [key, value] of Object.entries(initial.deployment ?? {}))
          add(['deployment', key], key, typeof value === 'string' ? 'text' : 'json');
        const secretNames = new Set();
        const collect = value => { if (!value || typeof value !== 'object') return;
          if (typeof value.$secret === 'string') secretNames.add(value.$secret);
          else Object.values(value).forEach(collect); };
        collect(initial.deployment);
        for (const key of secretNames) add(['secrets', key], key, 'secret');
        // One native write-only field can provision references for a newly
        // added channel without exposing or restating existing credentials.
        add(['secrets'], '新增或更新凭据（JSON）', 'secret-map');
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
            const edits = ops.flatMap(op => {
              const field = byId.get(op.path[0]);
              return field.type === 'secret-map' && op.op === 'set'
                ? Object.entries(op.value).map(([key, value]) => ({ op: 'set', path: ['secrets', key], value }))
                : [{ ...op, path: field.path }];
            });
            await rpc('saveSettings', { ops: edits, revision });
            const response = await ctx.remote.settings.describe();
            if (response.ok) {
              const view = response.value.namespaces.find(row => row.ns === 'asuna-cognition-core');
              if (view) ctx.configForms.describe().acceptView(view);
            }
            const current = await rpc('status');
            setStatus(current); setNotice(current.pending ? '已保存，尚未应用。' : '已保存，与当前应用配置一致。'); return true;
          } catch (error) { setNotice(error.message); return false; }
        } };
        const model = new SettingsFormModel(scope, fields.map(field => ({ field: field.field,
          format: value => value === undefined ? '' : field.type === 'json' ? JSON.stringify(value) : String(value),
          parse: text => { try {
            // An empty reasoning choice explicitly uses the provider default;
            // clearing an override would instead re-inherit a previous effort.
            if (field.path[2] === 'reasoningEffort') return { kind: 'set', value: text };
            if (field.type === 'choice') return text ? { kind: 'set', value: text } : undefined;
            if (!text.trim()) return { kind: 'clear' };
            const value = ['json', 'number', 'secret-map'].includes(field.type) ? JSON.parse(text) : text;
            if (field.type === 'number' && (!Number.isSafeInteger(value) || value < 1)) return undefined;
            if (field.type === 'secret-map' && (!value || Array.isArray(value) || typeof value !== 'object'
                || Object.values(value).some(item => typeof item !== 'string'))) return undefined;
            return { kind: 'set', value };
          } catch { return undefined; } } })));
        return { fields, model, actions: model.actions(), store: model.bind(() => ({ shell: model.shell(),
          fields: Object.fromEntries(fields.map(field => [field.field, model.field(field.field)])) })) };
      });
      const state = React.useSyncExternalStore(editor.store.subscribe, editor.store.getSnapshot);
      const routeValue = (lane, key) => state.fields[JSON.stringify(['routes', lane, key])].text;
      const choices = field => {
        if (field.path[0] === 'qqAdmission') return [['automatic', '自动接入私聊、群及新成员'], ['explicit', '仅接入已配置身份']];
        if (field.path[0] === 'persona') return (status?.personas ?? []).map(persona => [persona.id, persona.name || persona.id]);
        const [, lane, key] = field.path, providers = status?.providers ?? [];
        if (key === 'provider') return providers.map(provider => [provider.id, provider.name || provider.id]);
        const provider = providers.find(provider => provider.id === routeValue(lane, 'provider'));
        if (key === 'model') return (provider?.models ?? []).map(model => [model.id, model.name || model.id]);
        const model = provider?.models.find(model => model.id === routeValue(lane, 'model'));
        return model ? [['', '使用模型服务默认值'], ...(model.reasoning?.efforts ?? []).map(effort => [effort.id, effort.name])] : [];
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
      React.useEffect(() => { const controller = new AbortController();
        rpc('status', {}, controller.signal).then(setStatus).catch(error => { if (!controller.signal.aborted) setNotice(error.message); });
        return () => controller.abort(); }, []);
      const activate = async () => { setBusy(true); setNotice('');
        try { setStatus(await rpc('applySettings')); setNotice('已应用到业务 worker 与后续模型请求。'); }
        catch (error) { setNotice(error.message); } finally { setBusy(false); } };
      return h('section', { style: stack, 'aria-label': 'Asuna 设置' },
        h('h3', null, 'Asuna'),
        h('p', null, status ? '业务 worker：' + status.lifecycle.state + ' · Mongo：' + (status.worker?.database || '未连接') : '读取状态…'),
        status?.lifecycle.error && h('p', { role: 'alert' }, status.lifecycle.error),
        h('p', { style: small }, '配置由 DSH 保存；凭据只写不回显。模型与 API key 在 DSH 原生 provider 设置管理。会话中的模型选择优先于下方默认路由。'),
        h(SettingsForm, { state: state.shell, onSave: editor.actions.save, onDiscard: editor.actions.discard,
          labels: { unavailable: '配置暂不可用', readOnly: '当前配置只读', saveFailed: '保存失败，草稿已保留。', save: '保存设置', saving: '保存中…' } },
          ...editor.fields.map(field => {
            const props = { key: field.field, id: 'asuna-setting-' + field.field, label: field.label,
              ...state.fields[field.field], disabled: busy || state.shell.saving || !state.shell.writable,
              overriddenLabel: '已覆盖', resetLabel: '恢复默认',
              invalidLabel: field.type === 'number' ? '请输入正整数' : '请输入有效的 JSON 值',
              onEdit: text => editor.actions.edit(field.field, text), onReset: () => editor.actions.resetField(field.field) };
            if (field.type === 'choice') return h(Select, { ...props, value: props.text, options: choices(field),
              onChange: value => choose(field, value),
              hint: field.path[0] === 'routes' ? '选项来自 DSH 已配置的模型服务及其能力。' : undefined });
            return field.type.startsWith('secret') ? h(SettingsSecretField, { ...props, configured: status?.credentials?.includes(field.path[1]) ?? false,
              hint: field.type === 'secret-map' ? '例如 {"新通道/token":"值"}。只更新列出的名称；留空不修改。' : '留空保留现有凭据。',
              stateLabel: field.type === 'secret-map' ? '可添加凭据引用' : status?.credentials?.includes(field.path[1]) ? '已配置' : '未配置' })
              : h(SettingsValueField, { ...props, numeric: field.type === 'number',
                hint: field.type === 'json' ? 'JSON 配置；凭据使用 {"$secret":"名称"} 引用。' : undefined });
          })),
        status && h('p', { style: small }, '自我来源：' + (status.worker?.self_source || '等待连接')
          + ' · QQ：' + (status.worker?.channels_active ? '本机入口已启动；适配器 ' + status.worker.integration_state
            + '；平台连接未验证' : '未启用')
          + (status.worker?.integration_error ? ' · ' + status.worker.integration_error : '')
          + ' · 定时：' + (status.worker?.schedules_active ? '原生调度' : '未启用')),
        status && h('p', { role: 'status' }, status.pending ? '已保存的配置尚未应用。' : '保存配置与当前应用配置一致。'),
        h('div', { style: { display: 'flex', gap: 8, flexWrap: 'wrap' } },
          h(Button, { disabled: busy || state.shell.dirty || state.shell.saving, onClick: activate, variant: 'outline' }, '应用已保存设置'),
          h(Button, { disabled: busy, onClick: () => rpc('status').then(setStatus).catch(error => setNotice(error.message)) }, '刷新状态')),
        persona && h('section', { style: stack, 'aria-label': '人格数据' },
          h('h4', null, '人格数据 · ' + persona.persona),
          persona.render && h('p', { role: persona.render.over_budget ? 'alert' : 'status',
            style: persona.render.over_budget ? { color: 'var(--dsw-alias-status-danger, #c00)' } : small },
            '人格渲染估算 ' + persona.render.estimate_tokens + ' / 上限 ' + (persona.render.limit_tokens ?? '未设') + (persona.render.over_budget ? ' · 超出预算' : '')),
          h('p', { style: small }, persona.sources.length ? '源根：' + persona.sources.map(s => s.id + '（' + s.state + '，' + s.path + '）').join('；') : '未配置源根（本机配置 persona_sources）。'),
          ...persona.jobs.map(job => h('div', { key: job.id, style: { display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' } },
            h('span', null, '作业 ' + job.id + ' · 源根 ' + job.sources.join('、')),
            h(Button, { size: 'sm', disabled: busy, onClick: () => runJob(job.id, true) }, '试运行'),
            h(Button, { size: 'sm', disabled: busy, variant: 'outline', onClick: () => runJob(job.id, false) }, '运行'))),
          persona.runs.length > 0 && h('p', { style: small }, '最近运行：' + persona.runs.map(r => r.job + ' ' + r.status + (r.dry_run ? '（试）' : '')).join('；')),
          h(Button, { size: 'sm', disabled: busy || !persona.export_configured, onClick: exportDocs },
            persona.export_configured ? '导出文档' : '导出（未配置 export_dir）')),
        notice && h('p', { role: 'status' }, notice));
    }

    ctx.effect(() => ctx.sidebarRightTabs.register({ id: '@asuna/memory', kind: 'asuna-memory', title: () => '记忆',
      guide: [{ id: 'asuna-memory', order: 50, title: () => '记忆', description: () => '当前角色、场景与授权来源' }] }));
    ctx.slots.inject('sidebar.right.pane.tab', () => ctx.slots.register({ name: 'sidebar.right.pane.tab', key: '@asuna/memory' }, Memory));
    ctx.slots.inject('plugins.bundle.config', () => ctx.slots.register({ name: 'plugins.bundle.config', key: '@asuna/cognition-core' }, Settings));

    // Two context wheels in a character conversation (owner-approved, 2026-10-04): DSH's own meter,
    // tinted purple, is the character brain; one matching blue ring beside it is the latest action
    // session. Nothing is shown in other sessions.
    const formatK = value => value >= 1000 ? Math.round(value / 100) / 10 + 'K' : String(value);
    function BrainMeters({ sessionId }) {
      const [state, setState] = React.useState(null);
      React.useEffect(() => {
        if (!sessionId) return undefined;
        let alive = true;
        const load = () => rpc('brainContext', { sessionId }).then(value => alive && setState(value)).catch(() => {});
        load();
        const timer = setInterval(load, 5000);
        return () => { alive = false; clearInterval(timer); setState(null); };
      }, [sessionId]);
      if (!state) return null;
      const action = state.action;
      const length = 2 * Math.PI * 5.5;
      return h(React.Fragment, null,
        h('style', null, characterMeterTint),
        action && h(Tooltip, { label: '行动脑上下文已用 ' + action.percent + '%（' + formatK(action.used) + ' / ' + formatK(action.window) + '）',
          side: 'top', delayMs: 200 },
          h('span', { className: 'asuna-action-meter', 'aria-label': '行动脑上下文已用 ' + action.percent + '%' },
            h('svg', { viewBox: '0 0 14 14', width: 14, height: 14, 'aria-hidden': true },
              h('circle', { cx: 7, cy: 7, r: 5.5, className: 'asuna-meter-track' }),
              h('circle', { cx: 7, cy: 7, r: 5.5, className: 'asuna-meter-fill', transform: 'rotate(-90 7 7)',
                strokeDasharray: length * action.percent / 100 + ' ' + length })),
            h('span', null, action.percent + '%'))));
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
    for (const definition of stageDefinitions()) ctx.effect(() => ctx.uiConversation.events.register(definition));
    for (const definition of actionDefinitions()) ctx.effect(() => ctx.uiConversation.events.register(definition));
    function InlineAction(props) {
      const [reference, setReference] = React.useState(null), [error, setError] = React.useState('');
      React.useEffect(() => {
        const controller = new AbortController();
        setReference(null); setError('');
        const data = props.node.data;
        const target = data.parent_session_id ? { parentSessionId: data.parent_session_id,
          childSessionId: data.session_id, mode: 'unknown' }
          : ctx.sessions.subagentAddress(data.session_id) ?? data.session_id;
        const ref = ctx.sessions.retain(target, { source: 'asunaInline', signal: controller.signal });
        ref.ready.then(() => { if (!controller.signal.aborted) setReference(ref); })
          .catch(error => { if (!controller.signal.aborted) setError(error.message); });
        return () => { controller.abort(); ref.release(); };
      }, [props.node.data.session_id, props.node.data.parent_session_id]);
      return h(React.Fragment, null, h(Pill, { className: brainClass('executor') }, '行动脑'),
        reference ? h(props.SessionProvider, { session: reference },
          props.renderSlot('asuna.inline.fragment', { owner: props }))
          : h('p', { role: error ? 'alert' : 'status' }, error || '读取行动脑记录…'));
    }
    const actionKinds = ['assistant-step', 'tool-call', 'turn-error', 'turn-max-tokens',
      'model-retry', 'compaction', 'manual-compaction', 'command'];
    function NativeFragment(props) {
      const range = props.owner.node.data;
      return props.renderFactorySlot('conversation.chat.content', { variant: 'fragment', kinds: actionKinds,
        after: range.after_seq, through: range.through_seq });
    }
    ctx.slots.inject('conversation.chat.node', () => ctx.slots.register({
      name: 'conversation.chat.node', key: 'asuna-action-records', children: {
        'asuna.inline.fragment': { kind: 'single', scope: 'session' },
      },
    }, InlineAction));
    ctx.slots.inject('asuna.inline.fragment', () => ctx.slots.register({ name: 'asuna.inline.fragment' }, NativeFragment));
    ctx.slots.inject('conversation.chat.node', () => ctx.slots.register({
      name: 'conversation.chat.node', key: 'asuna-stage',
    }, props => stageLabel(props.node.data)
      ? h(Pill, { className: brainClass(props.node.data.lane) }, stageLabel(props.node.data)) : null));
    const injectChat = sessionId => ({ hooks: { chat: ctx.uiConversation.binding(ctx.sessions.binding(sessionId)).target('chat') } });
    function ActiveStage(props) {
      const stage = props.useChat(snapshot => {
        const timeline = snapshot?.timeline;
        const turn = timeline?.turns.get(timeline.turnOrder.at(-1));
        return turn?.status === 'open' ? turn.steps.at(-1)?.data.get('asuna-stage') : undefined;
      });
      return stageLabel(stage) ? h(Pill, { className: brainClass(stage.lane) }, stageLabel(stage)) : null;
    }
    ctx.slots.inject('conversation.session.header.actions', () => ctx.slots.register({
      name: 'conversation.session.header.actions', id: 'asuna-active-stage', order: 50, inject: injectChat,
    }, ActiveStage));

  }
  return { apply, stageDefinitions, actionDefinitions, stageIdentity, stageLabel, subscribeInputPolicies,
    inject: ['slots', 'sidebarRightTabs', 'connection', 'remote', 'remote.settings', 'configForms', 'sessions', 'conversation', 'uiConversation', 'uiWorkspace'] };
} });
