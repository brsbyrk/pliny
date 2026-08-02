// ── State ──
const state = {
  view: 'browse',
  query: '',
  selectedTags: new Set(),
  page: 1,
  totalPages: 1,
  total: 0,
  allTags: [],
  showAllTags: false,
  starredFilter: false,
  hasSearched: false,
  // Graph
};

const ITEMS_PER_PAGE = 24;
const TAGS_SHOWN = 15;
let searchTimeout = null;
let graphMinCount = 3;
let graphMaxEdges = 200;
let graphSimulation = null;

// ── Stats bar ──
function updateStatsBar(stats) {
  if (!stats) return;
  const el = document.getElementById('statsBar');
  if (!el) return;

  const totalEl = document.getElementById('statEntries');
  const tagsEl = document.getElementById('statTags');
  const starredEl = document.getElementById('statStarred');
  const updatedEl = document.getElementById('statUpdated');

  if (totalEl) totalEl.textContent = (stats.total_entries || 0).toLocaleString();
  if (tagsEl) tagsEl.textContent = (stats.total_tags || 0).toLocaleString();
  if (starredEl) starredEl.textContent = (stats.starred_entries || stats.starred_count || '—').toLocaleString();
  if (updatedEl) updatedEl.textContent = stats.last_updated
    ? timeAgo(stats.last_updated)
    : '—';
}

async function loadStatsBar() {
  try {
    const res = await fetch('/api/stats');
    const data = await res.json();
    updateStatsBar(data);
  } catch (e) { /* silent */ }
}

// ── Shared Context (cross-view state) ──
const appContext = {
  focusTag: '',
  activeTags: new Set(),
  lastQuery: '',
  lastSearch: '',
  lastSource: '',
  graphSelectedTag: '',
};

function renderContextBar() {
  var bar = document.getElementById('contextBar');
  var parts = [];

  if (appContext.focusTag) {
    parts.push('<span class="context-pill focus">focus: ' + appContext.focusTag +
      ' <span class="c-remove" onclick="clearFocusTag()">&times;</span></span>');
  }
  appContext.activeTags.forEach(function(t) {
    parts.push('<span class="context-pill tag">tag: ' + t +
      ' <span class="c-remove" onclick="removeContextTag(\'' + t + '\')">&times;</span></span>');
  });
  if (appContext.lastQuery) {
    parts.push('<span class="context-pill query">query: "' + appContext.lastQuery.slice(0, 40) + '"</span>');
  }
  if (appContext.lastSearch) {
    parts.push('<span class="context-pill query">search: "' + appContext.lastSearch.slice(0, 40) + '"</span>');
  }
  if (appContext.lastSource) {
    parts.push('<span class="context-pill source">source: ' + appContext.lastSource + '</span>');
  }

  if (parts.length > 0) {
    bar.innerHTML = '<span class="context-label">context:</span> ' + parts.join(' ') +
      ' <button class="context-clear" onclick="clearAllContext()">clear all</button>';
  } else {
    bar.innerHTML = '';
  }
}

function updateContext(updates) {
  for (var k in updates) {
    if (k === 'activeTags') {
      appContext.activeTags = updates[k];
    } else {
      appContext[k] = updates[k];
    }
  }
  renderContextBar();
}

function clearFocusTag() {
  appContext.focusTag = '';
  appContext.graphSelectedTag = '';
  renderContextBar();
  if (state.view === 'graph') loadGraph();
}

function removeContextTag(tag) {
  state.selectedTags.delete(tag);
  appContext.activeTags = new Set(state.selectedTags);
  renderContextBar();
  if (state.view === 'browse') { renderTags(); loadEntries(); }
}

function clearAllContext() {
  appContext.focusTag = '';
  appContext.graphSelectedTag = '';
  appContext.lastQuery = '';
  appContext.lastSearch = '';
  appContext.lastSource = '';
  appContext.activeTags.clear();
  state.selectedTags.clear();
  state.query = '';
  state.starredFilter = false;
  const sf = document.getElementById('starredFilter');
  if (sf) { sf.classList.remove('active'); sf.textContent = '☆ Starred'; }
  document.getElementById('search').value = '';
  const clearBtn = document.getElementById('searchClearBtn');
  if (clearBtn) clearBtn.style.display = 'none';
  renderContextBar();
  if (state.view === 'browse') { renderTags(); loadEntries(); }
  if (state.view === 'graph') loadGraph();
}

function switchView(view) {
  state.view = view;
  document.querySelectorAll('.view-tab').forEach(t => {
    t.classList.toggle('active', t.dataset.view === view);
  });
  document.getElementById('browseView').style.display = view === 'browse' ? '' : 'none';
  document.getElementById('graphView').style.display = view === 'graph' ? '' : 'none';
  document.getElementById('pipelineView').style.display = view === 'pipeline' ? '' : 'none';

  const labels = { browse: 'search', graph: 'graph', pipeline: 'pipeline' };
  document.getElementById('viewLabel').textContent = labels[view];

  if (view === 'graph') { renderContextBar(); loadGraph(); }
  if (view === 'pipeline') { renderContextBar(); loadPipeline(); }
  if (view === 'browse') { renderContextBar(); }
}

// ── API calls ──
async function fetchTags() {
  const res = await fetch('/api/tags');
  const data = await res.json();
  state.allTags = data.tags;
  return data.tags;
}

