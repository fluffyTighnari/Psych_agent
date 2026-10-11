/* ==========================================================================
   心迹 · Psych Journal — 前端逻辑
   后端为 FastAPI (默认 http://127.0.0.1:8000)
   ========================================================================== */

// 同源部署（挂在 FastAPI 下）时用相对路径；以 file:// 打开时回退到本地后端。
const API_BASE = (location.protocol === 'file:') ? 'http://127.0.0.1:8000' : '';

const API = {
  chat: '/chat',
  chatStream: '/chat/stream',
  sessionState: '/session/state',
  sessionClear: '/session/clear',
  sessionReset: '/session/reset',
  modelGet: '/tool/model',
  modelUpdate: '/tool/model/update',
  ollamaList: '/ollama/list',
  ollamaStart: '/ollama/start',
  ollamaPs: '/ollama/ps',
  metaFilter: '/tool/search/meta-filter',
  textFilter: '/tool/search/text-filter',
  preprocess: '/tool/preprocess',
  memoryFilter: '/tool/search/memory-filter',
  memoryVector: '/tool/search/memory-vector',
  saveDaily: '/tool/article/save-daily',
  saveWeekly: '/tool/article/save-weekly',
  summarize: '/tool/summarize',
  knowledgeAll: '/knowledge/all',
  memoryAll: '/memory/all',
  graph: '/graph/session-relation',
  traceAll: '/trace/all',
  traceStream: '/trace/stream',
  retrievalDebug: '/retrieval/debug',
  retrievalDocs: '/retrieval/documents',
  retrievalMeta: '/retrieval/meta',
};

const OLLAMA_MODELS = ['qwen2:1.5b', 'qwen3.5:9b-128k', 'qwen3.6-27b', 'phi3-3.8b'];
const API_MODELS = ['deepseek-v4-flash', 'deepseek-v4-pro', 'Qwen3.8-Max', 'Qwen3.7-Plus'];

const VALID_TOPICS = [
  'Self_Understanding', 'Self_Acceptance', 'Personal_Growth', 'Emotion_Regulation',
  'Anxiety', 'Uncertainty', 'Perfectionism', 'Motivation', 'Action', 'Learning',
  'Skill_Development', 'Career', 'Relationships', 'Cognitive_Patterns', 'Values',
  'Stress_Health', 'Lifestyle', 'Psychology', 'Philosophy', 'Happiness',
];

const TYPE_LABEL = { session: '会话', memory: '记忆', document: '文档', reason: '推理' };

// ================= 基础工具 =================
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

function esc(s) {
  return String(s ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
function stripPrefix(text) {
  return String(text ?? '').replace(/^【[^】]*】\s*/, '');
}
function splitMulti(str) {
  if (!str) return null;
  const arr = String(str).split(/[,，、;；\s]+/).map(s => s.trim()).filter(Boolean);
  return arr.length ? arr : null;
}
function emotionStr(em) {
  if (!em || typeof em !== 'object') return '—';
  const p = em.primary || em.primary_emotion || '';
  const s = em.secondary || em.secondary_emotion || '';
  const i = (em.intensity !== undefined && em.intensity !== null) ? em.intensity : null;
  let out = p || 'Neutral';
  if (s) out += ' · ' + s;
  if (i !== null) out += ' (' + Math.round(Number(i) * 100) + '%)';
  return out;
}
function fmtTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString('zh-CN', { hour12: false });
}

async function apiFetch(path, { method = 'GET', body } = {}) {
  const opts = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const res = await fetch(API_BASE + path, opts);
  let j;
  try { j = await res.json(); } catch (e) { throw new Error('响应解析失败 (HTTP ' + res.status + ')'); }
  if (j.code !== 200) throw new Error(j.msg || ('请求失败 code=' + j.code));
  return j.data;
}

// ================= Toast =================
function toast(msg, type = 'ok', duration = 2600) {
  const box = $('#toasts');
  const el = document.createElement('div');
  el.className = 'toast ' + type;
  el.textContent = msg;
  el.style.whiteSpace = 'pre-wrap';
  box.appendChild(el);
  setTimeout(() => {
    el.classList.add('out');
    setTimeout(() => el.remove(), 300);
  }, duration);
}

// ================= 全局状态 =================
let currentModels = null;
let originalModels = null;
let allDocs = [];
let allMemories = [];
let sessionState = null;
let graphData = null;
let graph = null;
let chatMode = null;      // null 未选 / 'direct' 直接咨询 / 'guided' 引导咨询；首条后锁定
let anchorProblem = '';   // guided 锚定的核心问题（sticky 展示）

// ================= 视图切换 =================
function bindNavigation() {
  $$('.nav-item').forEach(btn => {
    btn.addEventListener('click', () => {
      const view = btn.dataset.view;
      $$('.nav-item').forEach(b => b.classList.toggle('active', b === btn));
      $$('.view').forEach(v => v.classList.toggle('active', v.id === 'view-' + view));
      if (view === 'chat') {
        requestAnimationFrame(applyGraph);
      }
      if (view === 'records') {
        const tab = $('#records-tabs .tab.active');
        if (tab) renderDefaultList(tab.dataset.recordsTab);
      }
    });
  });
}

// ================= 主对话 =================
function bindChat() {
  const input = $('#chat-input');
  const send = $('#btn-send');

  const sendMessage = async () => {
    const text = input.value.trim();
    if (!text) return;
    const sendmode = document.querySelector('input[name="sendmode"]:checked').value;
    const situation = $('#chat-situation').value.trim() || null;
    if (!chatMode) {
      const sel = $('#mode-picker .mode-card.active');
      chatMode = (sel && sel.dataset.mode) || 'direct';
    }
    if (chatMode === 'guided' && !anchorProblem) anchorProblem = text;
    renderModeUI();
    addMessage('user', text);
    input.value = '';
    input.style.height = 'auto';
    $('#chat-situation').value = '';
    send.disabled = true;
    try {
      if (sendmode === 'stream') await sendStream(text, situation, chatMode);
      else await sendOnce(text, situation, chatMode);
    } catch (e) {
      addMessage('assistant', '（请求出错：' + e.message + '）', false, 'advisor');
      toast('对话失败：' + e.message, 'err');
    } finally {
      send.disabled = false;
      input.focus();
    }
  };

  // 模式选择：开局点击即选中，首条发送后锁定
  $$('#mode-picker .mode-card').forEach(card => {
    card.addEventListener('click', () => {
      $$('#mode-picker .mode-card').forEach(x => x.classList.toggle('active', x === card));
    });
  });

  send.addEventListener('click', sendMessage);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  input.addEventListener('input', () => {
    input.style.height = 'auto';
    input.style.height = input.scrollHeight + 'px';
  });

  $('#btn-situation-toggle').addEventListener('click', () => {
    const ta = $('#chat-situation');
    const show = ta.style.display === 'none';
    ta.style.display = show ? 'block' : 'none';
    $('#btn-situation-toggle').textContent = show ? '－ 收起具体情境' : '＋ 补充具体情境（可选）';
    if (show) ta.focus();
  });

  $('#btn-session-clear').addEventListener('click', async () => {
    try {
      await apiFetch(API.sessionClear, { method: 'POST', body: {} });
      $('#chat-list').innerHTML = '';
      showChatEmpty();
      chatMode = null;
      anchorProblem = '';
      renderModeUI();
      toast('已清空本轮对话', 'ok');
    } catch (e) { toast('清空失败：' + e.message, 'err'); }
  });

  $('#btn-session-reset').addEventListener('click', async () => {
    if (!confirm('确定完全重置会话？将清空对话、记忆引用并开启新会话。')) return;
    try {
      await apiFetch(API.sessionReset, { method: 'POST', body: {} });
      $('#chat-list').innerHTML = '';
      showChatEmpty();
      sessionState = null;
      chatMode = null;
      anchorProblem = '';
      renderModeUI();
      $('#rail-session').textContent = 'session · —';
      toast('会话已完全重置', 'ok');
      loadGraph();
    } catch (e) { toast('重置失败：' + e.message, 'err'); }
  });
}

async function sendOnce(text, situation, mode) {
  const data = await apiFetch(API.chat, { method: 'POST', body: { user_input: text, situation: situation || null, mode: mode || 'direct' } });
  const speaker = data.intent_type === 'guided_reason' ? 'guide' : 'advisor';
  addMessage('assistant', stripPrefix(data.reply || ''), false, speaker);
  if (data.ended) toast('本轮引导已结束，建议已生成；可点击「一键总结」归档。', 'info', 4000);
}

async function sendStream(text, situation, mode) {
  const bubble = addMessage('assistant', '', true, 'guide'); // 默认按引导者渲染，meta 事件到达后修正
  const contentEl = bubble.querySelector('.stream-text');

  const res = await fetch(API_BASE + API.chatStream, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_input: text, situation: situation || null, mode: mode || 'direct' }),
  });
  if (!res.ok || !res.body) throw new Error('流式连接失败');

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  let full = '';

  const handleEvent = (raw) => {
    const dataLines = raw.split('\n').filter(l => l.startsWith('data:')).map(l => l.slice(5).trim());
    if (!dataLines.length) return;
    let obj;
    try { obj = JSON.parse(dataLines.join('')); } catch (e) { return; }
    if (obj.type === 'reply_chunk') {
      full += obj.content || '';
      contentEl.innerHTML = renderAssistantHTML(full);
      scrollChat();
    } else if (obj.type === 'trace_all' && Array.isArray(obj.logs)) {
      addTrace(obj.logs);
    } else if (obj.type === 'meta') {
      const spk = obj.intent_type === 'guided_reason' ? 'guide' : 'advisor';
      const nameEl = bubble.querySelector('.msg-name');
      if (nameEl) nameEl.textContent = spk === 'guide' ? '引导者' : '建议者';
      const bub = bubble.querySelector('.msg-bubble');
      if (bub) { bub.classList.remove('speaker-guide', 'speaker-advisor'); bub.classList.add('speaker-' + spk); }
      if (obj.ended) toast('本轮引导已结束，建议已生成；可点击「一键总结」归档。', 'info', 4000);
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      handleEvent(buf.slice(0, idx));
      buf = buf.slice(idx + 2);
    }
  }
  removeTypingCursor(bubble);
}

function showChatEmpty() {
  $('#chat-list').insertAdjacentHTML('beforeend', `
    <div class="chat-empty" id="chat-empty">
      <div class="empty-seal">迹</div>
      <p class="empty-title">此刻，你在想些什么？</p>
      <p class="empty-sub">写下你的情绪、困惑或迷茫，我会认真倾听。</p>
    </div>`);
}

