//! Reddit extractor — JSON API (no auth).
//!
//! ## Strategy
//!
//! 1. **Primary (`extract`)**: Fetch `reddit.com/r/{sub}/comments/{id}.json`.
//!    Returns post title, body, author, score, and top comments. No auth.
//! 2. **Enrichment (`enrich`)**: No-op — JSON API already returns rich content.

use anyhow::Result;
use async_trait::async_trait;
use serde::Deserialize;
use url::Url;

use crate::core::{Entry, EntryId, Extractor, SourceType};

pub struct RedditExtractor;

#[async_trait]
impl Extractor for RedditExtractor {
    fn can_handle(&self, url: &Url) -> bool {
        url.host_str().unwrap_or("").contains("reddit.com")
    }

    async fn extract(&self, client: &reqwest::Client, url: &Url) -> Result<Option<Entry>> {
        let post_id = match extract_post_id(url) {
            Some(id) => id,
            None => return Ok(None),
        };

        let api_url = format!("https://www.reddit.com/comments/{post_id}.json");
        let response = client
            .get(&api_url)
            .header("User-Agent", USER_AGENT)
            .send()
            .await?;

        if !response.status().is_success() {
            return Ok(None);
        }

        let data: Vec<RedditListing> = response.json().await?;
        let post_data = match data.first() {
            Some(listing) => &listing.data.children,
            None => return Ok(None),
        };

        let post = match post_data.first() {
            Some(child) => &child.data,
            None => return Ok(None),
        };

        // Reject deleted/removed posts
        if post.selftext == "[removed]" && post.author == "[deleted]" {
            return Ok(None);
        }

        let title = post.title.clone();
        let content = format_post(post, &data);

        let id = EntryId(slugify(&title));

        Ok(Some(Entry {
            id,
            source_url: url.to_string(),
            title,
            content,
            source_type: SourceType::Reddit,
            tags: Vec::new(),
            created_at: chrono::Utc::now(),
        }))
    }

    fn name(&self) -> &'static str {
        "reddit"
    }
}

const USER_AGENT: &str = "Mozilla/5.0 (compatible; Pliny/0.1; +https://github.com/brsbyrk/pliny)";

// ── URL parsing ────────────────────────────────────────────────

/// Extract Reddit post ID from various URL formats.
fn extract_post_id(url: &Url) -> Option<String> {
    let path = url.path();

    // Format: /r/subreddit/comments/{id}/slug
    // Format: /comments/{id}/slug
    let segments: Vec<&str> = path.split('/').filter(|s| !s.is_empty()).collect();

    if let Some(pos) = segments.iter().position(|&s| s == "comments") {
        if pos + 1 < segments.len() {
            let id = segments[pos + 1];
            if id.chars().all(|c| c.is_alphanumeric()) && id.len() >= 4 {
                return Some(id.to_string());
            }
        }
    }

    None
}

// ── Content formatting ─────────────────────────────────────────

fn format_post(post: &RedditPost, data: &[RedditListing]) -> String {
    let mut content = String::new();

    // Header: subreddit + author + score
    content.push_str(&format!(
        "r/{}  •  u/{}  •  ▲{}  •  💬{} comments\n\n",
        post.subreddit,
        post.author,
        post.score,
        post.num_comments
    ));

    // Post body
    let body = if post.selftext.is_empty() { "[no text]" } else { &post.selftext };
    content.push_str(body);
    content.push_str("\n\n---\n\n");

    // Top comments (from second listing)
    if let Some(comments_listing) = data.get(1) {
        let comments: Vec<&RedditChild> = comments_listing
            .data
            .children
            .iter()
            .filter(|c| c.kind == "t1") // t1 = comment
            .take(5)
            .collect();

        if !comments.is_empty() {
            content.push_str("Comments:\n\n");
            for comment in comments {
                content.push_str(&format!(
                    "u/{} ({} pts):\n{}\n\n",
                    comment.data.author,
                    comment.data.score,
                    comment.data.body
                ));
            }
        }
    }

    content.trim().to_string()
}

// ── Slug ───────────────────────────────────────────────────────