async function fetchEntries() {
  const params = new URLSearchParams({
    q: state.query,
    tags: [...state.selectedTags].join(','),
    page: state.page,
    per_page: ITEMS_PER_PAGE,
  });
  if (state.starredFilter) params.set('starred', '1');

  // Read advanced filters
  const sourceEl = document.getElementById('browseSource');
  if (sourceEl && sourceEl.value) params.set('source', sourceEl.value);
  const contentEl = document.getElementById('browseContent');
  if (contentEl && contentEl.value !== 'all') params.set('content', contentEl.value);
  const sortEl = document.getElementById('browseSort');
  if (sortEl && sortEl.value !== 'date_desc') params.set('sort', sortEl.value);
  const datePreset = document.getElementById('browseDatePreset');
  if (datePreset) {
    if (datePreset.value === 'custom') {
      const fromEl = document.getElementById('browseDateFrom');
      const toEl = document.getElementById('browseDateTo');
      if (fromEl && fromEl.value) params.set('date_from', fromEl.value);
      if (toEl && toEl.value) params.set('date_to', toEl.value);
    } else if (datePreset.value) {
      const days = parseInt(datePreset.value);
      const d = new Date();
      d.setDate(d.getDate() - days);
      params.set('date_from', d.toISOString().split('T')[0]);
    }
  }
  const vectorEl = document.getElementById('browseVector');
  if (vectorEl && vectorEl.checked) params.set('mode', 'vector');
  const entryTypeEl = document.getElementById('browseEntryType');
  if (entryTypeEl && entryTypeEl.value) params.set('entry_type', entryTypeEl.value);

  const res = await fetch(`/api/entries?${params}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

async function fetchRelatedTags(tag) {
  const res = await fetch(`/api/tags/related/${encodeURIComponent(tag)}`);
  return res.json();
}

async function fetchGraphData(minCount, maxEdges) {
  const res = await fetch(`/api/tags/graph?min_count=${minCount}&max_edges=${maxEdges}`);
  return res.json();
}

async function fetchStats() {
  const res = await fetch('/api/stats');
  return res.json();
}

async function fetchPipeline() {
  const res = await fetch('/api/pipeline');
  return res.json();
}

async function fetchActivity(limit) {
  const res = await fetch(`/api/activity?limit=${limit || 15}`);
  return res.json();
}

// ── Entries (search and display) ──

// ── BROWSE: render tags ──
function renderTags() {
  const bar = document.getElementById('tagBar');
  const tags = state.allTags;
  bar.innerHTML = '<span class="tag-bar-label">Tags:</span>';
  const visibleCount = state.showAllTags ? tags.length : Math.min(TAGS_SHOWN, tags.length);
  let shown = 0;
  for (let i = 0; i < tags.length && shown < visibleCount; i++) {
    if (tags[i].count < 1) continue;
    shown++;
    const t = tags[i];
    const active = state.selectedTags.has(t.tag);
    const chip = document.createElement('span');
    chip.className = `tag-chip${active ? ' active' : ''}`;
    chip.textContent = t.tag;
    const count = document.createElement('span');
    count.className = 'count';
    count.textContent = t.count;
    chip.appendChild(count);
    chip.onclick = (ev) => { if (ev.ctrlKey || ev.metaKey) { showTagInfo(t.tag, ev); } else { toggleTag(t.tag); } };
    bar.appendChild(chip);
  }
  if (tags.length > TAGS_SHOWN) {
    const toggle = document.createElement('button');
    toggle.className = 'tag-toggle';
    toggle.textContent = state.showAllTags
      ? `▲ Show fewer (${tags.length} total)`
      : `▼ Show all ${tags.length} tags`;
    toggle.onclick = () => { state.showAllTags = !state.showAllTags; renderTags(); };
    bar.appendChild(toggle);
  }
}

// ── BROWSE: render cards ──
function renderCards(data) {
  const container = document.getElementById('results');
  const header = document.getElementById('resultCount');
  const pagination = document.getElementById('pagination');
  state.total = data.total;
  state.totalPages = data.total_pages;
  header.textContent = data.entries.length > 0
    ? `${data.total} results${state.query ? ` for "${state.query}"` : ''}`
    : '';
  // Stats bar is updated via loadStatsBar() called from loadEntries/init

  if (data.entries.length === 0) {
    const hasFilters = state.query || state.selectedTags.size > 0 || state.starredFilter;
    container.innerHTML = renderEmptyState(state.query, hasFilters);
    pagination.innerHTML = '';
    return;
  }

  const grid = document.createElement('div');
  grid.className = 'card-grid';
  const domainEmoji = { 'github': '💻', 'x/twitter': '🐦', 'youtube': '📺', 'reddit': '👽', 'hacker news': '📰', 'arxiv': '📄', 'medium': '📝', 'substack': '✉️' };
  for (const entry of data.entries) {
    const card = document.createElement('div');
    card.className = 'card';
    card.dataset.id = entry.id;
    if (selectedIds.has(entry.id)) card.classList.add('selected');
    const indicator = document.createElement('div');
    indicator.className = 'sel-indicator';
    card.appendChild(indicator);
    const titleRow = document.createElement('div');
    titleRow.className = 'card-title-row';
    const title = document.createElement('div');
    title.className = 'card-title';
    const domain = entry.domain && domainEmoji[entry.domain.toLowerCase()] ? domainEmoji[entry.domain.toLowerCase()] : '🔗';
    const iconSpan = document.createElement('span');
    iconSpan.className = 'card-domain-icon';
    iconSpan.textContent = domain;
    title.appendChild(iconSpan);
    const titleText = document.createElement('span');
    titleText.className = 'card-title-text';
    titleText.textContent = entry.title || '(no title)';
    title.appendChild(titleText);
    titleRow.appendChild(title);
    const starBtn = document.createElement('button');
    starBtn.className = `star-btn${entry.starred ? ' active' : ''}`;
    starBtn.textContent = entry.starred ? '★' : '☆';
    starBtn.setAttribute('aria-label', entry.starred ? 'Unstar' : 'Star');
    starBtn.onclick = async (e) => {
      e.stopPropagation();
      const ok = await toggleStar(entry.id, !entry.starred);
      if (ok) { entry.starred = !entry.starred; starBtn.textContent = entry.starred ? '★' : '☆'; starBtn.className = `star-btn${entry.starred ? ' active' : ''}`; starBtn.setAttribute('aria-label', entry.starred ? 'Unstar' : 'Star'); }
    };
    starBtn.style.marginLeft = 'auto';
    titleRow.appendChild(starBtn);
    const similarBtn = document.createElement('button');
    similarBtn.className = 'card-action-btn';
    similarBtn.textContent = '⟷';
    similarBtn.title = 'Show similar entries';
    similarBtn.setAttribute('aria-label', 'Show similar entries');
    similarBtn.onclick = (e) => { e.stopPropagation(); showSimilar(entry.id); };
    titleRow.appendChild(similarBtn);
    card.appendChild(titleRow);

    // Content preview with fadeout wrapper
    const contentPreview = entry.summary || entry.preview?.slice(0, 200) || '';
    if (contentPreview) {
      const previewWrap = document.createElement('div');
      previewWrap.className = 'card-preview-wrap';
      const preview = document.createElement('div');
      preview.className = 'card-preview';
      preview.textContent = contentPreview;
      previewWrap.appendChild(preview);
      card.appendChild(previewWrap);
    }

    const tagsDiv = document.createElement('div');
    tagsDiv.className = 'card-tags';
    for (const tag of (entry.tags || []).slice(0, 5)) {
      const el = document.createElement('span');
      el.className = 'card-tag tag-badge';
      el.textContent = tag;
      tagsDiv.appendChild(el);
    }
    const meta = document.createElement('div');
    meta.className = 'card-meta';
    const metaLeft = document.createElement('span');
    metaLeft.className = 'meta-flex-row';
    // Date with relative time
    const date = document.createElement('span');
    const dateStr = entry.created_at
      ? (typeof timeAgo === 'function' ? timeAgo(entry.created_at) : new Date(entry.created_at).toLocaleDateString())
      : '';
    date.textContent = dateStr || new Date(entry.created_at).toLocaleDateString();
    metaLeft.appendChild(date);
    // Status dot
    const statusDot = document.createElement('span');
    statusDot.className = 'status-dot ' + (entry.extraction_status || 'pending');
    statusDot.title = entry.extraction_status || 'pending';
    metaLeft.appendChild(statusDot);
    meta.appendChild(metaLeft);
    const metaRight = document.createElement('span');
    metaRight.className = 'meta-flex-row';
    // Source domain
    const source = document.createElement('span');
    try { source.textContent = new URL(entry.source_url).hostname; } catch { source.textContent = ''; }
    metaRight.appendChild(source);
    // Entry type badge
    if (entry.entry_type && entry.entry_type !== 'bookmark') {
      const badge = document.createElement('span');
      const badgeClass = entry.entry_type.startsWith('x_') ? 'blue'
        : entry.entry_type === 'youtube' ? 'red'
        : entry.entry_type === 'github' ? 'gray'
        : entry.entry_type === 'reddit' ? 'orange'
        : entry.entry_type === 'synthesis' ? 'purple'
        : 'gray';
      badge.className = 'entry-badge ' + badgeClass;
      badge.textContent = entry.entry_type === 'synthesis' ? '📖 synthesis' : entry.entry_type.replace('_', ' ');
      metaRight.appendChild(badge);
    }
    meta.appendChild(metaRight);
    card.appendChild(tagsDiv);
    card.appendChild(meta);
    const sizeBar = document.createElement('div');
    sizeBar.className = 'card-size-bar';
    const contentLen = (entry.content || '').length;
    sizeBar.style.width = Math.min(100, (contentLen / 10000) * 100) + '%';
    card.appendChild(sizeBar);
    card.title = entry.title || '(no title)';
    card.onclick = (e) => {
      if (e.shiftKey) {
        e.preventDefault();
        selToggle(entry.id, e);
        return;
      }
      if (e.ctrlKey || e.metaKey || e.button === 1) { window.open(entry.source_url, '_blank'); }
      else { showDetail(entry.id); }
    };
    card.onauxclick = (e) => { if (e.button === 1) { e.preventDefault(); window.open(entry.source_url, '_blank'); } };
    grid.appendChild(card);
  }
  container.innerHTML = '';
  container.appendChild(grid);
  renderPagination();
}

function renderPagination() {
  const el = document.getElementById('pagination');
  if (state.totalPages <= 1) { el.innerHTML = ''; return; }
  const parts = [];
  const p = state.page, tp = state.totalPages;
  const addBtn = (label, pg, active) => {
    const btn = document.createElement('button');
    btn.className = `page-btn${active ? ' active' : ''}`;
    btn.textContent = label;
    btn.disabled = active;
    btn.onclick = () => { state.page = pg; loadEntries(); };
    parts.push(btn);
  };
  const span = (text) => { const s = document.createElement('span'); s.className = 'page-info'; s.textContent = text; parts.push(s); };
  addBtn('‹ Prev', p - 1, p === 1);
  const start = Math.max(1, p - 2);
  const end = Math.min(tp, p + 2);
  if (start > 1) { addBtn(1, 1, false); if (start > 2) span('…'); }
  for (let i = start; i <= end; i++) addBtn(i, i, i === p);
  if (end < tp) { if (end < tp - 1) span('…'); addBtn(tp, tp, false); }
  addBtn('Next ›', p + 1, p === tp);
  el.innerHTML = '';
  for (const p of parts) el.appendChild(p);
}

// ── Modal ──
async function showDetail(id) {
  const res = await fetch(`/api/entry/${encodeURIComponent(id)}`);
  const entry = await res.json();

  // Title
  const modalTitleEl = document.getElementById('modalTitle');
  modalTitleEl.textContent = entry.title || '(no title)';
  modalTitleEl.style.display = 'flex';
  modalTitleEl.style.alignItems = 'center';
  modalTitleEl.style.gap = '8px';
  // Clear existing star btn if any
  const existingStar = modalTitleEl.querySelector('.modal-star-btn');
  if (existingStar) existingStar.remove();
  const starBtn = document.createElement('button');
  starBtn.className = `star-btn modal-star-btn${entry.starred ? ' active' : ''}`;
  starBtn.textContent = entry.starred ? '★' : '☆';
  starBtn.onclick = async (e) => {
    e.stopPropagation();
    try {
      const r = await fetch(`/api/entry/${id}/star`, { method: 'POST' });
      const d = await r.json();
      starBtn.textContent = d.starred ? '★' : '☆';
      starBtn.classList.toggle('active', d.starred);
    } catch (e) { /* ignore */ }
  };
  modalTitleEl.appendChild(starBtn);

  // Metadata bar
  const domain = (() => { try { return new URL(entry.source_url).hostname; } catch { return ''; } })();
  const dateStr = entry.created_at ? new Date(entry.created_at).toLocaleDateString() : '';
  const contentSize = entry.content ? (entry.content.length < 1024 ? `${entry.content.length}B` : `${(entry.content.length / 1024).toFixed(1)}KB`) : '';
  const metaBar = document.getElementById('modalMetaBar');
  metaBar.innerHTML = '';
  if (domain) {
    const badge = document.createElement('span');
    badge.className = 'modal-domain-badge';
    badge.textContent = domain;
    metaBar.appendChild(badge);
  }
  if (dateStr) {
    const dateEl = document.createElement('span');
    dateEl.className = 'modal-stat';
    dateEl.textContent = dateStr;
    metaBar.appendChild(dateEl);
  }
  if (contentSize) {
    const sizeEl = document.createElement('span');
    sizeEl.className = 'modal-stat';
    sizeEl.textContent = contentSize;
    metaBar.appendChild(sizeEl);
  }

  // URL with open-in-new-tab button
  document.getElementById('modalMeta').innerHTML = '';
  const urlEl = document.createElement('span');
  const urlLink = document.createElement('a');
  urlLink.href = entry.source_url;
  urlLink.target = '_blank';
  urlLink.textContent = entry.source_url;
  urlEl.appendChild(urlLink);
  document.getElementById('modalMeta').appendChild(urlEl);
  const openBtn = document.createElement('a');
  openBtn.href = entry.source_url;
  openBtn.target = '_blank';
  openBtn.className = 'searchide-btn modal-open-link';
  openBtn.textContent = 'Open';
  document.getElementById('modalMeta').appendChild(openBtn);

  // Entry type badge
  const typeBadgeEl = document.getElementById('modalTypeBadge');
  if (entry.entry_type && entry.entry_type !== 'bookmark') {
    const colorMap = { x_thread: '#58a6ff', x_article: '#58a6ff', x_observation: '#58a6ff',
      youtube: '#f85149', github: '#8b949e', reddit: '#f0883e',
      synthesis: '#bc8cff' };
    const color = colorMap[entry.entry_type] || 'var(--text-dim)';
    typeBadgeEl.innerHTML = `<span style="display:inline-block;padding:2px 10px;border-radius:100px;font-size:0.7rem;font-weight:600;color:${color};background:${color}18;border:1px solid ${color}40;text-transform:uppercase;">${entry.entry_type.replace('_', ' ')}</span>`;
  } else {
    typeBadgeEl.innerHTML = '';
  }

  // Tags
  const tagsEl = document.getElementById('modalTags');
  tagsEl.innerHTML = '';
  for (const tag of (entry.tags || [])) {
    const el = document.createElement('span');
    el.className = 'card-tag tag-badge';
    el.textContent = tag;
    tagsEl.appendChild(el);
  }

  // Source refs (synthesis backlinks)
  const refsEl = document.getElementById('modalSourceRefs');
  if (refsEl) {
    refsEl.innerHTML = '';
    if (entry.source_refs && entry.source_refs.length > 0) {
      refsEl.style.display = 'block';
      const label = document.createElement('span');
      label.className = 'modal-source-refs-label';
      label.textContent = 'Synthesized from:';
      refsEl.appendChild(label);
      for (const refId of entry.source_refs) {
        const link = document.createElement('a');
        link.className = 'modal-source-ref-link';
        link.href = '#';
        link.textContent = refId;
        link.onclick = (e) => {
          e.preventDefault();
          showDetail(refId);
        };
        refsEl.appendChild(link);
      }
    } else {
      refsEl.style.display = 'none';
    }
  }

  // Summary & content
  const summaryEl = document.getElementById('modalSummary');
  const contentEl = document.getElementById('modalContent');
  if (entry.content && entry.content.length > 200) {
    summaryEl.textContent = entry.summary || '';
    summaryEl.style.display = 'block';
  } else {
    summaryEl.style.display = 'none';
  }
  contentEl.textContent = entry.content || '(no content)';

  // Toggle overflow gradient indicator — only show when content scrolls
  setTimeout(() => {
    contentEl.classList.toggle('has-overflow', contentEl.scrollHeight > contentEl.clientHeight);
  }, 50);

  // Fetch related entries as mini-cards
  const relatedEl = document.getElementById('relatedListModal');
  relatedEl.innerHTML = '<span class="text-dim" style="font-size: 0.85rem;">Loading...</span>';
  try {
    const relRes = await fetch(`/api/entry/${encodeURIComponent(id)}/related`);
    if (relRes.ok) {
      const related = await relRes.json();
      const items = related.entries || related;
      if (items.length === 0) {
        relatedEl.innerHTML = '<span class="text-dim" style="font-size: 0.85rem;">No related entries found.</span>';
      } else {
        relatedEl.innerHTML = items.map(r => {
          const sim = r.similarity !== undefined ? r.similarity : (r.score !== undefined ? r.score : null);
          const badge = sim !== null
            ? `<span style="background: rgba(88,166,255,0.12); color: var(--accent); padding: 2px 8px; border-radius: 100px; font-size: 0.7rem; white-space: nowrap;">${Math.round(sim)}%</span>`
            : '';
          const concepts = r.shared_concepts && r.shared_concepts.length > 0
            ? r.shared_concepts.slice(0, 3).map(t => `<span class="modal-tag-chip" style="font-size:0.65rem;padding:1px 6px;border-radius:100px;background:var(--bg-hover);border:1px solid var(--border);color:var(--text-dim);display:inline-block;margin:0 2px;">${t}</span>`).join('')
            : '';
          return `<div class="card mini-card" style="margin-bottom:6px;padding:8px 12px;cursor:pointer;" onclick="showDetail('${r.id}')">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;">
              <span style="color: var(--accent); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; font-size:0.85rem;">${escapeHtml(r.title || r.name || '(untitled)')}</span>
              ${badge}
            </div>
            ${concepts ? `<div style="margin-top:4px;">${concepts}</div>` : ''}
          </div>`;
        }).join('');
      }
    } else {
      relatedEl.innerHTML = '<span class="text-dim" style="font-size: 0.85rem;">Unable to load related entries.</span>';
    }
  } catch (e) {
    relatedEl.innerHTML = '<span class="text-dim" style="font-size: 0.85rem;">Error loading related entries.</span>';
  }

  // Add explore similarity button (single instance — uses dedicated container)
  const exploreBtn = document.getElementById('exploreSimilarityBtn');
  exploreBtn.innerHTML = `<button class="explore-sim-btn" data-id="${id.replace(/"/g, '&quot;')}" style="font-size:0.8rem;color:var(--accent);background:none;border:none;cursor:pointer;">Open in Similarity Explorer →</button>`;
  exploreBtn.querySelector('.explore-sim-btn').onclick = (e) => {
    exploreSimilarity(id);
  };

  document.getElementById('modal').classList.add('open');
  // Close info panel if open (prevents z-index stacking issues)
  closeInfoPanel();
}

