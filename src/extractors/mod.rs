//! Content extractors — each source type has its own module.
//!
//! Extractors are registered in order. The first extractor that
//! `can_handle` a URL wins. Web is always last (catch-all).

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

/// Run the extractor pipeline: find the right extractor, fetch content, return Entry.
pub async fn extract(client: &reqwest::Client, url_str: &str) -> Result<Option<Entry>> {
    let url = Url::parse(url_str)?;
    for ext in registry() {
        if ext.can_handle(&url) {
            return ext.extract(client, &url).await;
        }
    }
    // Fallback: treat as web
    WebExtractor.extract(client, &url).await
}
