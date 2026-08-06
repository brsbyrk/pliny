//! YouTube extractor — oembed metadata + timedtext captions.
//!
//! ## Strategy (no external dependencies)
//!
//! 1. **Primary (`extract`)**: YouTube oembed API for title, author, description.
//!    Also tries to fetch auto-generated captions via timedtext API.
//! 2. **Enrichment (`enrich`)**: No-op — primary already does everything.

use anyhow::Result;
use async_trait::async_trait;
use serde::Deserialize;
use url::Url;

use crate::core::{Entry, EntryId, Extractor, SourceType};

pub struct YouTubeExtractor;

#[async_trait]
impl Extractor for YouTubeExtractor {
    fn can_handle(&self, url: &Url) -> bool {
        let host = url.host_str().unwrap_or("");
        host.contains("youtube.com") || host.contains("youtu.be")
    }

    async fn extract(&self, client: &reqwest::Client, url: &Url) -> Result<Option<Entry>> {
        let video_id = match extract_video_id(url) {
            Some(id) => id,
            None => return Ok(None),
        };

        // 1. Fetch oembed metadata
        let oembed_url = format!(
            "https://www.youtube.com/oembed?url=https://www.youtube.com/watch?v={video_id}&format=json"
        );
        let oembed: OEmbed = client.get(&oembed_url).send().await?.json().await?;

        let title = oembed.title.clone();
        let author = oembed.author_name.clone();

        // 2. Try to fetch auto-generated captions (best-effort)
        let transcript = fetch_transcript(client, &video_id).await;

        // Build content
        let mut content = format!(
            "{author}\n\n{oembed_desc}",
            author = format!("{author} (@YouTube)"),
            oembed_desc = if transcript.is_some() {
                String::new()
            } else {
                format!("Description: {}\n\n[No transcript available]", 
                    oembed.description.as_deref().unwrap_or("(no description)"))
            }
        );

        if let Some(transcript) = transcript {
            content = format!(
                "{author} (@YouTube)\n\n{desc}\n\n---\n\nTranscript:\n\n{transcript}",
                author = author,
                desc = oembed.description.as_deref().unwrap_or("(no description)"),
                transcript = transcript
            );
        }

        let id = EntryId(slugify(&title));

        Ok(Some(Entry {
            id,
            source_url: url.to_string(),
            title,
            content,
            source_type: SourceType::YouTube,
            tags: Vec::new(),
            created_at: chrono::Utc::now(),
        }))
    }

    fn name(&self) -> &'static str {
        "youtube"
    }
}

const USER_AGENT: &str = "Mozilla/5.0 (compatible; Pliny/0.1; +https://github.com/brsbyrk/pliny)";

// ── Video ID extraction ────────────────────────────────────────

fn extract_video_id(url: &Url) -> Option<String> {
    let host = url.host_str()?;

    // youtu.be/{id}
    if host.contains("youtu.be") {
        return url.path().trim_start_matches('/').split('?').next()
            .filter(|s| !s.is_empty() && s.len() >= 11)
            .map(|s| s.to_string());
    }

    // youtube.com/watch?v={id}
    // youtube.com/shorts/{id}
    if host.contains("youtube.com") {
        let path = url.path();

        // /shorts/{id}
        if path.starts_with("/shorts/") {
            return path.trim_start_matches("/shorts/").split('/').next()
                .filter(|s| !s.is_empty())
                .map(|s| s.to_string());
        }

        // /watch?v={id}
        for (key, value) in url.query_pairs() {
            if key == "v" {
                return Some(value.to_string());
            }
        }
    }

    None
}

// ── Transcript fetching (timedtext API) ─────────────────────────

async fn fetch_transcript(client: &reqwest::Client, video_id: &str) -> Option<String> {
    // YouTube's timedtext API for auto-generated English captions
    let url = format!(
        "https://www.youtube.com/watch?v={video_id}"
    );

    // Fetch the watch page to find the caption track URL
    let html = client
        .get(&url)
        .header("User-Agent", USER_AGENT)
        .send().await.ok()?
        .text().await.ok()?;

    // Extract the caption track URL from player_response JSON
    // YouTube embeds this in ytInitialPlayerResponse
    let caption_url = extract_caption_url(&html)?;

    // Fetch and parse the caption XML
    let xml = client
        .get(&caption_url)
        .header("User-Agent", USER_AGENT)
        .send().await.ok()?
        .text().await.ok()?;

    Some(parse_timedtext(&xml))
}