function closeModal() {
  document.getElementById('modal').classList.remove('open');
}
document.getElementById('modal').onclick = (e) => { if (e.target === e.currentTarget) closeModal(); };
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeModal(); });

// ── Star toggle ──
async function toggleStar(id, starred) {
  try {
    const res = await fetch(`/api/entry/${id}/star`, { method: 'POST' });
    const data = await res.json();
    return true;
  } catch (e) { return false; }
}

// ── Browse actions ──
function toggleTag(tag) {
  if (state.selectedTags.has(tag)) state.selectedTags.delete(tag);
  else state.selectedTags.add(tag);
  state.page = 1;
  updateContext({ activeTags: new Set(state.selectedTags), lastQuery: state.query });
  renderTags();
  loadEntries();
}

function clearFilters() {
  state.query = '';
  state.selectedTags.clear();
  state.page = 1;
  state.starredFilter = false;
  const sf = document.getElementById('starredFilter');
  if (sf) { sf.classList.remove('active'); sf.textContent = '☆ Starred'; }
  document.getElementById('search').value = '';
  document.getElementById('searchClearBtn').style.display = 'none';
  loadEntries();
}

function clearSearch() {
  document.getElementById('search').value = '';
  document.getElementById('searchClearBtn').style.display = 'none';
  state.query = '';
  state.page = 1;
  loadEntries();
}

function toggleStarredFilter() {
  state.starredFilter = !state.starredFilter;
  const btn = document.getElementById('starredFilter');
  btn.classList.toggle('active');
  btn.textContent = state.starredFilter ? '★ Starred' : '☆ Starred';
  state.page = 1;
  loadEntries();
}

// ── Browse filter panel ──
function toggleBrowseFilters() {
  const panel = document.getElementById('browseFilters');
  const btn = document.getElementById('filterToggleBtn');
  const isOpen = panel.classList.contains('open');
  panel.classList.toggle('open');
  btn.textContent = isOpen ? '▼ Filters' : '▲ Filters';
  btn.classList.toggle('active', !isOpen);
}

