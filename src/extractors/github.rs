//! GitHub extractor — raw README primary + API fallback.
//!
//! ## Strategy
//!
//! 1. **Primary (`extract`)**: Fetch raw README from `raw.githubusercontent.com`.
//!    Try `main` branch first, then `master`. If both fail, try GitHub API
//!    for repo description.
//! 2. **Enrichment (`enrich`)**: GitHub API for stars, description, topics.

use anyhow::Result;
use async_trait::async_trait;
use serde::Deserialize;
use url::Url;

use crate::core::{Entry, EntryId, Extractor, SourceType};

pub struct GitHubExtractor;

#[async_trait]
impl Extractor for GitHubExtractor {
    fn can_handle(&self, url: &Url) -> bool {
        url.host_str().unwrap_or("").contains("github.com")
    }

    async fn extract(&self, client: &reqwest::Client, url: &Url) -> Result<Option<Entry>> {
        let (owner, repo) = match parse_owner_repo(url) {
            Some(pair) => pair,
            None => return Ok(None),
        };

        let title = format!("{owner}/{repo}");

        // Try raw README from main branch
        let readme_url = format!("https://raw.githubusercontent.com/{owner}/{repo}/main/README.md");
        if let Some(content) = fetch_text(client, &readme_url).await {
            return Ok(build_entry(&title, &content, url));
        }

        // Fallback: try master branch
        let readme_url = format!("https://raw.githubusercontent.com/{owner}/{repo}/master/README.md");
        if let Some(content) = fetch_text(client, &readme_url).await {
            return Ok(build_entry(&title, &content, url));
        }

        // Fallback: GitHub API for repo description
        let api_url = format!("https://api.github.com/repos/{owner}/{repo}");
        if let Some(desc) = fetch_repo_description(client, &api_url).await {
            if !desc.is_empty() {
                return Ok(build_entry(&title, &desc, url));
            }
        }

        Ok(None)
    }

    async fn enrich(&self, client: &reqwest::Client, entry: &mut Entry) -> Result<()> {
        let (owner, repo) = match parse_owner_repo_str(&entry.source_url) {
            Some(pair) => pair,
            None => return Ok(()),
        };

        let api_url = format!("https://api.github.com/repos/{owner}/{repo}");
        let response = client
            .get(&api_url)
            .header("User-Agent", USER_AGENT)
            .header("Accept", "application/vnd.github.v3+json")
            .send()
            .await?;

        if !response.status().is_success() {
            return Ok(());
        }

        let repo: GitHubRepo = response.json().await?;

        // Enrich content with stars, language, description
        let mut extra = String::new();
        if let Some(desc) = &repo.description {
            extra.push_str(&format!("Description: {desc}\n"));
        }
        if let Some(lang) = &repo.language {
            extra.push_str(&format!("Language: {lang}\n"));
        }
        extra.push_str(&format!(
            "⭐ {}  🍴 {}",
            repo.stargazers_count, repo.forks_count
        ));

        entry.content = format!("{}\n\n---\n{extra}", entry.content);
        Ok(())
    }

    fn name(&self) -> &'static str {
        "github"
    }
}

const USER_AGENT: &str = "Mozilla/5.0 (compatible; Pliny/0.1; +https://github.com/brsbyrk/pliny)";

// ── Helpers ────────────────────────────────────────────────────

/// Parse owner/repo from a GitHub URL.
/// Returns None for non-repo URLs (profile pages, explore, etc.).
fn parse_owner_repo(url: &Url) -> Option<(String, String)> {
    let path = url.path().trim_start_matches('/');
    let segments: Vec<&str> = path.split('/').filter(|s| !s.is_empty()).collect();

    // Must have at least owner/repo
    if segments.len() < 2 {
        return None;
    }

    // Skip non-repo paths
    let skip_prefixes = [
        "explore", "settings", "notifications", "marketplace",
        "topics", "trending", "collections", "events", "sponsors",
        "codespaces", "organizations",
    ];
    if skip_prefixes.contains(&segments[0]) {
        return None;
    }

    Some((segments[0].to_string(), segments[1].to_string()))
}

fn parse_owner_repo_str(url_str: &str) -> Option<(String, String)> {
    let url = Url::parse(url_str).ok()?;
    parse_owner_repo(&url)
}

/// Fetch text content from a URL, returning None on any failure.
async fn fetch_text(client: &reqwest::Client, url: &str) -> Option<String> {
    let response = client.get(url).send().await.ok()?;
    if !response.status().is_success() {
        return None;
    }
    response.text().await.ok()
}

/// Fetch repo description from GitHub API.
async fn fetch_repo_description(client: &reqwest::Client, url: &str) -> Option<String> {
    let response = client
        .get(url)
        .header("User-Agent", USER_AGENT)
        .header("Accept", "application/vnd.github.v3+json")
        .send()
        .await
        .ok()?;

    if !response.status().is_success() {
        return None;
    }

    #[derive(Deserialize)]
    struct ApiRepo {
        description: Option<String>,
    }

    let repo: ApiRepo = response.json().await.ok()?;
    repo.description
}

fn build_entry(title: &str, content: &str, url: &Url) -> Option<Entry> {
    let id = EntryId(slugify(title));
    Some(Entry {
        id,
        source_url: url.to_string(),
        title: title.to_string(),
        content: content.to_string(),
        source_type: SourceType::GitHub,
        tags: Vec::new(),
        created_at: chrono::Utc::now(),
    })
}

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

// ── API types ──────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct GitHubRepo {
    description: Option<String>,
    language: Option<String>,
    #[serde(default)]
    stargazers_count: u64,
    #[serde(default)]
    forks_count: u64,
}

// ── Tests ───────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_owner_repo_from_url() {
        let url = Url::parse("https://github.com/brsbyrk/pliny").unwrap();
        let (owner, repo) = parse_owner_repo(&url).unwrap();
        assert_eq!(owner, "brsbyrk");
        assert_eq!(repo, "pliny");
    }

    #[test]
    fn parse_owner_repo_with_trailing_slash() {
        let url = Url::parse("https://github.com/rust-lang/rust/").unwrap();
        let (owner, repo) = parse_owner_repo(&url).unwrap();
        assert_eq!(owner, "rust-lang");
        assert_eq!(repo, "rust");
    }

    #[test]
    fn parse_rejects_profile_url() {
        let url = Url::parse("https://github.com/brsbyrk").unwrap();
        assert!(parse_owner_repo(&url).is_none());
    }

    #[test]
    fn parse_rejects_explore() {
        let url = Url::parse("https://github.com/explore").unwrap();
        assert!(parse_owner_repo(&url).is_none());
    }

    #[test]
    fn parse_rejects_settings() {
        let url = Url::parse("https://github.com/settings/profile").unwrap();
        assert!(parse_owner_repo(&url).is_none());
    }

    #[test]
    fn slugify_owner_repo() {
        assert_eq!(slugify("brsbyrk/pliny"), "brsbyrk-pliny");
    }
}
