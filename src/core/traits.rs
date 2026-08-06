//! The Extractor trait — every source type implements this.

use anyhow::Result;
use async_trait::async_trait;
use url::Url;

use super::types::Entry;

/// A content extractor for a specific source type.
///
/// Each extractor is a stateless unit struct implementing this trait.
/// The orchestrator iterates through registered extractors in order —
/// the first one that `can_handle` the URL wins.
///
/// ## Extraction lifecycle
///
/// 1. `can_handle()` — does this extractor own this URL?
/// 2. `extract()` — **primary extraction.** Must always work with minimal
///    external dependencies. Returns `Ok(None)` if the source is dead,
///    unavailable, or has no meaningful content.
/// 3. `enrich()` — **optional enrichment.** Best-effort. May add richer
///    data (thread assembly, media URLs, engagement counts) from
///    external APIs. Failure is silent — the primary extraction
///    result is always preserved. Default is a no-op.
#[async_trait]
pub trait Extractor: Send + Sync {
    /// Can this extractor handle the given URL?
    fn can_handle(&self, url: &Url) -> bool;

    /// Primary extraction — minimal dependencies, must always work.
    ///
    /// Returns `Ok(None)` if the source has no extractable content.
    async fn extract(&self, client: &reqwest::Client, url: &Url) -> Result<Option<Entry>>;

    /// Optional enrichment — best-effort enhancement of the entry.
    ///
    /// Called after successful `extract()`. Failure is silent —
    /// the entry from `extract()` is preserved regardless.
    /// Default implementation is a no-op.
    async fn enrich(&self, _client: &reqwest::Client, _entry: &mut Entry) -> Result<()> {
        Ok(())
    }

    /// Human-readable name for logging and statistics.
    fn name(&self) -> &'static str;
}