function renderModeUI() {
  const picker = $('#mode-picker');
  const anchor = $('#problem-anchor');
  const input = $('#chat-input');
  const sitBtn = $('#btn-situation-toggle');
  const sitTa = $('#chat-situation');
  if (!picker || !input) return;
  if (!chatMode) {
    picker.style.display = 'flex';
    anchor.style.display = 'none';
    input.placeholder = '说点什么…';
    sitBtn.style.display = '';
  } else if (chatMode === 'direct') {
    picker.style.display = 'none';
    anchor.style.display = 'none';
    input.placeholder = '说点什么…';
    sitBtn.style.display = '';
  } else { // guided
    picker.style.display = 'none';
    anchor.style.display = 'flex';
    $('#problem-anchor-text').textContent = anchorProblem || '—';
    input.placeholder = '回答引导者的问题…';
    sitBtn.style.display = 'none';
    sitTa.style.display = 'none';
  }
  $$('#mode-picker .mode-card').forEach(c => { c.disabled = !!chatMode; });
}

function addMessage(role, text, streaming = false, speaker = 'advisor') {
  const empty = $('#chat-empty');
  if (empty) empty.remove();
  const list = $('#chat-list');
  const wrap = document.createElement('div');
  const isAssistant = role === 'assistant';
  wrap.className = 'msg ' + role + (isAssistant ? (' speaker-' + speaker) : '');
  const avatarChar = role === 'user' ? '我' : (speaker === 'guide' ? '引' : '师');
  const nameLabel = role === 'user' ? '我' : (speaker === 'guide' ? '引导者' : '建议者');
  const spkClass = isAssistant ? (' speaker-' + speaker) : '';
  let bubbleHTML;
  if (streaming) {
    bubbleHTML = `<div class="msg-bubble${spkClass}"><div class="msg-name">${nameLabel}</div><span class="stream-text"></span><span class="typing-cursor"></span></div>`;
  } else {
    const content = isAssistant ? renderAssistantHTML(text) : esc(text);
    bubbleHTML = `<div class="msg-bubble${spkClass}"><div class="msg-name">${nameLabel}</div><span class="stream-text">${content}</span></div>`;
  }
  wrap.innerHTML = `<div class="msg-avatar">${avatarChar}</div>${bubbleHTML}`;
  list.appendChild(wrap);
  scrollChat();
  return wrap;
}

function removeTypingCursor(bubble) {
  const c = bubble.querySelector('.typing-cursor');
  if (c) c.remove();
}

function scrollChat() {
  const s = $('#chat-scroll');
  s.scrollTop = s.scrollHeight;
}

function renderAssistantHTML(text) {
  return esc(text)
    .replace(/\[\[cite:([^\]\n]+)\]\]/g, (m, id) =>
      `<span class="cite-chip" data-node-id="${esc(id)}" title="悬停定位图谱 · 点击查看详情">引用</span>`)
    .replace(/\[\[guide:([^\]\n]+)\]\]/g, (m, id) =>
      `<span class="guide-chip" data-node-id="${esc(id)}" title="引导提问 · 点击定位推理链">引导提问</span>`);
}

function openCitationModal(id) {
  let node = graphData && graphData.nodes ? graphData.nodes.find(n => n.id === id) : null;
  if (!node) {
    const doc = allDocs.find(d => d.doc_id === id);
    if (doc) node = { id: doc.doc_id, type: 'document', name: doc.title, summary: doc.summary, source: doc.source };
    else {
      const mem = allMemories.find(m => m.id === id);
      if (mem) node = { id: mem.id, type: 'memory', name: mem.title, summary: mem.summary };
    }
  }
  if (node) { openNodeModal(node); return; }
  toast('未找到对应的知识节点', 'err');
}

function bindCitations() {
  const list = $('#chat-list');
  const chipSel = '.cite-chip, .guide-chip';
  list.addEventListener('mouseover', e => {
    const chip = e.target.closest(chipSel);
    if (chip && graph && graph.highlight) graph.highlight(chip.dataset.nodeId);
  });
  list.addEventListener('mouseout', e => {
    const chip = e.target.closest(chipSel);
    if (chip && graph && graph.clearHighlight) graph.clearHighlight();
  });
  list.addEventListener('click', e => {
    const chip = e.target.closest(chipSel);
    if (!chip) return;
    openCitationModal(chip.dataset.nodeId);
  });
}

async function loadSessionState() {
  try {
    sessionState = await apiFetch(API.sessionState);
    $('#rail-session').textContent = 'session · ' + (sessionState.session_id || '—');
    chatMode = sessionState.mode || null;
    anchorProblem = sessionState.mode_problem || '';
    const hist = sessionState.full_chat_history || [];
    if (hist.length) {
      $('#chat-empty')?.remove();
      hist.forEach(m => addMessage(m.role === 'user' ? 'user' : 'assistant', stripPrefix(m.content), false, m.speaker || 'advisor'));
    } else {
      $('#chat-list').innerHTML = '';
      showChatEmpty();
    }
    renderModeUI();
    setConn(true);
  } catch (e) {
    setConn(false);
    console.warn('session state load failed', e);
  }
}

// ================= 模型配置 =================
function modelDisplayName(m) {
  return m.driver === 'ollama' ? m.ollama_name : (m.api_model_name || m.ollama_name || '—');
}

async function loadModels() {
  try {
    const data = await apiFetch(API.modelGet);
    currentModels = JSON.parse(JSON.stringify(data));
    originalModels = JSON.parse(JSON.stringify(data));
    renderModelChips();
    renderModelSlots();
  } catch (e) { console.warn('model load failed', e); }
}

function renderModelChips() {
  if (!currentModels) return;
  const box = $('#model-chips');
  box.innerHTML = ['small', 'large', 'chat'].map(k => {
    const m = currentModels[k];
    return `<span class="model-chip"><b>${k}</b><code>${esc(modelDisplayName(m))}</code></span>`;
  }).join('');
}

function renderModelSlots() {
  const box = $('#model-slots');
  if (!currentModels) return;
  box.innerHTML = '';
  ['small', 'large', 'chat'].forEach(k => {
    const m = currentModels[k];
    const slot = document.createElement('div');
    slot.className = 'model-slot';
    slot.innerHTML = `
      <div class="model-slot-head">
        <span class="slot-name">${k.toUpperCase()}<small>${k === 'small' ? '预处理/分类' : k === 'large' ? '预处理/总结' : '路由/生成'}</small></span>
        <div class="slot-driver">
          <button data-slot="${k}" data-driver="ollama" class="${m.driver === 'ollama' ? 'active' : ''}">ollama</button>
          <button data-slot="${k}" data-driver="api" class="${m.driver === 'api' ? 'active' : ''}">api</button>
        </div>
      </div>
      <div class="slot-field">
        <label>模型（选择预设，自动切换 driver）</label>
        <select data-slot="${k}" data-field="preset">
          <option value="">保持当前：${esc(modelDisplayName(m))}</option>
          <optgroup label="Ollama 本地">${OLLAMA_MODELS.map(n => `<option>${n}</option>`).join('')}</optgroup>
          <optgroup label="API 云端">${API_MODELS.map(n => `<option>${n}</option>`).join('')}</optgroup>
        </select>
      </div>
      <div class="slot-field">
        <label>temperature</label>
        <input type="number" step="0.1" data-slot="${k}" data-field="temperature" value="${m.temperature ?? 0}" />
      </div>
      <div class="slot-note">${m.driver === 'api' ? 'API 密钥与地址由后端 .env 自动注入' : '本地 Ollama 模型'}</div>`;
    box.appendChild(slot);

    slot.querySelectorAll('[data-driver]').forEach(b => {
      b.addEventListener('click', () => {
        currentModels[k].driver = b.dataset.driver;
        if (b.dataset.driver === 'ollama') currentModels[k].api_model_name = '';
        else currentModels[k].ollama_name = '';
        renderModelSlots();
      });
    });
    slot.querySelector('[data-field="preset"]').addEventListener('change', e => {
      const v = e.target.value;
      if (!v) return;
      if (OLLAMA_MODELS.includes(v)) { currentModels[k].driver = 'ollama'; currentModels[k].ollama_name = v; currentModels[k].api_model_name = ''; }
      else { currentModels[k].driver = 'api'; currentModels[k].api_model_name = v; currentModels[k].ollama_name = ''; }
      renderModelSlots();
    });
    slot.querySelector('[data-field="temperature"]').addEventListener('input', e => {
      currentModels[k].temperature = parseFloat(e.target.value) || 0;
    });
  });
}

async function loadOllamaList() {
  const sel = $('#ollama-start-model');
  try {
    const data = await apiFetch(API.ollamaList);
    const models = data.models || [];
    sel.innerHTML = models.length
      ? models.map(n => `<option>${esc(n)}</option>`).join('')
      : '<option value="">（无可用模型）</option>';
  } catch (e) {
    sel.innerHTML = '<option value="">（列表获取失败）</option>';
    toast('获取 Ollama 模型列表失败：' + e.message, 'err');
  }
}

function fmtSize(bytes) {
  if (bytes === undefined || bytes === null) return '';
  if (bytes >= 1e9) return (bytes / 1e9).toFixed(1) + ' GB';
  if (bytes >= 1e6) return (bytes / 1e6).toFixed(1) + ' MB';
  return bytes + ' B';
}

async function loadOllamaPs() {
  const box = $('#ollama-running');
  try {
    const data = await apiFetch(API.ollamaPs);
    const models = data.models || [];
    if (!models.length) {
      box.innerHTML = '<span class="muted">暂无运行中的模型</span>';
      return;
    }
    box.innerHTML = models.map(m => {
      const name = m.model || m.name || '';
      let expires = '—';
      if (m.expires_at) {
        const d = new Date(m.expires_at); // Ollama 返回 ISO 字符串，非时间戳
        if (!isNaN(d.getTime())) expires = d.toLocaleString('zh-CN', { hour12: false });
      }
      return `<div class="ollama-running-item">
        <span class="ollama-running-name">${esc(name)}</span>
        <span class="ollama-running-meta">${fmtSize(m.size)} · 至 ${esc(expires)}</span>
      </div>`;
    }).join('');
  } catch (e) {
    box.innerHTML = '<span class="muted">运行状态获取失败</span>';
    toast('获取运行中模型失败：' + e.message, 'err');
  }
}

