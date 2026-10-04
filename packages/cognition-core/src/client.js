/* Native DSH Client contribution. React and controls come from the Host bundle. */
window.__ModuleLoader__.load({ id: '@asuna/cognition-core', factory: require => {
  const React = require('react');
  const { Button, Input, DisclosureRow, MarkdownText, CodeBlock } = require('@deepseek-ai/dsh-client-ui-primitives');
  const h = React.createElement;
  const labels = { code: { copyLabel: '复制', copiedLabel: '已复制' }, footnotes: '来源' };
  const stack = { display: 'flex', flexDirection: 'column', gap: 12, padding: 16, minWidth: 0,
    overflowWrap: 'anywhere', fontSize: 14, lineHeight: 1.6 };
  const selectStyle = { font: 'inherit', color: 'inherit', background: 'var(--dsw-alias-bg-base)',
    border: '1px solid var(--dsw-alias-border-l4)', borderRadius: 8, padding: 6, maxWidth: '100%' };
  const small = { fontSize: 12, color: 'var(--dsw-alias-label-tertiary)' };
  function Select({ label, value, options, onChange }) {
    return h('label', { style: { display: 'flex', flexDirection: 'column', gap: 4 } }, label,
      h('select', { 'aria-label': label, style: selectStyle, value, onChange: e => onChange(e.target.value) },
        options.map(([id, text]) => h('option', { key: id, value: id }, text))));
  }

  function apply(ctx) {
    const rpc = async (method, payload = {}, signal) => {
      const result = await ctx.connection.rpc.call('/api', 'asunaApi/' + method, { args: payload }, signal);
      if (!result.ok) throw new Error(result.error.message);
      return result.value;
    };
    const form = ctx.configForms.get('asuna-cognition-core');
    const subscribe = fn => form.subscribe(fn), snapshot = () => form.getSnapshot();

    function Memory(props) {
      const visible = props.useTabInfo().tab.visible;
      const [category, setCategory] = React.useState('all'), [offset, setOffset] = React.useState(0);
      const [page, setPage] = React.useState(null), [error, setError] = React.useState('');
      const [selected, setSelected] = React.useState(null), [detail, setDetail] = React.useState(null);
      const [refresh, setRefresh] = React.useState(0);
      React.useEffect(() => {
        if (!visible) return;
        const controller = new AbortController(); setPage(null); setError(''); setSelected(null); setDetail(null);
        rpc('memory', { request: { session_id: props.sessionId, category, offset } }, controller.signal)
          .then(setPage).catch(error => { if (!controller.signal.aborted) setError(error.message); });
        return () => controller.abort();
      }, [visible, props.sessionId, category, offset, refresh]);
      React.useEffect(() => {
        setDetail(null);
        if (!visible || !selected) return;
        const controller = new AbortController();
        rpc('memory', { request: { session_id: props.sessionId, id: selected } }, controller.signal)
          .then(setDetail).catch(error => { if (!controller.signal.aborted) setError(error.message); });
        return () => controller.abort();
      }, [visible, props.sessionId, selected]);
      return h('section', { style: { ...stack, height: '100%', overflowY: 'auto' }, 'aria-label': 'Asuna 记忆' },
        h(Select, { label: '记忆类型', value: category, options: [['all', '全部'], ['documents', '文档'], ['self', '自我'],
          ['relation', '关系与偏好'], ['summary', '交流摘要'], ['source', '原始来源']],
          onChange: value => { setCategory(value); setOffset(0); } }),
        h(Button, { size: 'sm', onClick: () => setRefresh(x => x + 1) }, '刷新记忆'),
        page && h('p', { style: small }, page.persona + ' · ' + page.scene_id,
          page.linked_scenes.length ? ' · 联动来源：' + page.linked_scenes.join('、') : ''),
        error && h('p', { role: 'alert' }, error.includes('NOT_BOUND') ? '当前会话尚无 Asuna 场景绑定。完成角色交互后可查看。' : error),
        !page && !error && h('p', null, '读取当前场景…'),
        page?.rows.map(row => h('article', { key: row.id },
          h(DisclosureRow, { icon: null, title: row.title, open: selected === row.id, expandable: true,
            expandOnRowClick: true, onToggle: () => setSelected(selected === row.id ? null : row.id) },
            selected === row.id && (detail ? h('div', { style: { padding: '8px 0', color: 'var(--dsw-alias-label-primary)' } },
              h('p', { style: small }, detail.interpretation ? '理解 / 当前自我' : '原话'),
              h(MarkdownText, { text: detail.body, labels, variant: 'compact' }),
              h('p', { style: small }, [detail.revision, detail.speaker || detail.author, detail.generated_at || detail.occurred_at].filter(Boolean).join(' · ')),
              detail.levels && Object.keys(detail.levels).length > 0 && h(CodeBlock, {
                code: JSON.stringify(detail.levels, null, 2), lang: 'json', copyLabel: '复制', copiedLabel: '已复制' }),
              ...detail.sources.map(source => h('blockquote', { key: source._id },
                h('p', { style: small }, '原始来源 · ' + source.author + ' · ' + source.scene_id),
                h(MarkdownText, { text: source.text, labels, variant: 'compact' })))) : h('p', null, '读取详情…'))),
          selected !== row.id && h('p', { style: { margin: '4px 0', whiteSpace: 'pre-wrap' } }, row.excerpt),
          h('p', { style: small }, [row.kind, row.scene_id || row.scope_key, row.updated_at].filter(Boolean).join(' · ')))),
        page && !page.rows.length && h('p', null, '当前范围暂无记录。'),
        page && h('div', { style: { display: 'flex', gap: 8 } },
          h(Button, { disabled: offset === 0, onClick: () => setOffset(Math.max(0, offset - 24)) }, '上一页'),
          h(Button, { disabled: page.next_offset === null, onClick: () => setOffset(page.next_offset) }, '下一页')));
    }

    function Settings() {
      const saved = React.useSyncExternalStore(subscribe, snapshot);
      const [draft, setDraft] = React.useState(null), [status, setStatus] = React.useState(null);
      const [notice, setNotice] = React.useState(''), [busy, setBusy] = React.useState(false);
      React.useEffect(() => { if (!draft && saved.value) setDraft(structuredClone(saved.value)); }, [saved.value, draft]);
      React.useEffect(() => { const controller = new AbortController();
        rpc('status', {}, controller.signal).then(setStatus).catch(error => { if (!controller.signal.aborted) setNotice(error.message); });
        return () => controller.abort(); }, []);
      const changeRoute = (lane, key, value) => setDraft(old => ({ ...old, routes: { ...old.routes,
        [lane]: { ...old.routes[lane], [key]: value } } }));
      const save = async () => {
        setBusy(true); setNotice('');
        try {
          // The native form's boolean writer discards refusal details. Use its
          // same public Settings Remote and fold the returned native view.
          const result = await ctx.remote.settings.mutate('asuna-cognition-core',
            ['persona', 'routes'].map(key => ({ op: 'set', path: [key], value: draft[key] })), saved.revision);
          if (!result.ok) throw new Error(result.error.message);
          ctx.configForms.describe().acceptView(result.value);
          setStatus(await rpc('status')); setNotice('已保存。点击“应用已保存设置”后启动业务 worker；当前会话配置暂未改变。');
        } catch (error) { setNotice(error.message); } finally { setBusy(false); }
      };
      const activate = async () => { setBusy(true); setNotice('');
        try { setStatus(await rpc('applySettings')); setNotice('已应用到业务 worker 与后续模型请求。'); }
        catch (error) { setNotice(error.message); } finally { setBusy(false); } };
      return h('section', { style: stack, 'aria-label': 'Asuna 设置' },
        h('h3', null, 'Asuna'),
        h('p', null, status ? '业务 worker：' + status.lifecycle.state + ' · Mongo：' + (status.worker?.database || '未连接') : '读取状态…'),
        status?.lifecycle.error && h('p', { role: 'alert' }, status.lifecycle.error),
        h('p', { style: small }, '连接凭据保存在本机配置。模型引用来自 DSH 的原生 provider 设置。'),
        draft && h('p', { style: small }, '配置引用：' + draft.configPath + ' · 工作目录：' + draft.workspace),
        draft && h(Select, { label: '当前角色', value: draft.persona,
          options: (status?.personas || []).map(p => [p.id, p.name + ' · ' + p.version]),
          onChange: value => setDraft(old => ({ ...old, persona: value })) }),
        draft && ['character', 'action'].map(lane => h('fieldset', { key: lane, style: { border: 'none', padding: 0, display: 'grid', gap: 8 } },
          h('legend', null, lane === 'character' ? '角色脑' : '行动脑'),
          h(Select, { label: (lane === 'character' ? '角色' : '行动') + ' provider', value: draft.routes?.[lane]?.provider,
            options: (status?.providers || []).map(p => [p.id, p.id]), onChange: value => changeRoute(lane, 'provider', value) }),
          h(Select, { label: (lane === 'character' ? '角色' : '行动') + ' model', value: draft.routes?.[lane]?.model,
            options: (status?.providers.find(p => p.id === draft.routes[lane].provider)?.models || []).map(m => [m.id, m.id]),
            onChange: value => changeRoute(lane, 'model', value) }),
          h('label', null, 'Reasoning effort', h(Input, { 'aria-label': lane + ' reasoning',
            value: draft.routes?.[lane]?.reasoningEffort || '', onChange: e => changeRoute(lane, 'reasoningEffort', e.target.value) })),
          h('label', null, '输出上限', h(Input, { type: 'number', min: 1, 'aria-label': lane + ' max tokens',
            value: draft.routes?.[lane]?.maxTokens || '', onChange: e => changeRoute(lane, 'maxTokens', Number(e.target.value)) })))),
        status && h('p', { style: small }, '自我来源：' + (status.worker?.self_source || '等待连接')
          + ' · QQ：' + (status.worker?.channels_active ? '已连接现有入口' : '未启用')
          + ' · 定时：' + (status.worker?.schedules_active ? '原生调度' : '未启用')),
        status && h('p', { role: 'status' }, status.pending ? '已保存的配置尚未应用。' : '保存配置与当前应用配置一致。'),
        h('div', { style: { display: 'flex', gap: 8, flexWrap: 'wrap' } },
          h(Button, { disabled: busy || !draft || !saved.writable, onClick: save, variant: 'primary' }, '保存设置'),
          h(Button, { disabled: busy, onClick: activate, variant: 'outline' }, '应用已保存设置'),
          h(Button, { disabled: busy, onClick: () => rpc('status').then(setStatus).catch(error => setNotice(error.message)) }, '刷新状态')),
        notice && h('p', { role: 'status' }, notice));
    }

    ctx.effect(() => ctx.sidebarRightTabs.register({ id: '@asuna/memory', kind: 'asuna-memory', title: () => '记忆',
      guide: [{ id: 'asuna-memory', order: 50, title: () => '记忆', description: () => '当前角色、场景与授权来源' }] }));
    ctx.slots.inject('sidebar.right.pane.tab', () => ctx.slots.register({ name: 'sidebar.right.pane.tab', key: '@asuna/memory' }, Memory));
    ctx.slots.inject('plugins.bundle.config', () => ctx.slots.register({ name: 'plugins.bundle.config', key: '@asuna/cognition-core' }, Settings));

    // A small association over actual native events, using DSH's location data.
    // It neither streams nor copies role/action conversation contents.
    ctx.effect(() => ctx.uiConversation.events.register({ kind: 'asuna-actions',
      match: event => event.type === 'turn/start' ? { id: String(event.data.turn), role: 'start' }
        : event.type === 'asuna/action-linked' ? { id: String(event.data.turn), role: 'update' } : null,
      start: (_context, match) => ({ turn: match.event.data.turn, links: [] }),
      update: (context, match) => ({ ...context.state, links: [...context.state.links, match.event.data] }),
      buildLocationData: (context, scope, previous) => {
        if (scope !== 'turn' || !context.state) return null;
        if (previous?.value.links === context.state.links) return previous;
        return { kind: 'turn', turn: context.state.turn, key: 'asuna-actions', value: { links: context.state.links } };
      } }));
    function ActionLinks(props) {
      const data = props.useChat(snapshot => snapshot.timeline.turns.get(props.turn.turn)?.data.get('asuna-actions'));
      const links = data?.links || [];
      return links.map(link => h(Button, { key: link.session_id, size: 'sm', variant: 'outline',
        onClick: () => ctx.uiWorkspace.openSession(link.session_id) }, '打开行动会话 · ' + link.task_id));
    }
    ctx.slots.inject('conversation.chat.turnTail', () => ctx.slots.register({
      name: 'conversation.chat.turnTail', id: 'asuna-actions', order: 50,
      inject: sessionId => {
        const binding = ctx.sessions.binding(sessionId);
        const chat = ctx.uiConversation.binding(binding).target('chat');
        return { hooks: { chat } };
      },
    }, ActionLinks));
  }
  return { apply, inject: ['slots', 'sidebarRightTabs', 'connection', 'remote', 'remote.settings', 'configForms', 'sessions', 'uiConversation', 'uiWorkspace'] };
} });
