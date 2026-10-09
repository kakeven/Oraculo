const token = document.querySelector('meta[name="oraculo-token"]').content;
const labels = {ability: 'Habilidade', skill: 'Perícia', advantage: 'Vantagem', effect: 'Efeito', power_example: 'Exemplo de poder', modifier_extra: 'Extra', modifier_flaw: 'Falha'};
const state = {items: [], selected: null, category: 'all', view: 'pending', search: '', editing: false};
const el = id => document.getElementById(id);

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {'X-Oraculo-Token': token, ...(options.headers || {})},
  });
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || 'Não foi possível concluir a solicitação.');
  return payload;
}

function notice(message) {
  const node = el('notice');
  node.textContent = message;
  node.hidden = false;
  clearTimeout(notice.timer);
  notice.timer = setTimeout(() => { node.hidden = true; }, 4500);
}

function visibleItems() {
  const query = state.search.trim().toLocaleLowerCase('pt-BR');
  return state.items.filter(item =>
    (state.category === 'all' || item.type === state.category) &&
    (state.view === 'all' || item.state === (state.view === 'approved' ? 'approved' : 'needs_review')) &&
    (!query || item.name.toLocaleLowerCase('pt-BR').includes(query))
  );
}

function renderFilters() {
  const host = el('filters');
  host.replaceChildren();
  for (const [key, label] of [['all', 'Tudo'], ...Object.entries(labels)]) {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.classList.toggle('active', state.category === key);
    button.setAttribute('aria-pressed', state.category === key);
    button.addEventListener('click', () => { state.category = key; render(); });
    host.append(button);
  }
}

function renderList() {
  const list = el('item-list');
  list.replaceChildren();
  const items = visibleItems();
  el('list-count').textContent = `${items.length} ${items.length === 1 ? 'item' : 'itens'} nesta lista`;
  if (!items.length) {
    const empty = document.createElement('p');
    empty.className = 'list-count';
    empty.textContent = state.search ? 'Nenhum nome corresponde à busca.' : 'Nenhum item neste filtro.';
    list.append(empty);
  }
  for (const item of items) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'item-row';
    button.classList.toggle('active', state.selected?.id === item.id);
    button.setAttribute('role', 'listitem');
    const name = document.createElement('span');
    name.className = 'item-name';
    name.textContent = item.name;
    const meta = document.createElement('span');
    meta.className = 'item-meta';
    meta.textContent = `${labels[item.type]} · PDF p. ${item.page_start}${item.page_end !== item.page_start ? '–' + item.page_end : ''}${item.edited ? ' · editado' : ''}`;
    const status = document.createElement('span');
    status.className = 'item-status';
    status.classList.toggle('approved', item.state === 'approved');
    status.setAttribute('aria-label', item.state === 'approved' ? 'Aprovado' : 'Pendente');
    button.append(name, meta, status);
    button.addEventListener('click', () => selectItem(item.id));
    list.append(button);
  }
}

function renderProgress() {
  const approved = state.items.filter(item => item.state === 'approved').length;
  el('progress-label').textContent = `${approved} de ${state.items.length} aprovados`;
  el('progress-fill').style.width = `${state.items.length ? approved / state.items.length * 100 : 0}%`;
}

function renderDetail() {
  const item = state.selected;
  el('empty-state').hidden = !!item;
  el('document').hidden = !item;
  if (!item) return;
  el('item-category').textContent = `${labels[item.type]}${item.subtype ? ' · ' + item.subtype : ''}`;
  el('item-title').textContent = item.name;
  el('item-state').textContent = item.state === 'approved' ? 'Aprovado' : 'Pendente de revisão';
  el('item-state').classList.toggle('approved', item.state === 'approved');
  el('item-pages').textContent = `PDF p. ${item.page_start}${item.page_end !== item.page_start ? '–' + item.page_end : ''} · linhas ${item.line_start}–${item.line_end}`;
  el('pdf-link').href = `/source.pdf#page=${item.page_start}`;
  el('item-text').textContent = item.text;
  el('item-text').hidden = state.editing;
  el('editor').hidden = !state.editing;
  el('edited-badge').hidden = !item.edited;
  el('original-panel').hidden = !item.edited;
  el('original-text').textContent = item.original_text;
  el('edit').hidden = state.editing;
  el('restore').hidden = state.editing || !item.edited;
  el('approve').disabled = item.state === 'approved';
  el('reopen').disabled = item.state !== 'approved';
  el('approve').hidden = state.editing;
  el('reopen').hidden = state.editing;
  el('next').hidden = state.editing;
  el('decision-copy').textContent = item.state === 'approved'
    ? 'Aprovado para esta versão exata do texto. Você pode voltar o item para revisão.'
    : 'A aprovação fica vinculada a esta versão exata do trecho.';
}

