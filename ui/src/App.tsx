import { useState, useEffect, useCallback } from 'react';

interface Entry {
  id: string;
  title: string;
  source_url: string;
  source_type: string;
  created_at: string;
  snippet: string;
  content?: string;
  tags?: string[];
}

interface Stats {
  total_entries: number;
}

const API = '';
const PER_PAGE = 24;

function sourceIcon(type: string): string {
  switch (type) {
    case 'x': return '𝕏';
    case 'youtube': return '▶';
    case 'github': return '⬡';
    case 'reddit': return '⬆';
    case 'web': return '🌐';
    case 'feed': return '📡';
    default: return '•';
  }
}

function timeAgo(iso: string): string {
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  return d.toLocaleDateString();
}

function highlightSnippet(snippet: string) {
  const parts = snippet.split(/(<mark>.*?<\/mark>)/g);
  return parts.map((p, i) => {
    if (p.startsWith('<mark>')) {
      return <mark key={i} style={{
        background: 'rgba(88,166,255,0.2)', color: 'var(--accent)',
        borderRadius: 2, padding: '0 2px',
      }}>{p.replace(/<\/?mark>/g, '')}</mark>;
    }
    return p;
  });
}

export default function App() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [stats, setStats] = useState<Stats | null>(null);
  const [query, setQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [ingesting, setIngesting] = useState(false);
  const [page, setPage] = useState(1);
  const [detail, setDetail] = useState<Entry | null>(null);

  const fetchEntries = useCallback(async (q: string = '', p: number = 1) => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (q) params.set('q', q);
      params.set('limit', String(PER_PAGE));
      params.set('page', String(p));
      const res = await fetch(`${API}/api/entries?${params}`);
      const data = await res.json();
      setEntries(data.entries || []);
    } catch (e) {
      console.error('Search failed:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/stats`);
      const data = await res.json();
      setStats(data);
    } catch { /* not critical */ }
  }, []);

  useEffect(() => {
    fetchEntries();
    fetchStats();
  }, [fetchEntries, fetchStats]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    setPage(1);
    fetchEntries(query, 1);
  };

  const handlePage = (p: number) => {
    setPage(p);
    fetchEntries(query, p);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleIngest = async () => {
    const url = prompt('URL to capture:');
    if (!url) return;
    setIngesting(true);
    try {
      const res = await fetch(`${API}/api/ingest/add-url`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      const data = await res.json();
      if (data.status === 'ingested') {
        fetchEntries(query, page);
        fetchStats();
      } else {
        alert('No content found at that URL.');
      }
    } catch {
      alert('Failed to ingest URL.');
    } finally {
      setIngesting(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') setDetail(null);
    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
      e.preventDefault();
      (document.querySelector('input') as HTMLInputElement)?.focus();
    }
  };

  return (
    <div onKeyDown={handleKeyDown}>
      {/* Header */}
      <header style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 16, paddingBottom: 12,
        borderBottom: '1px solid var(--border-subtle)',
      }}>
        <h1 style={{
          fontFamily: 'var(--font-mono)', fontSize: '1.25rem', fontWeight: 650,
          color: 'var(--accent)', letterSpacing: '-0.4px',
        }}>
          Pliny
        </h1>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {stats && (
            <span style={{ fontSize: '0.78rem', color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums' }}>
              {stats.total_entries} entries
            </span>
          )}
          <button onClick={handleIngest} disabled={ingesting}
            style={{
              background: 'var(--accent-muted)', color: 'var(--accent)',
              border: '1px solid rgba(88,166,255,0.2)', borderRadius: 'var(--radius-sm)',
              padding: '4px 14px', fontSize: '0.82rem', fontWeight: 500,
              cursor: 'pointer', fontFamily: 'var(--font)',
            }}>
            {ingesting ? '...' : '+ Capture'}
          </button>
        </div>
      </header>

      {/* Search */}
      <form onSubmit={handleSearch} style={{ marginBottom: 20 }}>
        <input type="text" value={query} onChange={e => setQuery(e.target.value)}
          placeholder="Search your knowledge... (⌘K to focus)"
          autoFocus
          style={{
            width: '100%', maxWidth: 680, display: 'block', margin: '0 auto',
            background: 'var(--bg-input)', border: '1px solid var(--border-standard)',
            borderRadius: 'var(--radius-md)', padding: '0 16px', height: 40,
            fontSize: '0.92rem', fontFamily: 'var(--font)', color: 'var(--text)',
            outline: 'none', transition: 'border-color 0.15s',
          }}
          onFocus={e => { e.currentTarget.style.borderColor = 'var(--accent)'; }}
          onBlur={e => { e.currentTarget.style.borderColor = 'var(--border-standard)'; }}
        />
      </form>

      {/* Content */}
      {loading ? (
        <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
          {Array.from({length: 6}).map((_, i) => (
            <div key={i} style={{
              background: 'var(--bg-card)', border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-md)', padding: 16, height: 110,
              opacity: 0.4,
            }} />
          ))}
        </div>
      ) : entries.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '64px 24px', color: 'var(--text-muted)' }}>
          <div style={{ fontSize: '2rem', marginBottom: 12, opacity: 0.4 }}>🔍</div>
          <div style={{ fontSize: '0.95rem', fontWeight: 550, color: 'var(--text-dim)', marginBottom: 6 }}>
            {query ? 'Nothing found' : 'Your knowledge base is empty'}
          </div>
          <div style={{ fontSize: '0.82rem', marginBottom: 16 }}>
            {query ? 'Try a different search term.' : 'Capture your first URL to get started.'}
          </div>
          {!query && (
            <button onClick={handleIngest}
              style={{
                background: 'var(--accent-muted)', color: 'var(--accent)',
                border: 'none', borderRadius: 'var(--radius-sm)',
                padding: '6px 20px', fontSize: '0.85rem', fontWeight: 500,
                cursor: 'pointer', fontFamily: 'var(--font)',
              }}>
              Capture a URL
            </button>
          )}
        </div>
      ) : (
        <>
          <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
            {entries.map(entry => (
              <article key={entry.id}
                onClick={() => setDetail(entry)}
                style={{
                  background: 'var(--bg-card)', border: '1px solid var(--border-subtle)',
                  borderRadius: 'var(--radius-md)', padding: '14px 16px',
                  cursor: 'pointer', transition: 'background 0.12s, border-color 0.12s',
                }}
                onMouseEnter={e => {
                  e.currentTarget.style.background = 'var(--bg-hover)';
                  e.currentTarget.style.borderColor = 'var(--border-standard)';
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.background = 'var(--bg-card)';
                  e.currentTarget.style.borderColor = 'var(--border-subtle)';
                }}>
                <div style={{ display: 'flex', gap: 10, marginBottom: 6 }}>
                  <span style={{
                    width: 24, height: 24, borderRadius: 'var(--radius-sm)',
                    background: 'var(--bg-hover)', display: 'flex',
                    alignItems: 'center', justifyContent: 'center',
                    fontSize: '0.75rem', flexShrink: 0,
                    border: '1px solid var(--border-subtle)',
                  }}>{sourceIcon(entry.source_type)}</span>
                  <h3 style={{
                    fontSize: '0.88rem', fontWeight: 550, lineHeight: 1.35,
                    overflow: 'hidden', display: '-webkit-box',
                    WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                  }}>{entry.title}</h3>
                </div>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: 6 }}>
                  [{entry.source_type}] · {timeAgo(entry.created_at)}
                </div>
                <p style={{
                  fontSize: '0.78rem', color: 'var(--text-dim)', lineHeight: 1.45,
                  overflow: 'hidden', display: '-webkit-box',
                  WebkitLineClamp: 3, WebkitBoxOrient: 'vertical',
                }}>{highlightSnippet(entry.snippet)}</p>
              </article>
            ))}
          </div>

          {/* Pagination */}
          <div style={{
            display: 'flex', justifyContent: 'center', gap: 6,
            marginTop: 24, paddingTop: 16,
            borderTop: '1px solid var(--border-subtle)',
          }}>
            <button onClick={() => handlePage(page - 1)} disabled={page <= 1}
              style={paginationBtnStyle(page <= 1)}>← Prev</button>
            <span style={{
              fontSize: '0.78rem', color: 'var(--text-muted)',
              display: 'flex', alignItems: 'center', padding: '0 8px',
              fontVariantNumeric: 'tabular-nums',
            }}>Page {page}</span>
            <button onClick={() => handlePage(page + 1)} disabled={entries.length < PER_PAGE}
              style={paginationBtnStyle(entries.length < PER_PAGE)}>Next →</button>
          </div>
        </>
      )}

      {/* Detail modal */}
      {detail && (
        <div onClick={() => setDetail(null)}
          style={{
            position: 'fixed', inset: 0, zIndex: 100,
            background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(4px)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
          <div onClick={e => e.stopPropagation()}
            style={{
              width: 680, maxWidth: '92vw', maxHeight: '85vh',
              background: 'var(--bg-card)', border: '1px solid var(--border-standard)',
              borderRadius: 'var(--radius-lg)', overflow: 'auto',
              padding: '20px 24px', boxShadow: '0 16px 48px rgba(0,0,0,0.5)',
            }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 12 }}>
              <h2 style={{ fontSize: '1rem', fontWeight: 600 }}>{detail.title}</h2>
              <button onClick={() => setDetail(null)}
                style={{
                  background: 'none', border: 'none', color: 'var(--text-dim)',
                  fontSize: '1.3rem', cursor: 'pointer', padding: 4,
                }}>×</button>
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginBottom: 16 }}>
              [{detail.source_type}] · {timeAgo(detail.created_at)} ·{' '}
              <a href={detail.source_url} target="_blank" rel="noopener noreferrer"
                style={{ color: 'var(--accent)' }}>Open original →</a>
            </div>
            <div style={{
              fontSize: '0.85rem', lineHeight: 1.6, color: 'var(--text-dim)',
              whiteSpace: 'pre-wrap', wordBreak: 'break-word',
            }}>
              {detail.content || detail.snippet}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

const paginationBtnStyle = (disabled: boolean): React.CSSProperties => ({
  background: 'var(--bg-card)', color: disabled ? 'var(--text-faint)' : 'var(--text-dim)',
  border: '1px solid var(--border-standard)', borderRadius: 'var(--radius-sm)',
  padding: '5px 14px', fontSize: '0.82rem', cursor: disabled ? 'default' : 'pointer',
  fontFamily: 'var(--font)', transition: 'background 0.1s',
});