function browseSearch() {
  state.page = 1;
  loadEntries();
}

function browseDateChange() {
  const preset = document.getElementById('browseDatePreset');
  const custom = document.getElementById('browseCustomDate');
  custom.style.display = preset.value === 'custom' ? 'flex' : 'none';
  browseSearch();
}

function browseExport(format) {
  const params = new URLSearchParams({
    q: state.query,
    tags: [...state.selectedTags].join(','),
    per_page: 500,
  });
  const sourceEl = document.getElementById('browseSource');
  if (sourceEl && sourceEl.value) params.set('source', sourceEl.value);
  const contentEl = document.getElementById('browseContent');
  if (contentEl && contentEl.value !== 'all') params.set('content', contentEl.value);
  const sortEl = document.getElementById('browseSort');
  if (sortEl && sortEl.value !== 'date_desc') params.set('sort', sortEl.value);
  const entryTypeEl = document.getElementById('browseEntryType');
  if (entryTypeEl && entryTypeEl.value) params.set('entry_type', entryTypeEl.value);
  window.open(`/api/entries?${params}&_export=${format}`, '_blank');
}

function browseReset() {
  document.getElementById('browseSource').value = '';
  document.getElementById('browseEntryType').value = '';
  document.getElementById('browseContent').value = 'all';
  document.getElementById('browseSort').value = 'date_desc';
  document.getElementById('browseDatePreset').value = '';
  document.getElementById('browseCustomDate').style.display = 'none';
  document.getElementById('browseDateFrom').value = '';
  document.getElementById('browseDateTo').value = '';
  document.getElementById('browseVector').checked = false;
  state.page = 1;
  loadEntries();
}

// ── Ask Pliny ──
function openAskPanel() {
  const panel = document.getElementById('askPanel');
  panel.style.display = '';
  document.getElementById('askBody').style.display = '';
  document.getElementById('askToggle').textContent = '▾';
  document.getElementById('askInput').focus();
}

function toggleAskPanel() {
  const body = document.getElementById('askBody');
  const toggle = document.getElementById('askToggle');
  const isOpen = body.style.display !== 'none';
  body.style.display = isOpen ? 'none' : '';
  toggle.textContent = isOpen ? '▸' : '▾';
  if (!isOpen) document.getElementById('askInput').focus();
}

async function askPliny() {
  const input = document.getElementById('askInput');
  const q = input.value.trim();
  if (!q) return;

  const btn = document.getElementById('askBtn');
  const status = document.getElementById('askStatus');
  const answer = document.getElementById('askAnswer');
  const sources = document.getElementById('askSources');
  const error = document.getElementById('askError');

  btn.disabled = true;
  status.textContent = 'Thinking...';
  answer.style.display = 'none';
  sources.style.display = 'none';
  error.style.display = 'none';

  try {
    const res = await fetch('/api/ask', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({q}),
    });
    const data = await res.json();

    if (data.error) {
      error.textContent = data.error;
      error.style.display = '';
      status.textContent = '';
      return;
    }

    status.textContent = `${data.sources.length} sources consulted`;
    answer.textContent = data.answer;
    answer.style.display = '';

    if (data.sources.length > 0) {
      let html = '<div class="ask-sources-title">Sources</div>';
      data.sources.forEach(s => {
        const tags = (s.tags || []).slice(0, 3).map(t => `<span class="src-tag">${t}</span>`).join('');
        html += `<div class="ask-source-item" onclick="openModal('${s.id}')">
          <span class="src-title">${s.title}</span>
          <span class="src-tags">${tags}</span>
        </div>`;
      });
      sources.innerHTML = html;
      sources.style.display = '';
    }
  } catch (e) {
    error.textContent = `Error: ${e.message}`;
    error.style.display = '';
    status.textContent = '';
  } finally {
    btn.disabled = false;
  }
}

// ── Tag cloud in Browse ──
async function loadBrowseTagCloud() {
  const data = await fetch('/api/tags').then(r => r.json());
  const cloud = document.getElementById('browseTagCloud');
  const count = document.getElementById('browseTagsCount');
  if (!cloud) return;
  cloud.innerHTML = '';
  if (!data.tags || data.tags.length === 0) {
    cloud.innerHTML = '<span class="text-dim" style="font-size:0.8rem;">No tags yet</span>';
    return;
  }
  if (count) count.textContent = `${data.total} tags`;
  data.tags.slice(0, 60).forEach(t => {
    const el = document.createElement('span');
    el.className = 'tag-cloud-item' + (state.selectedTags.has(t.tag) ? ' active' : '');
    el.textContent = `${t.tag} (${t.count})`;
    el.onclick = () => {
      if (state.selectedTags.has(t.tag)) {
        state.selectedTags.delete(t.tag);
        el.classList.remove('active');
      } else {
        state.selectedTags.add(t.tag);
        el.classList.add('active');
      }
      renderTags();
      state.page = 1;
      loadEntries();
    };
    cloud.appendChild(el);
  });
}

function toggleTagCloud() {
  const cloud = document.getElementById('browseTagCloud');
  const toggle = document.getElementById('browseTagsToggle');
  if (!cloud) return;
  const isOpen = cloud.style.display !== 'none';
  cloud.style.display = isOpen ? 'none' : '';
  toggle.textContent = isOpen ? '▸ Tags' : '▾ Tags';
  if (!isOpen && cloud.children.length === 0) {
    loadBrowseTagCloud();
  }
}

// ── Show Similar / Explore ──
async function showSimilar(entryId) {
  const res = await fetch(`/api/entry/${entryId}`);
  const entry = await res.json();
  showDetail(entry.id);
}

async function exploreSimilarity(entryId) {
  // Get the entry and search for similar entries by title keywords
  try {
    const res = await fetch(`/api/entry/${entryId}`);
    const entry = await res.json();
    if (entry && entry.title) {
      // Use title as search query to find similar entries
      const words = entry.title.split(/\s+/).slice(0, 4).join(' ');
      document.getElementById('search').value = words;
      state.query = words;
      state.page = 1;
      updateContext({ lastQuery: words });
      closeModal();
      loadEntries();
    }
  } catch (e) { /* ignore */ }
}

async function loadEntries() {
  const container = document.getElementById('results');
  container.innerHTML = renderSkeletons(6);
  let data;
  try {
    data = await fetchEntries();
  } catch (err) {
    showError(`Failed to load entries: ${err.message}`);
    return;
  }
  renderCards(data);
  updateActiveFilterCount();
  updateActiveFilterChips();
  loadStatsBar();
}

function renderSkeletons(count = 6) {
  let html = '<div class="card-grid">';
  for (let i = 0; i < count; i++) {
    html += `<div class="card skeleton-card">
      <div class="skeleton-line" style="width:45%"></div>
      <div class="skeleton-line" style="width:80%"></div>
      <div class="skeleton-line" style="width:35%"></div>
      <div class="skeleton-line" style="width:55%"></div>
    </div>`;
  }
  html += '</div>';
  return html;
}

function renderEmptyState(query, hasFilters) {
  let icon = '📭';
  let msg = 'No entries yet';
  let hint = '';
  let action = '';

  if (query) {
    icon = '🔍';
    msg = `No results for "${query}"`;
    hint = 'Try a broader search term or different keywords.';
    action = '<button class="searchide-btn empty-action" onclick="clearSearch()">Clear Search</button>';
  } else if (hasFilters) {
    icon = '🏷️';
    msg = 'No results match these filters';
    hint = 'Try removing some filters or broadening your criteria.';
    action = '<button class="searchide-btn empty-action" onclick="browseReset()">Clear All Filters</button>';
  } else if (state.starredFilter) {
    icon = '⭐';
    msg = 'No starred entries';
    hint = 'Star entries you want to keep track of by clicking the ☆ button.';
    action = '<button class="searchide-btn empty-action" onclick="toggleStarredFilter()">Show All</button>';
  } else {
    icon = '📚';
    msg = 'Your library is empty';
    hint = 'Add URLs via the Pipeline tab to start building your knowledge base.';
    action = '<button class="searchide-btn empty-action" onclick="switchView(\'pipeline\')">Go to Pipeline</button>';
  }

  return `<div class="empty-state">
    <div class="empty-icon">${icon}</div>
    <div class="empty-title">${msg}</div>
    <div class="empty-hint">${hint}</div>
    ${action}
  </div>`;
}

function showError(msg) {
  const container = document.getElementById('results');
  container.innerHTML = `<div class="error-banner"><span class="error-icon">⚠</span><span>${msg}</span><button class="searchide-btn" onclick="loadEntries()" style="margin-left:12px;padding:4px 10px;">Retry</button></div>`;
}

