// The old direct route now opens the DSH main-slot composition.
if (location.pathname === '/asuna/' || location.pathname === '/asuna') {
  const target = new URL('/', location.origin);
  target.search = location.search;
  target.searchParams.set('asuna', '1');
  location.replace(target);
}
// The ADR-004 inspector moved intact into the DSH main-slot composition.
const valueText = value => typeof value === 'string' ? value : JSON.stringify(value, null, 2);
const el = (tag, value, cls) => {
  const node = document.createElement(tag);
  if (value != null) node.textContent = valueText(value);
  if (cls) node.className = cls;
  return node;
};
const time = value => {
  const date = new Date(value);
  return value && !Number.isNaN(date.valueOf()) ? date.toLocaleString('zh-CN',
    {month:'2-digit', day:'2-digit', hour:'2-digit', minute:'2-digit', second:'2-digit', hour12:false}) : (value || '');
};
const names = {memory: '记忆', preference: '偏好', group_preference: '群偏好', relationship: '关系'};

export function mountInspector(root, api) {
  let tab = 'memory', selected, selectedDetail, detailError, state, lastScene, detailRequest = 0;
  const header = el('header');
  header.append(el('h2', '会话检查器'), el('p', '当前场景记录 · 只读（非历史快照）'));
  const tabs = el('div'); tabs.id = 'tabs'; tabs.role = 'tablist'; tabs.setAttribute('aria-label', '检查器类型');
  const searchLabel = el('label', '搜索记录', 'asuna-sr-only'); searchLabel.htmlFor = 'search';
  const search = el('input'); search.id = 'search'; search.type = 'search'; search.placeholder = '搜索记录…';
  const records = el('div'); records.id = 'records'; records.role = 'tabpanel'; records.setAttribute('aria-label', '检查器记录');
  const detail = el('section'); detail.id = 'detail'; detail.setAttribute('aria-label', '记录详情');
  root.append(header, tabs, searchLabel, search, records, detail);
  function render(next) {
    state = next;
    if (!state) {
      selected = undefined; selectedDetail = undefined; lastScene = undefined; detailRequest++;
      tabs.replaceChildren(); records.replaceChildren(); detail.replaceChildren();
      detail.append(el('p', '正在读取当前场景记录…', 'empty'));
      return;
    }
    if (lastScene !== state.sceneId) {
      selected = undefined; selectedDetail = undefined; lastScene = state.sceneId; detailRequest++;
    }
    const kinds = [...new Set([...Object.keys(names), ...state.records.map(record => record.kind)])];
    tabs.replaceChildren();
    kinds.forEach(kind => {
      const button = el('button', names[kind] || (kind === 'integration' ? '集成' : kind));
      button.role = 'tab'; button.id = `tab-${kind}`;
      button.setAttribute('aria-controls', 'records');
      button.setAttribute('aria-selected', String(kind === tab));
      button.onclick = () => { tab = kind; selected = undefined; selectedDetail = undefined; detailRequest++; render(state); };
      tabs.append(button);
    });
    records.setAttribute('aria-labelledby', `tab-${tab}`);
    const query = search.value.toLocaleLowerCase();
    const visible = state.records.filter(record => record.kind === tab &&
      `${record.title} ${record.description || ''} ${record.excerpt || ''} ${record.badge || ''}`.toLocaleLowerCase().includes(query));
    if (!visible.some(record => record.id === selected)) { selected = undefined; selectedDetail = undefined; detailRequest++; }
    records.replaceChildren();
    visible.forEach(record => {
      const button = el('button', null, `record ${selected === record.id ? 'selected' : ''}`);
      button.append(el('strong', record.title), el('small',
        [record.description || record.kind, time(record.createdAt), record.badge].filter(Boolean).join(' · ')));
      button.onclick = () => {
        selected = record.id; selectedDetail = undefined; detailError = undefined;
        const request = ++detailRequest, scene = state.sceneId;
        render(state);
        api(`inspector-detail?scene=${encodeURIComponent(scene)}&kind=${encodeURIComponent(record.kind)}&id=${encodeURIComponent(record.id)}`)
          .then(detail => { if (request === detailRequest) { selectedDetail = detail; render(state); } })
          .catch(error => { if (request === detailRequest) { detailError = error.message; render(state); } });
      };
      records.append(button);
    });
    if (!visible.length) records.append(el('p', query ? '没有匹配的记录' :
      (state.emptyReasons?.[tab] || '暂无此类记录'), 'empty'));
    detail.replaceChildren();
    const record = visible.find(row => row.id === selected);
    if (!record) { detail.append(el('p', '选择一条记录查看详情', 'empty')); return; }
    detail.append(el('h2', record.title));
    if (!selectedDetail) { detail.append(el('p', detailError || '正在读取记录详情…', 'empty')); return; }
    const fields = el('dl');
    const fieldValue = value => el('dd', value, value !== null && typeof value === 'object' ? 'json-value' : '');
    for (const [key, value] of Object.entries(selectedDetail)) {
      if (key === 'title') continue;
      if (key === 'fields' && Array.isArray(value)) {
        for (const field of value) fields.append(el('dt', field.label || field.key), fieldValue(field.value));
      } else if (key === 'fields' && value && typeof value === 'object') {
        for (const [field, content] of Object.entries(value)) fields.append(el('dt', field), fieldValue(content));
      } else fields.append(el('dt', key), fieldValue(value));
    }
    detail.append(fields);
  }
  search.oninput = () => render(state);
  return {render, dispose() { root.replaceChildren(); }};
}

