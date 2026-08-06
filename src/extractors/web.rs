//! Web article extractor using readability.

use anyhow::Result;
use async_trait::async_trait;
use std::io::Cursor;
use url::Url;

use crate::core::{Entry, EntryId, Extractor, SourceType};

pub struct WebExtractor;

#[async_trait]
impl Extractor for WebExtractor {
    fn can_handle(&self, _url: &Url) -> bool {
        // Web is the catch-all — always returns true.
        // It must be registered LAST in the extractor chain.
        true
    }

    async fn extract(&self, client: &reqwest::Client, url: &Url) -> Result<Option<Entry>> {
        let response = client.get(url.as_str()).send().await?;

        // Reject non-success status codes
        if !response.status().is_success() {
            return Ok(None);
        }

        // Reject non-HTML content
        let content_type = response
            .headers()
            .get(reqwest::header::CONTENT_TYPE)
            .and_then(|v| v.to_str().ok())
            .unwrap_or("");
        if !content_type.contains("text/html") && !content_type.is_empty() {
            return Ok(None);
        }

        let html = response.text().await?;

        // Run readability extraction
        let mut cursor = Cursor::new(html.as_bytes());
        let product = readability::extractor::extract(&mut cursor, url)?;

        // Reject empty or near-empty content
        let text = product.text.trim().to_string();
        if text.len() < 50 {
            return Ok(None);
        }

        let id = EntryId(slugify(&product.title));

        Ok(Some(Entry {
            id,
            source_url: url.to_string(),
            title: product.title,
            content: text,
            source_type: SourceType::Web,
            tags: Vec::new(),
            created_at: chrono::Utc::now(),
        }))
    }

    fn name(&self) -> &'static str {
        "web"
    }
}

/// Generate a URL-safe slug from a title.
fn slugify(title: &str) -> String {
    let slug = title.to_lowercase();
    let slug: String = slug
        .chars()
        .map(|c| if c.is_alphanumeric() || c == '-' || c == ' ' { c } else { ' ' })
        .collect();
    let slug: Vec<&str> = slug.split_whitespace().collect();
    let slug = slug.join("-");
    if slug.len() > 64 {
        slug[..64].to_string()
    } else if slug.is_empty() {
        "untitled".to_string()
    } else {
        slug
    }
}
