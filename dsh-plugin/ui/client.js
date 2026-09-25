// DSH 0.1.5-rc.2 primitives share the host React and theme. Asuna owns only
// scene projection, stable message identity, and trusted command callbacks.
window.__ModuleLoader__.load({id: 'asuna-ui-elements-v1', factory: (require) => {
  const React = require('react');
  const {createElement: h, memo, useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore} = React;
  const {Button, Input, DisclosureRow, MarkdownText, CodeBlock, StateDot, ConnectionIndicator,
    IconCodeOutline16, IconThinkOutline14, IconSearchOutline16, IconRefreshOutline16} = require('@deepseek-ai/dsh-client-ui-primitives');
  const labels = Object.freeze({code: Object.freeze({copyLabel: '复制', copiedLabel: '已复制'}), footnotes: '脚注'});
  let localeRuntime, translate;
  const localeSubscribe = listener => localeRuntime.subscribe(listener);
  const localeSnapshot = () => localeRuntime.getSnapshot();
  const text = value => typeof value === 'string' ? value : JSON.stringify(value, null, 2);
  const clock = value => { const date = new Date(value); return value && !Number.isNaN(date.valueOf()) ? date.toLocaleString('zh-CN', {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false}) : (value || ''); };
  const code = value => h(CodeBlock, {code: text(value) ?? '', copyLabel: '复制显示内容', copiedLabel: '已复制'});
  async function api(path, body) {
    const response = await fetch(`/asuna/api/${path}`, {method: body === undefined ? 'GET' : 'POST',
      headers: {'Content-Type': 'application/json', 'X-Asuna-UI': '1'},
      body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(28000)});
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }
  function viewStore() {
    let value = {state: null, inspector: null, calls: [], connected: false, error: '', busy: false, stopped: false,
      loadingOlder: false, olderRevision: 0};
    let selected = '', revision = '', stream, timer, active = false, request = 0;
    let history = new Map(), beforeSeq = null, hasMore = false;
    let inspectorRequest = 0, inspectorAt = 0;
    const settlementTimers = new Set();
    const clearSettlementTimers = () => { for (const pending of settlementTimers) clearTimeout(pending); settlementTimers.clear(); };
    const listeners = new Set();
    const set = patch => { value = {...value, ...patch}; listeners.forEach(listener => listener()); };
    const subscribe = listener => { listeners.add(listener); return () => listeners.delete(listener); };
    const getSnapshot = () => value;
    function mergePage(page, older = false) {
      if (beforeSeq === null || (page.beforeSeq !== null && page.beforeSeq <= beforeSeq)) {
        beforeSeq = page.beforeSeq; hasMore = page.hasMore;
      }
      for (const message of page.messages || []) if (Number.isSafeInteger(message.sceneSeq)) {
        const existing = history.get(message.id);
        history.set(message.id, existing && message.revision && existing.revision === message.revision ? existing : message);
      }
      const messages = [...history.values()].sort((a, b) => a.sceneSeq - b.sceneSeq);
      messages.push(...(older ? value.state?.messages || [] : page.messages || []).filter(message => !Number.isSafeInteger(message.sceneSeq)));
      return {...(older ? value.state : page), messages, beforeSeq, hasMore};
    }
    async function refreshInspector(force = false) {
      const scene = selected;
      if (!active || (!force && value.inspector?.sceneId === value.state?.sceneId &&
          Date.now() - inspectorAt < 30000)) return;
      const number = ++inspectorRequest;
      try {
        const next = await api(`inspector-list?scene=${encodeURIComponent(scene)}`);
        if (!active || scene !== selected || number !== inspectorRequest) return;
        inspectorAt = Date.now();
        if (next.inspectorRevision !== value.inspector?.inspectorRevision ||
            next.sceneId !== value.inspector?.sceneId) set({inspector: next});
      } catch (cause) { if (active && scene === selected && number === inspectorRequest)
        set({error: cause.message}); }
    }
    async function refresh(forceInspector = false) {
      const number = ++request;
      try {
        const next = await api(`state?scene=${encodeURIComponent(selected)}`);
        if (!active || number !== request) return;
        if (next.revision !== revision || value.error) {
          revision = next.revision;
          const state = mergePage(next);
          const durable = new Set(state.messages.flatMap(message => (message.internalSteps || [])
            .filter(isOutput).map(step => step.displayKey)));
          set({state, calls: value.calls.filter(call => !(call.status !== 'running' && durable.has(call.operation))), error: ''});
        }
        void refreshInspector(forceInspector);
      } catch (cause) { if (active && number === request) { revision = ''; set({error: cause.message, connected: false}); } }
    }
    function connect() {
      stream?.close(); clearSettlementTimers(); set({calls: [], connected: false});
      if (!active || value.stopped) return;
      const opened = new EventSource(`/asuna/api/stream?scene=${encodeURIComponent(selected)}`);
      stream = opened;
      opened.addEventListener('snapshot', event => {
        if (stream !== opened) return;
        try { const prior = new Map(value.calls.map(call => [call.id, call]));
          set({calls: (JSON.parse(event.data).calls || []).map(call =>
            ({...call, parts: prior.get(call.id)?.parts || []})), connected: true}); }
        catch { /* Observation is never an agent control path. */ }
      });
      opened.addEventListener('start', event => {
        if (stream !== opened) return;
        try { const next = JSON.parse(event.data);
          set({calls: [...value.calls.filter(call => call.id !== next.id), {...next, parts: []}]});
        } catch { /* Observation is never an agent control path. */ }
      });
      opened.addEventListener('delta', event => {
        if (stream !== opened) return;
        try { const next = JSON.parse(event.data);
          set({calls: value.calls.map(call => {
            if (call.id !== next.id) return call;
            const parts = [...(call.parts || [])];
            if (parts.at(-1)?.field === next.field) parts[parts.length - 1] =
              {...parts.at(-1), text: parts.at(-1).text + next.text};
            else parts.push({field: next.field, text: next.text});
            return {...call, parts, sequence: next.sequence};
          })});
        } catch { /* Observation is never an agent control path. */ }
      });
      opened.addEventListener('end', event => {
        if (stream !== opened) return;
        try { const next = JSON.parse(event.data);
          set({calls: value.calls.map(call => call.id === next.id ? {...call, status: next.status} : call)});
          void refresh();
          const pending = setTimeout(() => {
            settlementTimers.delete(pending);
            if (stream !== opened) return;
            const calls = value.calls.filter(call => call.id !== next.id || call.status === 'running');
            if (calls.length !== value.calls.length) set({calls});
          }, 30000);
          settlementTimers.add(pending);
        } catch { /* Observation is never an agent control path. */ }
      });
      opened.addEventListener('reset', () => {
        if (stream !== opened) return;
        set({calls: []}); void refresh(true);
      });
      opened.onerror = () => { if (stream === opened) set({connected: false}); };
    }
    async function poll() { await refresh(); if (active && !value.stopped)
      timer = setTimeout(poll, value.state?.hasPendingWork ? 2000 : 30000); }
    function start() { if (active) return; active = true; connect(); void poll(); }
    function stop() { active = false; ++request; ++inspectorRequest; clearTimeout(timer); clearSettlementTimers(); stream?.close(); stream = undefined; }
    function select(id) { if (id === selected) return; selected = id; ++request; ++inspectorRequest; revision = '';
      history = new Map(); beforeSeq = null; hasMore = false; inspectorAt = 0;
      set({state: null, inspector: null, calls: [], error: '', loadingOlder: false, olderRevision: 0}); connect(); void refresh(true); }
    async function loadOlder() {
      if (!active || value.loadingOlder || !value.state?.hasMore || !value.state.beforeSeq) return;
      const scene = selected, cursor = value.state.beforeSeq;
      set({loadingOlder: true});
      try {
        const page = await api(`state?scene=${encodeURIComponent(scene)}&before=${cursor}`);
        if (!active || scene !== selected) return;
        if (page.beforeSeq !== null && page.beforeSeq >= cursor) throw new Error('历史页没有向前推进');
        set({state: mergePage(page, true), olderRevision: value.olderRevision + 1, error: ''});
      } catch (cause) { if (active && scene === selected) set({error: cause.message}); }
      finally { if (active && scene === selected) set({loadingOlder: false}); }
    }
    async function command(path, body) { set({busy: true});
      try { const result = await api(path, body); await refresh(true); set({error: ''}); return result; }
      catch (cause) { set({error: cause.message}); throw cause; }
      finally { set({busy: false}); } }
    async function stopHost() { await api('stop', {}); clearTimeout(timer); clearSettlementTimers(); stream?.close(); set({stopped: true, connected: false}); }
    return {subscribe, getSnapshot, start, stop, refresh, loadOlder, select, command, stopHost, connect};
  }
  const isOutput = step => ['phase.output', 'execution.output'].includes(step.type);
  const isExecutionCall = call => call?.phase === 'execution' || call?.phase === 'execution-repair';
  const callKey = call => `${call.operation}:${call.request_ref || call.id}`;
  function publicOperation(message) {
    const speak = (message.internalSteps || []).filter(step => step.type === 'phase.output' &&
      step.sourceStreamId === message.episodeId && step.payload?.phase === 'SPEAK' && step.status !== 'error').at(-1);
    return speak?.displayKey || message.displayKey;
  }
  function hostFor(messages, call) {
    if (typeof call.operation !== 'string') return null;
    const episodes = messages.filter(row => row.internalSteps && call.operation.startsWith(`${row.episodeId}:`));
    if (episodes.length) return (episodes.find(row => row.role === 'assistant') || episodes.at(-1)).id;
    const tasks = messages.filter(row => row.internalSteps &&
      [row.taskId, ...(row.taskIds || [])].some(taskId => taskId && call.operation.startsWith(`${taskId}:`)));
    return tasks.length ? (tasks.find(row => row.episodeId === row.taskOwnerEpisodeId) || tasks.at(-1)).id : null;
  }
  function nodesFor(state, calls) {
    const messages = state?.messages || [], live = new Map(), nodes = [];
    const publicKeys = new Set(messages.filter(row => row.role === 'assistant').map(publicOperation));
    const durableKeys = new Set(messages.flatMap(row => (row.internalSteps || []).filter(isOutput).map(step => step.displayKey)));
    for (const call of calls) {
      // DSH context compaction can run inside an Asuna phase operation. Its
      // summary is not the phase's Assistant text and must never occupy that key.
      if (call.phase === 'compaction' || !call.operation || !(call.parts || []).some(part => part.text)) continue;
      const host = hostFor(messages, call); if (!host) continue;
      const list = live.get(host) || []; list.push(call); live.set(host, list);
    }
    for (const message of messages) {
      const steps = message.internalSteps || [];
      if (message.role !== 'assistant') nodes.push({key: `message:${message.id}`, kind: 'message', message,
        createdAt: message.createdAt});
      const outputKeys = new Set(steps.filter(isOutput).map(step => step.displayKey).filter(Boolean));
      const latestOutput = new Map(steps.filter(isOutput).map(step => [step.displayKey || `event:${step.id}`, step]));
      const process = [];
      for (const step of steps) {
        if (isOutput(step)) {
          const operation = step.displayKey || `event:${step.id}`;
          // A later task revision can reuse an attempt number. Keep its older
          // durable output at its event identity instead of losing the text.
          const key = latestOutput.get(operation) === step ? operation : `event:${step.id}`;
          if (step.payload?.phase === 'SPEAK' && publicKeys.has(operation) && key === operation) continue;
          const started = steps.find(row => row.type === 'phase.started' && row.payload?.operation === operation);
          if (step.summary || step.status === 'error') {
            const nativeCalls = step.type === 'execution.output' ? step.providerCalls || [] : [];
            if (nativeCalls.length) {
              nativeCalls.forEach((call, index) => {
                if (!(call.parts || []).some(part => part.text) && index !== nativeCalls.length - 1) return;
                process.push({key: `generation:${call.id}`, kind: 'generation',
                  step: index === nativeCalls.length - 1 ? step : undefined,
                  calls: [call], createdAt: call.createdAt});
              });
            } else process.push({key: `generation:${key}`, kind: 'generation', step,
              calls: key === operation ? (live.get(message.id) || []).filter(call => call.operation === operation) : [],
              createdAt: started?.createdAt || step.createdAt});
          }
        } else if (['tool_call', 'tool_result', 'tool.failed'].includes(step.type))
          process.push({key: `tool:${step.id}`, kind: 'tool', step, createdAt: step.createdAt});
      }
      const groups = new Map();
      for (const call of live.get(message.id) || []) {
        if (outputKeys.has(call.operation) || durableKeys.has(call.operation) || publicKeys.has(call.operation)) continue;
        const list = groups.get(call.operation) || []; list.push(call); groups.set(call.operation, list);
      }
      for (const [operation, group] of groups) {
        if (group.some(isExecutionCall)) {
          for (const call of group) process.push({key: `generation:${callKey(call)}`, kind: 'generation',
            calls: [call], createdAt: call.createdAt});
        } else process.push({key: `generation:${operation}`, kind: 'generation', calls: group,
          createdAt: group[0].createdAt});
      }
      process.sort((a, b) => new Date(a.createdAt || 0) - new Date(b.createdAt || 0));
      nodes.push(...process);
      const rest = steps.filter(step => !isOutput(step) && !['tool_call','tool_result','tool.failed'].includes(step.type)
        && !(step.type.endsWith('.started') && step.status === 'running'));
      if (rest.length) nodes.push({key: `trace:${message.episodeId || message.id}`, kind: 'trace', steps: rest,
        createdAt: rest.find(step => step.createdAt)?.createdAt || message.createdAt});
      if (message.role === 'assistant') {
        const operation = publicOperation(message);
        const settled = steps.filter(step => step.type === 'phase.output' && step.displayKey === operation).at(-1);
        nodes.push({key: `generation:${operation || message.id}`, kind: 'generation', message, step: settled,
          calls: (live.get(message.id) || []).filter(call => call.operation === operation),
          createdAt: steps.find(step => step.type === 'phase.started' && step.payload?.operation === operation)?.createdAt
            || settled?.createdAt || message.createdAt});
      }
    }
    const seen = new Set();
    return nodes.filter(node => { if (seen.has(node.key)) return false; seen.add(node.key); return true; })
      .map((node, index) => ({node, index, time: Date.parse(node.createdAt)}))
      .sort((a, b) => (Number.isFinite(a.time) ? a.time : Number.MAX_SAFE_INTEGER) -
        (Number.isFinite(b.time) ? b.time : Number.MAX_SAFE_INTEGER) || a.index - b.index)
      .map(row => row.node);
  }
  function Diagnostic({step, calls, scene}) {
    const [open, setOpen] = useState(false), [loaded, setLoaded] = useState(null);
    useEffect(() => {
      if (!open || !step?.hasProviderDiagnostic) return;
      let mounted = true;
      setLoaded(null);
      api(`provider-diagnostic?event=${encodeURIComponent(step.id)}&scene=${encodeURIComponent(scene)}`)
        .then(result => { if (mounted) setLoaded({event: step.id, diagnostic: result.diagnostic}); })
        .catch(cause => { if (mounted) setLoaded({event: step.id, error: cause.message}); });
      return () => { mounted = false; };
    }, [open, step?.id, scene]);
    const current = loaded?.event === step?.id ? loaded : null;
    const diagnostic = step ? current?.diagnostic : calls?.length ? {provider_calls: calls.map(call => ({
      id: call.id, lane: call.lane, phase: call.phase, operation: call.operation, status: call.status}))} : null;
    const fallback = current?.error || (step?.hasProviderDiagnostic ? '正在读取 provider 元数据…' : '没有关联的 provider 请求');
    return h(DisclosureRow, {icon: h(IconCodeOutline16, {size: 14}), title: '诊断 · provider 元数据',
      open, expandable: true, expandOnRowClick: true, onToggle: () => setOpen(!open), className: 'asuna-diagnostic'},
      diagnostic ? code(diagnostic) : h('p', {className: 'asuna-muted'}, fallback));
  }
  function Thinking({body, live}) {
    const [open, setOpen] = useState(false);
    useSyncExternalStore(localeSubscribe, localeSnapshot, localeSnapshot);
    const visible = live ? body.trimEnd() : body;
    const line = live ? visible.slice(visible.lastIndexOf('\n') + 1) : visible.split('\n', 1)[0];
    const preview = line.replaceAll('**', '');
    return h('div', {className: 'asuna-thinking', 'data-variant': 'think', 'data-state': live ? 'running' : 'ok',
      'data-expanded': open || undefined},
      live && h('span', {className: 'asuna-sr-only'}, translate('running')),
      h(DisclosureRow, {icon: h(IconThinkOutline14, {size: 14}),
      title: translate('thinking'), open, expandable: true, expandOnRowClick: true,
      onToggle: () => setOpen(value => !value), rowClassName: 'asuna-thinking-row',
      leadingClassName: 'asuna-thinking-leading',
      titleClassName: 'asuna-thinking-title', chevronClassName: 'asuna-thinking-chevron',
      collapsedContent: h(React.Fragment, null,
        h('span', {className: 'asuna-thinking-separator', 'aria-hidden': true}),
        h('span', {className: 'asuna-thinking-summary', 'data-follow-end': live || undefined},
          h('span', {className: 'asuna-thinking-summary-text'}, preview)))},
      h('div', {className: 'asuna-thinking-text'}, body)));
  }
  function decisionGoal(value) {
    if (typeof value !== 'string') return '';
    const source = value.trimStart();
    if (!source.startsWith('{')) return '';
    try {
      const parsed = JSON.parse(source);
      return typeof parsed?.goal === 'string' ? parsed.goal : '';
    } catch { /* A live DECIDE content block may be an unfinished JSON object. */ }
    const key = /(?:^|[,{])\s*"goal"\s*:\s*"/.exec(source);
    if (!key) return '';
    let raw = '', escaped = false;
    for (let i = key.index + key[0].length; i < source.length; i++) {
      const char = source[i];
      if (char === '"' && !escaped) break;
      raw += char;
      if (escaped) escaped = false;
      else if (char === '\\') escaped = true;
    }
    if (escaped) raw = raw.slice(0, -1);
    raw = raw.replace(/\\u[0-9a-fA-F]{0,3}$/, '');
    try { return JSON.parse(`"${raw}"`); } catch { return ''; }
  }
  function HistoricalDetail({step, scene, field, renderContent}) {
    const [open, setOpen] = useState(false), [detail, setDetail] = useState(null), [error, setError] = useState('');
    useEffect(() => {
      if (!open) return;
      let mounted = true;
      api(`trace-detail?event=${encodeURIComponent(step.id)}&scene=${encodeURIComponent(scene)}`)
        .then(value => { if (mounted) { setDetail(value); setError(''); } })
        .catch(cause => { if (mounted) setError(cause.message); });
      return () => { mounted = false; };
    }, [open, step.id, scene]);
    const thinking = field === 'reasoning';
    const body = detail?.payload?.[field];
    const expanded = detail && !thinking && h(React.Fragment, null,
      renderContent(body || step.summary),
      ...(detail.providerCalls || []).map((call, index) => h('div', {key: call.id, className: 'asuna-native-call'},
        h('p', {className: 'asuna-muted'}, `行动步骤 ${index + 1} · ${clock(call.createdAt)}`),
        ...(call.parts || []).map((part, partIndex) => h('section',
          {className: 'asuna-part', key: `${call.id}:${partIndex}`},
          part.field === 'reasoning_content' ? h(Thinking, {body: part.text}) : renderContent(part.text))))));
    return h('section', {className: thinking ? 'asuna-part asuna-thinking' : 'asuna-part',
      'data-expanded': thinking && open || undefined},
      h(DisclosureRow, {icon: thinking ? h(IconThinkOutline14, {size: 14}) : h(IconCodeOutline16, {size: 14}),
        title: thinking ? translate('thinking') : step.type === 'execution.output' ? '完整输出与行动步骤' : '完整输出',
        open, expandable: true,
        expandOnRowClick: true, onToggle: () => setOpen(value => !value),
        rowClassName: thinking ? 'asuna-thinking-row' : undefined,
        leadingClassName: thinking ? 'asuna-thinking-leading' : undefined,
        titleClassName: thinking ? 'asuna-thinking-title' : undefined,
        chevronClassName: thinking ? 'asuna-thinking-chevron' : undefined,
        collapsedContent: thinking ? h(React.Fragment, null,
          h('span', {className: 'asuna-thinking-separator', 'aria-hidden': true}),
          h('span', {className: 'asuna-thinking-summary'},
            h('span', {className: 'asuna-thinking-summary-text'}, step.reasoningPreview || '已保存的思考'))) : undefined},
        error ? h('p', {className: 'asuna-error-text'}, error) :
          detail ? (thinking ? h('div', {className: 'asuna-thinking-text'}, body || '') : expanded) :
            h('p', {className: 'asuna-muted'},
              thinking ? '正在读取思考…' : '正在读取完整输出…')));
  }
  function Contents({step, calls, message, scene}) {
    const parts = (calls || []).flatMap(call => (call.parts || []).map((part, index) => ({...part,
      key: `${call.operation}:${call.request_ref || call.id}:${index}`, streaming: call.status === 'running'})));
    const decision = step?.payload?.phase === 'DECIDE' || calls?.some(call => call.phase === 'DECIDE');
    const structured = !decision && step?.type === 'execution.output' && step.structuredContent;
    const contentParts = parts.filter(part => part.field === 'content');
    const liveContent = contentParts.map(part => part.text).join('');
    const renderContent = (content, streaming) => {
      const shown = decision ? decisionGoal(content) || (step ? content : '') : content;
      return shown && (structured ? code(shown) : h(MarkdownText, {text: shown, streaming, labels}));
    };
    const liveParts = () => h(React.Fragment, null, ...parts.map(part => {
      const child = part.field === 'reasoning_content' ?
        h(Thinking, {body: part.text, live: part.streaming}) :
        decision && part.key !== contentParts[0]?.key ? null :
        renderContent(decision ? liveContent : part.text, part.streaming);
      return child ? h('section', {className: 'asuna-part', key: part.key}, child) : null;
    }));
    if (step || message) {
      const content = message?.text ?? step?.summary ?? '';
      if (!step?.hasReasoning && !step?.hasFullContent && parts.length &&
          parts.filter(part => part.field === 'content').map(part => part.text).join('') === content &&
          !parts.some(part => part.field === 'reasoning_content' && part.text))
        return liveParts();
      return h(React.Fragment, null,
        step?.hasReasoning && h(HistoricalDetail, {step, scene, field: 'reasoning', renderContent}),
        content && renderContent(content),
        !message && (step?.hasFullContent || (step?.type === 'execution.output' && step.hasProviderDiagnostic)) &&
          h(HistoricalDetail, {step, scene, field: 'content', renderContent}));
    }
    return liveParts();
  }
  function Generation({node, scene}) {
    const {step, calls, message} = node, call = calls?.at(-1);
    const error = step?.status === 'error' || call?.status === 'error' || message?.deliveryState === 'FAILED';
    const ongoing = !step && !message && !error && (!call || call.status === 'running');
    const pendingDelivery = ['READY','SENDING','QUEUED_EXTERNAL'].includes(message?.deliveryState);
    const uncertainDelivery = message?.deliveryState === 'UNKNOWN';
    const delivery = ({DELIVERED:'已送达',QUEUED_EXTERNAL:'待平台接收',SENDING:'发送中',READY:'待发送',FAILED:'发送失败',UNKNOWN:'送达未知'})[message?.deliveryState];
    const lane = message ? undefined : step?.actorRole === 'role' ? 'character' :
      step?.actorRole === 'action' ? 'executor' : call?.lane;
    const decision = !message && (step?.payload?.phase === 'DECIDE' || call?.phase === 'DECIDE');
    if (decision && !error) {
      const content = step?.summary || (calls || []).flatMap(row => row.parts || [])
        .filter(part => part.field === 'content').map(part => part.text).join('');
      const reasoning = (calls || []).some(row =>
        (row.parts || []).some(part => part.field === 'reasoning_content' && part.text?.trim()));
      if (!decisionGoal(content) && !reasoning && !step) return null;
    }
    const phase = step?.type === 'execution.output' ? 'EXECUTION' : step?.payload?.phase || call?.phase || '';
    const actor = message ? `${message.authorLabel || 'Asuna'} · SPEAK` :
      `${lane === 'character' ? '角色脑' : '行动脑'}${phase ? ` · ${String(phase).toUpperCase()}` : ''}`;
    return h('article', {className: `asuna-message ${message ? 'asuna-assistant' : 'asuna-process'}`,
      'data-message-key': node.key, 'data-lane': lane},
      h('div', {className: 'asuna-meta'}, h(StateDot, {state: error ? 'error' : ongoing || pendingDelivery ? 'ongoing' : uncertainDelivery ? 'warning' : 'done'}),
        h('strong', null, actor), h('time', null, clock(node.createdAt || step?.createdAt || call?.createdAt || message?.createdAt)),
        delivery && h('small', null, delivery)),
      h('div', {className: 'asuna-body'}, h(Contents, {step, calls, message, scene})),
      error && h('p', {className: 'asuna-error-text'}, step?.payload?.finish_reason ||
        (decision ? '决策生成失败，部分内容已保留' : '生成或发送失败，部分正文已保留')),
      h(Diagnostic, {step, calls, scene}));
  }
  function Message({message, nodeKey}) {
    return h('article', {className: `asuna-message asuna-${message.role}`, 'data-message-key': nodeKey},
      h('div', {className: 'asuna-meta'}, h('strong', null, message.authorLabel || (message.role === 'user' ? '你' : '系统')),
        h('time', null, clock(message.createdAt))),
      h('div', {className: 'asuna-body'}, h(MarkdownText, {text: message.text || '', labels})),
      message.turnStatus && h('p', {className: 'asuna-turn-status'}, `${message.turnStatus.label} · ${message.turnStatus.detail}`));
  }
  function TraceStep({step, scene}) {
    const [open, setOpen] = useState(false), [detail, setDetail] = useState(null);
    useEffect(() => { if (!open) return; let mounted = true;
      api(`trace-detail?event=${encodeURIComponent(step.id)}&scene=${encodeURIComponent(scene)}`)
        .then(result => { if (mounted) setDetail(result); }).catch(error => { if (mounted) setDetail({error:error.message}); });
      return () => { mounted = false; };
    }, [open, step.id, scene]);
    return h('div', {className: 'asuna-tool', 'data-message-key': `tool:${step.id}`},
      h(DisclosureRow, {icon: h(StateDot, {state: step.status === 'error' ? 'error' : 'done'}),
        title: `${step.actor || '系统'} · ${step.payload?.tool || step.type}`, open, expandable: true, expandOnRowClick: true,
        onToggle: () => setOpen(!open), collapsedContent: h(React.Fragment, null,
          h('span', {className: 'asuna-tool-separator', 'aria-hidden': true}),
          h('time', {className: 'asuna-tool-time'}, clock(step.createdAt)))},
        detail ? code(detail.payload || detail) : h('p', {className: 'asuna-muted'}, '正在读取详情…')));
  }
  function Tool({step, scene}) { return h(TraceStep, {step, scene}); }
  function Trace({steps, nodeKey, scene}) {
    const [open, setOpen] = useState(false);
    const failed = steps.filter(step => step.status === 'error');
    return h('div', {className: 'asuna-trace', 'data-message-key': nodeKey},
      ...failed.map(step => h('p', {className: 'asuna-error-text', key: step.id}, `${step.label || step.type}：${step.summary || step.type}`)),
      h(DisclosureRow, {icon: h(IconCodeOutline16, {size: 14}), title: `内部执行记录 · ${steps.length} 项`,
        open, expandable: true, expandOnRowClick: true, onToggle: () => setOpen(!open)},
        h('ol', null, ...steps.map(step => h('li', {key: step.id},
          h(TraceStep, {step, scene}))))));
  }
  function Inspector({state}) {
    const root = useRef(null), controller = useRef(null), latest = useRef(state), rendered = useRef(null);
    latest.current = state;
    useEffect(() => { let mounted = true;
      import('/asuna/workbench.js').then(module => { if (mounted && root.current) {
        controller.current = module.mountInspector(root.current, api); controller.current.render(latest.current);
        rendered.current = latest.current ? `${latest.current.sceneId}:${latest.current.inspectorRevision}` : '';
      }}).catch(() => { if (root.current) root.current.textContent = '检查器加载失败，请刷新页面。'; });
      return () => { mounted = false; controller.current?.dispose(); };
    }, []);
    useEffect(() => { const marker = state ? `${state.sceneId}:${state.inspectorRevision}` : '';
      if (controller.current && marker !== rendered.current) {
        controller.current.render(state); rendered.current = marker;
      }
    }, [state]);
    return h('aside', {ref: root, className: 'asuna-inspector', 'aria-label': '会话检查器'});
  }
  const StableGeneration = memo(Generation, (previous, next) => previous.scene === next.scene &&
    previous.node.key === next.node.key && previous.node.message === next.node.message &&
    previous.node.step === next.node.step && previous.node.calls?.length === next.node.calls?.length &&
    (previous.node.calls || []).every((call, index) => call === next.node.calls[index]));
  const StableMessage = memo(Message, (previous, next) => previous.message === next.message &&
    previous.nodeKey === next.nodeKey);
  const StableTool = memo(Tool, (previous, next) => previous.step === next.step && previous.scene === next.scene);
  const StableTrace = memo(Trace, (previous, next) => previous.scene === next.scene &&
    previous.steps.length === next.steps.length && previous.steps.every((step, index) => step === next.steps[index]));
  function Workbench() {
    const storeRef = useRef(null); if (!storeRef.current) storeRef.current = viewStore();
    const store = storeRef.current, view = useSyncExternalStore(store.subscribe, store.getSnapshot, store.getSnapshot);
    const state = view.state, items = nodesFor(state, view.calls);
    const [draft, setDraft] = useState(''), [search, setSearch] = useState('');
    const [notice, setNotice] = useState(''), [atBottom, setAtBottom] = useState(true), [settingsReady, setSettingsReady] = useState(false);
    const scroll = useRef(null), stick = useRef(true), lastScrollTop = useRef(0), settings = useRef(null);
    const olderAnchor = useRef(null);
    useEffect(() => { store.start(); return () => store.stop(); }, [store]);
    useEffect(() => { let mounted = true;
      import('/asuna/workbench.js').then(module => { if (mounted) {
        settings.current = module.mountModelSettings(document.body, api, store.refresh);
        settings.current.update(store.getSnapshot().state); setSettingsReady(true);
      }}).catch(() => setNotice('模型设置加载失败，请刷新页面。'));
      return () => { mounted = false; settings.current?.dispose(); };
    }, [store]);
    useEffect(() => { settings.current?.update(state); }, [state]);
    useLayoutEffect(() => { const box = scroll.current;
      if (box && olderAnchor.current) {
        if (view.olderRevision > olderAnchor.current.revision) {
          box.scrollTop = olderAnchor.current.top + box.scrollHeight - olderAnchor.current.height;
          lastScrollTop.current = box.scrollTop; olderAnchor.current = null;
        }
        return;
      }
      if (box && stick.current && (!window.getSelection() || window.getSelection().isCollapsed)) box.scrollTop = box.scrollHeight;
    }, [items]);
    const loadOlder = async () => {
      const box = scroll.current;
      if (box) { olderAnchor.current = {top: box.scrollTop, height: box.scrollHeight,
        revision: store.getSnapshot().olderRevision}; stick.current = false; }
      await store.loadOlder();
      if (store.getSnapshot().error || store.getSnapshot().olderRevision === olderAnchor.current?.revision)
        olderAnchor.current = null;
    };
    const send = async event => { event.preventDefault(); const value = draft.trim();
      if (!value || !state?.canSend || state.readOnly || view.busy) return;
      try { await store.command('send', {text: value, scene: state.sceneId});
        setDraft(''); setNotice('已入队，可继续输入。'); }
      catch { setNotice('未确认送达；输入已保留，请先刷新检查，避免重复发送。'); } };
    const choose = item => { stick.current = true; olderAnchor.current = null;
      lastScrollTop.current = 0; setAtBottom(true); setNotice(''); store.select(item.id); };
    return h('div', {className: 'asuna-workbench'},
      h('aside', {className: 'asuna-sidebar'},
        h('header', null, h('h1', null, 'Asuna'), h('p', null, '场景 / 通道')),
        h(Input, {type: 'search', icon: h(IconSearchOutline16, {size: 16}), value: search,
          onChange: event => setSearch(event.target.value), placeholder: '搜索场景…', 'aria-label': '搜索场景'}),
        h('nav', {'aria-label': '场景与通道'}, ...(state?.scenes || []).filter(item =>
          `${item.title} ${item.id}`.toLocaleLowerCase().includes(search.toLocaleLowerCase())).map(item =>
          h(Button, {key: item.id, variant: 'ghost', className: `asuna-scene ${state.sceneId === item.id ? 'selected' : ''}`,
            onClick: () => choose(item), 'aria-current': state.sceneId === item.id ? 'page' : undefined},
            h('span', null, item.title), h('small', null, `${item.channelType} · ${clock(item.updatedAt)}`)))),
        state?.modelSettings && h('div', {className: 'asuna-sidebar-footer'},
          h(Button, {variant: 'ghost', onClick: () => settings.current?.open(state), disabled: !settingsReady}, '模型设置'),
          h('small', null, `角色脑：${state.modelSettings.models.character.model} · 行动脑：${state.modelSettings.models.executor.model}`)),
        h(ConnectionIndicator, {state: view.connected || !state ? undefined : 'disconnected',
          disconnectedLabel: '观察连接中断', reconnectLabel: '重新连接', connectingLabel: '正在连接', recoveredLabel: '已恢复',
          reconnectActionLabel: '重新连接观察', restartActionLabel: '重新连接观察',
          onReconnect: () => { store.connect(); void store.refresh(); }})),
      h('main', {className: 'asuna-center'},
        h('header', {className: 'asuna-header'}, h('div', null, h('h2', null, state?.title || '本机聊天'),
          h('p', null, state?.runtimeState === 'restarting' ? 'RuntimeHost 正在重启，Web 页面保持可用' :
            state?.runtimeState === 'ready' ? `${state.subtitle} · RuntimeHost ready` :
            state?.subtitle || '连接现有 Asuna 交互进程')),
          h(Button, {variant: 'ghost', onClick: () => void store.command('self-development/offer', {}).then(() => setNotice('内部机会已入队。')).catch(cause => setNotice(cause.message)),
            disabled: !state?.canSend || state.readOnly || state.scenePrompt || view.busy || view.stopped,
            title: '向角色脑提供一次内部自我开发机会，不作为用户消息'}, '自我开发机会'),
          h(Button, {variant: 'toolbar', onClick: () => void store.refresh(true), icon: h(IconRefreshOutline16, {size: 16})}, '刷新'),
          h(Button, {variant: 'ghost', onClick: () => void store.stopHost().catch(cause => setNotice(cause.message)),
            disabled: view.stopped, title: '停止整个宿主与行动，不是停止当前生成'}, '停止整个服务')),
        view.error && h('div', {className: 'asuna-error', role: 'alert'}, view.error),
        h('section', {ref: scroll, className: 'asuna-messages', 'aria-label': '聊天记录',
          onScroll: event => { const box = event.currentTarget;
            const bottom = box.scrollHeight - box.scrollTop - box.clientHeight < 100;
            // Content can grow before the follow-up layout pass. A larger
            // bottom gap alone is not evidence that the operator scrolled up.
            if (box.scrollTop < lastScrollTop.current - 1 && !bottom) stick.current = false;
            if (bottom) stick.current = true;
            lastScrollTop.current = box.scrollTop;
            setAtBottom(bottom);
          }},
          state?.hasMore && h('div', {className: 'asuna-older'},
            h(Button, {variant: 'ghost', onClick: () => void loadOlder(), disabled: view.loadingOlder},
              view.loadingOlder ? translate('loadingOlder') : translate('loadOlder'))),
          !state ? h('p', {className: 'asuna-muted'}, '正在读取对话…') : !items.length
            ? h('p', {className: 'asuna-muted'}, '当前场景暂无消息。可以从下方开始聊天。')
            : items.map(node => node.kind === 'generation' ? h(StableGeneration, {key: node.key, node, scene: state.sceneId})
              : node.kind === 'message' ? h(StableMessage, {key: node.key, message: node.message, nodeKey: node.key})
              : node.kind === 'tool' ? h(StableTool, {key: node.key, step: node.step, scene: state.sceneId})
              : h(StableTrace, {key: node.key, steps: node.steps, nodeKey: node.key, scene: state.sceneId}))),
        !atBottom && h(Button, {variant: 'outline', className: 'asuna-bottom', onClick: () => {
          if (scroll.current) scroll.current.scrollTop = scroll.current.scrollHeight;
          stick.current = true; lastScrollTop.current = scroll.current?.scrollTop || 0; setAtBottom(true);
        }}, '回到底部'),
        h('form', {className: 'asuna-composer', onSubmit: send},
          h('label', {className: 'asuna-sr-only', htmlFor: 'asuna-input'}, '输入消息'),
          h('textarea', {id: 'asuna-input', value: draft, onChange: event => setDraft(event.target.value),
            onKeyDown: event => { if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault(); event.currentTarget.form.requestSubmit(); } },
            rows: 2, maxLength: 16000, disabled: !state?.canSend || state.readOnly || view.stopped,
            placeholder: state?.scenePrompt ? state.scenePromptPlaceholder : '输入消息…（Enter 发送，Shift + Enter 换行）'}),
          h(Button, {type: 'submit', variant: 'primary', disabled: !state?.canSend || view.busy || view.stopped},
            state?.scenePrompt ? state.scenePromptLabel : '发送'),
          h('p', {role: 'status'}, view.stopped ? '已请求停止整个宿主。' : notice))),
      h(Inspector, {state: view.inspector}));
  }
  return {inject: ['slots', 'layout', 'locale'], apply(ctx) {
    localeRuntime = ctx.locale;
    ctx.effect(() => ctx.locale.register('asuna', {
      zh: {thinking: '思考', running: '运行中', loadOlder: '加载更早', loadingOlder: '正在加载…'},
      en: {thinking: 'Think', running: 'Running', loadOlder: 'Load earlier', loadingOlder: 'Loading…'}
    }), 'Asuna message labels');
    translate = ctx.locale.bind('asuna');
    ctx.effect(() => { const link = document.createElement('link'); link.rel = 'stylesheet'; link.href = '/asuna/style.css';
      document.head.append(link); return () => link.remove(); }, 'Asuna primitive layout');
    ctx.slots.inject('main', () => {
      const dispose = ctx.slots.register({name: 'main', key: 'asuna'}, Workbench);
      if (new URLSearchParams(location.search).has('asuna')) queueMicrotask(() => ctx.layout.selectPanel('asuna'));
      return dispose;
    });
    ctx.slots.inject('sidebar.panellist', () => ctx.slots.register({name: 'sidebar.panellist', id: 'asuna', label: 'Asuna', order: 0}, () => h('span', null, 'A')));
  }};
}});
