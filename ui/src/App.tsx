import { useState, useEffect, useCallback } from 'react';

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
  const now = new Date();
  const diff = now.getTime() - d.getTime();
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
      return <mark key={i}>{p.replace(/<\/?mark>/g, '')}</mark>;
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

  const fetchEntries = useCallback(async (q: string = '') => {
    setLoading(true);
    try {
      const params = new URLSearchParams();
      if (q) params.set('q', q);
      params.set('limit', '50');
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
    } catch (e) {
      // stats not critical
    }
  }, []);

  useEffect(() => {
    fetchEntries();
    fetchStats();
  }, [fetchEntries, fetchStats]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    fetchEntries(query);
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
        fetchEntries(query);
        fetchStats();
      } else {
        alert('No content found at that URL.');
      }
    } catch (e) {
      alert('Failed to ingest URL.');
    } finally {
      setIngesting(false);
    }
  };

  return (
    <div>
      {/* Header */}
      <header style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 16, paddingBottom: 12,
        borderBottom: '1px solid var(--border-subtle)',
      }}>
        <h1 style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '1.25rem', fontWeight: 650,
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
          <button
            onClick={handleIngest}
            disabled={ingesting}
            style={{
              background: 'var(--accent-muted)', color: 'var(--accent)',
              border: '1px solid rgba(88,166,255,0.2)', borderRadius: 'var(--radius-sm)',
              padding: '4px 14px', fontSize: '0.82rem', fontWeight: 500,
              cursor: 'pointer', fontFamily: 'var(--font)',
            }}
          >
            {ingesting ? '...' : '+ Capture'}
          </button>
        </div>
      </header>

      {/* Search */}
      <form onSubmit={handleSearch} style={{ marginBottom: 20 }}>
        <input
          type="text"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search your knowledge..."
          autoFocus
          style={{
            width: '100%', maxWidth: 680, display: 'block', margin: '0 auto',
            background: 'var(--bg-input)', border: '1px solid var(--border-standard)',
            borderRadius: 'var(--radius-md)', padding: '0 16px', height: 40,
            fontSize: '0.92rem', fontFamily: 'var(--font)', color: 'var(--text)',
            outline: 'none', transition: 'border-color 0.15s',
          }}
          onFocus={e => { e.target.style.borderColor = 'var(--accent)'; }}
          onBlur={e => { e.target.style.borderColor = 'var(--border-standard)'; }}
        />
      </form>

      {/* Entries */}
      {loading ? (
        <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
          {[1,2,3,4,5,6].map(i => (
            <div key={i} style={{
              background: 'var(--bg-card)', border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-md)', padding: 16, height: 120,
              opacity: 0.5, animation: 'shimmer 1.5s ease-in-out infinite',
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
        <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
          {entries.map(entry => (
            <a
              key={entry.id}
              href={entry.source_url}
              target="_blank"
              rel="noopener noreferrer"
              style={{ textDecoration: 'none', color: 'inherit' }}
            >
              <article style={{
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
              }}
              >
                <div style={{ display: 'flex', gap: 10, marginBottom: 6 }}>
                  <span style={{
                    width: 24, height: 24, borderRadius: 'var(--radius-sm)',
                    background: 'var(--bg-hover)', display: 'flex',
                    alignItems: 'center', justifyContent: 'center',
                    fontSize: '0.75rem', flexShrink: 0,
                    border: '1px solid var(--border-subtle)',
                  }}>
                    {sourceIcon(entry.source_type)}
                  </span>
                  <h3 style={{
                    fontSize: '0.88rem', fontWeight: 550, lineHeight: 1.35,
                    overflow: 'hidden', display: '-webkit-box',
                    WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                  }}>
                    {entry.title}
                  </h3>
                </div>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginBottom: 6 }}>
                  [{entry.source_type}] · {timeAgo(entry.created_at)}
                </div>
                <p style={{
                  fontSize: '0.78rem', color: 'var(--text-dim)', lineHeight: 1.45,
                  overflow: 'hidden', display: '-webkit-box',
                  WebkitLineClamp: 3, WebkitBoxOrient: 'vertical',
                }}>
                  {highlightSnippet(entry.snippet)}
                </p>
              </article>
            </a>
          ))}
        </div>
      )}
    </div>
  );
}