function render() {
  renderFilters();
  document.querySelectorAll('[data-view]').forEach(button => {
    button.classList.toggle('active', button.dataset.view === state.view);
    button.setAttribute('aria-pressed', button.dataset.view === state.view);
  });
  renderList();
  renderProgress();
  renderDetail();
}

async function selectItem(id, scrollMobile = true) {
  if (state.editing && id !== state.selected?.id &&
      el('edit-text').value !== state.selected?.text &&
      !confirm('Descartar as alterações ainda não salvas?')) return;
  try {
    const item = await api(`/api/items/${encodeURIComponent(id)}`);
    state.selected = item;
    state.editing = false;
    render();
    document.querySelector('.reading-room').scrollTo(0, 0);
    if (scrollMobile && window.innerWidth <= 780) el('document').scrollIntoView({behavior: 'smooth'});
  } catch (error) { notice(error.message); }
}

function startEdit() {
  if (!state.selected) return;
  state.editing = true;
  renderDetail();
  el('edit-text').value = state.selected.text;
  el('edit-text').focus();
}

function cancelEdit() {
  state.editing = false;
  renderDetail();
}

async function saveText(text) {
  const item = state.selected;
  if (!item) return;
  el('save-edit').disabled = true;
  el('restore').disabled = true;
  try {
    const updated = await api(`/api/items/${encodeURIComponent(item.id)}/text`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({text, fingerprint: item.fingerprint}),
    });
    state.selected = updated;
    state.editing = false;
    const summary = state.items.find(row => row.id === item.id);
    if (summary) Object.assign(summary, {state: updated.state, edited: updated.edited, fingerprint: updated.fingerprint});
    render();
    notice(updated.edited ? 'Texto salvo. Revise e aprove a nova versão.' : 'Texto original restaurado.');
  } catch (error) {
    notice(error.message);
  } finally {
    el('save-edit').disabled = false;
    el('restore').disabled = false;
  }
}

async function decide(decision) {
  const item = state.selected;
  if (!item) return;
  el('approve').disabled = true;
  el('reopen').disabled = true;
  try {
    await api(`/api/items/${encodeURIComponent(item.id)}/review`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({decision, fingerprint: item.fingerprint}),
    });
    item.state = decision;
    const summary = state.items.find(row => row.id === item.id);
    if (summary) summary.state = decision;
    render();
    notice(decision === 'approved' ? 'Item aprovado.' : 'Item voltou para revisão.');
  } catch (error) {
    renderDetail();
    notice(error.message);
  }
}

function nextPending() {
  const pending = state.items.filter(item => item.state === 'needs_review' &&
    (state.category === 'all' || item.type === state.category));
  if (!pending.length) { notice('Não há itens pendentes neste filtro.'); return; }
  const index = pending.findIndex(item => item.id === state.selected?.id);
  selectItem(pending[(index + 1) % pending.length].id);
}

document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => {
  state.view = button.dataset.view;
  render();
}));
el('search').addEventListener('input', event => { state.search = event.target.value; renderList(); });
el('approve').addEventListener('click', () => decide('approved'));
el('reopen').addEventListener('click', () => decide('needs_review'));
el('next').addEventListener('click', nextPending);
el('edit').addEventListener('click', startEdit);
el('cancel-edit').addEventListener('click', cancelEdit);
el('save-edit').addEventListener('click', () => saveText(el('edit-text').value));
el('restore').addEventListener('click', () => {
  if (state.selected && confirm('Restaurar o texto extraído originalmente do PDF?')) {
    saveText(state.selected.original_text);
  }
});

api('/api/catalog').then(items => {
  state.items = items;
  render();
  const first = items.find(item => item.state === 'needs_review') || items[0];
  if (first) selectItem(first.id, false);
}).catch(error => notice(error.message));