function bindModel() {
  $('#btn-model-settings').addEventListener('click', () => {
    if (currentModels) renderModelSlots();
    loadOllamaList();
    loadOllamaPs();
    $('#model-drawer').classList.add('show');
    $('#model-drawer-mask').classList.add('show');
  });
  $('#model-close').addEventListener('click', closeModelDrawer);
  $('#model-drawer-mask').addEventListener('click', closeModelDrawer);

  $('#btn-ollama-start').addEventListener('click', async () => {
    const model_name = $('#ollama-start-model').value;
    if (!model_name) { toast('请选择要启动的模型', 'err'); return; }
    const btn = $('#btn-ollama-start');
    btn.disabled = true;
    try {
      await apiFetch(API.ollamaStart, { method: 'POST', body: {
        model_name,
        keep_alive: $('#ollama-start-keepalive').value,
      }});
      toast('模型已加载至显存：' + model_name, 'ok');
      await loadOllamaPs();
    } catch (e) { toast('启动失败：' + e.message, 'err'); }
    finally { btn.disabled = false; }
  });
  $('#btn-ollama-ps-refresh').addEventListener('click', loadOllamaPs);

  $('#btn-model-save').addEventListener('click', async () => {
    const payload = {};
    ['small', 'large', 'chat'].forEach(k => {
      const m = currentModels[k];
      const o = originalModels[k];
      payload[k] = {
        driver: m.driver,
        ollama_name: m.ollama_name || '',
        api_key: o.api_key || '',
        base_url: o.base_url || '',
        api_model_name: m.api_model_name || '',
        temperature: m.temperature ?? 0,
      };
    });
    try {
      await apiFetch(API.modelUpdate, { method: 'POST', body: payload });
      await loadModels();
      closeModelDrawer();
      toast('模型配置已保存并生效', 'ok');
    } catch (e) { toast('保存失败：' + e.message, 'err'); }
  });
}

function closeModelDrawer() {
  $('#model-drawer').classList.remove('show');
  $('#model-drawer-mask').classList.remove('show');
}

// ================= 主题多选 =================
function buildTopicCheckboxes(containerId) {
  const box = $('#' + containerId);
  if (!box) return;
  box.innerHTML = VALID_TOPICS.map(t =>
    `<label class="topic-check"><input type="checkbox" value="${t}" /><span>${t}</span></label>`
  ).join('');
}
function getCheckedTopics(containerId) {
  const vals = $$('#' + containerId + ' input[type="checkbox"]:checked').map(cb => cb.value);
  return vals.length ? vals : null;
}
function uncheckAllTopics(containerId) {
  $$('#' + containerId + ' input[type="checkbox"]').forEach(cb => cb.checked = false);
}

// ================= 过往记录 =================
let kMode = 'meta';
let mMode = 'filter';

function bindRecords() {
  $$('#records-tabs .tab').forEach(t => {
    t.addEventListener('click', () => {
      $$('#records-tabs .tab').forEach(b => b.classList.toggle('active', b === t));
      const kind = t.dataset.recordsTab;
      $('#panel-knowledge').classList.toggle('active', kind === 'knowledge');
      $('#panel-memory').classList.toggle('active', kind === 'memory');
      renderDefaultList(kind);
    });
  });

  $$('#k-submodes .submode').forEach(b => {
    b.addEventListener('click', () => setKMode(b.dataset.kmode));
  });
  $$('#m-submodes .submode').forEach(b => {
    b.addEventListener('click', () => setMMode(b.dataset.mmode));
  });

  $('#btn-k-search').addEventListener('click', onKSearch);
  $('#btn-k-clear').addEventListener('click', clearK);
  $('#btn-m-search').addEventListener('click', onMSearch);
  $('#btn-m-clear').addEventListener('click', clearM);

  // 回到开头
  $('#back-top').addEventListener('click', () => $('#view-records').scrollTo({ top: 0, behavior: 'smooth' }));

  setKMode('meta');
  setMMode('filter');
}

function setKMode(mode) {
  kMode = mode;
  $$('#k-submodes .submode').forEach(b => b.classList.toggle('active', b.dataset.kmode === mode));
  $('#k-form').style.display = mode === 'preprocess' ? 'none' : 'grid';
  $('#k-preprocess-box').style.display = mode === 'preprocess' ? 'block' : 'none';
  $('#k-target-field').style.display = mode === 'text' ? 'flex' : 'none';
  $('#btn-k-search').textContent = mode === 'preprocess' ? '运行预处理' : '搜索';
}

function setMMode(mode) {
  mMode = mode;
  $$('#m-submodes .submode').forEach(b => b.classList.toggle('active', b.dataset.mmode === mode));
  $('#m-filter-form').style.display = mode === 'filter' ? 'grid' : 'none';
  $('#m-vector-form').style.display = mode === 'vector' ? 'grid' : 'none';
}

function kCommonPayload() {
  return {
    doc_type: $('#k-doc-type').value || null,
    start_date: $('#k-start').value || null,
    end_date: $('#k-end').value || null,
    topic_keyword: getCheckedTopics('k-topic-checkboxes'),
    keyword: splitMulti($('#k-keyword').value),
    emotion: splitMulti($('#k-emotion').value),
  };
}

async function onKSearch() {
  if (kMode === 'preprocess') return runPreprocess();
  const btn = $('#btn-k-search');
  btn.disabled = true;
  try {
    let res;
    if (kMode === 'meta') {
      res = await apiFetch(API.metaFilter, { method: 'POST', body: kCommonPayload() });
    } else {
      const target = $('#k-target').value.trim();
      if (!target) { toast('精准文本过滤需要填写 target_text', 'err'); return; }
      res = await apiFetch(API.textFilter, { method: 'POST', body: { ...kCommonPayload(), target_text: target } });
    }
    renderDocs(res.result || []);
  } catch (e) {
    toast('检索失败：' + e.message, 'err');
  } finally {
    btn.disabled = false;
  }
}

async function runPreprocess() {
  const btn = $('#btn-k-search');
  btn.disabled = true;
  btn.textContent = '预处理中…';
  toast('开始预处理，耗时较长请耐心等待', 'info', 4000);
  try {
    await apiFetch(API.preprocess, { method: 'POST', body: {} });
    toast('预处理完成', 'ok');
    await loadKnowledge();
  } catch (e) {
    toast('预处理失败：' + e.message, 'err');
  } finally {
    btn.disabled = false;
    btn.textContent = '运行预处理';
  }
}

async function onMSearch() {
  const btn = $('#btn-m-search');
  btn.disabled = true;
  try {
    let res;
    if (mMode === 'filter') {
      res = await apiFetch(API.memoryFilter, { method: 'POST', body: {
        topic_keyword: getCheckedTopics('m-topic-checkboxes'),
        start_date: $('#m-start').value || null,
        end_date: $('#m-end').value || null,
        keyword: splitMulti($('#m-keyword').value),
        emotion: splitMulti($('#m-emotion').value),
      }});
    } else {
      res = await apiFetch(API.memoryVector, { method: 'POST', body: {
        query: $('#m-query').value.trim(),
        top_k: parseInt($('#m-topk').value, 10) || 3,
      }});
    }
    renderMemories(res.result || []);
  } catch (e) {
    toast('检索失败：' + e.message, 'err');
  } finally {
    btn.disabled = false;
  }
}

function clearK() {
  ['k-doc-type', 'k-start', 'k-end', 'k-keyword', 'k-emotion', 'k-target'].forEach(id => {
    $('#' + id).value = '';
  });
  uncheckAllTopics('k-topic-checkboxes');
  renderDocs(allDocs);
}

function clearM() {
  ['m-start', 'm-end', 'm-keyword', 'm-emotion', 'm-query'].forEach(id => {
    $('#' + id).value = '';
  });
  $('#m-topk').value = '3';
  uncheckAllTopics('m-topic-checkboxes');
  renderMemories(allMemories);
}

function renderDefaultList(kind) {
  if (kind === 'knowledge') renderDocs(allDocs);
  else renderMemories(allMemories);
}

function setResultCount(n) {
  $('#records-count').textContent = n + ' 条';
}

function renderDocs(docs) {
  const box = $('#records-results');
  box.innerHTML = '';
  setResultCount(docs.length);
  if (!docs.length) {
    box.innerHTML = '<div class="results-empty">未匹配到任何文档</div>';
    return;
  }
  docs.forEach((d, i) => {
    const card = document.createElement('div');
    card.className = 'result-card';
    card.style.animationDelay = (i * 30) + 'ms';
    const topics = (d.topic || d.topics || []);
    const keywords = d.keywords || [];
    const isWeekly = d.doc_type === 'weekly';
    const isDaily = d.doc_type === 'daily';

    let detailHtml = '';
    if (isWeekly) {
      detailHtml += `
        <h5>problem · 问题</h5><pre>${esc(d.problem || '—')}</pre>
        <h5>analysis · 分析</h5><pre>${esc(d.analysis || '—')}</pre>
        <h5>solution · 方案</h5><pre>${esc(d.solution || '—')}</pre>`;
    }
    if (isDaily) {
      detailHtml += `
        <h5>正文内容</h5><pre>${esc(d.content || '暂无内容')}</pre>`;
    }
    // 统一追加来源
    detailHtml += `
      <h5>来源</h5><pre>${esc(d.relative_path || d.source || '—')}</pre>`;

    card.innerHTML = `
      <div class="result-top">
        <span class="result-title">${esc(d.title || d.doc_id || '无标题')}</span>
        <span class="badge ${esc(d.doc_type)}">${esc(d.doc_type || '')}</span>
        ${d.date ? `<span class="badge date">${esc(d.date)}</span>` : ''}
      </div>
      <div class="result-summary">${esc(d.summary || '（无摘要）')}</div>
      <div class="result-meta">
        ${topics.map(t => `<span class="chip topic">${esc(t)}</span>`).join('')}
        ${keywords.map(t => `<span class="chip keyword">${esc(t)}</span>`).join('')}
        ${d.emotion ? `<span class="chip emotion">${esc(emotionStr(d.emotion))}</span>` : ''}
      </div>
      <div class="result-detail">
        ${detailHtml}
      </div>`;

    card.addEventListener('click', () => card.classList.toggle('open'));
    box.appendChild(card);
  });
}


function renderDialogues(dialogues) {
  if (!dialogues || !dialogues.length) return '';
  return `<h5>对话记录（${dialogues.length} 轮）</h5>
    <div class="dialogues">
      ${dialogues.map(d => {
        const isUser = d.role === 'user';
        return `<div class="dlg ${isUser ? 'user' : 'assistant'}">
          <div class="dlg-role">${isUser ? '用户' : '咨询师'}</div>
          <div class="dlg-content">${esc(d.content || '')}</div>
        </div>`;
      }).join('')}
    </div>`;
}