async function loadBrowseDefault() {
  const container = document.getElementById('results');
  container.innerHTML = renderSkeletons(6);
  try {
    const [recentRes, starredRes, tagsRes] = await Promise.all([
      fetch('/api/entries?per_page=12'),
      fetch('/api/entries/starred?per_page=5'),
      fetch('/api/tags'),
    ]);
    const recent = await recentRes.json();
    const starred = await starredRes.json();
    const tags = await tagsRes.json();
    let html = '';
    if (tags.tags && tags.tags.length > 0) {
      html += '<div class="default-section"><div class="default-section-title">Top Tags</div><div class="default-tags">';
      tags.tags.slice(0, 12).forEach(t => {
        html += `<span class="tag-cloud-item" onclick="state.selectedTags.add('${t.tag.replace(/'/g, "\\'")}');renderTags();loadEntries();">${t.tag}</span>`;
      });
      html += '</div></div>';
    }
    if (starred.total > 0) {
      html += '<div class="default-section"><div class="default-section-title">★ Starred</div><div class="card-grid">';
      starred.entries.forEach(e => {
        html += `<div class="card mini-card" onclick="showDetail('${e.id}')"><div class="card-title">${escapeHtml(e.title || '(no title)')}</div></div>`;
      });
      html += '</div></div>';
    }
    if (recent.total > 0) {
      html += '<div class="default-section"><div class="default-section-title">Recently Added</div></div>';
      container.innerHTML = html;
      renderCards(recent);
      return;
    }
    container.innerHTML = html || renderEmptyState('', false);
  } catch (e) {
    container.innerHTML = renderEmptyState('', false);
  }
  loadStatsBar();
}

function updateActiveFilterCount() {
  const el = document.getElementById('filterCount');
  let count = 0;
  const sourceEl = document.getElementById('browseSource');
  if (sourceEl && sourceEl.value) count++;
  const entryTypeEl = document.getElementById('browseEntryType');
  if (entryTypeEl && entryTypeEl.value) count++;
  const contentEl = document.getElementById('browseContent');
  if (contentEl && contentEl.value !== 'all') count++;
  const sortEl = document.getElementById('browseSort');
  if (sortEl && sortEl.value !== 'date_desc') count++;
  const datePreset = document.getElementById('browseDatePreset');
  if (datePreset && datePreset.value) count++;
  const vectorEl = document.getElementById('browseVector');
  if (vectorEl && vectorEl.checked) count++;
  if (state.query) count++;
  if (state.selectedTags.size > 0) count++;
  if (state.starredFilter) count++;
  if (count > 0) {
    el.textContent = count + ' active';
    el.style.display = '';
  } else {
    el.style.display = 'none';
  }
}

function updateActiveFilterChips() {
  const el = document.getElementById('activeFilterChips');
  const chips = [];
  function addChip(label, value, onremove) {
    chips.push('<span class="active-filter-chip">' + label + ': ' + value +
      ' <span class="af-remove" onclick="' + onremove + '">&times;</span></span>');
  }
  if (state.query) {
    addChip('Search', state.query.length > 20 ? state.query.slice(0, 20) + '...' : state.query,
      'clearSearch()');
  }
  if (state.selectedTags.size > 0) {
    state.selectedTags.forEach(function(t) {
      addChip('Tag', t, 'toggleTag("' + t.replace(/"/g, '&quot;') + '");loadEntries()');
    });
  }
  const sourceEl = document.getElementById('browseSource');
  if (sourceEl && sourceEl.value) {
    addChip('Source', sourceEl.value, "document.getElementById('browseSource').value='';browseSearch()");
  }
  const entryTypeEl = document.getElementById('browseEntryType');
  if (entryTypeEl && entryTypeEl.value) {
    addChip('Type', entryTypeEl.value, "document.getElementById('browseEntryType').value='';browseSearch()");
  }
  const contentEl = document.getElementById('browseContent');
  if (contentEl && contentEl.value !== 'all') {
    addChip('Content', contentEl.value, "document.getElementById('browseContent').value='all';browseSearch()");
  }
  const datePreset = document.getElementById('browseDatePreset');
  if (datePreset && datePreset.value) {
    addChip('Date', datePreset.value === 'custom' ? 'Custom' : datePreset.value,
      "document.getElementById('browseDatePreset').value='';browseSearch()");
  }
  if (state.starredFilter) {
    addChip('Starred', '\u2605', 'toggleStarredFilter()');
  }
  if (chips.length > 0) {
    el.innerHTML = chips.join('');
    el.style.display = '';
  } else {
    el.style.display = 'none';
  }
}

document.getElementById('search').addEventListener('input', (e) => {
  clearTimeout(searchTimeout);
  const clearBtn = document.getElementById('searchClearBtn');
  clearBtn.style.display = e.target.value ? '' : 'none';
  searchTimeout = setTimeout(() => {
    state.query = e.target.value.trim();
    state.page = 1;
    state.hasSearched = true;
    updateContext({ lastQuery: state.query });
    loadEntries();
  }, 200);
});

// ── Graph search filter ──
function filterGraphNodes(query) {
  const q = query.toLowerCase().trim();
  const svg = document.querySelector('#graph-container svg');
  if (!svg) return;
  // Find all text elements (labels) and their parent circles
  const texts = svg.querySelectorAll('text');
  texts.forEach(function(t) {
    const text = t.textContent.toLowerCase();
    const match = !q || text.includes(q);
    t.style.opacity = match ? '1' : '0.08';
    // Find corresponding circle (same parent g)
    const g = t.closest('g');
    if (g) {
      const circle = g.querySelector('circle');
      if (circle) circle.style.opacity = match ? '0.85' : '0.05';
    }
  });
  // Also dim edges connected to hidden nodes
  const lines = svg.querySelectorAll('line');
  lines.forEach(function(l) {
    l.style.opacity = q ? '0.04' : '';
  });
}

// ── GRAPH VIEW ──
async function loadGraph() {
  const container = document.getElementById('graph-container');
  const tooltip = document.getElementById('graphTooltip');
  const selectedEl = document.getElementById('graphSelectedTag');

  container.innerHTML = '<div class="loading" style="padding-top:120px;"><div class="spinner"></div>Loading graph...</div>';

  try {
    const data = await fetchGraphData(graphMinCount, graphMaxEdges);
    if (data.nodes.length === 0) {
      container.innerHTML = '<div class="empty-state"><div class="empty-icon">🕸️</div><div class="empty-title">No graph data</div><div class="empty-hint">Try lowering the minimum tag frequency below.</div></div>';
      return;
    }

    container.innerHTML = '';

    const width = container.clientWidth;
    const height = container.clientHeight;

    const nodeCount = data.nodes.length;
    const edgeCount = data.edges.length;

    // Color scale based on tag categories
    const color = d3.scaleOrdinal(d3.schemeCategory10);
    const radiusScale = d3.scaleSqrt()
      .domain([1, d3.max(data.nodes, d => d.count)])
      .range([4, 24]);

    const svg = d3.select('#graph-container')
      .append('svg')
      .attr('width', width)
      .attr('height', height);

    // Zoom behavior
    const g = svg.append('g');
    const zoom = d3.zoom()
      .scaleExtent([0.1, 8])
      .on('zoom', (event) => { g.attr('transform', event.transform); });
    svg.call(zoom);

    // Edges
    const edgeWeightScale = d3.scaleLinear()
      .domain([1, d3.max(data.edges, d => d.weight)])
      .range([0.1, 0.6]);

    const link = g.append('g')
      .selectAll('line')
      .data(data.edges)
      .join('line')
      .attr('stroke', '#30363d')
      .attr('stroke-width', d => Math.max(0.5, Math.log(d.weight) * 0.8))
      .attr('stroke-opacity', d => edgeWeightScale(d.weight));

    // Nodes
    const node = g.append('g')
      .selectAll('circle')
      .data(data.nodes)
      .join('circle')
      .attr('r', d => radiusScale(d.count))
      .attr('fill', d => color(d.id))
      .attr('stroke', '#0d1117')
      .attr('stroke-width', 1.5)
      .attr('opacity', 0.85)
      .style('cursor', 'pointer')
      .on('mouseover', (event, d) => {
        tooltip.style.display = 'block';
        tooltip.innerHTML = `<div class="tt-tag">${d.id}</div><div class="tt-count">×${d.count} entries</div>`;
        // Move tooltip
        const rect = container.getBoundingClientRect();
        tooltip.style.left = (event.clientX - rect.left + 12) + 'px';
        tooltip.style.top = (event.clientY - rect.top - 10) + 'px';
        d3.select(event.currentTarget).attr('stroke', '#fff').attr('stroke-width', 2.5);
      })
      .on('mousemove', (event) => {
        const rect = container.getBoundingClientRect();
        tooltip.style.left = (event.clientX - rect.left + 12) + 'px';
        tooltip.style.top = (event.clientY - rect.top - 10) + 'px';
      })
      .on('mouseout', (event) => {
        tooltip.style.display = 'none';
        d3.select(event.currentTarget).attr('stroke', '#0d1117').attr('stroke-width', 1.5);
      })
      .on('click', (event, d) => {
        event.stopPropagation();
        selectedEl.textContent = `Selected: ${d.id} (×${d.count})`;
        updateContext({ focusTag: d.id, graphSelectedTag: d.id });
        showTagInfo(d.id, event);
        // Highlight node
        node.attr('opacity', 0.3);
        link.attr('stroke-opacity', 0.05);
        d3.select(event.currentTarget).attr('opacity', 1).attr('stroke', '#fff').attr('stroke-width', 3);
        // Highlight connected nodes and edges
        const connectedEdges = data.edges.filter(e => e.source === d.id || e.target === d.id);
        const connectedIds = new Set();
        connectedEdges.forEach(e => { connectedIds.add(e.source); connectedIds.add(e.target); });
        node.filter(n => connectedIds.has(n.id)).attr('opacity', 0.8);
        link.filter(l => connectedEdges.includes(l)).attr('stroke-opacity', 0.5).attr('stroke', '#58a6ff');
      });

    // Labels on larger nodes
    const labels = g.append('g')
      .selectAll('text')
      .data(data.nodes.filter(d => d.count >= 5))
      .join('text')
      .text(d => d.id)
      .attr('font-size', d => Math.min(11, radiusScale(d.count) * 0.6))
      .attr('text-anchor', 'middle')
      .attr('dy', 3)
      .attr('fill', '#c9d1d9')
      .style('pointer-events', 'none')
      .style('text-shadow', '0 1px 3px rgba(0,0,0,0.8)');

    // Force simulation
    const simulation = d3.forceSimulation(data.nodes)
      .force('link', d3.forceLink(data.edges).id(d => d.id).distance(80).strength(d => d.weight / 20))
      .force('charge', d3.forceManyBody().strength(-120))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(d => radiusScale(d.count) + 6))
      .on('tick', () => {
        link
          .attr('x1', d => d.source.x)
          .attr('y1', d => d.source.y)
          .attr('x2', d => d.target.x)
          .attr('y2', d => d.target.y);
        node
          .attr('cx', d => d.x)
          .attr('cy', d => d.y);
        labels
          .attr('x', d => d.x)
          .attr('y', d => d.y);
      });

    simulation.on('end', () => {
      // Re-center after layout settles
    });

    // Click on background to reset
    svg.on('click', () => {
      selectedEl.textContent = '';
      appContext.focusTag = '';
      appContext.graphSelectedTag = '';
      renderContextBar();
      node.attr('opacity', 0.85);
      link.attr('stroke', '#30363d')
        .attr('stroke-opacity', d => edgeWeightScale(d.weight));
      node.attr('stroke', '#0d1117').attr('stroke-width', 1.5);
    });

    // Handle window resize
    const resizeHandler = () => {
      const newWidth = container.clientWidth;
      const newHeight = container.clientHeight;
      svg.attr('width', newWidth).attr('height', newHeight);
      simulation.force('center', d3.forceCenter(newWidth / 2, newHeight / 2));
      simulation.alpha(0.3).restart();
    };
    window.addEventListener('resize', resizeHandler);

    // Store for cleanup
    graphSimulation = { simulation, svg, resizeHandler };

    selectedEl.textContent = `${data.nodes.length} topics · ${data.edges.length} connections`;

  } catch (e) {
    container.innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-title">Error loading graph</div><div class="empty-hint">${e.message}</div><button class="searchide-btn empty-action" onclick="loadGraph()">Retry</button></div>`;
  }
}