fn slugify(text: &str) -> String {
    let slug = text.to_lowercase();
    let slug: String = slug
        .chars()
        .map(|c| if c.is_alphanumeric() || c == '-' || c == ' ' { c } else { ' ' })
        .collect();
    let slug: Vec<&str> = slug.split_whitespace().collect();
    let slug = slug.join("-");
    if slug.len() > 64 { slug[..64].to_string() }
    else if slug.is_empty() { "untitled".to_string() }
    else { slug }
}

// ── Reddit JSON types ──────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct RedditListing {
    data: RedditListingData,
}

#[derive(Debug, Deserialize)]
struct RedditListingData {
    children: Vec<RedditChild>,
}

#[derive(Debug, Deserialize)]
struct RedditChild {
    kind: String,
    data: RedditPost,
}

#[derive(Debug, Deserialize, Clone)]
struct RedditPost {
    title: String,
    #[serde(default)]
    selftext: String,
    #[serde(default)]
    author: String,
    #[serde(default)]
    score: i64,
    #[serde(default)]
    num_comments: i64,
    #[serde(default)]
    subreddit: String,
    #[serde(default)]
    permalink: String,
    #[serde(default)]
    body: String,
}

// ── Tests ───────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extract_post_id_from_comments_url() {
        let url = Url::parse("https://www.reddit.com/r/rust/comments/abc123/some_post/").unwrap();
        assert_eq!(extract_post_id(&url).unwrap(), "abc123");
    }

    #[test]
    fn extract_post_id_short_comments_path() {
        let url = Url::parse("https://reddit.com/comments/xyz789/title").unwrap();
        assert_eq!(extract_post_id(&url).unwrap(), "xyz789");
    }

    #[test]
    fn extract_post_id_old_reddit() {
        let url = Url::parse("https://old.reddit.com/r/programming/comments/def456/").unwrap();
        assert_eq!(extract_post_id(&url).unwrap(), "def456");
    }

    #[test]
    fn extract_post_id_no_comments() {
        let url = Url::parse("https://reddit.com/r/rust").unwrap();
        assert!(extract_post_id(&url).is_none());
    }

    #[test]
    fn format_post_includes_subreddit_and_score() {
        let post = RedditPost {
            title: "Test Post".into(),
            selftext: "Body text here.".into(),
            author: "testuser".into(),
            score: 42,
            num_comments: 5,
            subreddit: "rust".into(),
            permalink: "/r/rust/comments/abc/test_post/".into(),
            body: String::new(),
        };
        let content = format_post(&post, &[]);
        assert!(content.contains("r/rust"));
        assert!(content.contains("u/testuser"));
        assert!(content.contains("▲42"));
        assert!(content.contains("Body text here"));
    }

    #[test]
    fn format_post_with_comments() {
        let post = RedditPost {
            title: "Post with comments".into(),
            selftext: "OP text".into(),
            author: "op".into(),
            score: 10,
            num_comments: 2,
            subreddit: "test".into(),
            permalink: String::new(),
            body: String::new(),
        };
        let listing = vec![
            RedditListing { data: RedditListingData { children: vec![] } },
            RedditListing {
                data: RedditListingData {
                    children: vec![
                        RedditChild {
                            kind: "t1".into(),
                            data: RedditPost {
                                title: String::new(),
                                selftext: String::new(),
                                author: "commenter1".into(),
                                score: 5,
                                num_comments: 0,
                                subreddit: String::new(),
                                permalink: String::new(),
                                body: "Great insight!".into(),
                            },
                        },
                    ],
                },
            },
        ];
        let content = format_post(&post, &listing);
        assert!(content.contains("Comments:"));
        assert!(content.contains("u/commenter1"));
        assert!(content.contains("Great insight!"));
    }

    #[test]
    fn format_post_no_text() {
        let post = RedditPost {
            title: "Link post".into(),
            selftext: String::new(),
            author: "poster".into(),
            score: 100,
            num_comments: 10,
            subreddit: "news".into(),
            permalink: String::new(),
            body: String::new(),
        };
        let content = format_post(&post, &[]);
        assert!(content.contains("[no text]"));
    }
}