function renderMemories(mems) {
  const box = $('#records-results');
  box.innerHTML = '';
  setResultCount(mems.length);
  if (!mems.length) { box.innerHTML = '<div class="results-empty">未匹配到任何记忆</div>'; return; }
  mems.forEach((m, i) => {
    const card = document.createElement('div');
    card.className = 'result-card';
    card.style.animationDelay = (i * 30) + 'ms';
    const topics = m.topics || [];
    const keywords = m.keywords || [];
    const insights = m.insights || [];
    const dialogues = m.dialogues || [];
    card.innerHTML = `
      <div class="result-top">
        <span class="result-title">${esc(m.title || '（无标题）')}</span>
        <span class="badge memory">memory</span>
        <span class="badge date">${esc((m.start_time || '').slice(0, 16))} ~ ${esc((m.end_time || '').slice(0, 16))}</span>
      </div>
      <div class="result-summary">${esc(m.summary || '（无摘要）')}</div>
      <div class="result-meta">
        ${topics.map(t => `<span class="chip topic">${esc(t)}</span>`).join('')}
        ${keywords.map(t => `<span class="chip keyword">${esc(t)}</span>`).join('')}
        ${m.emotion && Object.keys(m.emotion).length ? `<span class="chip emotion">${esc(emotionStr(m.emotion))}</span>` : ''}
      </div>
      <div class="result-detail">
        <h5>记忆 ID</h5><pre>${esc(m.id || '—')}</pre>
        ${insights.length ? `<h5>核心洞察</h5><pre>${esc(insights.join('；'))}</pre>` : ''}
        <h5>引用文档</h5><pre>${esc((m.referenced_documents || []).join('、') || '无')}</pre>
        ${renderDialogues(dialogues)}
      </div>`;
    card.addEventListener('click', () => card.classList.toggle('open'));
    box.appendChild(card);
  });
}

async function loadKnowledge() {
  try { allDocs = await apiFetch(API.knowledgeAll); } catch (e) { console.warn('knowledge load failed', e); }
  if ($('#panel-knowledge').classList.contains('active')) renderDocs(allDocs);
}

async function loadMemory() {
  try { allMemories = await apiFetch(API.memoryAll); } catch (e) { console.warn('memory load failed', e); }
}

// ================= 码字编辑 =================
function setTodayDate() {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  $('#d-date').value = `${y}-${m}-${d}`;
}
function dailyFilename() {
  const v = $('#d-date').value;
  if (!v) return null; // 未选择日期时交由后端按今天生成
  const [y, m, d] = v.split('-');
  return `${y}.${parseInt(m, 10)}.${parseInt(d, 10)}.md`;
}

function bindWriting() {
  setTodayDate();
  $$('input[name="writemode"]').forEach(r => {
    r.addEventListener('change', () => {
      const daily = document.querySelector('input[name="writemode"]:checked').value === 'daily';
      $('#write-daily').style.display = daily ? 'block' : 'none';
      $('#write-weekly').style.display = daily ? 'none' : 'block';
    });
  });

  $('#btn-d-save').addEventListener('click', async () => {
    const contentVal = $('#d-content').value.trim();
    if (!contentVal) { toast('正文不能为空', 'err'); return; }
    const btn = $('#btn-d-save');
    btn.disabled = true;
    try {
      const data = await apiFetch(API.saveDaily, { method: 'POST', body: {
        content: contentVal,
        custom_filename: dailyFilename(),
      }});
      toast('已保存：' + data.file_name, 'ok');
    } catch (e) { toast('保存失败：' + e.message, 'err'); }
    finally { btn.disabled = false; }
  });

  $('#btn-d-clear').addEventListener('click', () => {
    $('#d-content').value = '';
    $('#d-content').focus();
  });

  $('#btn-w-save').addEventListener('click', async () => {
    const filename = $('#w-filename').value.trim();
    const title = $('#w-title').value.trim();
    if (!filename) { toast('请填写文件名', 'err'); return; }
    if (!title) { toast('请填写标题', 'err'); return; }
    const btn = $('#btn-w-save');
    btn.disabled = true;
    try {
      const data = await apiFetch(API.saveWeekly, { method: 'POST', body: {
        filename,
        title,
        problem: $('#w-problem').value,
        analysis: $('#w-analysis').value,
        solution: $('#w-solution').value,
      }});
      toast('已保存：' + data.file_name, 'ok');
    } catch (e) { toast('保存失败：' + e.message, 'err'); }
    finally { btn.disabled = false; }
  });

  $('#btn-w-clear').addEventListener('click', () => {
    ['w-filename', 'w-title', 'w-problem', 'w-analysis', 'w-solution'].forEach(id => { $('#' + id).value = ''; });
    $('#w-filename').focus();
  });
}

// ================= 关联图谱 =================
function bindGraph() {
  graph = makeGraph($('#graph-canvas'), $('#graph-tooltip'), openNodeModal);

  $('#btn-graph-refresh').addEventListener('click', () => loadGraph());
  $('#btn-graph-summarize').addEventListener('click', async () => {
    const btn = $('#btn-graph-summarize');
    btn.disabled = true;
    try {
      const data = await apiFetch(API.summarize, { method: 'POST', body: {} });
      toast(data.summary_text || '会话总结完成', 'ok', 5000);
      await Promise.allSettled([loadGraph(), loadMemory(), loadSessionState()]);
    } catch (e) { toast('总结失败：' + e.message, 'err'); }
    finally { btn.disabled = false; }
  });

  window.addEventListener('resize', () => {
    if ($('#view-chat').classList.contains('active')) applyGraph();
  });
}

async function loadGraph() {
  try {
    graphData = await apiFetch(API.graph);
    if ($('#view-chat').classList.contains('active')) applyGraph();
  } catch (e) {
    toast('图谱加载失败：' + e.message, 'err');
  }
}

function applyGraph() {
  if (!graph) return;
  graph.resize();
  if (graphData) graph.setData(graphData);
  const hasNodes = !!(graphData && graphData.nodes && graphData.nodes.length);
  const empty = $('#graph-empty');
  if (empty) empty.style.display = hasNodes ? 'none' : 'grid';
  graph.start();
}

function makeGraph(canvas, tooltip, onNodeClick) {
  const ctx = canvas.getContext('2d');
  let nodes = [], links = [];
  let W = 0, H = 0, dpr = 1;
  let raf = null, running = false;
  let hovered = null, dragging = null;
  let focusId = null;

  const COLORS = { session: '#c24a2e', memory: '#b08a4c', document: '#4e6d6a', reason: '#7a5c8e' };
  const LINK_STYLE = {
    session_bind_memory: { color: '#c24a2e', dash: [] },
    session_ref_doc: { color: '#4e6d6a', dash: [6, 5] },
    memory_ref_doc: { color: '#b08a4c', dash: [2, 4] },
    memory_related_memory: { color: '#b08a4c', dash: [1, 3] },
    reason_next: { color: '#7a5c8e', dash: [] },
    session_bind_reason: { color: '#7a5c8e', dash: [4, 4] },
  };

  function resize() {
    const rect = canvas.parentElement.getBoundingClientRect();
    dpr = window.devicePixelRatio || 1;
    W = Math.max(rect.width, 1); H = Math.max(rect.height, 1);
    canvas.width = W * dpr; canvas.height = H * dpr;
    canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function baseRadius(n) {
    return n.type === 'session' ? 20 : n.type === 'memory' ? 15 : 11;
  }

  function setData(data) {
    const prev = {};
    nodes.forEach(n => prev[n.id] = n);
    const nodeMap = {};
    nodes = (data.nodes || []).map(n => {
      let x, y, vx = 0, vy = 0;
      if (prev[n.id]) { x = prev[n.id].x; y = prev[n.id].y; }
      else {
        const a = Math.random() * Math.PI * 2;
        const r = 100 + Math.random() * 110;
        x = W / 2 + Math.cos(a) * r; y = H / 2 + Math.sin(a) * r;
      }
      const node = { id: n.id, name: n.name, type: n.type, summary: n.summary, source: n.source, x, y, vx, vy, r: baseRadius(n) };
      nodeMap[n.id] = node;
      return node;
    });
    const sess = nodes.find(n => n.type === 'session');
    if (sess && !prev[sess.id]) { sess.x = W / 2; sess.y = H / 2; }
    links = (data.links || []).map(l => ({ source: nodeMap[l.source], target: nodeMap[l.target], relation: l.relation })).filter(l => l.source && l.target);
    const deg = {};
    links.forEach(l => { deg[l.source.id] = (deg[l.source.id] || 0) + 1; deg[l.target.id] = (deg[l.target.id] || 0) + 1; });
    nodes.forEach(n => { n.r = Math.min(baseRadius(n) + (deg[n.id] || 0) * 1.4, baseRadius(n) + 8); });
  }

  function tick() {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i], b = nodes[j];
        let dx = b.x - a.x, dy = b.y - a.y;
        let d2 = dx * dx + dy * dy; if (d2 < 1) d2 = 1;
        const d = Math.sqrt(d2);
        const f = 4800 / d2;
        const fx = (dx / d) * f, fy = (dy / d) * f;
        if (!a.fixed) { a.vx -= fx; a.vy -= fy; }
        if (!b.fixed) { b.vx += fx; b.vy += fy; }
      }
    }
    links.forEach(l => {
      const a = l.source, b = l.target;
      let dx = b.x - a.x, dy = b.y - a.y;
      const d = Math.sqrt(dx * dx + dy * dy) || 1;
      const f = (d - 150) * 0.03;
      const fx = (dx / d) * f, fy = (dy / d) * f;
      if (!a.fixed) { a.vx += fx; a.vy += fy; }
      if (!b.fixed) { b.vx -= fx; b.vy -= fy; }
    });
    nodes.forEach(n => {
      if (n.fixed) { n.vx = 0; n.vy = 0; return; }
      n.vx += (W / 2 - n.x) * 0.008;
      n.vy += (H / 2 - n.y) * 0.008;
      n.vx *= 0.88; n.vy *= 0.88;
      n.x += n.vx; n.y += n.vy;
      n.x = Math.max(n.r, Math.min(W - n.r, n.x));
      n.y = Math.max(n.r, Math.min(H - n.r, n.y));
    });
  }

  function draw() {
    ctx.clearRect(0, 0, W, H);
    links.forEach(l => {
      const st = LINK_STYLE[l.relation] || LINK_STYLE.session_ref_doc;
      ctx.strokeStyle = st.color;
      ctx.setLineDash(st.dash);
      ctx.lineWidth = 1.2;
      ctx.globalAlpha = 0.55;
      ctx.beginPath();
      ctx.moveTo(l.source.x, l.source.y);
      ctx.lineTo(l.target.x, l.target.y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
    });
    nodes.forEach(n => {
      const c = COLORS[n.type] || '#8a7f70';
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      ctx.fillStyle = c;
      ctx.fill();
      ctx.lineWidth = 2;
      ctx.strokeStyle = 'rgba(255,255,255,.85)';
      ctx.stroke();
      if (hovered === n || n.id === focusId) {
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r + 5, 0, Math.PI * 2);
        ctx.strokeStyle = c; ctx.lineWidth = 1.5; ctx.globalAlpha = .5; ctx.stroke(); ctx.globalAlpha = 1;
      }
      const docCount = nodes.filter(x => x.type === 'document').length;
      const showLabel = n.type !== 'document' || docCount <= 24 || hovered === n || n.id === focusId;
      if (showLabel && n.name) {
        ctx.font = (n.type === 'session' ? '600 13px "Noto Serif SC",serif' : '500 11px "Noto Sans SC",sans-serif');
        ctx.fillStyle = '#2a231c';
        ctx.textAlign = 'center';
        ctx.fillText(n.name.length > 12 ? n.name.slice(0, 12) + '…' : n.name, n.x, n.y + n.r + 14);
      }
    });
  }

  function loop() { if (!running) return; tick(); draw(); raf = requestAnimationFrame(loop); }
  function start() { if (running) return; running = true; loop(); }
  function stop() { running = false; if (raf) cancelAnimationFrame(raf); raf = null; }
  function highlight(id) { focusId = id; }
  function clearHighlight() { focusId = null; }

  function findNode(mx, my) {
    for (let i = nodes.length - 1; i >= 0; i--) {
      const n = nodes[i];
      const dx = mx - n.x, dy = my - n.y;
      if (dx * dx + dy * dy <= (n.r + 6) * (n.r + 6)) return n;
    }
    return null;
  }
  function getPos(e) {
    const rect = canvas.getBoundingClientRect();
    return { x: e.clientX - rect.left, y: e.clientY - rect.top };
  }

  canvas.addEventListener('mousemove', e => {
    const p = getPos(e);
    if (dragging) { dragging.x = p.x; dragging.y = p.y; return; }
    const n = findNode(p.x, p.y);
    hovered = n;
    canvas.style.cursor = n ? 'pointer' : 'grab';
    if (n) {
      tooltip.innerHTML = `<div class="tt-type">${TYPE_LABEL[n.type] || n.type}</div><div class="tt-id">${esc(n.id || '—')}</div><div class="tt-sum">${esc(n.summary || '（无摘要）')}</div>`;
      tooltip.style.left = (e.clientX + 16) + 'px';
      tooltip.style.top = (e.clientY + 16) + 'px';
      tooltip.classList.add('show');
    } else tooltip.classList.remove('show');
  });
  canvas.addEventListener('mouseleave', () => { tooltip.classList.remove('show'); hovered = null; });
  canvas.addEventListener('mousedown', e => {
    const p = getPos(e);
    const n = findNode(p.x, p.y);
    if (n) { dragging = n; n.fixed = true; }
  });
  window.addEventListener('mouseup', () => { if (dragging) { dragging.fixed = false; dragging = null; } });
  canvas.addEventListener('click', e => {
    const p = getPos(e);
    const n = findNode(p.x, p.y);
    if (n) onNodeClick(n);
  });

  return { setData, start, stop, resize, highlight, clearHighlight };
}

