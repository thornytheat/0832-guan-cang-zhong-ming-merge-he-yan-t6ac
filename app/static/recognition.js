import {request, element} from './client.js';

const STATUS_LABELS = {
  READY: '待签 · 核验合格',
  HELD: '暂缓 · 组内核验不合格',
  SUSPENDED: '暂缓 · 被互认冲突牵连',
};

const notice = document.querySelector('#notice');
const groupBody = document.querySelector('#group-rows tbody');
const conflictList = document.querySelector('#conflict-list');
const seq = document.querySelector('#seq');
let snapshotData = null;

function announce(text, failure = false) {
  notice.textContent = text;
  notice.dataset.failure = String(failure);
}

function signoffFor(gid) {
  return (snapshotData?.signoffs || []).find(row => row.gid === gid) || null;
}

function renderGroups() {
  groupBody.replaceChildren();
  const status = snapshotData?.status || {};
  for (const gid of Object.keys(status)) {
    const tr = document.createElement('tr');
    tr.insertCell().textContent = gid;
    const stateCell = tr.insertCell();
    stateCell.append(element('span', STATUS_LABELS[status[gid]] || status[gid],
      {class: 'badge', 'data-result': status[gid], title: status[gid]}));
    const issued = signoffFor(gid);
    tr.insertCell().textContent = issued
      ? `已签发 r${issued.revision}（基于事件 #${issued.base_seq}）` : '—';
    const actionCell = tr.insertCell();
    const button = element('button', '签发', {type: 'button', 'data-sign': gid});
    button.disabled = status[gid] !== 'READY';
    button.title = status[gid] === 'READY' ? '提交签发' : '当前状态不具备签发资格';
    button.addEventListener('click', () => {
      document.querySelector('#s-group').value = gid;
      document.querySelector('#s-revision').value = issued ? issued.revision : 0;
      document.querySelector('#s-note').focus();
    });
    actionCell.append(button);
    groupBody.append(tr);
  }
  if (!Object.keys(status).length) {
    groupBody.insertRow().insertCell().textContent = '尚无分组，请先登记';
  }
  seq.textContent = `事件序号 #${snapshotData?.sequence ?? 0}`;
}

function renderConflicts() {
  conflictList.replaceChildren();
  const conflicts = snapshotData?.conflicts || [];
  if (!conflicts.length) {
    conflictList.append(element('p', '暂无权威冲突。', {class: 'muted'}));
    return;
  }
  for (const conflict of conflicts) {
    const card = document.createElement('div');
    card.className = 'conflict-card';
    card.append(element('h3', `冲突：权威编号 ${conflict.authorities.join(' / ')}`));
    card.append(element('p', `牵连作者：${conflict.authors.join('、')}`));
    card.append(element('p', `互认证据：${conflict.claims.join('、')}`));
    const groups = [...new Set(conflict.authors.map(ref => ref.split('/')[0]))];
    card.append(element('p', `牵连分组（一并暂缓）：${groups.join('、')}`, {class: 'tainted'}));
    conflictList.append(card);
  }
}

function render(data) {
  snapshotData = data;
  renderGroups();
  renderConflicts();
}

async function refresh() {
  render(await request('/api/recognition'));
}

async function post(path, body) {
  const data = await request(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  });
  render(data);
}

// 事件类型切换时只显示相关字段。
const kindSelect = document.querySelector('#event-kind');
function toggleFields() {
  const kind = kindSelect.value;
  document.querySelectorAll('label[data-when]').forEach(label => {
    const visible = label.dataset.when.split(' ').includes(kind);
    label.hidden = !visible;
    label.querySelectorAll('input,select').forEach(field => { field.disabled = !visible; });
  });
}
kindSelect.addEventListener('change', toggleFields);
toggleFields();

function readEvent() {
  const kind = kindSelect.value;
  const group = document.querySelector('#f-group').value.trim();
  if (kind === 'group') {
    return {kind, group, headcount_ok: document.querySelector('#f-headcount').value === 'true'};
  }
  if (kind === 'authority') {
    return {kind, group, author: document.querySelector('#f-author').value.trim(),
            authority: Number(document.querySelector('#f-authority').value)};
  }
  if (kind === 'recognize') {
    return {kind, claim: document.querySelector('#f-claim').value.trim(), group,
            author: document.querySelector('#f-author').value.trim(),
            peer_group: document.querySelector('#f-peer-group').value.trim(),
            peer_author: document.querySelector('#f-peer-author').value.trim()};
  }
  return {kind, claim: document.querySelector('#f-claim').value.trim()};
}

document.querySelector('#event-form').addEventListener('submit', async event => {
  event.preventDefault();
  try {
    await post('/api/recognition/events', {events: [readEvent()]});
    announce('更正已入账，各组状态已重算');
  } catch (error) { announce(error.message, true); }
});

document.querySelector('#signoff-form').addEventListener('submit', async event => {
  event.preventDefault();
  const body = {
    group: document.querySelector('#s-group').value.trim(),
    revision: Number(document.querySelector('#s-revision').value),
    note: document.querySelector('#s-note').value,
  };
  try {
    await post('/api/recognition/signoffs', body);
    announce(`分组 ${body.group} 已签发`);
    event.target.reset();
    document.querySelector('#s-revision').value = 0;
  } catch (error) { announce(error.message, true); }
});

document.querySelector('#combo-form').addEventListener('submit', async event => {
  event.preventDefault();
  let events, signoffs;
  try {
    events = JSON.parse(document.querySelector('#c-events').value || '[]');
    signoffs = JSON.parse(document.querySelector('#c-signoffs').value || '[]');
  } catch {
    announce('JSON 格式不正确', true);
    return;
  }
  try {
    await post('/api/recognition/submissions', {events, signoffs});
    announce('同批提交完成：更正先入账，签发按重算结果处理');
  } catch (error) {
    announce(error.message, true);
    await refresh();
  }
});

refresh().then(() => announce('互认登记册已载入')).catch(error => announce(error.message, true));
