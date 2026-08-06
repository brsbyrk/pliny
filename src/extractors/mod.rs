//! Content extractors — each source type has its own module.
//!
//! Extractors are registered in order. The first extractor that
//! `can_handle` a URL wins. Web is always last (catch-all).
//!
//! ## Extraction pipeline (per URL)
//!
//! 1. Find matching extractor via `can_handle()`
//! 2. Run `extract()` → primary content (always works)
//! 3. Run `enrich()` → best-effort enhancement (may fail silently)

mod github;
mod reddit;
mod twitter;
mod web;
mod youtube;

pub use github::GitHubExtractor;
pub use reddit::RedditExtractor;
pub use twitter::XExtractor;
pub use web::WebExtractor;
pub use youtube::YouTubeExtractor;

use anyhow::Result;
use url::Url;

use crate::core::{Entry, Extractor};

/// All registered extractors in priority order.
pub fn registry() -> Vec<Box<dyn Extractor>> {
    vec![
        Box::new(XExtractor),
        Box::new(YouTubeExtractor),
        Box::new(GitHubExtractor),
        Box::new(RedditExtractor),
        Box::new(WebExtractor),
    ]
}

/// Run the full extraction pipeline for a URL.
///
/// 1. Find matching extractor
/// 2. Primary extraction (must succeed)
/// 3. Best-effort enrichment (silent on failure)
pub async fn extract(client: &reqwest::Client, url_str: &str) -> Result<Option<Entry>> {
    let url = Url::parse(url_str)?;

    for ext in registry() {
        if ext.can_handle(&url) {
            let mut entry = match ext.extract(client, &url).await? {
                Some(e) => e,
                None => return Ok(None),
            };

            // Best-effort enrichment — never fails the whole pipeline.
            if let Err(e) = ext.enrich(client, &mut entry).await {
                tracing::warn!(
                    "[{}] enrichment failed (non-fatal): {e}",
                    ext.name()
                );
            }

            return Ok(Some(entry));
        }
    }

    // Fallback: web extractor as catch-all
    WebExtractor.extract(client, &url).await
}