function openNodeModal(node) {
  $('#node-modal-type').textContent = TYPE_LABEL[node.type] || node.type;
  $('#node-modal-title').textContent = node.name || node.id || '节点';
  const body = $('#node-modal-body');

  let html = `<dl class="kv"><dt>ID</dt><dd>${esc(node.id || '—')}</dd><dt>类型</dt><dd>${esc(node.type)}</dd>`;
  if (node.source) html += `<dt>来源</dt><dd>${esc(node.source)}</dd>`;
  html += `<dt>摘要</dt><dd>${esc(node.summary || '—')}</dd></dl>`;

  if (node.type === 'document') {
    const doc = allDocs.find(d => d.doc_id === node.id);
    if (doc) {
      const topics = (doc.topic || doc.topics || []);
      html += `<h5>主题 / 关键词</h5><div class="tag-row">${topics.map(t => `<span class="chip topic">${esc(t)}</span>`).join('')}${(doc.keywords || []).map(t => `<span class="chip keyword">${esc(t)}</span>`).join('')}</div>`;
      html += `<h5>情绪</h5><p>${esc(emotionStr(doc.emotion))}</p>`;
      if (doc.doc_type === 'weekly') {
        html += `<h5>problem · 问题</h5><pre>${esc(doc.problem || '—')}</pre>`;
        html += `<h5>analysis · 分析</h5><pre>${esc(doc.analysis || '—')}</pre>`;
        html += `<h5>solution · 方案</h5><pre>${esc(doc.solution || '—')}</pre>`;
      } else {
        html += `<h5>正文</h5><pre>${esc(doc.content || '—')}</pre>`;
      }
    }
  } else if (node.type === 'memory') {
    const mem = allMemories.find(m => m.id === node.id);
    if (mem) {
      html += `<h5>时间</h5><p>${esc(mem.start_time || '—')} ~ ${esc(mem.end_time || '—')}</p>`;
      html += `<h5>主题 / 关键词</h5><div class="tag-row">${(mem.topics || []).map(t => `<span class="chip topic">${esc(t)}</span>`).join('')}${(mem.keywords || []).map(t => `<span class="chip keyword">${esc(t)}</span>`).join('')}</div>`;
      html += `<h5>情绪</h5><p>${esc(emotionStr(mem.emotion))}</p>`;
      if (mem.insights && mem.insights.length) html += `<h5>核心洞察</h5><pre>${esc(mem.insights.join('；'))}</pre>`;
      html += `<h5>引用文档</h5><pre>${esc((mem.referenced_documents || []).join('、') || '无')}</pre>`;
    }
  } else if (node.type === 'session') {
    html += `<h5>当前会话</h5><p>${sessionState && sessionState.full_chat_history ? '已有 ' + sessionState.full_chat_history.length + ' 条消息' : '暂无对话'}</p>`;
    if (sessionState && sessionState.referenced_doc_ids) {
      html += `<h5>引用文档</h5><pre>${esc([...sessionState.referenced_doc_ids].join('、') || '无')}</pre>`;
    }
  } else if (node.type === 'reason') {
    html += `<h5>引导问答</h5><pre>${esc(node.summary || '—')}</pre>`;
  }

  body.innerHTML = html;
  $('#node-modal').classList.add('show');
}

function bindNodeModal() {
  $('#node-modal-close').addEventListener('click', () => $('#node-modal').classList.remove('show'));
  $('#node-modal').addEventListener('click', e => { if (e.target === $('#node-modal')) $('#node-modal').classList.remove('show'); });
}

// ================= 流程日志 =================
let traceSignatures = new Set();
let latestTrace = null;
let traceVersion = null;

function bindTrace() {
  $('#btn-trace-refresh').addEventListener('click', loadTraceAll);
  const clearBtn = $('#btn-trace-clear');
  if (clearBtn) clearBtn.addEventListener('click', clearTraceView);
  startTraceStream();
}

/** 清空页面上的实时日志列表（只影响前端视图，不清后端日志） */
function clearTraceView() {
  traceSignatures = new Set();
  latestTrace = null;
  updateLatestTrace();
  const list = $('#trace-list');
  if (list) list.querySelectorAll('.trace-item').forEach(el => el.remove());
  const empty = $('#trace-empty');
  if (empty) empty.style.display = 'block';
}

/** 后端 clear_trace（版本号变化）后重置视图游标，保证新日志必然完整显示 */
function resetTraceViewForVersion(version) {
  traceVersion = version;
  clearTraceView();
}

async function loadTraceAll() {
  try {
    const payload = await apiFetch(API.traceAll);
    const logs = Array.isArray(payload) ? payload : ((payload && Array.isArray(payload.logs)) ? payload.logs : []);
    if (payload && !Array.isArray(payload) && payload.version !== undefined) traceVersion = payload.version;
    traceSignatures = new Set();
    latestTrace = null;
    updateLatestTrace();
    $('#trace-list').querySelectorAll('.trace-item').forEach(el => el.remove());
    if (!logs.length) { $('#trace-empty').style.display = 'block'; }
    addTrace(logs);
  } catch (e) { toast('日志加载失败：' + e.message, 'err'); }
}

function startTraceStream() {
  try {
    const es = new EventSource(API_BASE + API.traceStream);
    es.onmessage = (ev) => {
      try {
        const payload = JSON.parse(ev.data);
        const items = Array.isArray(payload) ? payload : (payload && Array.isArray(payload.logs) ? payload.logs : []);
        if (payload && !Array.isArray(payload) && payload.version !== undefined) {
          // 版本号变化 = 后端已开启新一轮日志（clear_trace）：先重置视图，避免旧条目占位导致「显示不全」
          if (traceVersion !== null && payload.version !== traceVersion) resetTraceViewForVersion(payload.version);
          else traceVersion = payload.version;
        }
        addTrace(items);
      } catch (e) { /* ignore */ }
    };
    es.onerror = () => {
      $('#trace-status').innerHTML = '<span class="conn-dot off"></span>SSE 已断开（自动重连）';
    };
    es.onopen = () => {
      $('#trace-status').innerHTML = '<span class="conn-dot on"></span>SSE 监听中';
    };
  } catch (e) { console.warn('trace stream failed', e); }
}

function addTrace(items) {
  if (!items || !items.length) return;
  const list = $('#trace-list');
  let added = 0;
  items.forEach(item => {
    const sig = item.timestamp + '_' + item.stage + '_' + item.label + '_' + JSON.stringify(item.content || {});
    if (traceSignatures.has(sig)) return;
    traceSignatures.add(sig);
    list.appendChild(buildTraceItem(item));
    latestTrace = item;
    added++;
  });
  if (added) {
    $('#trace-empty').style.display = 'none';
    list.scrollTop = list.scrollHeight;
    updateLatestTrace();
  }
}

