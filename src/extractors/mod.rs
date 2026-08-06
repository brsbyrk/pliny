//! Content extractors — each source type has its own module.
//!
//! Extractors are registered in order. The first extractor that
//! `can_handle` a URL wins. Web is always last (catch-all).

mod github;
mod reddit;
mod twitter;
mod web;
mod youtube;

use anyhow::Result;
use url::Url;

use crate::core::{Entry, Extractor};

/// All registered extractors in priority order.
pub fn registry() -> Vec<Box<dyn Extractor>> {
    vec![
        Box::new(twitter::XExtractor),
        Box::new(youtube::YouTubeExtractor),
        Box::new(github::GitHubExtractor),
        Box::new(reddit::RedditExtractor),
        Box::new(web::WebExtractor),
    ]
}

/// Run the extractor pipeline: find the right extractor, fetch content, return Entry.
pub fn extract(client: &reqwest::Client, url_str: &str) -> Result<Option<Entry>> {
    let url = Url::parse(url_str)?;
    for ext in registry() {
        if ext.can_handle(&url) {
            return ext.extract(client, &url);
        }
    }
    // Fallback: treat as web
    web::WebExtractor.extract(client, &url)
}
