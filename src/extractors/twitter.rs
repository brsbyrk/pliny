//! X/Twitter extractor.
//!
//! ## Strategy (Option C: og:meta primary + fxtwitter enrichment)
//!
//! 1. **Primary (`extract`)**: Scrape `<meta property="og:description">` from the
//!    tweet page. Always works — even for deleted tweets. No external API dependency.
//! 2. **Enrichment (`enrich`)**: Call fxtwitter API (3s timeout) for thread assembly,
//!    media URLs, and engagement stats. Best-effort — failure is silent.

use anyhow::Result;
use async_trait::async_trait;
use scraper::{Html, Selector};
use serde::Deserialize;
use url::Url;

use crate::core::{Entry, EntryId, Extractor, SourceType};

pub struct XExtractor;

#[async_trait]
impl Extractor for XExtractor {
    fn can_handle(&self, url: &Url) -> bool {
        let host = url.host_str().unwrap_or("");
        host.contains("x.com") || host.contains("twitter.com")
    }

    async fn extract(&self, client: &reqwest::Client, url: &Url) -> Result<Option<Entry>> {
        let html = client
            .get(url.as_str())
            .header("User-Agent", USER_AGENT)
            .send()
            .await?
            .text()
            .await?;

        let document = Html::parse_document(&html);

        // Extract og:description — contains "Author: tweet text..."
        let og_selector = Selector::parse(r#"meta[property="og:description"]"#).unwrap();
        let og_text = document
            .select(&og_selector)
            .find_map(|el| el.value().attr("content"))
            .map(|s| s.to_string());

        let Some(og_text) = og_text else {
            return Ok(None);
        };

        // Parse "Author: tweet text" from og:description
        let (author, text) = parse_og_description(&og_text);

        // Reject empty or "this tweet is unavailable"
        if text.is_empty() || text.contains("This Tweet is unavailable") {
            return Ok(None);
        }

        // Extract og:title for the author name
        let title_selector = Selector::parse(r#"meta[property="og:title"]"#).unwrap();
        let og_title = document
            .select(&title_selector)
            .find_map(|el| el.value().attr("content"))
            .unwrap_or("Untitled");

        let title = if let Some(author) = &author {
            format!("{author}: {}", &text[..text.len().min(60)])
        } else {
            og_title.to_string()
        };

        let content = if let Some(author) = &author {
            format!("{author} (@X):\n\n{text}")
        } else {
            text.clone()
        };

        let id = EntryId(slugify(&title));

        Ok(Some(Entry {
            id,
            source_url: url.to_string(),
            title,
            content,
            source_type: SourceType::X,
            tags: Vec::new(),
            created_at: chrono::Utc::now(),
        }))
    }

    async fn enrich(&self, client: &reqwest::Client, entry: &mut Entry) -> Result<()> {
        // Extract tweet ID from URL
        let tweet_id = extract_tweet_id(&entry.source_url);
        let Some(tweet_id) = tweet_id else {
            return Ok(());
        };

        // Try fxtwitter with 3s timeout
        let api_url = format!("https://api.fxtwitter.com/status/{tweet_id}");
        let Ok(response) = tokio::time::timeout(
            std::time::Duration::from_secs(3),
            client.get(&api_url).send(),
        )
        .await
        else {
            return Ok(());
        };

        let Ok(response) = response else {
            return Ok(());
        };

        if !response.status().is_success() {
            return Ok(());
        }

        let Ok(data) = response.json::<FxTwitterResponse>().await else {
            return Ok(());
        };

        let tweet = &data.tweet;

        // Enrich title with author info
        let author_name = &tweet.author.name;
        let screen_name = &tweet.author.screen_name;
        entry.title = format!("{author_name} (@{screen_name}): {}", &tweet.text[..tweet.text.len().min(60)]);

        // Build enriched content
        let mut content = format!("{author_name} (@{screen_name}):\n\n{}\n", tweet.text);

        // Add media references
        let photos: Vec<_> = tweet.media.photos.iter().filter_map(|p| p.url.as_deref()).collect();
        if !photos.is_empty() {
            content.push_str("\n📷 Images:\n");
            for url in &photos {
                content.push_str(&format!("  {url}\n"));
            }
        }

        // Add engagement
        content.push_str(&format!(
            "\n❤️ {}  🔄 {}",
            tweet.public_metrics.like_count, tweet.public_metrics.retweet_count
        ));

        entry.content = content;

        Ok(())
    }

    fn name(&self) -> &'static str {
        "x"
    }
}

const USER_AGENT: &str = "Mozilla/5.0 (compatible; Pliny/0.1; +https://github.com/brsbyrk/pliny)";

// ── og:description parsing ──────────────────────────────────────

/// Parse "Author Name: tweet text" from og:description.
/// Returns (author, text) — author is None if no colon separator found.
fn parse_og_description(desc: &str) -> (Option<String>, String) {
    // og:description format: "Author: text of the tweet..."
    if let Some((author_part, text)) = desc.split_once(": ") {
        // Only treat as author:text if the author part looks like a name
        // (not a URL, not starting with "http", reasonable length)
        if !author_part.starts_with("http")
            && author_part.len() >= 2
            && author_part.len() <= 80
        {
            return (Some(author_part.to_string()), text.to_string());
        }
    }
    (None, desc.to_string())
}

// ── URL helpers ─────────────────────────────────────────────────

/// Extract numeric tweet ID from an X/Twitter URL.
fn extract_tweet_id(url: &str) -> Option<String> {
    let parsed = Url::parse(url).ok()?;
    let path = parsed.path();
    // Match /user/status/1234567890 or /user/status/1234567890/photo/1
    let segments: Vec<&str> = path.split('/').collect();
    if let Some(pos) = segments.iter().position(|&s| s == "status") {
        if pos + 1 < segments.len() {
            let id = segments[pos + 1];
            if id.chars().all(|c| c.is_ascii_digit()) {
                return Some(id.to_string());
            }
        }
    }
    None
}

// ── Slug generation ─────────────────────────────────────────────

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

// ── fxtwitter API types ─────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct FxTwitterResponse {
    tweet: FxTweet,
}