function updateLatestTrace() {
  const el = $('#graph-latest');
  if (!el) return;
  if (!latestTrace) {
    el.innerHTML = '<span class="gl-empty">暂无运行进度</span>';
    return;
  }
  const stage = latestTrace.stage || 'unknown';
  el.innerHTML = `
    <span class="gl-stage stage-${esc(stage)}">${esc(stage)}</span>
    <span class="gl-label">${esc(latestTrace.label || '')}</span>`;
}

function renderTraceContent(content) {
  if (!content || typeof content !== 'object' || !Object.keys(content).length) return '';
  const rows = Object.keys(content).map(k => {
    const v = content[k];
    const isComplex = (v !== null && typeof v === 'object');
    const rendered = isComplex
      ? `<pre class="trace-json">${esc(JSON.stringify(v, null, 2))}</pre>`
      : `<span class="trace-val">${esc(v)}</span>`;
    return `<div class="trace-kv-row"><span class="trace-k">${esc(k)}</span>${rendered}</div>`;
  }).join('');
  return `<div class="trace-kv">${rows}</div>`;
}

function buildTraceItem(item) {
  const el = document.createElement('div');
  el.className = 'trace-item' + (item.is_error ? ' error' : '');
  const stage = item.stage || 'unknown';
  const hasDetail = item.is_error || (item.content && Object.keys(item.content).length > 0);

  el.innerHTML = `
    <span class="trace-stage stage-${esc(stage)}">${esc(stage)}</span>
    <div class="trace-body">
      <div class="trace-head">
        <span class="trace-caret">▸</span>
        <span class="trace-label">${esc(item.label || '')}</span>
        <span class="trace-time">${fmtTime(item.timestamp)}</span>
      </div>
      <div class="trace-content">
        ${item.is_error ? `<pre class="trace-err">${esc(item.error_msg || '')}</pre>` : ''}
        ${renderTraceContent(item.content)}
      </div>
    </div>`;

  if (hasDetail) {
    el.classList.add('expandable');
    el.querySelector('.trace-head').addEventListener('click', () => el.classList.toggle('open'));
  }
  if (item.is_error) el.classList.add('open');
  return el;
}

// ================= 检索调试 =================
const RD_STAGES = [
  { name: 'dense', label: 'Dense 向量召回', desc: '语义向量相似度召回，擅长捕捉同义与抽象表达' },
  { name: 'bm25', label: 'BM25 关键词召回', desc: 'jieba 分词 + 主题/关键词倒排，精确匹配词面' },
  { name: 'rrf', label: 'RRF 倒数排名融合', desc: '按倒数排名融合多路召回，对齐不同链路的排名' },
  { name: 'rerank', label: 'Cross-Encoder 重排', desc: '交叉编码器精排上游候选，并按阈值过滤低分' },
];
const RD_FALLBACK_DEFAULTS = { raw_top_k: 6, final_top_k: 3, rrf_k: 60, score_threshold: 0.08 };
const RD_STAGE_LABEL = { optimize_prompt: '查询优化' };

let rdMeta = null;
let rdDocs = [];
let rdDocTypes = { daily: 0, weekly: 0 };
let rdDocTotal = 0;
let rdRunning = false;
let rdParamsTouched = false;

// ---- 开关卡片（默认值优先取 /retrieval/meta） ----
function rdStageDefs() {
  const fromMeta = (rdMeta && Array.isArray(rdMeta.stages)) ? rdMeta.stages : [];
  const byName = {};
  fromMeta.forEach(s => { if (s && s.name) byName[String(s.name)] = s; });
  return RD_STAGES.map(def => {
    const s = byName[def.name] || {};
    const metaLabel = s.label ? String(s.label) : '';
    return {
      name: def.name,
      label: def.label,                                             // 契约 §4 约定的开关名称
      alias: (metaLabel && metaLabel !== def.label) ? metaLabel : '',  // meta 中的阶段别名
      desc: s.desc || def.desc,                                     // 说明文案优先取 meta
      enabled: (typeof s.enabled === 'boolean') ? s.enabled : true,
    };
  });
}

function rdFlags() {
  const flags = {};
  $$('#rd-switches input[data-rd-stage]').forEach(cb => { flags[cb.dataset.rdStage] = !!cb.checked; });
  return flags;
}

function renderRetrievalSwitches() {
  const box = $('#rd-switches');
  if (!box) return;
  const prev = rdFlags();
  const hasPrev = Object.keys(prev).length > 0;
  box.innerHTML = rdStageDefs().map(s => {
    const on = (hasPrev && (s.name in prev)) ? prev[s.name] : s.enabled;
    return `<label class="rd-switch${on ? ' on' : ''}" data-stage="${esc(s.name)}" title="${esc(s.alias ? s.alias + ' · ' : '')}${esc(s.desc || '')}">
      <input type="checkbox" data-rd-stage="${esc(s.name)}" ${on ? 'checked' : ''} />
      <span class="rd-switch-body">
        <span class="rd-switch-name">${esc(s.label)}${s.alias ? `<em class="rd-switch-alias">${esc(s.alias)}</em>` : ''}</span>
        <span class="rd-switch-desc">${esc(s.desc || '')}</span>
      </span>
      <span class="rd-switch-mark">✓</span>
    </label>`;
  }).join('');
  $$('#rd-switches input[data-rd-stage]').forEach(cb => {
    cb.addEventListener('change', () => {
      const card = cb.closest('.rd-switch');
      if (card) card.classList.toggle('on', cb.checked);
    });
  });
}

function rdNum(sel, fallback, min, max) {
  const el = $(sel);
  const raw = el ? String(el.value).trim() : '';
  if (raw === '') return fallback;
  let n = parseInt(raw, 10);
  if (!isFinite(n)) return fallback;
  if (min !== undefined) n = Math.max(min, n);
  if (max !== undefined) n = Math.min(max, n);
  return n;
}

function rdThreshold() {
  const el = $('#rd-score-threshold');
  const raw = el ? String(el.value).trim() : '';
  if (raw === '') return null;
  const n = Number(raw);
  if (!isFinite(n)) return null;
  return Math.min(1, Math.max(0, n));
}

async function loadRetrievalMeta() {
  try {
    const data = await apiFetch(API.retrievalMeta);
    rdMeta = (data && typeof data === 'object') ? data : null;
  } catch (e) {
    console.warn('retrieval meta load failed', e);
    rdMeta = null;
  }
  const d = (rdMeta && rdMeta.defaults && typeof rdMeta.defaults === 'object') ? rdMeta.defaults : {};
  if (!rdParamsTouched) {
    const setVal = (sel, val) => { const el = $(sel); if (el && val !== undefined && val !== null) el.value = String(val); };
    setVal('#rd-raw-topk', d.raw_top_k != null ? d.raw_top_k : RD_FALLBACK_DEFAULTS.raw_top_k);
    setVal('#rd-final-topk', d.final_top_k != null ? d.final_top_k : RD_FALLBACK_DEFAULTS.final_top_k);
    setVal('#rd-rrf-k', d.rrf_k != null ? d.rrf_k : RD_FALLBACK_DEFAULTS.rrf_k);
    const thr = d.score_threshold != null ? d.score_threshold : RD_FALLBACK_DEFAULTS.score_threshold;
    const thrEl = $('#rd-score-threshold');
    if (thrEl && !thrEl.value) thrEl.placeholder = '空 = 默认 ' + thr;
  }
  renderRetrievalSwitches();
}

// ---- 全部文档 ----
async function loadRetrievalDocs() {
  const box = $('#rd-doc-list');
  try {
    const data = await apiFetch(API.retrievalDocs);
    const docs = (data && Array.isArray(data.documents)) ? data.documents : (Array.isArray(data) ? data : []);
    rdDocs = docs.filter(d => d && typeof d === 'object');
    const counts = (data && data.doc_types && typeof data.doc_types === 'object') ? data.doc_types : {};
    const daily = rdDocs.filter(x => x.doc_type === 'daily').length;
    const weekly = rdDocs.filter(x => x.doc_type === 'weekly').length;
    rdDocTypes = { daily: Number(counts.daily) || daily, weekly: Number(counts.weekly) || weekly };
    rdDocTotal = (data && data.total != null && isFinite(Number(data.total))) ? Number(data.total) : rdDocs.length;
    renderRetrievalDocs();
    return true;
  } catch (e) {
    console.warn('retrieval documents load failed', e);
    if (box) box.innerHTML = '<div class="rd-empty rd-err">文档加载失败：' + esc(e.message) + '</div>';
    return false;
  }
}

function rdFilteredDocs() {
  const kwEl = $('#rd-doc-keyword');
  const typeEl = $('#rd-doc-type');
  const kw = (kwEl ? kwEl.value : '').trim().toLowerCase();
  const type = typeEl ? typeEl.value : '';
  return rdDocs.filter(d => {
    if (type && d.doc_type !== type) return false;
    if (!kw) return true;
    const topics = Array.isArray(d.topic) ? d.topic : (Array.isArray(d.topics) ? d.topics : []);
    const hay = [d.doc_id, d.title, d.summary, d.content, d.problem, d.analysis, d.solution,
      topics.join(' '), (Array.isArray(d.keywords) ? d.keywords.join(' ') : '')]
      .filter(Boolean).join(' ').toLowerCase();
    return hay.indexOf(kw) >= 0;
  });
}

function rdDocCardHTML(d) {
  const topics = Array.isArray(d.topic) ? d.topic : (Array.isArray(d.topics) ? d.topics : []);
  const keywords = Array.isArray(d.keywords) ? d.keywords : [];
  return `
    <div class="rd-doc-top">
      <span class="rd-doc-title">${esc(d.title || d.doc_id || '无标题')}</span>
      ${d.doc_type ? `<span class="badge ${esc(d.doc_type)}">${esc(d.doc_type)}</span>` : ''}
      ${d.date ? `<span class="badge date">${esc(d.date)}</span>` : ''}
      <span class="rd-doc-toggle">展开详情</span>
    </div>
    <div class="rd-doc-sum">${esc(d.summary || '（无摘要）')}</div>
    <div class="rd-doc-meta">
      ${topics.map(t => `<span class="chip topic">${esc(t)}</span>`).join('')}
      ${keywords.map(t => `<span class="chip keyword">${esc(t)}</span>`).join('')}
      ${d.emotion ? `<span class="chip emotion">${esc(emotionStr(d.emotion))}</span>` : ''}
    </div>
    <div class="rd-doc-detail"><div class="rd-empty">展开后加载正文…</div></div>`;
}

