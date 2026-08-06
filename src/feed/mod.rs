//! RSS/Atom feed monitor — poll feeds and auto-ingest new entries.

use anyhow::Result;
use std::path::Path;
use std::time::Duration;

use crate::store::Store;

/// Monitor RSS/Atom feeds, auto-ingesting new entries.
pub struct FeedMonitor {
    feeds: Vec<String>,
    poll_interval: Duration,
}

impl FeedMonitor {
    /// Create a monitor from a feeds file (one URL per line, # comments).
    pub fn from_file(path: &Path, poll_interval_secs: u64) -> Result<Self> {
        let content = std::fs::read_to_string(path)?;
        let feeds: Vec<String> = content
            .lines()
            .map(|l| l.trim().to_string())
            .filter(|l| !l.is_empty() && !l.starts_with('#'))
            .collect();

        if feeds.is_empty() {
            anyhow::bail!("No feeds found in {}", path.display());
        }

        Ok(Self {
            feeds,
            poll_interval: Duration::from_secs(poll_interval_secs),
        })
    }

    /// Poll all feeds once and ingest new entries.
    pub async fn poll_once(&self, store: &Store) -> Result<FeedStats> {
        let client = reqwest::Client::builder()
            .user_agent("Pliny/0.1 RSS Monitor")
            .timeout(Duration::from_secs(30))
            .build()?;

        let mut stats = FeedStats::default();

        for feed_url in &self.feeds {
            match self.poll_feed(&client, store, feed_url).await {
                Ok(s) => {
                    stats.feeds_polled += 1;
                    stats.entries_found += s.entries_found;
                    stats.entries_new += s.entries_new;
                    stats.errors += s.errors;
                }
                Err(e) => {
                    tracing::warn!("Feed error [{}]: {e}", feed_url);
                    stats.errors += 1;
                }
            }
        }

        Ok(stats)
    }

    async fn poll_feed(
        &self,
        client: &reqwest::Client,
        store: &Store,
        feed_url: &str,
    ) -> Result<FeedStats> {
        let response = client.get(feed_url).send().await?;
        let body = response.text().await?;
        let feed = feed_rs::parser::parse(body.as_bytes())?;

        let mut stats = FeedStats::default();
        stats.entries_found = feed.entries.len();

        for entry in &feed.entries {
            // Get the entry URL
            let link: Option<String> = entry.links.first()
                .map(|l| l.href.clone())
                .or_else(|| {
                    if entry.id.starts_with("http") {
                        Some(entry.id.clone())
                    } else {
                        None
                    }
                });

            let Some(link) = link else { continue };

            // Dedup: skip if already in DB
            let conn = store.conn();
            let exists: bool = conn
                .query_row(
                    "SELECT COUNT(*) > 0 FROM entries WHERE source_url = ?1",
                    rusqlite::params![link],
                    |r| r.get(0),
                )
                .unwrap_or(false);

            if exists {
                continue;
            }

            // Ingest via the extractor pipeline
            match crate::extractors::extract(client, &link).await {
                Ok(Some(entry)) => {
                    if let Err(e) = store.insert(&entry) {
                        tracing::warn!("Failed to store feed entry [{}]: {e}", link);
                        stats.errors += 1;
                    } else {
                        stats.entries_new += 1;
                        tracing::info!("Feed ingest: {} [{}]", entry.title, entry.source_type.as_str());
                    }
                }
                Ok(None) => {
                    // Source has no extractable content — skip
                }
                Err(e) => {
                    tracing::warn!("Feed extraction failed [{}]: {e}", link);
                    stats.errors += 1;
                }
            }
        }

        Ok(stats)
    }

    /// Run continuous polling loop (Ctrl+C to stop).
    pub async fn run_loop(self, store: Store) -> Result<()> {
        tracing::info!(
            "RSS monitor started: {} feeds, {}s interval",
            self.feeds.len(),
            self.poll_interval.as_secs()
        );

        loop {
            let stats = self.poll_once(&store).await?;
            tracing::info!(
                "Poll: {} feeds, {} entries, {} new, {} errors",
                stats.feeds_polled,
                stats.entries_found,
                stats.entries_new,
                stats.errors
            );
            tokio::time::sleep(self.poll_interval).await;
        }
    }
}

#[derive(Debug, Default)]
pub struct FeedStats {
    pub feeds_polled: usize,
    pub entries_found: usize,
    pub entries_new: usize,
    pub errors: usize,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn from_file_parses_feeds() {
        let dir = std::env::temp_dir();
        let path = dir.join("pliny-test-feeds.txt");
        std::fs::write(&path, "# comments\nhttps://blog1.com/feed.xml\n\nhttps://blog2.com/rss\n").unwrap();

        let monitor = FeedMonitor::from_file(&path, 3600).unwrap();
        assert_eq!(monitor.feeds.len(), 2);
        assert!(monitor.feeds.contains(&"https://blog1.com/feed.xml".to_string()));
        assert!(monitor.feeds.contains(&"https://blog2.com/rss".to_string()));

        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn from_file_empty_is_error() {
        let dir = std::env::temp_dir();
        let path = dir.join("pliny-test-empty.txt");
        std::fs::write(&path, "# only comments\n").unwrap();

        let result = FeedMonitor::from_file(&path, 3600);
        assert!(result.is_err());

        let _ = std::fs::remove_file(&path);
    }

    #[test]
    fn default_stats() {
        let stats = FeedStats::default();
        assert_eq!(stats.feeds_polled, 0);
        assert_eq!(stats.entries_new, 0);
    }
}