/// Extract the first English caption track URL from ytInitialPlayerResponse.
///
/// This is the same approach yt-dlp uses: parse the player response JSON
/// embedded in the watch page, navigate to caption tracks, pick English.
fn extract_caption_url(html: &str) -> Option<String> {
    // Find the ytInitialPlayerResponse JSON blob
    let marker = "var ytInitialPlayerResponse = ";
    let start = html.find(marker)? + marker.len();
    let slice = &html[start..];

    // Find the closing marker
    let end = slice.find(";</script>")
        .or_else(|| slice.find("};var "))?;
    let json_str = &slice[..end];

    // Parse the full JSON structure
    let player_response: serde_json::Value = serde_json::from_str(json_str).ok()?;

    // Navigate: captions → playerCaptionsTracklistRenderer → captionTracks
    let tracks = player_response
        .get("captions")?
        .get("playerCaptionsTracklistRenderer")?
        .get("captionTracks")?
        .as_array()?;

    // Find first English track (languageCode "en" or "en-US", etc.)
    for track in tracks {
        let lang = track.get("languageCode")?.as_str()?;
        if lang.starts_with("en") {
            return track.get("baseUrl")?.as_str().map(|s| s.to_string());
        }
    }

    None
}

/// Parse YouTube timedtext XML into plain text.
fn parse_timedtext(xml: &str) -> String {
    // Simple regex-based parsing — faster than full XML parser for this format
    let re = regex::Regex::new(r#"<text[^>]*>(.*?)</text>"#).unwrap();
    let mut lines: Vec<String> = Vec::new();

    for cap in re.captures_iter(xml) {
        if let Some(text) = cap.get(1) {
            let decoded = decode_xml_entities(text.as_str());
            let trimmed = decoded.trim().to_string();
            if !trimmed.is_empty() {
                lines.push(trimmed);
            }
        }
    }

    lines.join(" ")
}

fn decode_xml_entities(s: &str) -> String {
    s.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", "\"")
        .replace("&#39;", "'")
        .replace("&apos;", "'")
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

// ── API types ──────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct OEmbed {
    title: String,
    #[serde(rename = "author_name")]
    author_name: String,
    #[serde(default)]
    description: Option<String>,
}

// ── Tests ───────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn extract_video_id_from_watch_url() {
        let url = Url::parse("https://www.youtube.com/watch?v=dQw4w9WgXcQ").unwrap();
        assert_eq!(extract_video_id(&url).unwrap(), "dQw4w9WgXcQ");
    }

    #[test]
    fn extract_video_id_from_short_url() {
        let url = Url::parse("https://youtu.be/dQw4w9WgXcQ").unwrap();
        assert_eq!(extract_video_id(&url).unwrap(), "dQw4w9WgXcQ");
    }

    #[test]
    fn extract_video_id_from_shorts() {
        let url = Url::parse("https://www.youtube.com/shorts/abc123def45").unwrap();
        assert_eq!(extract_video_id(&url).unwrap(), "abc123def45");
    }

    #[test]
    fn extract_video_id_with_extra_params() {
        let url = Url::parse("https://www.youtube.com/watch?v=video123&t=30&list=PLxyz").unwrap();
        assert_eq!(extract_video_id(&url).unwrap(), "video123");
    }

    #[test]
    fn extract_video_id_no_v_param() {
        let url = Url::parse("https://www.youtube.com/feed/trending").unwrap();
        assert!(extract_video_id(&url).is_none());
    }

    #[test]
    fn parse_timedtext_simple() {
        let xml = r#"<?xml version="1.0"?><transcript><text start="0.0" dur="1.5">Hello world</text><text start="1.5" dur="2.0">This is a test</text></transcript>"#;
        let text = parse_timedtext(xml);
        assert!(text.contains("Hello world"));
        assert!(text.contains("This is a test"));
    }

    #[test]
    fn parse_timedtext_with_xml_entities() {
        let xml = r#"<text start="0">Hello &amp; welcome to &lt;Rust&gt;</text>"#;
        let text = parse_timedtext(xml);
        assert!(text.contains("Hello & welcome to <Rust>"));
    }

    #[test]
    fn parse_timedtext_empty() {
        assert_eq!(parse_timedtext(""), "");
    }
}
