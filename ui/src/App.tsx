import { useState, useEffect, useCallback, useRef } from 'react';

interface Entry {
  id: string;
  title: string;
  source_url: string;
  source_type: string;
  created_at: string;
  snippet: string;
}

interface Stats {
  total_entries: number;
}

const API = '';
const PER_PAGE = 24;

const SOURCE_TYPES = ['all', 'web', 'x', 'youtube', 'github', 'reddit'] as const;
type SourceFilter = (typeof SOURCE_TYPES)[number];

function sourceIcon(type: string): string {
  const icons: Record<string, string> = {
    x: '𝕏', youtube: '▶', github: '⬡', reddit: '⬆', web: '🌐', feed: '📡',
  };
  return icons[type] || '•';
}

function sourceLabel(type: string): string {
  const labels: Record<string, string> = {
    x: 'X', youtube: 'YouTube', github: 'GitHub', reddit: 'Reddit',
    web: 'Web', feed: 'Feed',
  };
  return labels[type] || type;
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d`;
  return new Date(iso).toLocaleDateString();
}

function highlightSnippet(snippet: string) {
  return snippet.split(/(<mark>.*?<\/mark>)/g).map((p, i) =>
    p.startsWith('<mark>') ? (
      <mark key={i} style={{
        background: 'var(--accent-muted)', color: 'var(--accent)',
        borderRadius: 2, padding: '0 2px',
      }}>{p.replace(/<\/?mark>/g, '')}</mark>
    ) : p
  );
}

type Theme = 'dark' | 'light';

export default function App() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [detail, setDetail] = useState<Entry | null>(null);
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('all');
  const [captureOpen, setCaptureOpen] = useState(false);
  const [captureUrl, setCaptureUrl] = useState('');
  const [capturing, setCapturing] = useState(false);
  const [theme, setTheme] = useState<Theme>(() => {
    if (typeof window === 'undefined') return 'dark';
    const stored = localStorage.getItem('pliny-theme');
    if (stored === 'light' || stored === 'dark') return stored;
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  });

  const searchRef = useRef<HTMLInputElement>(null);

  // Apply theme
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('pliny-theme', theme);
  }, [theme]);

  const toggleTheme = () => setTheme(t => t === 'dark' ? 'light' : 'dark');

  const fetchEntries = useCallback(async (q: string = '', p: number = 1) => {
    setLoading(true);
    try {
      const params = new URLSearchParams({ q, limit: String(PER_PAGE), page: String(p) });
      const res = await fetch(`${API}/api/entries?${params}`);
      const data = await res.json();
      setEntries(data.entries || []);
    } catch { /* server not running */ }
    finally { setLoading(false); }
  }, []);

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/stats`);
      setStats(await res.json());
    } catch { /* not critical */ }
  }, []);

  useEffect(() => { fetchEntries(); fetchStats(); }, [fetchEntries, fetchStats]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchEntries(query, 1);
  };

  const handleCapture = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!captureUrl.trim()) return;
    setCapturing(true);
    try {
      const res = await fetch(`${API}/api/ingest/add-url`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: captureUrl.trim() }),
      });
      const data = await res.json();
      if (data.status === 'ingested') {
        setCaptureUrl('');
        setCaptureOpen(false);
        fetchEntries(query, page);
        fetchStats();
      }
    } catch { /* */ }
    finally { setCapturing(false); }
  };

  const filteredEntries = sourceFilter === 'all'
    ? entries
    : entries.filter(e => e.source_type === sourceFilter);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setDetail(null); setCaptureOpen(false); }
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        searchRef.current?.focus();
      }
      if (e.key === '/' && document.activeElement !== searchRef.current) {
        e.preventDefault();
        searchRef.current?.focus();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  return (
    <div>
      {/* Header */}
      <header style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        paddingBottom: 12, marginBottom: 16,
        borderBottom: '1px solid var(--border-subtle)',
      }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
          <h1 style={{
            fontFamily: 'var(--font-mono)', fontSize: '1.2rem', fontWeight: 650,
            color: 'var(--accent)', letterSpacing: '-0.4px',
          }}>Pliny</h1>
          {stats && (
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>
              {stats.total_entries} entries
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <button onClick={() => setCaptureOpen(!captureOpen)}
            style={btnStyle}>
            {captureOpen ? '✕' : '+ Capture'}
          </button>
          <button onClick={toggleTheme}
            title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
            style={{ ...btnStyle, fontSize: '1rem', padding: '4px 8px' }}>
            {theme === 'dark' ? '☀' : '☾'}
          </button>
        </div>
      </header>

      {/* Inline capture form */}
      {captureOpen && (
        <form onSubmit={handleCapture}
          style={{
            display: 'flex', gap: 8, marginBottom: 16,
            animation: 'fadeIn 0.2s ease',
          }}>
          <input
            type="url"
            value={captureUrl}
            onChange={e => setCaptureUrl(e.target.value)}
            placeholder="Paste a URL to capture..."
            autoFocus
            style={inputStyle}
          />
          <button type="submit" disabled={capturing || !captureUrl.trim()}
            style={{
              ...btnStyle,
              background: captureUrl.trim() ? 'var(--accent)' : 'var(--bg-input)',
              color: captureUrl.trim() ? '#fff' : 'var(--text-muted)',
            }}>
            {capturing ? '...' : 'Save'}
          </button>
        </form>
      )}

      {/* Search + filters */}
      <form onSubmit={handleSearch} style={{ marginBottom: 12 }}>
        <input
          ref={searchRef}
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search... (⌘K or / to focus)"
          style={{ ...inputStyle, width: '100%' }}
        />
      </form>

      {/* Source filter chips */}
      <div style={{ display: 'flex', gap: 4, marginBottom: 20, flexWrap: 'wrap' }}>
        {SOURCE_TYPES.map(type => (
          <button key={type}
            onClick={() => { setSourceFilter(type); setPage(1); }}
            style={{
              padding: '2px 10px', borderRadius: 9999,
              fontSize: '0.72rem', fontWeight: 500,
              border: '1px solid',
              cursor: 'pointer',
              fontFamily: 'var(--font)',
              transition: 'all 0.12s',
              background: sourceFilter === type ? 'var(--accent-muted)' : 'transparent',
              color: sourceFilter === type ? 'var(--accent)' : 'var(--text-muted)',
              borderColor: sourceFilter === type ? 'rgba(88,166,255,0.2)' : 'var(--border-subtle)',
            }}>
            {type === 'all' ? 'All' : sourceLabel(type)}
          </button>
        ))}
      </div>

      {/* Content */}
      {loading ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {Array.from({length: 5}).map((_, i) => (
            <div key={i} style={{
              background: 'var(--bg-card)', border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-md)', height: 72, opacity: 0.4,
            }} />
          ))}
        </div>
      ) : filteredEntries.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '48px 24px', color: 'var(--text-muted)' }}>
          <div style={{ fontSize: '1.5rem', marginBottom: 8, opacity: 0.3 }}>
            {query || sourceFilter !== 'all' ? '🔍' : '📚'}
          </div>
          <p style={{ fontSize: '0.88rem', fontWeight: 500, color: 'var(--text-dim)', marginBottom: 4 }}>
            {query ? 'Nothing found' : sourceFilter !== 'all' ? `No ${sourceLabel(sourceFilter)} entries` : 'No entries yet'}
          </p>
          <p style={{ fontSize: '0.78rem' }}>
            {query ? 'Try a different search.' : sourceFilter !== 'all' ? 'Try a different filter.' : 'Capture your first URL to start.'}
          </p>
        </div>
      ) : (
        <>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {filteredEntries.map(entry => (
              <article key={entry.id}
                onClick={() => setDetail(entry)}
                style={{
                  background: 'var(--bg-card)', border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-md)', padding: '12px 16px',
                  cursor: 'pointer', transition: 'background 0.1s, border-color 0.1s',
                  animation: 'fadeIn 0.2s ease',
                }}
                onMouseEnter={e => {
                  e.currentTarget.style.background = 'var(--bg-hover)';
                  e.currentTarget.style.borderColor = 'var(--border-standard)';
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.background = 'var(--bg-card)';
                  e.currentTarget.style.borderColor = 'var(--border-subtle)';
                }}>
                <div style={{ display: 'flex', gap: 10, alignItems: 'flex-start' }}>
                  <span style={{
                    width: 22, height: 22, borderRadius: 4,
                    background: 'var(--bg-hover)', display: 'flex',
                    alignItems: 'center', justifyContent: 'center',
                    fontSize: '0.7rem', flexShrink: 0,
                    border: '1px solid var(--border-subtle)',
                    marginTop: 1,
                  }}>{sourceIcon(entry.source_type)}</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{
                      fontSize: '0.85rem', fontWeight: 550, lineHeight: 1.35,
                      marginBottom: 4,
                      overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}>
                      {entry.title}
                    </div>
                    <div style={{
                      fontSize: '0.78rem', color: 'var(--text-dim)', lineHeight: 1.45,
                      overflow: 'hidden', display: '-webkit-box',
                      WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                    }}>
                      {highlightSnippet(entry.snippet)}
                    </div>
                  </div>
                  <span style={{
                    fontSize: '0.68rem', color: 'var(--text-faint)',
                    whiteSpace: 'nowrap', marginTop: 2,
                  }}>
                    {timeAgo(entry.created_at)}
                  </span>
                </div>
              </article>
            ))}
          </div>

          {/* Pagination */}
          <div style={{
            display: 'flex', justifyContent: 'center', gap: 6,
            marginTop: 20, paddingTop: 14,
            borderTop: '1px solid var(--border-subtle)',
          }}>
            <button onClick={() => { setPage(p => Math.max(1, p - 1)); fetchEntries(query, page - 1); }}
              disabled={page <= 1}
              style={pageBtnStyle(page <= 1)}>←</button>
            <span style={{
              fontSize: '0.75rem', color: 'var(--text-muted)',
              display: 'flex', alignItems: 'center', padding: '0 6px',
              fontVariantNumeric: 'tabular-nums',
            }}>{page}</span>
            <button onClick={() => { setPage(p => p + 1); fetchEntries(query, page + 1); }}
              disabled={entries.length < PER_PAGE}
              style={pageBtnStyle(entries.length < PER_PAGE)}>→</button>
          </div>
        </>
      )}

      {/* Detail modal */}
      {detail && (
        <div onClick={() => setDetail(null)}
          style={{
            position: 'fixed', inset: 0, zIndex: 100,
            background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(4px)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: 20,
          }}>
          <div onClick={e => e.stopPropagation()}
            style={{
              width: 640, maxWidth: '100%', maxHeight: '85vh',
              background: 'var(--bg-card)', border: '1px solid var(--border-standard)',
              borderRadius: 'var(--radius-lg)', overflow: 'auto',
              padding: '20px 24px',
              animation: 'modalIn 0.15s ease',
            }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
              <div>
                <h2 style={{ fontSize: '1rem', fontWeight: 600, lineHeight: 1.3 }}>{detail.title}</h2>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: 4 }}>
                  {sourceLabel(detail.source_type)} · {timeAgo(detail.created_at)}
                </div>
              </div>
              <button onClick={() => setDetail(null)}
                style={{
                  background: 'none', border: 'none', color: 'var(--text-dim)',
                  fontSize: '1.3rem', cursor: 'pointer', padding: '0 4px',
                  lineHeight: 1,
                }}>×</button>
            </div>
            <a href={detail.source_url} target="_blank" rel="noopener noreferrer"
              style={{
                display: 'inline-block', marginBottom: 14,
                fontSize: '0.78rem', color: 'var(--accent)',
              }}>
              Open original →
            </a>
            <div style={{
              fontSize: '0.84rem', lineHeight: 1.6, color: 'var(--text-dim)',
              whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            }}>
              {detail.snippet.replace(/<\/?mark>/g, '')}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const inputStyle: React.CSSProperties = {
  background: 'var(--bg-input)',
  border: '1px solid var(--border-standard)',
  borderRadius: 'var(--radius-md)',
  padding: '0 14px',
  height: 38,
  fontSize: '0.88rem',
  fontFamily: 'var(--font)',
  color: 'var(--text)',
  outline: 'none',
  flex: 1,
};

const btnStyle: React.CSSProperties = {
  background: 'var(--accent-muted)',
  color: 'var(--accent)',
  border: '1px solid rgba(88,166,255,0.15)',
  borderRadius: 'var(--radius-sm)',
  padding: '4px 12px',
  fontSize: '0.8rem',
  fontWeight: 500,
  cursor: 'pointer',
  fontFamily: 'var(--font)',
};

const pageBtnStyle = (disabled: boolean): React.CSSProperties => ({
  background: 'var(--bg-card)',
  color: disabled ? 'var(--text-faint)' : 'var(--text-dim)',
  border: '1px solid var(--border-standard)',
  borderRadius: 'var(--radius-sm)',
  padding: '4px 10px',
  fontSize: '0.82rem',
  cursor: disabled ? 'default' : 'pointer',
  fontFamily: 'var(--font)',
  transition: 'background 0.1s',
});