// Keep the existing two-lane model editor and its trusted Asuna endpoints.
const modelEl = (tag, value, cls) => {
  const node = document.createElement(tag);
  if (value != null) node.textContent = value;
  if (cls) node.className = cls;
  return node;
};

export function mountModelSettings(root, api, refresh) {
  let state, modelRevision = '', wasApplying = false;
  const controls = {};
  const dialog = modelEl('dialog'); dialog.id = 'asuna-model-dialog';
  const form = modelEl('form'); form.id = 'asuna-model-form';
  const header = modelEl('header');
  header.append(modelEl('h2', '模型设置'), modelEl('p', '角色脑与行动脑分别配置，也可以使用同一模型。空闲时保存并应用。'));
  const hint = modelEl('p', '采用 DSH 的模型 ID、连接和兼容参数。当前审计桥支持本机/LAN 的 OpenAI Chat Completions 协议。', 'hint');
  const fields = modelEl('div'); fields.id = 'asuna-model-fields';
  const status = modelEl('p'); status.id = 'asuna-model-status'; status.role = 'status';
  const footer = modelEl('footer'), close = modelEl('button', '关闭'), save = modelEl('button', '保存并应用');
  close.type = 'button'; save.type = 'submit'; close.onclick = () => dialog.close();
  footer.append(close, save); form.append(header, hint, fields, status, footer); dialog.append(form); root.append(dialog);
  function field(parent, lane, key, label, value, type = 'text', options) {
    const row = modelEl('label', label), id = `model-${lane}-${key}`;
    row.htmlFor = id;
    const input = modelEl(options ? 'select' : type === 'json' ? 'textarea' : 'input'); input.id = id;
    if (options) options.forEach(([v, title]) => { const option = modelEl('option', title); option.value = v; input.append(option); });
    else if (type !== 'json') input.type = type;
    input.value = type === 'json' ? JSON.stringify(value, null, 2) : value;
    if (type === 'number') { input.min = '1'; input.required = true; }
    if (type === 'password') { input.autocomplete = 'new-password'; input.placeholder = '留空保留；更换地址时不会沿用旧密钥'; }
    row.append(input); parent.append(row); controls[lane][key] = input; return input;
  }
  function draft(lane) {
    const source = controls[lane], model = {};
    for (const key of ['base_url','model','api_key','token_counter','reasoning_effort']) model[key] = source[key].value.trim();
    for (const key of ['max_tokens','context_window']) model[key] = Number(source[key].value);
    for (const key of ['sampling','compat','reasoning_efforts']) model[key] = JSON.parse(source[key].value);
    model.api = 'openai-completions'; model.clear_api_key = source.clear_api_key.checked;
    return model;
  }
  function populate(models) {
    fields.replaceChildren();
    for (const [lane, label] of [['character','角色脑'],['executor','行动脑']]) {
      const model = models[lane], box = modelEl('fieldset'); box.append(modelEl('legend', label)); controls[lane] = {};
      field(box, lane, 'base_url', '连接地址（Base URL）', model.base_url).required = true;
      const id = field(box, lane, 'model', '模型 ID', model.model); id.required = true; id.setAttribute('list', `${lane}-models`);
      const choices = modelEl('datalist'); choices.id = `${lane}-models`; box.append(choices);
      const discover = modelEl('button', '读取服务模型列表'); discover.type = 'button';
      discover.onclick = async () => {
        discover.disabled = true;
        try {
          const value = draft(lane);
          const result = await api('models/discover', {lane, base_url: value.base_url, api_key: value.api_key, clear_api_key: value.clear_api_key});
          choices.replaceChildren();
          result.models.forEach(item => { const option = modelEl('option'); option.value = item.id; choices.append(option); });
          status.textContent = `${label}可选模型：${result.models.map(item => item.id).join('、') || '服务未返回模型'}。可在模型 ID 中选择或手动填写。`;
        } catch (cause) { status.textContent = cause.message; }
        finally { discover.disabled = false; }
      }; box.append(discover);
      field(box, lane, 'api_key', model.api_key_set ? 'API key（已设置）' : 'API key（可选）', '', 'password');
      const clearLabel = modelEl('label', '清除已保存的 API key'), clear = modelEl('input'); clear.type = 'checkbox';
      clearLabel.append(clear); box.append(clearLabel); controls[lane].clear_api_key = clear;
      const sizes = modelEl('div', null, 'model-sizes');
      field(sizes, lane, 'context_window', '上下文窗口', model.context_window, 'number');
      field(sizes, lane, 'max_tokens', '输出上限', model.max_tokens, 'number'); box.append(sizes);
      const advanced = modelEl('details'); advanced.append(modelEl('summary', '高级兼容设置'));
      field(advanced, lane, 'token_counter', 'Token 计数', model.token_counter, 'text',
        [['conservative_bytes','通用保守估算'],['llama_cpp','llama.cpp 原生计数'],['anthropic_count','服务 count_tokens 接口']]);
      field(advanced, lane, 'reasoning_effort', '推理强度', model.reasoning_effort, 'text',
        ['off','minimal','low','medium','high','xhigh'].map(v => [v,v]));
      field(advanced, lane, 'sampling', '采样参数（JSON）', model.sampling, 'json');
      field(advanced, lane, 'compat', 'DSH compat（JSON）', model.compat, 'json');
      field(advanced, lane, 'reasoning_efforts', 'DSH reasoningEfforts（JSON）', model.reasoning_efforts, 'json');
      box.append(advanced); fields.append(box);
    }
  }
  form.onsubmit = async event => {
    event.preventDefault(); save.disabled = true;
    try {
      await api('models', {revision: modelRevision, models: {character: draft('character'), executor: draft('executor')}});
      wasApplying = true; status.textContent = '正在应用…'; await refresh();
    } catch (cause) { status.textContent = cause.message; save.disabled = state?.readOnly || state?.modelSettings?.applying; }
  };
  return {
    open(next) {
      if (!next?.modelSettings) return;
      state = next; modelRevision = next.modelSettings.revision; populate(next.modelSettings.models);
      status.textContent = next.modelSettings.applying ? '正在应用模型配置…' :
        next.modelSettings.error || '配置将持久保存。模型 ID 和可用能力以实际服务为准。';
      dialog.showModal();
    },
    update(next) {
      state = next;
      if (!next?.modelSettings) return;
      save.disabled = next.readOnly || next.modelSettings.applying;
      if (next.modelSettings.applying) status.textContent = '正在应用模型配置，暂时停止接收新消息…';
      else if (wasApplying) {
        status.textContent = next.modelSettings.error ? `未应用：${next.modelSettings.error}` : '已保存并应用；后续消息使用当前两条模型路由。';
        wasApplying = false;
      }
    },
    dispose() { dialog.remove(); },
  };
}
