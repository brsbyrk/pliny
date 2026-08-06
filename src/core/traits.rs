//! The Extractor trait — every source type implements this.

use anyhow::Result;
use url::Url;

use super::types::Entry;

/// A content extractor for a specific source type.
///
/// Each extractor is a stateless unit struct implementing this trait.
/// The orchestrator iterates through registered extractors in order —
/// the first one that `can_handle` the URL wins.
pub trait Extractor: Send + Sync {
    /// Can this extractor handle the given URL?
    fn can_handle(&self, url: &Url) -> bool;

    /// Extract content from the URL.
    ///
    /// Returns `Ok(None)` if the source is dead, unavailable, or has no
    /// meaningful content (deleted tweet, 404, empty page, etc.).
    fn extract(&self, client: &reqwest::Client, url: &Url) -> Result<Option<Entry>>;

    /// Human-readable name for logging and statistics.
    fn name(&self) -> &'static str;
}