// ── Add URL ──
async function addUrls() {
  const input = document.getElementById('addUrlInput');
  const status = document.getElementById('addUrlStatus');
  const urls = input.value.split('\n').map(s => s.trim()).filter(s => s.startsWith('http'));
  if (urls.length === 0) { status.textContent = 'No valid URLs found'; return; }
  status.textContent = 'Adding ' + urls.length + ' URLs...';
  let ok = 0, err = 0;
  for (const url of urls) {
    try {
      const res = await fetch('/api/ingest/add-url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      if (res.ok) ok++; else err++;
    } catch { err++; }
  }
  status.textContent = ok + ' added, ' + err + ' errors';
  if (ok > 0) { input.value = ''; setTimeout(() => { status.textContent = ''; }, 5000); }
}

// ── Pipeline Actions ──
async function runPipelineAction(action) {
  const status = document.getElementById('pipelineStatus-' + action);
  if (!status) return;
  if (action === 'cleanup-dead' && !confirm('Delete dead entries? This cannot be undone.')) return;
  status.textContent = 'Running...';
  status.style.color = 'var(--accent)';
  try {
    const res = await fetch('/api/pipeline/' + action, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
    const data = await res.json();
    if (action === 'cleanup-dead') {
      status.textContent = 'Deleted ' + (data.deleted || 0) + ' entries';
    } else if (action === 're-extract-thin') {
      status.textContent = 'Queued ' + (data.queued || 0) + ' entries';
    } else {
      status.textContent = 'Done (' + (data.output || '').slice(0, 80) + '...)';
    }
    status.style.color = 'var(--accent-green)';
    // Refresh pipeline stats
    if (window.loadPipeline) loadPipeline();
  } catch (e) {
    status.textContent = 'Error: ' + e.message;
    status.style.color = '#ff7b72';
  }
  setTimeout(() => { status.textContent = ''; }, 8000);
}

// ── PIPELINE VIEW ──
async function loadPipeline() {
  document.getElementById('statCards').innerHTML = '<div class="loading"><div class="spinner"></div></div>';
  try {
    const [stats, pipeline, activity] = await Promise.all([
      fetchStats(), fetchPipeline(), fetchActivity(15),
    ]);
    renderStatCards(stats, pipeline);
    renderPipelineHealth(pipeline, stats);
    renderDomainChart(stats.domains);
    renderDailyChart(stats.daily_activity);
    renderTopTags(stats.top_tags);
    renderActivity(activity.entries);
  } catch (e) {
    document.getElementById('statCards').innerHTML = `<div class="empty-state"><div class="empty-icon">⚠️</div><div class="empty-title">Error loading pipeline</div><div class="empty-hint">${e.message}</div><button class="searchide-btn empty-action" onclick="loadPipeline()">Retry</button></div>`;
  }
}

function renderStatCards(s, p) {
  const total = s.total_entries || 1;
  const deadEntries = p && p.dead_entries !== undefined ? p.dead_entries : (s.dead_entries || 0);
  const cards = [
    { label: 'Total Entries', value: s.total_entries.toLocaleString(), color: 'accent' },
    { label: 'Tags', value: s.total_tags.toLocaleString(), color: 'accent-green' },
    { label: 'Enriched', value: s.enriched_entries, color: 'accent-green', pct: Math.round(s.enriched_entries / total * 100) },
    { label: 'Thin', value: s.thin_entries, color: s.thin_entries > 100 ? 'accent-orange' : 'accent-green' },
    { label: 'Dead', value: deadEntries, color: deadEntries > 0 ? '#f85149' : 'accent-green' },
  ];
  document.getElementById('statCards').innerHTML = cards.map(c =>
    `<div class="stat-card" style="border-left: 3px solid var(--${c.color.startsWith('#') ? '' : c.color});${c.color.startsWith('#') ? 'border-left: 3px solid ' + c.color + ';' : ''}">
      <div class="stat-card-value">${c.value}</div>
      <div class="stat-card-label">${c.label}</div>
      ${c.pct !== undefined ? `<div class="stat-card-sub">${c.pct}% of total</div>` : ''}
    </div>`
  ).join('');
}

function renderPipelineHealth(p, s) {
  // Enrichment
  const total = p.x_entries_total;
  const enriched = p.x_enriched;
  const pending = p.x_pending;
  const pct = total > 0 ? (enriched / total * 100) : 0;
  document.getElementById('enrichmentSummary').innerHTML =
    `<span class="value">${enriched} enriched · ${pending} pending · ${total} total X entries</span>`;
  document.getElementById('enrichmentBar').style.width = Math.min(pct, 100) + '%';
  document.getElementById('enrichmentCron').textContent = 'Cron: ' + p.enrichment_cron;

  document.getElementById('ingestValue').textContent = `${p.entries_last_30d} entries (last 30d)`;
  document.getElementById('lastImport').textContent = p.last_import_time ? new Date(p.last_import_time).toLocaleString() : '—';
  document.getElementById('dailyAvg').textContent = p.daily_avg_30d;

  document.getElementById('contentValue').textContent = `${s.content_min}B – ${s.content_max}B (range)`;
  document.getElementById('thinCount').textContent = s.thin_entries;

  document.getElementById('deadValue').textContent = p.dead_entries;
}

function renderDomainChart(domains) {
  const entries = Object.entries(domains).sort((a, b) => b[1] - a[1]);
  const maxCount = Math.max(...entries.map(e => e[1]));
  const colors = ['#58a6ff', '#3fb950', '#d29922', '#bc8cff', '#f0883e', '#79c0ff', '#56d4dd', '#ff7b72'];
  const total = entries.reduce((s, e) => s + e[1], 0);
  document.getElementById('domainChart').innerHTML =
    `<div class="domain-list">${entries.map(([name, count], i) =>
      `<div class="domain-row">
        <span class="domain-name">${name}</span>
        <div class="domain-bar-wrap">
          <div class="domain-bar" style="width:${Math.max(count / maxCount * 100, 5)}%;background:${colors[i % colors.length]}">
            ${count > 20 ? count : ''}
          </div>
        </div>
        <span class="domain-count">${count} (${(count/total*100).toFixed(0)}%)</span>
      </div>`
    ).join('')}</div>`;
}

function renderDailyChart(daily) {
  if (!daily || daily.length === 0) {
    document.getElementById('dailyChart').innerHTML = '<div class="empty-state"><p>No data</p></div>';
    return;
  }
  const maxCount = Math.max(...daily.map(d => d.count));
  const chart = document.createElement('div');
  chart.className = 'daily-chart';
  daily.forEach(d => {
    const bar = document.createElement('div');
    bar.className = 'daily-bar';
    bar.style.height = `${Math.max(d.count / maxCount * 100, 5)}%`;
    bar.title = `${d.day}: ${d.count} entries`;
    bar.innerHTML = `<span class="bar-label">${d.count}</span>`;
    chart.appendChild(bar);
  });
  document.getElementById('dailyChart').innerHTML = '';
  document.getElementById('dailyChart').appendChild(chart);
  // Labels — show all date labels for accessibility
  const labels = document.createElement('div');
  labels.className = 'daily-labels';
  const step = Math.max(1, Math.floor(daily.length / 7));
  daily.forEach((d, i) => {
    const span = document.createElement('span');
    span.textContent = i % step === 0 || i === daily.length - 1 ? d.day.slice(5) : '';
    span.title = d.day;
    labels.appendChild(span);
  });
  document.getElementById('dailyChart').appendChild(labels);
}

function renderTopTags(tags) {
  if (!tags || tags.length === 0) {
    document.getElementById('topTags').innerHTML = '<span class="text-dim">No tags</span>';
    return;
  }
  const colors = ['#58a6ff', '#3fb950', '#d29922', '#bc8cff', '#f0883e', '#79c0ff', '#56d4dd', '#ff7b72', '#ffa657', '#e3b341'];
  document.getElementById('topTags').innerHTML = tags.map((t, i) =>
    `<span class="tag-chip" onclick="switchView('browse');state.selectedTags.add('${t.tag.replace(/'/g, "\\'")}');renderTags();loadEntries();"
          style="background:rgba(${hexToRgb(colors[i % colors.length])},0.1);border-color:${colors[i % colors.length]};color:${colors[i % colors.length]}">
      ${t.tag} <span class="count">${t.count}</span>
    </span>`
  ).join(' ');
}

function renderActivity(entries) {
  if (!entries || entries.length === 0) {
    document.getElementById('activityList').innerHTML = '<div class="empty-state"><p>No activity</p></div>';
    return;
  }
  const list = document.getElementById('activityList');
  list.innerHTML = entries.map(e => {
    const statusClass = e.status === 'enriched' ? 'status-enriched' : e.status === 'thin' ? 'status-thin' : 'status-normal';
    const levelClass = e.status === 'enriched' ? 'activity-level-info' : e.status === 'thin' ? 'activity-level-warn' : '';
    const date = e.created_at ? timeAgo(e.created_at) : '';
    const title = e.title || '(no title)';
    return `<div class="activity-item" onclick="showDetail('${e.id}')">
      <span class="act-status ${statusClass}" title="${e.status}"></span>
      <span class="activity-time">${date}</span>
      <span class="activity-msg ${levelClass}">${escapeHtml(title)}</span>
      <span class="act-meta">${(e.tags || []).slice(0, 2).join(', ')} · ${e.content_len}B</span>
    </div>`;
  }).join('');
}

function timeAgo(dateStr) {
  const diff = Date.now() - new Date(dateStr).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

// ── COMMAND BAR ──

const COMMANDS = [
  // View navigation
  { key: 'b',      label: 'Browse',        desc: 'Switch to Browse view',       action: () => switchView('browse') },
  { key: 'g',      label: 'Graph',         desc: 'Switch to Graph view',         action: () => switchView('graph') },
  { key: 'pipe',   label: 'Pipeline',      desc: 'Switch to Pipeline view',      action: () => switchView('pipeline') },

  // Actions
  { key: 'ask',    label: 'Ask Pliny',    desc: 'Ask a question: /ask <question>',  action: (q) => { cmdClose(); openAskPanel(); if(q) document.getElementById('askInput').value = q; } },
  { key: 'find',   label: 'Find',          desc: 'Search bookmarks: /find <query>',    action: (query) => cmdFind(query) },
  { key: 'reset',  label: 'Reset filters', desc: 'Clear all active filters',           action: () => cmdReset() },
  { key: 'export', label: 'Export',        desc: 'Export results: /export md|json',    action: (fmt) => cmdExport(fmt) },
  { key: 'tag',    label: 'Filter by tag', desc: 'Add tag filter: /tag <name>',        action: (tag) => cmdTag(tag) },
  { key: 'source', label: 'Filter source', desc: 'Filter by source: /source <name>',   action: (s) => cmdSource(s) },
  { key: 'sort',   label: 'Sort',          desc: 'Sort results: /sort field',          action: (f) => cmdSort(f) },
  { key: 'date',   label: 'Date range',    desc: 'Date filter: /date 7d|30d|90d',      action: (d) => cmdDate(d) },
];

let cmdActiveIndex = -1;

function cmdOpen() {
  document.getElementById('cmdOverlay').classList.add('open');
  document.getElementById('cmdPalette').classList.add('open');
  document.getElementById('cmdFeedback').style.display = 'none';
  setTimeout(() => document.getElementById('cmdInput').focus(), 50);
  cmdFilter();
}

function cmdClose() {
  document.getElementById('cmdOverlay').classList.remove('open');
  document.getElementById('cmdPalette').classList.remove('open');
  document.getElementById('cmdInput').value = '';
  document.getElementById('cmdActions').innerHTML = '';
  cmdActiveIndex = -1;
}

// Keyboard shortcut
document.addEventListener('keydown', (e) => {
  if ((e.metaKey || e.ctrlKey) && e.key === '/') {
    e.preventDefault();
    const palette = document.getElementById('cmdPalette');
    if (palette.classList.contains('open')) cmdClose();
    else cmdOpen();
  }
  if (e.key === 'Escape') cmdClose();
});

// Input handling
document.getElementById('cmdInput')?.addEventListener('input', cmdFilter);
document.getElementById('cmdInput')?.addEventListener('keydown', (e) => {
  const actions = document.querySelectorAll('.command-action');
  if (e.key === 'ArrowDown') {
    e.preventDefault();
    cmdActiveIndex = Math.min(cmdActiveIndex + 1, actions.length - 1);
    cmdHighlight(actions);
  } else if (e.key === 'ArrowUp') {
    e.preventDefault();
    cmdActiveIndex = Math.max(cmdActiveIndex - 1, 0);
    cmdHighlight(actions);
  } else if (e.key === 'Enter') {
    e.preventDefault();
    const selected = document.querySelector('.command-action.selected');
    if (selected) selected.click();
    else if (e.target.value.trim()) cmdSubmitFallback(e.target.value.trim());
  } else if (e.key === 'Tab') {
    e.preventDefault();
    // Auto-complete first match
    const first = document.querySelector('.command-action');
    if (first) first.click();
  }
});

function cmdHighlight(actions) {
  actions.forEach((el, i) => el.classList.toggle('selected', i === cmdActiveIndex));
  const sel = document.querySelector('.command-action.selected');
  if (sel) sel.scrollIntoView({ block: 'nearest' });
}

function cmdFilter() {
  const input = document.getElementById('cmdInput').value.trim().toLowerCase();
  const container = document.getElementById('cmdActions');
  cmdActiveIndex = -1;

  if (!input) {
    // Show all commands
    container.innerHTML = COMMANDS.map(c =>
      `<div class="command-action" onclick="cmdExec('${c.key}', '')">
        <span class="ca-key">/${c.key}</span>
        <span class="ca-label">${c.label}</span>
        <span class="ca-desc">${c.desc}</span>
      </div>`
    ).join('');
    return;
  }

  // Split into command and args
  const parts = input.split(/\s+/);
  const cmdKey = parts[0];
  const args = parts.slice(1).join(' ');

  // Try to match built-in commands
  const exact = COMMANDS.find(c => c.key === cmdKey);
  if (exact) {
    container.innerHTML = `<div class="command-action" onclick="cmdExec('${exact.key}', '${args.replace(/'/g, "\\'")}')">
      <span class="ca-key">/${exact.key}</span>
      <span class="ca-label">${exact.label}</span>
      <span class="ca-desc">${args ? `with: ${args}` : exact.desc}</span>
      <span class="ca-badge">↵ execute</span>
    </div>`;
    return;
  }

  // Fuzzy match commands
  const fuzzy = COMMANDS.filter(c =>
    c.key.includes(cmdKey) || c.label.toLowerCase().includes(cmdKey)
  );
  if (fuzzy.length > 0) {
    container.innerHTML = fuzzy.map(c =>
      `<div class="command-action" onclick="cmdExec('${c.key}', '${args.replace(/'/g, "\\'")}')">
        <span class="ca-key">/${c.key}</span>
        <span class="ca-label">${c.label}</span>
        <span class="ca-desc">${c.desc}</span>
      </div>`
    ).join('');
    return;
  }

  // Fallback: send to Pliny
  container.innerHTML = `<div class="command-action" onclick="cmdAskPliny('${input.replace(/'/g, "\\'")}')">
    <span class="ca-key">/ask</span>
    <span class="ca-label">Ask Pliny: "${input}"</span>
    <span class="ca-desc">Sends to chat queue for next turn</span>
    <span class="ca-badge">→ queue</span>
  </div>`;
}

function cmdExec(key, args) {
  const cmd = COMMANDS.find(c => c.key === key);
  if (cmd) {
    cmd.action(args);
    cmdClose();
  }
}

function cmdSubmitFallback(text) {
  cmdClose();
  cmdAskPliny(text);
}

async function cmdAskPliny(text) {
  const feedback = document.getElementById('cmdFeedback');
  feedback.style.display = 'block';
  feedback.className = 'command-feedback';
  feedback.innerHTML = '<div class="spinner"></div>Sending to Pliny...';

  try {
    const view = state.view;
    const context = { view, query: state.query, tags: [...state.selectedTags] };

    const res = await fetch('/api/command', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: text, context, timestamp: new Date().toISOString() }),
    });
    if (res.ok) {
      feedback.className = 'command-feedback success';
      feedback.innerHTML = '✓ Sent to Pliny. It will be processed on next interaction.';
      setTimeout(cmdClose, 2000);
    } else {
      feedback.className = 'command-feedback error';
      feedback.innerHTML = '✗ Failed to send command';
    }
  } catch (e) {
    feedback.className = 'command-feedback error';
    feedback.innerHTML = `✗ ${e.message}`;
  }
}

