import { useState, useEffect, useCallback, useRef } from 'react';

interface Entry {
  id: string;
  title: string;
  source_url: string;
  source_type: string;
  created_at: string;
  snippet: string;
  tags?: string[];
}

interface Stats {
  total_entries: number;
}

const API = '';
const PER_PAGE = 24;

const SOURCE_TYPES = ['all', 'web', 'x', 'youtube', 'github', 'reddit'] as const;
type SourceFilter = (typeof SOURCE_TYPES)[number];
type Theme = 'dark' | 'light';

const SRC_ICONS: Record<string, string> = {
  x: '𝕏', youtube: '▶', github: '⬡', reddit: '⬆', web: '🌐', feed: '📡',
};
const SRC_LABELS: Record<string, string> = {
  x: 'X', youtube: 'YouTube', github: 'GitHub', reddit: 'Reddit', web: 'Web', feed: 'Feed',
};

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'now';
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

function highlight(snippet: string) {
  return snippet.split(/(<mark>.*?<\/mark>)/g).map((p, i) =>
    p.startsWith('<mark>') ? (
      <mark key={i} style={{
        background: 'var(--accent-muted)', color: 'var(--accent)',
        borderRadius: 2, padding: '0 2px',
      }}>{p.replace(/<\/?mark>/g, '')}</mark>
    ) : p
  );
}

// ── Styles ──

const S = {
  input: {
    background: 'var(--bg-input)', border: '1px solid var(--border-standard)',
    borderRadius: 6, padding: '0 14px', height: 38, fontSize: '0.88rem',
    fontFamily: 'var(--font)', color: 'var(--text)', outline: 'none', flex: 1,
  } as React.CSSProperties,
  btn: {
    background: 'var(--accent-muted)', color: 'var(--accent)',
    border: '1px solid rgba(88,166,255,0.15)', borderRadius: 6,
    padding: '4px 12px', fontSize: '0.8rem', fontWeight: 500,
    cursor: 'pointer', fontFamily: 'var(--font)',
  } as React.CSSProperties,
  iconBtn: {
    background: 'none', border: '1px solid var(--border-subtle)', borderRadius: 6,
    padding: '4px 8px', fontSize: '0.9rem', cursor: 'pointer',
    color: 'var(--text-dim)', fontFamily: 'var(--font)',
  } as React.CSSProperties,
  card: {
    background: 'var(--bg-card)', border: '1px solid var(--border-subtle)',
    borderRadius: 8, padding: '12px 16px', cursor: 'pointer',
    transition: 'background 0.1s, border-color 0.1s',
    animation: 'fadeIn 0.2s ease',
  } as React.CSSProperties,
  skeleton: {
    background: 'var(--bg-card)', border: '1px solid var(--border-subtle)',
    borderRadius: 8, height: 72, opacity: 0.4,
  } as React.CSSProperties,
  pageBtn: (d: boolean): React.CSSProperties => ({
    background: 'var(--bg-card)', color: d ? 'var(--text-faint)' : 'var(--text-dim)',
    border: '1px solid var(--border-standard)', borderRadius: 6,
    padding: '4px 10px', fontSize: '0.82rem', cursor: d ? 'default' : 'pointer',
    fontFamily: 'var(--font)',
  }),
  pill: (active: boolean): React.CSSProperties => ({
    padding: '2px 10px', borderRadius: 9999, fontSize: '0.72rem', fontWeight: 500,
    border: '1px solid', cursor: 'pointer', fontFamily: 'var(--font)',
    transition: 'all 0.12s',
    background: active ? 'var(--accent-muted)' : 'transparent',
    color: active ? 'var(--accent)' : 'var(--text-muted)',
    borderColor: active ? 'rgba(88,166,255,0.2)' : 'var(--border-subtle)',
  }),
};

// ── App ──