function rdDocDetailHTML(d) {
  const blocks = [];
  if (d.doc_type === 'weekly') {
    blocks.push(['problem · 问题', d.problem]);
    blocks.push(['analysis · 分析', d.analysis]);
    blocks.push(['solution · 方案', d.solution]);
    if (d.content) blocks.push(['正文', d.content]);
  } else {
    blocks.push(['正文', d.content]);
  }
  let html = blocks.map(b => `<h5>${esc(b[0])}</h5><pre>${esc(b[1] || '—')}</pre>`).join('');
  html += `<h5>来源</h5><pre>${esc(d.relative_path || d.source || d.knowledge_path || '—')}</pre>`;
  return html;
}

function renderRetrievalDocs() {
  const box = $('#rd-doc-list');
  if (!box) return;
  const list = rdFilteredDocs();
  const stats = $('#rd-doc-stats');
  if (stats) {
    let text = '总数 ' + rdDocTotal + ' · daily ' + rdDocTypes.daily + ' · weekly ' + rdDocTypes.weekly;
    if (rdDocs.length && list.length !== rdDocs.length) text += ' · 当前 ' + list.length;
    stats.textContent = text;
  }
  if (!rdDocs.length) {
    box.innerHTML = '<div class="rd-empty">暂无文档 · 可点击「刷新」重试</div>';
    return;
  }
  if (!list.length) {
    box.innerHTML = '<div class="rd-empty">没有匹配的文档</div>';
    return;
  }
  box.innerHTML = '';
  list.forEach((d, i) => {
    const card = document.createElement('div');
    card.className = 'rd-doc';
    card.dataset.docId = String(d.doc_id || '');
    card.style.animationDelay = (i * 20) + 'ms';
    card.innerHTML = rdDocCardHTML(d);
    card.addEventListener('click', () => openRdDocCard(card, d));
    box.appendChild(card);
  });
}

async function openRdDocCard(card, doc) {
  const open = card.classList.toggle('open');
  const toggle = card.querySelector('.rd-doc-toggle');
  if (toggle) toggle.textContent = open ? '收起详情' : '展开详情';
  if (!open || card.dataset.loaded === '1') return;
  const detail = card.querySelector('.rd-doc-detail');
  if (!detail) return;
  detail.innerHTML = '<div class="rd-empty">加载正文…</div>';
  try {
    const data = await apiFetch(API.retrievalDocs + '/' + encodeURIComponent(doc.doc_id));
    const full = (data && data.document && typeof data.document === 'object') ? data.document : doc;
    const idx = rdDocs.findIndex(x => String(x.doc_id) === String(doc.doc_id));
    if (idx >= 0) rdDocs[idx] = Object.assign({}, rdDocs[idx], full);
    card.dataset.loaded = '1';
    detail.innerHTML = rdDocDetailHTML(full);
  } catch (e) {
    detail.innerHTML = '<div class="rd-empty rd-err">详情加载失败：' + esc(e.message) + '</div>';
    toast('文档详情加载失败：' + e.message, 'err');
  }
}

// ---- 运行检索 ----
function rdSetRunning(running) {
  rdRunning = running;
  [$('#rd-run'), $('#rd-run-top')].forEach(btn => {
    if (!btn) return;
    if (btn.dataset.baseLabel === undefined) btn.dataset.baseLabel = btn.textContent;
    btn.disabled = running;
    btn.textContent = running ? '检索中…' : btn.dataset.baseLabel;
  });
  if (running) {
    const hint = $('#rd-result-hint');
    if (hint) hint.textContent = '检索中…';
    const box = $('#rd-stages');
    if (box) box.innerHTML = '<div class="rd-empty">正在执行检索链路 · 首次加载本地模型可能较慢…</div>';
    const finalHint = $('#rd-final-hint');
    if (finalHint) finalHint.textContent = '检索中…';
    const finalBox = $('#rd-final-list');
    if (finalBox) finalBox.innerHTML = '<div class="rd-empty">等待最终结果…</div>';
  }
}

async function runRetrievalDebug() {
  if (rdRunning) return;
  const promptEl = $('#rd-prompt');
  const query = promptEl ? String(promptEl.value).trim() : '';
  if (!query) { toast('请先填写 prompt', 'err'); if (promptEl) promptEl.focus(); return; }
  const flags = rdFlags();
  if (!flags.dense && !flags.bm25 && !flags.rrf && !flags.rerank) { toast('至少选择一种检索方式', 'err'); return; }

  const payload = {
    query,
    dense: !!flags.dense,
    bm25: !!flags.bm25,
    rrf: !!flags.rrf,
    rerank: !!flags.rerank,
    raw_top_k: rdNum('#rd-raw-topk', RD_FALLBACK_DEFAULTS.raw_top_k, 1, 50),
    final_top_k: rdNum('#rd-final-topk', RD_FALLBACK_DEFAULTS.final_top_k, 1, 50),
    rrf_k: rdNum('#rd-rrf-k', RD_FALLBACK_DEFAULTS.rrf_k, 1, 1000),
    score_threshold: rdThreshold(),
  };

  rdSetRunning(true);
  try {
    const data = await apiFetch(API.retrievalDebug, { method: 'POST', body: payload });
    const d = (data && typeof data === 'object') ? data : {};
    renderRetrievalRun(d);
    const final = (d.final && typeof d.final === 'object') ? d.final : {};
    const count = (final.count != null) ? final.count : 0;
    toast('检索完成 · ' + (d.latency_ms != null ? d.latency_ms + ' ms · ' : '') + '最终 ' + count + ' 条', 'ok');
  } catch (e) {
    toast('检索失败：' + e.message, 'err');
    const box = $('#rd-stages');
    if (box) box.innerHTML = '<div class="rd-empty rd-err">检索失败：' + esc(e.message) + '</div>';
    const finalBox = $('#rd-final-list');
    if (finalBox) finalBox.innerHTML = '<div class="rd-empty rd-err">检索失败，未产出最终结果</div>';
    const finalHint = $('#rd-final-hint');
    if (finalHint) finalHint.textContent = '运行失败';
    const hint = $('#rd-result-hint');
    if (hint) hint.textContent = '运行失败';
  } finally {
    rdSetRunning(false);
  }
}

// ---- 渲染：结果 / 摘要 / 日志 ----
function rdFormatScore(v) {
  const n = Number(v);
  return isFinite(n) ? n.toFixed(4) : '—';
}

function rdShortId(id) {
  const s = String(id || '');
  return (s.length > 12) ? (s.slice(0, 8) + '…') : s;
}

function rdTypeLabel(t) {
  const s = String(t || '');
  return s === 'daily' ? 'daily · 经验' : (s === 'weekly' ? 'weekly · 原理' : s);
}

/** 最终结果卡片：最终 Top-K 的排名、分数、类型、日期与摘要 */
function rdFinalCardHTML(item, idx) {
  const it = (item && typeof item === 'object') ? item : {};
  const doc = (it.doc && typeof it.doc === 'object') ? it.doc : null;
  const docId = it.doc_id != null ? String(it.doc_id) : (doc && doc.doc_id != null ? String(doc.doc_id) : '');
  const rank = it.rank != null ? it.rank : (idx + 1);
  const type = doc && doc.doc_type ? String(doc.doc_type) : '';
  return `<div class="rd-final-card">
    <div class="rd-final-no">#${esc(rank)}</div>
    <div class="rd-final-body">
      <div class="rd-final-top">
        <span class="rd-final-title">${esc((doc && doc.title) || docId || '—')}</span>
        ${type ? `<span class="badge ${esc(type)}" title="${esc(rdTypeLabel(type))}">${esc(type)}</span>` : ''}
        ${doc && doc.date ? `<span class="badge date">${esc(doc.date)}</span>` : ''}
        <span class="rd-final-score">${esc(rdFormatScore(it.score))}</span>
      </div>
      <div class="rd-final-sum">${esc((doc && doc.summary) || '（无摘要）')}</div>
      ${docId ? `<div class="rd-final-id" title="${esc(docId)}">${esc(rdShortId(docId))}</div>` : ''}
    </div>
  </div>`;
}

/** 渲染最终检索结果面板（运行摘要来自 data.final / data.final_summary） */
function renderRetrievalFinal(d) {
  const final = (d.final && typeof d.final === 'object') ? d.final : {};
  const summary = (d.final_summary && typeof d.final_summary === 'object') ? d.final_summary : {};
  const list = Array.isArray(final.results) ? final.results : [];
  const ids = Array.isArray(final.doc_ids) ? final.doc_ids : [];
  const count = (final.count != null) ? final.count : list.length;

  const hint = $('#rd-final-hint');
  if (hint) {
    const source = final.source || '—';
    const label = summary.label || '最终结果';
    hint.textContent = '来源 ' + source + ' · ' + count + ' 条 · ' + label;
  }

  const box = $('#rd-final-list');
  if (!box) return;
  if (!list.length) {
    if (ids.length) {
      box.innerHTML = `<div class="rd-final-ids">最终 doc_ids：${ids.map(id => `<code>${esc(rdShortId(id))}</code>`).join(' ')}</div>`;
    } else {
      box.innerHTML = '<div class="rd-empty">本次没有最终结果（候选被阈值过滤或未命中）</div>';
    }
    return;
  }
  box.innerHTML = list.map((it, i) => rdFinalCardHTML(it, i)).join('');
}

