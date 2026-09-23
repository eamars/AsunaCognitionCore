const $ = (id) => document.getElementById(id);
const text = (value) => typeof value === 'string' ? value : JSON.stringify(value, null, 2);
function el(tag, value, cls) { const node = document.createElement(tag); if (value != null) node.textContent = text(value); if (cls) node.className = cls; return node; }
// Only code spans/fences are formatted; model content never becomes HTML.
function codeText(tag, value, cls) {
  const node = el(tag, null, cls), source = text(value) ?? '';
  const parts = /(?<line>^|\n)[ \t]{0,3}(?<fence>`{3,}|~{3,})[^\n]*\n(?<block>[\s\S]*?)\n[ \t]{0,3}\k<fence>[ \t]*(?=\n|$)|(?<ticks>`+)(?<inline>[^`\n]+?)\k<ticks>/g;
  let end = 0;
  for (const match of source.matchAll(parts)) {
    node.append(document.createTextNode(source.slice(end, match.index)));
    if (match.groups.block !== undefined) {
      node.append(document.createTextNode(match.groups.line));
      const block = el(tag === 'span' ? 'code' : 'pre', null, 'code-block');
      if (tag === 'span') block.textContent = match.groups.block;
      else block.append(el('code', match.groups.block));
      node.append(block);
    } else node.append(el('code', match.groups.inline));
    end = match.index + match[0].length;
  }
  node.append(document.createTextNode(source.slice(end)));
  return node;
}
let state, conversation = '', tab = 'memory', selected, busy = false, revision = '', stopped = false, requestNumber = 0, actionError = '';
let liveCalls = [], stream, streamConnected = false;
const time = value => { const date = new Date(value); return value && !Number.isNaN(date.valueOf()) ? date.toLocaleString('zh-CN', {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false}) : (value || ''); };
const expanded = new Set();
const names = {memory: '记忆', preference: '偏好', group_preference: '群偏好', relationship: '关系'};
async function api(path, body) {
  const response = await fetch(`/asuna/api/${path}`, {method: body === undefined ? 'GET' : 'POST', headers: {'Content-Type': 'application/json', 'X-Asuna-UI': '1'}, body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(28000)});
  const data = await response.json(); if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`); return data;
}
function error(message) { $('error').textContent = message; $('error').hidden = !message; }
function disclosure(key, label) { const node = el('details'); node.open = expanded.has(key); node.append(el('summary', label)); node.addEventListener('toggle', () => node.open ? expanded.add(key) : expanded.delete(key)); return node; }
function errorSummary(step) {
  const full = text(step.summary || '执行错误');
  const lines = full.split('\n').map(line => line.trim()).filter(Boolean);
  const brief = full.includes('Traceback (most recent call last)') ? [...lines].reverse().find(line => !line.startsWith('For more information')) : full;
  return `${step.label || step.type}：${brief.slice(0, 240)}${brief.length > 240 ? '…' : ''}（展开执行步骤查看完整错误）`;
}
function renderTrace(message) {
  const settled = message.internalSteps || [];
  const finalRefs = new Set(settled.flatMap(step => ['phase.output', 'execution.output'].includes(step.type)
    ? (step.payload?.request_refs || []).map(ref => ref.artifact_path?.split('/').at(-1)) : []));
  const taskRows = state.messages.filter(row => row.role !== 'user' && row.taskId === message.taskId);
  const taskHost = taskRows.find(row => row.episodeId === row.taskOwnerEpisodeId) || taskRows.at(-1);
  const live = (message.role === 'user' ? [] : liveCalls).filter(call =>
    call.operation?.startsWith(`${message.episodeId}:`) ||
    (message.taskId && taskHost?.id === message.id && call.operation?.startsWith(`${message.taskId}:`)))
    .filter(call => !finalRefs.has(call.request_ref))
    .map(call => ({id: `live:${call.id}`, type: 'provider.live', actorRole: call.lane === 'character' ? 'role' : 'action',
      label: `${call.lane === 'character' ? '角色脑' : '行动脑'} · ${call.phase}`, status: call.status,
      createdAt: call.createdAt, summary: call.status === 'running' ? '原始回包传输中' : '等待记录结算',
      requestRef: call.request_ref, body_utf8: call.body_utf8}));
  const steps = [...settled, ...live].sort((left, right) =>
    new Date(left.createdAt || 0) - new Date(right.createdAt || 0));
  if (!steps.length) return [];
  const failed = steps.filter(step => step.status === 'error');
  const panelKey = `trace:${message.id}`;
  if (live.length) expanded.add(panelKey);
  const panel = disclosure(panelKey, `内部执行过程 · ${steps.length} 个步骤${failed.length ? ` · ${failed.length} 项错误` : ''}`); panel.className = 'trace';
  const rows = el('ol', null, 'steps');
  steps.forEach((step, index) => {
    const row = el('li', null, `step ${step.status === 'error' ? 'error' : ''}`);
    const providerOutput = ['phase.output', 'execution.output'].includes(step.type);
    const ref = step.requestRef || (providerOutput ? step.payload?.request_refs?.at(-1)?.artifact_path?.split('/').at(-1) : null);
    const detailKey = `step:${message.id}:${ref || step.id}`;
    if (step.type === 'provider.live') expanded.add(detailKey);
    const detail = disclosure(detailKey); const summary = detail.firstChild;
    const actor = step.actor || step.type;
    const color = ['role','action','tool'].includes(step.actorRole) ? step.actorRole : '';
    summary.append(el('span', index + 1, 'number'), el('span', step.label || actor, `actor ${color}`), el('small', `${step.type} · ${step.status || ''} · ${time(step.createdAt)}`), codeText('span', providerOutput ? '原始 provider response' : (step.summary || step.type), 'summary'));
    const payload = el('pre', step.type === 'provider.live' ? step.body_utf8 : providerOutput ? '正在读取原始 provider response…' : (step.payload ?? step));
    if (step.type === 'provider.live') detail.dataset.liveCall = step.id.slice(5);
    detail.append(payload);
    if (providerOutput) {
      let requested = false;
      const loadRawResponse = async () => {
        if (!detail.open || requested) return;
        requested = true;
        try {
          const response = await api(`provider-response?event=${encodeURIComponent(step.id)}&conversation=${encodeURIComponent(conversation)}`);
          payload.textContent = response.body_utf8;
        } catch (cause) {
          payload.textContent = `原始 provider response 读取失败：${cause.message}`;
        }
      };
      detail.addEventListener('toggle', loadRawResponse);
      if (detail.open) void loadRawResponse();
    }
    row.append(detail); rows.append(row);
  });
  panel.append(rows);
  // Error summary is outside the disclosure and remains visible when collapsed.
  return [...failed.map(step => el('div', errorSummary(step), 'trace-error')), panel];
}
function renderMessages() {
  const box = $('messages'), nearBottom = box.scrollHeight - box.scrollTop - box.clientHeight < 100;
  const oldScroll = box.scrollTop;
  box.replaceChildren();
  for (const message of state.messages) {
    const row = el('article', null, `message ${message.role}`);
    row.append(el('p', `${message.authorLabel || (message.role === 'user' ? '你' : 'Asuna')}  ${time(message.createdAt)}`, 'meta'), codeText('div', message.text, 'bubble'), ...renderTrace(message));
    box.append(row);
  }
  if (!state.messages.length) box.append(el('p', '当前上下文暂无消息。可以从下方开始聊天。', 'empty'));
  box.scrollTop = nearBottom ? box.scrollHeight : oldScroll;
}
function connectStream() {
  stream?.close();
  liveCalls = []; streamConnected = false;
  if (stopped) return;
  stream = new EventSource(`/asuna/api/stream?conversation=${encodeURIComponent(conversation)}`);
  const openedStream = stream;
  stream.addEventListener('snapshot', event => {
    if (stream !== openedStream) return;
    try {
      const next = JSON.parse(event.data).calls || [];
      const structureChanged = next.length !== liveCalls.length || next.some((call, index) =>
        call.id !== liveCalls[index]?.id || call.status !== liveCalls[index]?.status);
      liveCalls = next;
      streamConnected = true;
      if (state && structureChanged) renderMessages();
      else for (const detail of document.querySelectorAll('[data-live-call]')) {
        const call = liveCalls.find(item => item.id === detail.dataset.liveCall);
        if (call) detail.querySelector('pre').textContent = call.body_utf8;
      }
      $('connection').textContent = state?.readOnly ? '● 已连接 · 只读检查 · 实时流' : '● 已连接 · 本机交互 · 实时流';
    } catch { /* A display frame cannot stop the agent. */ }
  });
  stream.onerror = () => { if (stream !== openedStream) return; streamConnected = false; $('connection').textContent = '观察连接中断 · 正在重连'; };
}
function renderInspector() {
  const kinds = [...new Set([...Object.keys(names), ...state.records.map(record => record.kind)])];
  $('tabs').replaceChildren();
  kinds.forEach(kind => { const button = el('button', names[kind] || (kind === 'integration' ? '集成' : kind)); button.role = 'tab'; button.id = `tab-${kind}`; button.setAttribute('aria-controls', 'records'); button.setAttribute('aria-selected', String(kind === tab)); button.onclick = () => { tab = kind; selected = undefined; renderInspector(); }; $('tabs').append(button); });
  $('records').setAttribute('aria-labelledby', `tab-${tab}`);
  const search = $('search').value.toLocaleLowerCase();
  const records = state.records.filter(record => record.kind === tab && text(record).toLocaleLowerCase().includes(search));
  if (!records.some(record => record.id === selected)) selected = undefined;
  $('records').replaceChildren();
  records.forEach(record => {
    const button = el('button', null, `record ${selected === record.id ? 'selected' : ''}`);
    button.append(el('strong', record.title), el('small', [record.description || record.kind, time(record.createdAt), record.badge].filter(Boolean).join(' · ')));
    button.onclick = () => { selected = record.id; renderInspector(); }; $('records').append(button);
  });
  if (!records.length) $('records').append(el('p', search ? '没有匹配的记录' : (state.emptyReasons?.[tab] || '暂无此类记录'), 'empty'));
  $('detail').replaceChildren();
  const record = records.find(record => record.id === selected);
  if (!record) { $('detail').append(el('p', '选择一条记录查看详情', 'empty')); return; }
  $('detail').append(el('h2', record.title));
  const fields = el('dl');
  const fieldValue = value => value !== null && typeof value === 'object' ? el('dd', value, 'json-value') : codeText('dd', value);
  for (const [key, value] of Object.entries(record)) {
    if (key === 'title') continue;
    if (key === 'fields' && Array.isArray(value)) {
      for (const field of value) fields.append(el('dt', field.label || field.key), fieldValue(field.value));
    } else if (key === 'fields' && value && typeof value === 'object') {
      for (const [field, content] of Object.entries(value)) fields.append(el('dt', field), fieldValue(content));
    } else fields.append(el('dt', key), fieldValue(value));
  }
  $('detail').append(fields);
}
function render() {
  integrationLabel.hidden = !state.integrationAvailable;
  integrationStop.hidden = !state.integrationAvailable;
  integrationChoice.disabled = state.readOnly || !state.canSend || state.channelPrompt;
  if (state.channelPrompt) integrationChoice.checked = false;
  integrationStop.disabled = state.readOnly;
  $('title').textContent = state.title; $('subtitle').textContent = state.subtitle;
  $('connection').textContent = `${state.readOnly ? '● 已连接 · 只读检查' : '● 已连接 · 本机交互'}${streamConnected ? ' · 实时流' : ''}`;
  $('send').disabled = busy || state.readOnly || !state.canSend;
  $('input').disabled = state.readOnly || !state.canSend;
  $('new-session').disabled = busy || state.readOnly || state.channelPrompt;
  $('send').textContent = state.channelPrompt ? '请小满在群里发言' : '发送';
  $('input').placeholder = state.channelPrompt ? '给小满的本机指令；她将在当前群发言' : '输入消息…（Enter 发送，Shift + Enter 换行）';
  $('conversations').replaceChildren();
  for (const item of state.conversations) {
    const button = el('button', null, `session ${state.conversationId === item.id ? 'selected' : ''}`);
    button.append(el('span', item.title), el('small', `${item.channelType} · ${time(item.updatedAt)}`));
    button.onclick = async () => { conversation = item.id; selected = undefined; revision = ''; connectStream(); await refresh(); }; $('conversations').append(button);
  }
  renderMessages(); renderInspector();
  const config = state.modelSettings;
  if (config) {
    $('model-summary').textContent = `角色脑：${config.models.character.model} · 行动脑：${config.models.executor.model}`;
    $('model-summary').title = $('model-summary').textContent;
    $('model-save').disabled = state.readOnly || config.applying;
    $('new-session').disabled = busy || state.readOnly || state.channelPrompt || config.applying || !config.ready;
    if (config.applying) $('model-status').textContent = '正在应用模型配置，暂时停止接收新消息…';
    else if (modelWasApplying) { $('model-status').textContent = config.error ? `未应用：${config.error}` : '已保存并应用；后续消息使用当前两条模型路由。'; modelRevision = config.revision; }
    modelWasApplying = config.applying;
  }
}
async function refresh() {
  const request = ++requestNumber;
  try {
    const next = await api(`state?conversation=${encodeURIComponent(conversation)}`);
    if (request !== requestNumber) return;
    const signature = JSON.stringify(next);
    state = next;
    if (signature !== revision) { revision = signature; render(); }
    $('connection').textContent = `${state.readOnly ? '● 已连接 · 只读检查' : '● 已连接 · 本机交互'}${streamConnected ? ' · 实时流' : ''}`;
    error(actionError || state.modelSettings?.error || '');
  } catch (err) {
    if (request !== requestNumber) return;
    error(err.message); $('connection').textContent = '连接不可用'; $('send').disabled = true; $('new-session').disabled = true;
    revision = ''; // Re-enable controls even if reconnect returns the same snapshot.
  }
}
$('composer').onsubmit = async (event) => {
  event.preventDefault(); const value = $('input').value.trim(); if (!value || busy || !state?.canSend || state.readOnly) return;
  busy = true; $('send').disabled = true;
  try { await api('send', {text: value, integration: integrationChoice.checked, conversation}); integrationChoice.checked = false; actionError = ''; $('input').value = ''; $('send-status').textContent = '已入队，可继续输入；回复完成后自动显示。'; await refresh(); }
  catch (err) { actionError = err.message; error(actionError); $('send-status').textContent = '未确认送达；保留输入，请先刷新检查，避免重复发送。'; }
  finally { busy = false; $('send').disabled = state?.readOnly || !state?.canSend; }
};
$('input').onkeydown = event => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('composer').requestSubmit(); } };
$('new-session').onclick = async () => { busy = true; $('new-session').disabled = true; try { await api('new', {}); actionError = ''; conversation = ''; connectStream(); $('send-status').textContent = '已请求新上下文；有未结束的行动时不会切换，请查看系统消息。'; await refresh(); } catch (err) { actionError = err.message; error(actionError); } finally { busy = false; if (state) render(); } };
$('refresh').onclick = refresh;
const integrationLabel = el('label'); integrationLabel.hidden = true;
const integrationChoice = el('input'); integrationChoice.type = 'checkbox'; integrationChoice.id = 'integration-choice';
integrationLabel.append(integrationChoice, document.createTextNode('本条授权集成开发'));
$('composer').append(integrationLabel);
const integrationStop = el('button', '停止集成'); integrationStop.type = 'button'; integrationStop.hidden = true;
integrationStop.onclick = async () => { try { await api('integration/stop', {}); actionError = ''; await refresh(); } catch (err) { actionError = err.message; error(actionError); } };
$('composer').append(integrationStop);
const stopHost = el('button', '停止服务');
stopHost.title = '停止宿主与行动；关闭页面则保持宿主运行';
$('refresh').after(stopHost);
stopHost.onclick = async () => {
  stopHost.disabled = true;
  try {
    await api('stop', {});
    stopped = true; busy = true; requestNumber++;
    stream?.close();
    $('send').disabled = true; $('input').disabled = true; $('new-session').disabled = true;
    $('connection').textContent = '服务正在停止';
    $('send-status').textContent = '已请求停止整个宿主；再次运行 start-asuna.cmd 可恢复未开始的输入。';
  } catch (err) { error(err.message); stopHost.disabled = false; }
};
$('search').oninput = () => { if (state) renderInspector(); };
addEventListener('pagehide', () => { stopped = true; stream?.close(); });
async function poll() { await refresh(); if (!stopped) setTimeout(poll, 2000); }
connectStream();
poll();