export default function App() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [detail, setDetail] = useState<Entry | null>(null);
  const [detailContent, setDetailContent] = useState<string | null>(null);
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');
  const [captureOpen, setCaptureOpen] = useState(false);
  const [captureUrl, setCaptureUrl] = useState('');
  const [capturing, setCapturing] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [theme, setTheme] = useState<Theme>(() => {
    if (typeof window === 'undefined') return 'dark';
    const s = localStorage.getItem('pliny-theme');
    if (s === 'light' || s === 'dark') return s;
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  });
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('pliny-theme', theme);
  }, [theme]);

  const fetchEntries = useCallback(async (q = '', pg = 1) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ q, limit: String(PER_PAGE), page: String(pg) });
      const r = await fetch(`${API}/api/entries?${params}`);
      const d = await r.json();
      setEntries(d.entries || []);
    } catch { /* */ }
    finally { setLoading(false); }
  }, []);

  const fetchStats = useCallback(async () => {
    try {
      const r = await fetch(`${API}/api/stats`);
      setStats(await r.json());
    } catch { /* */ }
  }, []);

  useEffect(() => { fetchEntries(); fetchStats(); }, [fetchEntries, fetchStats]);

  const doSearch = (e: React.FormEvent) => { e.preventDefault(); setPage(1); fetchEntries(query, 1); };

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(null), 3000); };

  const doCapture = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!captureUrl.trim()) return;
    setCapturing(true);
    try {
      const r = await fetch(`${API}/api/ingest/add-url`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: captureUrl.trim() }),
      });
      const d = await r.json();
      if (d.status === 'ingested') {
        setCaptureUrl(''); setCaptureOpen(false);
        fetchEntries(query, page); fetchStats();
        showToast('✓ Saved');
      } else if (d.status === 'duplicate') {
        setCaptureUrl(''); setCaptureOpen(false);
        showToast('Already saved');
      } else {
        showToast('No content found');
      }
    } catch { showToast('Error'); }
    finally { setCapturing(false); }
  };

  const openDetail = async (entry: Entry) => {
    setDetail(entry); setDetailContent(null);
    try {
      const r = await fetch(`${API}/api/entry/${entry.id}`);
      if (r.ok) {
        const d = await r.json();
        setDetailContent(d.content || entry.snippet);
      } else { setDetailContent(entry.snippet); }
    } catch { setDetailContent(entry.snippet); }
  };

  const closeDetail = () => { setDetail(null); setDetailContent(null); };

  const filtered = sourceFilter === 'all' ? entries : entries.filter(e => e.source_type === sourceFilter);

  // Keyboard: esc, ⌘K, /
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { closeDetail(); setCaptureOpen(false); }
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); searchRef.current?.focus(); }
      if (e.key === '/' && document.activeElement !== searchRef.current) { e.preventDefault(); searchRef.current?.focus(); }
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, []);

  return (
    <div>
      {/* Header */}
      <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingBottom: 12, marginBottom: 16, borderBottom: '1px solid var(--border-subtle)' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <h1 style={{ fontFamily: 'var(--font-mono)', fontSize: '1.2rem', fontWeight: 650, color: 'var(--accent)', letterSpacing: '-0.4px' }}>Pliny</h1>
          {stats && <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>{stats.total_entries} entries</span>}
        </div>
        <div style={{ display: 'flex', gap: 6 }}>
          <button onClick={() => setCaptureOpen(!captureOpen)} style={S.btn}>{captureOpen ? '✕' : '+ Capture'}</button>
          <button onClick={() => setTheme(t => t === 'dark' ? 'light' : 'dark')} title="Toggle theme" style={S.iconBtn}>{theme === 'dark' ? '☀' : '☾'}</button>
        </div>
      </header>

      {/* Capture form */}
      {captureOpen && (
        <form onSubmit={doCapture} style={{ display: 'flex', gap: 8, marginBottom: 16, animation: 'fadeIn 0.2s ease' }}>
          <input type="url" value={captureUrl} onChange={e => setCaptureUrl(e.target.value)} placeholder="Paste a URL..." autoFocus style={S.input} />
          <button type="submit" disabled={capturing || !captureUrl.trim()} style={{ ...S.btn, background: captureUrl.trim() ? 'var(--accent)' : 'var(--bg-input)', color: captureUrl.trim() ? '#fff' : 'var(--text-muted)' }}>{capturing ? '...' : 'Save'}</button>
        </form>
      )}

      {/* Search */}
      <form onSubmit={doSearch} style={{ marginBottom: 12 }}>
        <input ref={searchRef} type="text" value={query} onChange={e => setQuery(e.target.value)} placeholder="Search... (/ to focus)" style={{ ...S.input, width: '100%' }} />
      </form>

      {/* Source filters */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20, flexWrap: 'wrap' }}>
        {SOURCE_TYPES.map(t => (
          <button key={t} onClick={() => { setSourceFilter(t); setPage(1); }} style={S.pill(sourceFilter === t)}>
            {t === 'all' ? 'All' : SRC_LABELS[t] || t}
          </button>
        ))}
      </div>

      {/* Content */}
      {loading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {Array.from({length: 5}).map((_, i) => <div key={i} style={S.skeleton} />)}
        </div>
      ) : filtered.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '48px 24px', color: 'var(--text-muted)' }}>
          <div style={{ fontSize: '1.5rem', marginBottom: 8, opacity: 0.3 }}>{query || sourceFilter !== 'all' ? '🔍' : '📚'}</div>
          <p style={{ fontSize: '0.88rem', fontWeight: 500, color: 'var(--text-dim)', marginBottom: 4 }}>
            {query ? 'Nothing found' : sourceFilter !== 'all' ? `No ${SRC_LABELS[sourceFilter] || sourceFilter} entries` : 'No entries yet'}
          </p>
          <p style={{ fontSize: '0.78rem' }}>{query ? 'Try a different search.' : sourceFilter !== 'all' ? 'Try a different filter.' : 'Capture your first URL.'}</p>
        </div>
      ) : (
        <>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {filtered.map(entry => (
              <article key={entry.id}
                onClick={() => openDetail(entry)}
                style={S.card}
                onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-hover)'; e.currentTarget.style.borderColor = 'var(--border-standard)'; }}
                onMouseLeave={e => { e.currentTarget.style.background = 'var(--bg-card)'; e.currentTarget.style.borderColor = 'var(--border-subtle)'; }}>
                <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                  <span style={{ width: 22, height: 22, borderRadius: 4, background: 'var(--bg-hover)', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '0.7rem', flexShrink: 0, border: '1px solid var(--border-subtle)', marginTop: 1 }}>
                    {SRC_ICONS[entry.source_type] || '•'}
                  </span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: '0.85rem', fontWeight: 550, lineHeight: 1.35, marginBottom: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{entry.title}</div>
                    <div style={{ fontSize: '0.78rem', color: 'var(--text-dim)', lineHeight: 1.45, overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', marginBottom: (entry.tags?.length ? 6 : 0) }}>
                      {highlight(entry.snippet)}
                    </div>
                    {entry.tags && entry.tags.length > 0 && (
                      <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                        {entry.tags.map(t => (
                          <span key={t} style={{ fontSize: '0.65rem', padding: '1px 7px', borderRadius: 9999, background: 'var(--accent-muted)', color: 'var(--accent)', border: '1px solid rgba(88,166,255,0.1)' }}>{t}</span>
                        ))}
                      </div>
                    )}
                  </div>
                  <span style={{ fontSize: '0.68rem', color: 'var(--text-faint)', whiteSpace: 'nowrap', marginTop: 2 }}>{timeAgo(entry.created_at)}</span>
                </div>
              </article>
            ))}
          </div>
          <div style={{ display: 'flex', justifyContent: 'center', gap: 6, marginTop: 20, paddingTop: 14, borderTop: '1px solid var(--border-subtle)' }}>
            <button onClick={() => { const p = Math.max(1, page - 1); setPage(p); fetchEntries(query, p); }} disabled={page <= 1} style={S.pageBtn(page <= 1)}>←</button>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'flex', alignItems: 'center', padding: '0 6px', fontVariantNumeric: 'tabular-nums' }}>{page}</span>
            <button onClick={() => { const p = page + 1; setPage(p); fetchEntries(query, p); }} disabled={entries.length < PER_PAGE} style={S.pageBtn(entries.length < PER_PAGE)}>→</button>
          </div>
        </>
      )}

      {/* Detail modal */}
      {detail && (
        <div onClick={closeDetail} style={{ position: 'fixed', inset: 0, zIndex: 100, background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(4px)', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <div onClick={e => e.stopPropagation()} style={{ width: 640, maxWidth: '100%', maxHeight: '85vh', background: 'var(--bg-card)', border: '1px solid var(--border-standard)', borderRadius: 12, overflow: 'auto', padding: '20px 24px', animation: 'modalIn 0.15s ease' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
              <div>
                <h2 style={{ fontSize: '1rem', fontWeight: 600, lineHeight: 1.3 }}>{detail.title}</h2>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 4 }}>{SRC_LABELS[detail.source_type] || detail.source_type} · {timeAgo(detail.created_at)}</div>
              </div>
              <button onClick={closeDetail} style={{ background: 'none', border: 'none', color: 'var(--text-dim)', fontSize: '1.3rem', cursor: 'pointer', padding: '0 4px', lineHeight: 1 }}>×</button>
            </div>
            <a href={detail.source_url} target="_blank" rel="noopener noreferrer" style={{ display: 'inline-block', marginBottom: 14, fontSize: '0.78rem', color: 'var(--accent)' }}>Open original →</a>
            <div style={{ fontSize: '0.84rem', lineHeight: 1.6, color: 'var(--text-dim)', whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
              {detailContent !== null
                ? detailContent.length > 0 ? detailContent : detail.snippet.replace(/<\/?mark>/g, '')
                : <span style={{ opacity: 0.4 }}>Loading...</span>}
            </div>
          </div>
        </div>
      )}
      {/* Toast */}
      {toast && (
        <div style={{
          position: 'fixed', bottom: 32, left: '50%', transform: 'translateX(-50%)',
          background: 'var(--bg-card)', border: '1px solid var(--border-standard)',
          borderRadius: 8, padding: '8px 20px', fontSize: '0.82rem',
          color: 'var(--text)', zIndex: 200,
          boxShadow: '0 4px 16px rgba(0,0,0,0.3)', animation: 'fadeIn 0.2s ease',
        }}>{toast}</div>
      )}
    </div>
  );
}