function rdStageCardHTML(stage, idSet) {
  const s = (stage && typeof stage === 'object') ? stage : {};
  const name = s.name ? String(s.name) : 'stage';
  const label = s.label || RD_STAGE_LABEL[name] || name;
  const results = Array.isArray(s.results) ? s.results : [];
  const latency = (s.latency_ms != null && isFinite(Number(s.latency_ms))) ? Number(s.latency_ms).toFixed(1) + ' ms' : '— ms';

  const rows = results.map((r, i) => {
    const item = (r && typeof r === 'object') ? r : {};
    const rank = item.rank != null ? item.rank : (i + 1);
    const doc = (item.doc && typeof item.doc === 'object') ? item.doc : null;
    const docId = item.doc_id != null ? String(item.doc_id) : (doc && doc.doc_id != null ? String(doc.doc_id) : '');
    const isFinal = !!docId && idSet.has(docId);
    const topics = doc ? (Array.isArray(doc.topic) ? doc.topic : (Array.isArray(doc.topics) ? doc.topics : [])) : [];
    const type = doc && doc.doc_type ? String(doc.doc_type) : '';
    return `<div class="rd-rank${isFinal ? ' is-final' : ''}">
      <span class="rd-rank-no">#${esc(rank)}</span>
      <span class="rd-rank-score" title="阶段分数">${esc(rdFormatScore(item.score))}</span>
      <div class="rd-rank-body">
        <div class="rd-rank-head">
          <span class="rd-rank-title">${esc((doc && doc.title) || docId || '—')}</span>
          ${type ? `<span class="badge ${esc(type)}">${esc(type)}</span>` : ''}
          ${isFinal ? '<span class="rd-final-badge">最终</span>' : ''}
        </div>
        <div class="rd-rank-sum">${esc((doc && doc.summary) || '（无摘要）')}</div>
        <div class="rd-rank-meta">
          ${topics.slice(0, 3).map(t => `<span class="chip topic">${esc(t)}</span>`).join('')}
          ${docId ? `<span class="rd-rank-id" title="${esc(docId)}">${esc(rdShortId(docId))}</span>` : ''}
        </div>
      </div>
    </div>`;
  }).join('');

  return `<div class="rd-stage open">
    <div class="rd-stage-head">
      <span class="rd-caret">▸</span>
      <span class="rd-stage-name">${esc(label)}</span>
      <span class="rd-stage-tag">${esc(name)}</span>
      <span class="rd-stage-meta">${esc(latency)}</span>
      <span class="rd-stage-count">${results.length} 候选</span>
    </div>
    <div class="rd-stage-body">
      ${rows ? `<div class="rd-rank-list">${rows}</div>` : '<div class="rd-empty">该阶段无排名输出（结构化信息见检索日志）</div>'}
    </div>
  </div>`;
}

function renderRetrievalStageCards(stages, idSet) {
  const box = $('#rd-stages');
  if (!box) return;
  if (!stages.length) {
    box.innerHTML = '<div class="rd-empty">本次运行未返回任何阶段结果</div>';
    return;
  }
  box.innerHTML = stages.map(s => rdStageCardHTML(s, idSet)).join('');
  $$('#rd-stages .rd-stage-head').forEach(head => {
    head.addEventListener('click', () => {
      const card = head.closest('.rd-stage');
      if (card) card.classList.toggle('open');
    });
  });
}

function rdChips(list, cls) {
  const arr = Array.isArray(list) ? list.filter(x => x !== null && x !== undefined && String(x) !== '') : [];
  if (!arr.length) return '<span class="rd-muted">—</span>';
  return arr.map(t => `<span class="chip ${cls}">${esc(t)}</span>`).join('');
}

function renderRetrievalSummary(d) {
  const box = $('#rd-log-summary');
  if (!box) return;
  const pipeline = Array.isArray(d.enabled_pipeline) ? d.enabled_pipeline : [];
  const opt = (d.optimized && typeof d.optimized === 'object') ? d.optimized : {};
  const final = (d.final && typeof d.final === 'object') ? d.final : {};
  const pipeHTML = pipeline.length
    ? pipeline.map((s, i) => `${i ? '<span class="rd-pipe-arrow">→</span>' : ''}<span class="rd-pipe-step">${esc(s)}</span>`).join('')
    : '<span class="rd-muted">—</span>';
  const rows = [
    ['启用链路', `<span class="rd-pipe">${pipeHTML}</span>`],
    ['search_query', `<span>${esc(opt.search_query || '—')}</span>`],
    ['match_topics', rdChips(opt.match_topics, 'topic')],
    ['keywords', rdChips(opt.keywords, 'keyword')],
    ['最终来源', `<span class="rd-pipe-step">${esc(final.source || '—')}</span><span class="rd-muted">${final.count != null ? ' · ' + esc(final.count) + ' 条' : ''}</span>`],
  ];
  box.innerHTML = rows.map(r => `<div class="rd-sum-row"><span class="rd-sum-k">${esc(r[0])}</span><span class="rd-sum-v">${r[1]}</span></div>`).join('');
}

function rdLogTime(ts) {
  if (ts === null || ts === undefined || ts === '') return '—';
  let date;
  if (typeof ts === 'number' || /^\d+(\.\d+)?$/.test(String(ts))) date = new Date(Number(ts) * 1000);
  else date = new Date(ts);
  if (isNaN(date.getTime())) return '—';
  return date.toLocaleTimeString('zh-CN', { hour12: false });
}

function rdRenderLogContent(content) {
  if (!content || typeof content !== 'object' || !Object.keys(content).length) return '';
  const rows = Object.keys(content).map(k => {
    const v = content[k];
    const complex = (v !== null && typeof v === 'object');
    const rendered = complex
      ? `<pre class="rd-log-json">${esc(JSON.stringify(v, null, 2))}</pre>`
      : `<span class="rd-log-val">${esc(v)}</span>`;
    return `<div class="rd-log-kv-row"><span class="rd-log-k">${esc(k)}</span>${rendered}</div>`;
  }).join('');
  return `<div class="rd-log-kv">${rows}</div>`;
}

function renderRetrievalLogs(logs) {
  const box = $('#rd-logs');
  const hint = $('#rd-log-hint');
  if (hint) hint.textContent = logs.length ? (logs.length + ' 条') : '—';
  if (!box) return;
  if (!logs.length) { box.innerHTML = '<div class="rd-empty">本次运行没有返回日志</div>'; return; }
  box.innerHTML = '';
  logs.forEach(raw => {
    const item = (raw && typeof raw === 'object') ? raw : {};
    const stage = item.stage ? String(item.stage) : 'unknown';
    const content = (item.content && typeof item.content === 'object') ? item.content : null;
    const isError = !!item.is_error;
    const hasDetail = isError || !!(content && Object.keys(content).length);
    const el = document.createElement('div');
    el.className = 'rd-log' + (isError ? ' error' : '') + (hasDetail ? ' expandable' : '') + (isError ? ' open' : '');
    el.innerHTML = `
      <span class="trace-stage stage-${esc(stage)}">${esc(stage)}</span>
      <div class="rd-log-body">
        <div class="rd-log-head">
          <span class="rd-caret">▸</span>
          <span class="rd-log-label">${esc(item.label || '')}</span>
          <span class="rd-log-time">${esc(rdLogTime(item.timestamp))}</span>
        </div>
        <div class="rd-log-content">
          ${isError ? `<pre class="rd-log-err">${esc(item.error_msg || '未知错误')}</pre>` : ''}
          ${rdRenderLogContent(content)}
        </div>
      </div>`;
    if (hasDetail) el.querySelector('.rd-log-head').addEventListener('click', () => el.classList.toggle('open'));
    box.appendChild(el);
  });
}

function renderRetrievalRun(data) {
  const d = (data && typeof data === 'object') ? data : {};
  const final = (d.final && typeof d.final === 'object') ? d.final : {};
  const results = Array.isArray(final.results) ? final.results : [];
  const stages = Array.isArray(d.stages) ? d.stages : [];
  const logs = Array.isArray(d.logs) ? d.logs : [];

  const idSet = new Set();
  (Array.isArray(final.doc_ids) ? final.doc_ids : []).forEach(id => { if (id !== null && id !== undefined) idSet.add(String(id)); });
  results.forEach(r => { if (r && r.doc_id !== null && r.doc_id !== undefined) idSet.add(String(r.doc_id)); });

  const latencyEl = $('#rd-latency');
  if (latencyEl) latencyEl.textContent = (d.latency_ms != null && isFinite(Number(d.latency_ms))) ? Number(d.latency_ms).toFixed(1) : '—';
  const countEl = $('#rd-final-count');
  if (countEl) countEl.textContent = String(final.count != null ? final.count : results.length);
  const hint = $('#rd-result-hint');
  if (hint) hint.textContent = stages.length ? ('已运行 ' + stages.length + ' 阶段' + (final.source ? ' · 最终来源 ' + final.source : '')) : '尚未运行';
  const pipeHint = $('#rd-pipeline-hint');
  if (pipeHint) pipeHint.textContent = (Array.isArray(d.enabled_pipeline) && d.enabled_pipeline.length) ? ('链路 · ' + d.enabled_pipeline.join(' → ')) : '尚未运行';

  renderRetrievalFinal(d);
  renderRetrievalStageCards(stages, idSet);
  renderRetrievalSummary(d);
  renderRetrievalLogs(logs);
}

function bindRetrieval() {
  const run = () => runRetrievalDebug();
  const runBtn = $('#rd-run');
  const runTop = $('#rd-run-top');
  if (runBtn) runBtn.addEventListener('click', run);
  if (runTop) runTop.addEventListener('click', run);

  const prompt = $('#rd-prompt');
  if (prompt) {
    prompt.addEventListener('keydown', e => {
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); run(); }
    });
  }
  ['#rd-raw-topk', '#rd-final-topk', '#rd-rrf-k', '#rd-score-threshold'].forEach(sel => {
    const el = $(sel);
    if (el) el.addEventListener('input', () => { rdParamsTouched = true; });
  });

  const kw = $('#rd-doc-keyword');
  if (kw) kw.addEventListener('input', renderRetrievalDocs);
  const type = $('#rd-doc-type');
  if (type) type.addEventListener('change', renderRetrievalDocs);
  const refresh = $('#rd-doc-refresh');
  if (refresh) {
    refresh.addEventListener('click', async () => {
      refresh.disabled = true;
      const ok = await loadRetrievalDocs();
      refresh.disabled = false;
      toast(ok ? '文档列表已刷新' : '刷新失败，请检查后端接口', ok ? 'ok' : 'err');
    });
  }

  renderRetrievalSwitches();
}

// ================= 连接状态 =================
function setConn(on) {
  const dot = $('#conn-dot');
  dot.classList.remove('on', 'off');
  if (on) { dot.classList.add('on'); $('#conn-text').textContent = '后端已连接'; }
  else { dot.classList.add('off'); $('#conn-text').textContent = '后端未连接'; }
}

// ================= 初始化 =================
async function init() {
  bindNavigation();
  bindChat();
  bindModel();
  bindRecords();
  bindWriting();
  bindGraph();
  bindNodeModal();
  bindCitations();
  bindTrace();
  bindRetrieval();

  buildTopicCheckboxes('k-topic-checkboxes');
  buildTopicCheckboxes('m-topic-checkboxes');

  await Promise.allSettled([
    loadSessionState(),
    loadModels(),
    loadKnowledge(),
    loadMemory(),
    loadTraceAll(),
    loadRetrievalMeta(),
    loadRetrievalDocs(),
  ]);
  // 图谱在主对话视图内，直接加载
  loadGraph();
  renderDocs(allDocs);
}

document.addEventListener('DOMContentLoaded', init);
