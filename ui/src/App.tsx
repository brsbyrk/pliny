import { useState, useEffect, useCallback, useRef } from 'react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { Search, Plus, Sun, Moon, X, ExternalLink } from 'lucide-react';

interface Entry {
  id: string;
  title: string;
  source_url: string;
  source_type: string;
  created_at: string;
  snippet: string;
  tags?: string[];
}

interface Stats { total_entries: number; }

const API = '';
const PER_PAGE = 24;
const SOURCE_TYPES = ['all', 'web', 'x', 'youtube', 'github', 'reddit'] as const;
type SourceFilter = (typeof SOURCE_TYPES)[number];
type Theme = 'dark' | 'light';

const SRC_LABELS: Record<string, string> = { x: 'X', youtube: 'YT', github: 'GH', reddit: 'Reddit', web: 'Web', feed: 'Feed' };

function timeAgo(iso: string) {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'now';
  if (mins < 60) return `${mins}m`;
  const h = Math.floor(mins / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

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
    return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  });
  const searchRef = useRef<HTMLInputElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  // Theme: apply + listen to system changes
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('pliny-theme', theme);
  }, [theme]);

  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: light)');
    const handler = (e: MediaQueryListEvent) => {
      if (!localStorage.getItem('pliny-theme')) setTheme(e.matches ? 'light' : 'dark');
    };
    mq.addEventListener('change', handler);
    return () => mq.removeEventListener('change', handler);
  }, []);

  const showToast = (msg: string) => { setToast(msg); setTimeout(() => setToast(null), 3000); };

  const fetchEntries = useCallback(async (q = '', pg = 1) => {
    setLoading(true);
    try {
      const p = new URLSearchParams({ q, limit: String(PER_PAGE), page: String(pg) });
      const r = await fetch(`${API}/api/entries?${p}`);
      const d = await r.json();
      setEntries(d.entries || []);
    } catch { /* */ }
    finally { setLoading(false); }
  }, []);

  const fetchStats = useCallback(async () => {
    try { const r = await fetch(`${API}/api/stats`); setStats(await r.json()); } catch { /* */ }
  }, []);

  useEffect(() => { fetchEntries(); fetchStats(); }, [fetchEntries, fetchStats]);

  // Debounced live search
  const onQueryChange = (value: string) => {
    setQuery(value);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setPage(1);
      fetchEntries(value, 1);
    }, 300);
  };

  const doSearch = (e: React.FormEvent) => {
    e.preventDefault();
    clearTimeout(debounceRef.current);
    setPage(1);
    fetchEntries(query, 1);
  };

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
      } else { showToast('No content found'); }
    } catch { showToast('Error'); }
    finally { setCapturing(false); }
  };

  const openDetail = async (entry: Entry) => {
    setDetail(entry); setDetailContent(null);
    try {
      const r = await fetch(`${API}/api/entry/${entry.id}`);
      if (r.ok) {
        const d = await r.json();
        setDetailContent(d.content && d.content.length > 0 ? d.content : entry.snippet);
      } else {
        setDetailContent(entry.snippet);
      }
    } catch { setDetailContent(entry.snippet); }
  };

  const filtered = sourceFilter === 'all' ? entries : entries.filter(e => e.source_type === sourceFilter);

  // Keyboard shortcuts
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setDetail(null); setDetailContent(null); setCaptureOpen(false); }
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') { e.preventDefault(); searchRef.current?.focus(); }
      if (e.key === '/' && document.activeElement !== searchRef.current) {
        e.preventDefault(); searchRef.current?.focus(); searchRef.current?.select();
      }
    };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, []);

  return (
    <div className="max-w-3xl mx-auto px-5 py-5 pb-20">
      {/* Header */}
      <header className="flex items-center justify-between pb-3 mb-4 border-b">
        <div className="flex items-baseline gap-3">
          <h1 className="font-mono text-lg font-semibold tracking-tight text-primary">Pliny</h1>
          {stats != null && (
            <span className="text-xs text-muted-foreground tabular-nums">
              {stats.total_entries} {stats.total_entries === 1 ? 'entry' : 'entries'}
            </span>
          )}
        </div>
        <div className="flex gap-2">
          <Button variant="default" size="sm" onClick={() => setCaptureOpen(!captureOpen)}>
            {captureOpen ? <X className="h-3.5 w-3.5" /> : <Plus className="h-3.5 w-3.5" />}
            {captureOpen ? '' : 'Capture'}
          </Button>
          <Button
            variant="ghost" size="icon"
            onClick={() => {
              localStorage.removeItem('pliny-theme');
              setTheme(t => t === 'dark' ? 'light' : 'dark');
            }}
            title={`Switch to ${theme === 'dark' ? 'light' : 'dark'} mode`}
          >
            {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </div>
      </header>

      {/* Capture form */}
      {captureOpen && (
        <form onSubmit={doCapture} className="flex gap-2 mb-4 animate-fade-in">
          <Input
            type="url" value={captureUrl} onChange={e => setCaptureUrl(e.target.value)}
            placeholder="Paste a URL to capture..." autoFocus
          />
          <Button type="submit" disabled={capturing || !captureUrl.trim()} size="sm">
            {capturing ? 'Saving...' : 'Save'}
          </Button>
        </form>
      )}

      {/* Search */}
      <form onSubmit={doSearch} className="mb-3">
        <div className="relative">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground pointer-events-none" />
          <Input
            ref={searchRef}
            type="text"
            value={query}
            onChange={e => onQueryChange(e.target.value)}
            placeholder="Search your knowledge..."
            className="pl-9 pr-16"
            autoFocus
          />
          <kbd className="absolute right-3 top-1/2 -translate-y-1/2 text-[10px] text-muted-foreground/40 pointer-events-none hidden sm:inline">
            /
          </kbd>
        </div>
      </form>

      {/* Source filters */}
      <div className="flex gap-1.5 mb-5 flex-wrap">
        {SOURCE_TYPES.map(t => (
          <Badge
            key={t}
            variant={sourceFilter === t ? 'default' : 'outline'}
            className="cursor-pointer select-none"
            onClick={() => { setSourceFilter(t); setPage(1); }}
          >
            {t === 'all' ? 'All' : SRC_LABELS[t] || t}
          </Badge>
        ))}
      </div>

      {/* Content */}
      {loading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <Skeleton key={i} className="h-[72px] w-full rounded-lg" />
          ))}
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 text-muted-foreground">
          <div className="text-2xl mb-3 opacity-30">
            {query ? '🔍' : sourceFilter !== 'all' ? '📂' : '📚'}
          </div>
          <p className="text-sm font-medium mb-1">
            {query
              ? 'Nothing found'
              : sourceFilter !== 'all'
              ? `No ${SRC_LABELS[sourceFilter] || sourceFilter} entries yet`
              : 'Your knowledge base is empty'}
          </p>
          <p className="text-xs max-w-xs mx-auto">
            {query
              ? 'Try broadening your search or clear the filter.'
              : sourceFilter !== 'all'
              ? `Capture a ${SRC_LABELS[sourceFilter]} URL to see it here.`
              : 'Click Capture above, paste a URL, or use the browser extension.'}
          </p>
        </div>
      ) : (
        <>
          <div className="flex flex-col gap-2">
            {filtered.map(entry => (
              <Card
                key={entry.id}
                className="cursor-pointer transition-colors animate-fade-in hover:bg-accent/40"
                onClick={() => openDetail(entry)}
              >
                <CardContent className="p-3 flex gap-3 items-start">
                  <Badge variant="outline" className="h-5 w-5 p-0 flex items-center justify-center shrink-0 mt-0.5 text-[10px] select-none">
                    {SRC_LABELS[entry.source_type]?.substring(0, 1) || 'W'}
                  </Badge>
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium leading-snug truncate mb-1">
                      {entry.title}
                    </div>
                    <div
                      className="text-xs text-muted-foreground leading-relaxed line-clamp-2"
                      dangerouslySetInnerHTML={{ __html: entry.snippet }}
                    />
                    {entry.tags && entry.tags.length > 0 && (
                      <div className="flex gap-1 mt-1.5 flex-wrap">
                        {entry.tags.map(t => (
                          <Badge key={t} variant="secondary" className="text-[10px] px-1.5 py-0">{t}</Badge>
                        ))}
                      </div>
                    )}
                  </div>
                  <span className="text-[10px] text-muted-foreground/50 whitespace-nowrap mt-1 tabular-nums">
                    {timeAgo(entry.created_at)}
                  </span>
                </CardContent>
              </Card>
            ))}
          </div>
          {entries.length >= PER_PAGE && (
            <div className="flex justify-center gap-2 mt-5 pt-4 border-t">
              <Button
                variant="outline" size="sm"
                onClick={() => { const p = Math.max(1, page - 1); setPage(p); fetchEntries(query, p); }}
                disabled={page <= 1}
              >
                Prev
              </Button>
              <span className="text-xs text-muted-foreground flex items-center tabular-nums">
                Page {page}
              </span>
              <Button
                variant="outline" size="sm"
                onClick={() => { const p = page + 1; setPage(p); fetchEntries(query, p); }}
                disabled={entries.length < PER_PAGE}
              >
                Next
              </Button>
            </div>
          )}
        </>
      )}

      {/* Detail dialog */}
      <Dialog open={!!detail} onOpenChange={(open) => { if (!open) { setDetail(null); setDetailContent(null); } }}>
        <DialogContent className="max-w-lg max-h-[80vh] overflow-y-auto">
          {detail && (
            <>
              <DialogHeader>
                <DialogTitle className="pr-6">{detail.title}</DialogTitle>
              </DialogHeader>
              <div className="space-y-3">
                <div className="flex gap-2 items-center text-xs text-muted-foreground">
                  <Badge variant="outline" className="text-[10px]">
                    {SRC_LABELS[detail.source_type] || detail.source_type}
                  </Badge>
                  <span>{timeAgo(detail.created_at)}</span>
                  <a
                    href={detail.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-primary hover:underline ml-auto inline-flex items-center gap-1"
                  >
                    Open <ExternalLink className="h-3 w-3" />
                  </a>
                </div>
                <div className="text-sm leading-relaxed text-foreground/80 whitespace-pre-wrap break-words">
                  {detailContent !== null
                    ? detailContent
                    : (
                      <div className="flex items-center gap-2 opacity-40">
                        <div className="h-3 w-3 border-2 border-current border-t-transparent rounded-full animate-spin" />
                        Loading content...
                      </div>
                    )}
                </div>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* Toast */}
      {toast && (
        <div className="fixed bottom-8 left-1/2 -translate-x-1/2 z-[200] bg-card border rounded-lg px-5 py-2 text-sm shadow-lg animate-fade-in select-none">
          {toast}
        </div>
      )}
    </div>
  );
}