#[derive(Debug, Deserialize)]
struct FxTweet {
    text: String,
    author: FxAuthor,
    #[serde(default)]
    media: FxMedia,
    #[serde(default)]
    public_metrics: FxMetrics,
}

#[derive(Debug, Deserialize)]
struct FxAuthor {
    name: String,
    screen_name: String,
}

#[derive(Debug, Default, Deserialize)]
struct FxMedia {
    #[serde(default)]
    photos: Vec<FxPhoto>,
}

#[derive(Debug, Deserialize)]
struct FxPhoto {
    url: Option<String>,
}

#[derive(Debug, Default, Deserialize)]
struct FxMetrics {
    #[serde(default)]
    like_count: u64,
    #[serde(default)]
    retweet_count: u64,
}

// ── Tests ───────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_og_simple_tweet() {
        let (author, text) = parse_og_description("Andrej Karpathy: Just read this paper on transformers");
        assert_eq!(author.unwrap(), "Andrej Karpathy");
        assert_eq!(text, "Just read this paper on transformers");
    }

    #[test]
    fn parse_og_no_author() {
        let (author, text) = parse_og_description("https://example.com/article");
        assert!(author.is_none());
        assert_eq!(text, "https://example.com/article");
    }

    #[test]
    fn parse_og_long_author() {
        // Names longer than 80 chars treated as no-author
        let long = "A".repeat(81);
        let desc = format!("{long}: some text");
        let (author, _) = parse_og_description(&desc);
        assert!(author.is_none());
    }

    #[test]
    fn extract_tweet_id_from_status_url() {
        let id = extract_tweet_id("https://x.com/karpathy/status/1234567890123456789");
        assert_eq!(id.unwrap(), "1234567890123456789");
    }

    #[test]
    fn extract_tweet_id_with_trailing_path() {
        let id = extract_tweet_id("https://twitter.com/user/status/999/photo/1");
        assert_eq!(id.unwrap(), "999");
    }

    #[test]
    fn extract_tweet_id_no_status() {
        let id = extract_tweet_id("https://x.com/karpathy");
        assert!(id.is_none());
    }

    #[test]
    fn slugify_basic() {
        assert_eq!(slugify("Deep Learning 101"), "deep-learning-101");
    }

    #[test]
    fn slugify_truncates() {
        let long = "a".repeat(100);
        assert_eq!(slugify(&long).len(), 64);
    }

    // ── fxtwitter JSON deserialization ──

    #[test]
    fn deserialize_fxtwitter_response_with_media() {
        let json = r#"{
            "tweet": {
                "text": "Check out this photo!",
                "author": { "name": "Test User", "screen_name": "testuser" },
                "media": {
                    "photos": [{ "url": "https://pbs.twimg.com/media/photo.jpg" }]
                },
                "public_metrics": { "like_count": 42, "retweet_count": 7 }
            }
        }"#;

        let data: FxTwitterResponse = serde_json::from_str(json).unwrap();
        assert_eq!(data.tweet.text, "Check out this photo!");
        assert_eq!(data.tweet.author.name, "Test User");
        assert_eq!(data.tweet.author.screen_name, "testuser");
        assert_eq!(data.tweet.media.photos.len(), 1);
        assert_eq!(data.tweet.media.photos[0].url.as_deref().unwrap(), "https://pbs.twimg.com/media/photo.jpg");
        assert_eq!(data.tweet.public_metrics.like_count, 42);
        assert_eq!(data.tweet.public_metrics.retweet_count, 7);
    }

    #[test]
    fn deserialize_fxtwitter_response_no_media() {
        let json = r#"{
            "tweet": {
                "text": "Just a text tweet",
                "author": { "name": "User", "screen_name": "user" },
                "media": {},
                "public_metrics": {}
            }
        }"#;

        let data: FxTwitterResponse = serde_json::from_str(json).unwrap();
        assert_eq!(data.tweet.text, "Just a text tweet");
        assert!(data.tweet.media.photos.is_empty());
        assert_eq!(data.tweet.public_metrics.like_count, 0);
        assert_eq!(data.tweet.public_metrics.retweet_count, 0);
    }
}