const modelButton = el('button', '模型设置'); modelButton.id = 'model-settings';
const modelSummary = el('p', '', 'model-summary'); modelSummary.id = 'model-summary';
document.querySelector('.sidebar header').append(modelButton, modelSummary);
let modelRevision = '', modelWasApplying = false;
const modelControls = {};
function modelField(parent, lane, key, label, value, type = 'text', options) {
  const row = el('label', label), id = `model-${lane}-${key}`; row.htmlFor = id;
  const input = el(options ? 'select' : type === 'json' ? 'textarea' : 'input'); input.id = id;
  if (options) options.forEach(([v, title]) => { const option = el('option', title); option.value = v; input.append(option); });
  else if (type !== 'json') input.type = type;
  input.value = type === 'json' ? JSON.stringify(value, null, 2) : value;
  if (type === 'number') { input.min = '1'; input.required = true; }
  if (type === 'password') { input.autocomplete = 'new-password'; input.placeholder = '留空保留；更换地址时不会沿用旧密钥'; }
  row.append(input); parent.append(row); modelControls[lane][key] = input; return input;
}
function draftModel(lane) {
  const fields = modelControls[lane], model = {};
  for (const key of ['base_url','model','api_key','token_counter','reasoning_effort']) model[key] = fields[key].value.trim();
  for (const key of ['max_tokens','context_window']) model[key] = Number(fields[key].value);
  for (const key of ['sampling','compat','reasoning_efforts']) model[key] = JSON.parse(fields[key].value);
  model.api = 'openai-completions'; model.clear_api_key = fields.clear_api_key.checked;
  return model;
}
function populateModels(models) {
  $('model-fields').replaceChildren();
  for (const [lane, label] of [['character','角色脑'],['executor','行动脑']]) {
    const model = models[lane], box = el('fieldset'); box.append(el('legend', label)); modelControls[lane] = {};
    modelField(box, lane, 'base_url', '连接地址（Base URL）', model.base_url).required = true;
    const id = modelField(box, lane, 'model', '模型 ID', model.model); id.required = true; id.setAttribute('list', `${lane}-models`);
    const choices = el('datalist'); choices.id = `${lane}-models`; box.append(choices);
    const discover = el('button','读取服务模型列表'); discover.type = 'button';
    discover.onclick = async () => {
      discover.disabled = true;
      try { const draft = draftModel(lane); const result = await api('models/discover',{lane,base_url:draft.base_url,api_key:draft.api_key,clear_api_key:draft.clear_api_key}); choices.replaceChildren(); result.models.forEach(model => { const option=el('option'); option.value=model.id; choices.append(option); }); $('model-status').textContent = `${label}可选模型：${result.models.map(model=>model.id).join('、') || '服务未返回模型'}。可在模型 ID 中选择或手动填写。`; }
      catch(err) { $('model-status').textContent = err.message; } finally { discover.disabled = false; }
    }; box.append(discover);
    modelField(box, lane, 'api_key', model.api_key_set ? 'API key（已设置）' : 'API key（可选）', '', 'password');
    const clearLabel = el('label','清除已保存的 API key'), clear = el('input'); clear.type='checkbox'; clearLabel.append(clear); box.append(clearLabel); modelControls[lane].clear_api_key=clear;
    const sizes = el('div',null,'model-sizes');
    modelField(sizes,lane,'context_window','上下文窗口',model.context_window,'number'); modelField(sizes,lane,'max_tokens','输出上限',model.max_tokens,'number'); box.append(sizes);
    const advanced = el('details'); advanced.append(el('summary','高级兼容设置'));
    modelField(advanced,lane,'token_counter','Token 计数',model.token_counter,'text',[['conservative_bytes','通用保守估算'],['llama_cpp','llama.cpp 原生计数'],['anthropic_count','服务 count_tokens 接口']]);
    modelField(advanced,lane,'reasoning_effort','推理强度',model.reasoning_effort,'text',['off','minimal','low','medium','high','xhigh'].map(v=>[v,v]));
    modelField(advanced,lane,'sampling','采样参数（JSON）',model.sampling,'json');
    modelField(advanced,lane,'compat','DSH compat（JSON）',model.compat,'json');
    modelField(advanced,lane,'reasoning_efforts','DSH reasoningEfforts（JSON）',model.reasoning_efforts,'json');
    box.append(advanced); $('model-fields').append(box);
  }
}
modelButton.onclick = () => {
  if (!state?.modelSettings) return;
  modelRevision=state.modelSettings.revision; populateModels(state.modelSettings.models);
  $('model-status').textContent=state.modelSettings.applying ? '正在应用模型配置…' : state.modelSettings.error || '配置将持久保存。模型 ID 和可用能力以实际服务为准。';
  $('model-dialog').showModal();
};
$('model-close').onclick=()=>$('model-dialog').close();
$('model-form').onsubmit=async event=>{
  event.preventDefault(); $('model-save').disabled=true;
  try { await api('models',{revision:modelRevision,models:{character:draftModel('character'),executor:draftModel('executor')}}); modelWasApplying=true; $('model-status').textContent='正在应用…'; await refresh(); }
  catch(err) { $('model-status').textContent=err.message; $('model-save').disabled=state?.readOnly || state?.modelSettings?.applying; }
};