// ── Built-in command handlers ──

function cmdFind(query) {
  switchView('browse');
  document.getElementById('search').value = query;
  state.query = query;
  state.page = 1;
  loadEntries();
}

function cmdReset() {
  if (state.view === 'browse') {
    clearFilters();
  }
}

function cmdExport(fmt) {
  alert('Export is only supported from Browse view, coming soon.');
}

function cmdTag(tag) {
  state.selectedTags.add(tag.toLowerCase());
  state.page = 1;
  renderTags();
  loadEntries();
}

function cmdSource(src) {
  // Source filter — for now, just switch to browse and add as a search term
  switchView('browse');
  document.getElementById('search').value = 'source:' + src;
  state.query = 'source:' + src;
  state.page = 1;
  loadEntries();
}

function cmdSort(field) {
  // Sort only applies to browse view
  alert('Sort command is not yet implemented for Browse view.');
}

function cmdDate(preset) {
  // Date filter — for now, switch to browse and add as search term
  switchView('browse');
  document.getElementById('search').value = '/date ' + preset;
  state.query = '/date ' + preset;
  state.page = 1;
  loadEntries();
}

// ── SELECTION AS ACTION ──

const selectedIds = new Set();

function selToggle(id, event) {
  if (selectedIds.has(id)) {
    selectedIds.delete(id);
  } else {
    selectedIds.add(id);
  }
  document.querySelectorAll('[data-id="' + id + '"]').forEach(function(el) {
    el.classList.toggle('selected', selectedIds.has(id));
  });
}

function selClear() {
  selectedIds.clear();
  document.querySelectorAll('.card.selected, .searchide-result-item.selected').forEach(function(el) {
    el.classList.remove('selected');
  });
}

// (selection action bar functions removed: selRenderBar, selSummarize, selReExtract, selTag, selExport, selOpenAll)

// ── INFO PANEL (inquisitive click) ──

function closeInfoPanel() {
  document.getElementById('infoOverlay').classList.remove('open');
  document.getElementById('infoPanel').classList.remove('open');
}

async function showTagInfo(tag, event) {
  if (event && event.shiftKey) return;
  var panel = document.getElementById('infoPanel');
  var overlay = document.getElementById('infoOverlay');
  document.getElementById('infoTitle').textContent = tag;
  document.getElementById('infoBody').innerHTML = '<div class="loading"><div class="spinner"></div>Loading...</div>';
  overlay.classList.add('open');
  panel.classList.add('open');

  try {
    // Fetch related tags, entries count, and sample entries in parallel
    var [relatedRes, entriesRes] = await Promise.all([
      fetch('/api/tags/related/' + encodeURIComponent(tag)),
      fetch('/api/entries?tags=' + encodeURIComponent(tag) + '&per_page=10'),
    ]);
    var related = await relatedRes.json();
    var entries = await entriesRes.json();

    var count = related.count || 0;
    var relatedTags = related.related || [];
    var sampleEntries = entries.entries || [];

    // Build body
    var html = '';

    // Stats
    html += '<div class="info-section">';
    html += '<div class="info-stat-row">';
    html += '<div class="info-stat"><div class="val">' + count + '</div><div class="lbl">entries</div></div>';
    html += '<div class="info-stat"><div class="val">' + relatedTags.length + '</div><div class="lbl">related tags</div></div>';
    html += '</div></div>';

    // Actions
    html += '<div class="info-section">';
    html += '<div class="info-actions">';
    html += '<button class="info-btn primary" onclick="closeInfoPanel();switchView(\'browse\');setTimeout(function(){toggleTag(\'' + tag.replace(/'/g, "\\'") + '\')},100)">Filter</button>';
    html += '<button class="info-btn" onclick="closeInfoPanel();switchView(\'graph\')">Graph</button>';
    html += '</div></div>';

    // Related tags
    if (relatedTags.length > 0) {
      html += '<div class="info-section"><h3>Related Tags</h3><div class="info-tag-list">';
      for (var i = 0; i < Math.min(relatedTags.length, 30); i++) {
        var rt = relatedTags[i];
        html += '<span class="info-tag" onclick="closeInfoPanel();showTagInfo(\'' + rt.tag.replace(/'/g, "\\'") + '\')">' + rt.tag + ' <span class="w">\u00d7' + rt.weight + '</span></span>';
      }
      html += '</div></div>';
    }

    // Sample entries
    if (sampleEntries.length > 0) {
      html += '<div class="info-section"><h3>Entries</h3><div class="info-entry-list">';
      for (var i = 0; i < Math.min(sampleEntries.length, 10); i++) {
        var e = sampleEntries[i];
        var domain = '';
        try { domain = new URL(e.source_url).hostname; } catch(ex) {}
        var date = e.created_at ? new Date(e.created_at).toLocaleDateString() : '';
        html += '<div class="info-entry" onclick="closeInfoPanel();showDetail(\'' + e.id + '\')">';
        html += '<span class="ie-title">' + escapeHtml(e.title || '(no title)') + '</span>';
        html += '<span class="ie-meta">' + domain + ' \u00b7 ' + date + '</span>';
        html += '</div>';
      }
      html += '</div></div>';
    }

    document.getElementById('infoBody').innerHTML = html;
  } catch (e) {
    document.getElementById('infoBody').innerHTML = '<div class="empty-state"><h3>Error</h3><p>' + e.message + '</p></div>';
  }
}

// ── Helpers ──
function formatBytes(bytes) {
  if (bytes >= 1000000) return (bytes / 1000000).toFixed(1) + 'M';
  if (bytes >= 1000) return (bytes / 1000).toFixed(1) + 'K';
  return bytes.toString();
}
function formatCompact(n) {
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
  return n.toString();
}
function hexToRgb(hex) {
  const r = parseInt(hex.slice(1,3), 16), g = parseInt(hex.slice(3,5), 16), b = parseInt(hex.slice(5,7), 16);
  return `${r},${g},${b}`;
}
function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML;
}

// ── Init ──
async function init() {
  await fetchTags();
  renderTags();
  if (state.hasSearched) {
    await loadEntries();
  } else {
    await loadBrowseDefault();
  }
  renderContextBar();
  document.getElementById('app').classList.add('app-wide'); // wider for graph
  loadStatsBar();

  // WebSocket for real-time updates
  try {
    const ws = new WebSocket('ws://' + location.host + '/ws');
    ws.onmessage = function(e) {
      try {
        const msg = JSON.parse(e.data);
        if (msg.type === 'pipeline_update' || msg.type === 'new_entry') {
          if (document.getElementById('pipelineView').style.display !== 'none') loadPipeline();
        }
      } catch(ex) {}
    };
    ws.onclose = function() { setTimeout(function() { /* reconnect handled by browser */ }, 5000); };
  } catch(ex) {}
}
init();
