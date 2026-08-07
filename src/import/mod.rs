//! Importers — batch import from browser bookmarks, Pocket, Raindrop.
//!
//! Auto-detects format from file extension and content.

use anyhow::Result;
use std::path::Path;

/// Detected import format.
#[derive(Debug)]
enum Format {
    Bookmarks, // Netscape HTML bookmarks
    Pocket,    // Pocket HTML export
    Raindrop,  // Raindrop CSV export
}

/// A parsed URL from an import file.
#[derive(Debug)]
struct ImportedLink {
    url: String,
    title: String,
    tags: Vec<String>,
}

/// Parse an import file and return all links.
pub fn parse(path: &Path) -> Result<Vec<ImportedLink>> {
    let content = std::fs::read_to_string(path)?;
    let format = detect_format(path, &content);

    let links = match format {
        Format::Bookmarks => parse_bookmarks(&content),
        Format::Pocket => parse_pocket(&content),
        Format::Raindrop => parse_raindrop(&content),
    };

    Ok(links)
}

/// Detect format from file extension and content.
fn detect_format(path: &Path, content: &str) -> Format {
    // Raindrop: CSV with header columns
    if content.starts_with("url,title") || content.starts_with("url,title,tags") {
        return Format::Raindrop;
    }

    // Pocket: HTML with pocket- prefix or specific structure
    if content.contains("<!DOCTYPE NETSCAPE-Bookmark-file") {
        if content.contains("POCKET-EXPORT") || content.contains("pocket-") {
            return Format::Pocket;
        }
        return Format::Bookmarks;
    }

    // Fallback: check extension
    match path.extension().and_then(|e| e.to_str()) {
        Some("csv") => Format::Raindrop,
        _ => Format::Bookmarks,
    }
}

/// Parse Netscape HTML bookmarks (Chrome, Firefox, Safari).
fn parse_bookmarks(content: &str) -> Vec<ImportedLink> {
    let mut links = Vec::new();
    let mut remaining = content;

    while let Some(start) = remaining.find("<A HREF=") {
        let tag = &remaining[start..];
        let end = tag.find('>').unwrap_or(tag.len());
        let tag_content = &tag[..end + 1];

        // Extract URL
        let url = extract_attr(tag_content, "HREF");
        let title = extract_attr(tag_content, "ADD_DATE") // skip over
            .map(|_| {
                // Title is between <A ...> and </A>
                let after_tag = &tag[end + 1..];
                let close = after_tag.find("</A>").unwrap_or(after_tag.len());
                after_tag[..close].trim().to_string()
            })
            .unwrap_or_default();

        if let Some(url) = url {
            if url.starts_with("http") && !url.contains("javascript:") {
                links.push(ImportedLink {
                    url: url.to_string(),
                    title: if title.is_empty() { url.to_string() } else { title.to_string() },
                    tags: Vec::new(),
                });
            }
        }

        remaining = &remaining[start + 1..];
    }

    links
}

/// Parse Pocket HTML export.
fn parse_pocket(content: &str) -> Vec<ImportedLink> {
    parse_bookmarks(content) // Same format as bookmarks
}

/// Parse Raindrop CSV export.
fn parse_raindrop(content: &str) -> Vec<ImportedLink> {
    let mut links = Vec::new();
    let mut lines = content.lines();

    // Parse header to find column positions
    let header = match lines.next() {
        Some(h) => h,
        None => return links,
    };

    let columns: Vec<&str> = header.split(',').map(|c| c.trim()).collect();
    let url_idx = columns.iter().position(|c| c == &"url");
    let title_idx = columns.iter().position(|c| c == &"title");
    let tags_idx = columns.iter().position(|c| c == &"tags");

    for line in lines {
        if line.trim().is_empty() { continue; }
        let fields = parse_csv_line(line);

        let url = url_idx.and_then(|i| fields.get(i)).cloned();
        let title = title_idx
            .and_then(|i| fields.get(i))
            .cloned()
            .unwrap_or_default();
        let tags: Vec<String> = tags_idx
            .and_then(|i| fields.get(i))
            .map(|t| {
                t.split(',')
                    .map(|s| s.trim().trim_matches('"').to_string())
                    .filter(|s| !s.is_empty())
                    .collect()
            })
            .unwrap_or_default();

        if let Some(url) = url {
            if url.starts_with("http") {
                links.push(ImportedLink {
                    url: url.trim().to_string(),
                    title: if title.is_empty() { url.trim().to_string() } else { title.trim().to_string() },
                    tags,
                });
            }
        }
    }

    links
}

/// Extract an HTML attribute value (case-insensitive).
fn extract_attr<'a>(tag: &'a str, attr: &str) -> Option<&'a str> {
    let tag_lower = tag.to_lowercase();
    let attr_lower = attr.to_lowercase();
    let search = format!("{}=\"", attr_lower);

    let pos = tag_lower.find(&search)?;
    let value_start = pos + search.len();
    let value = &tag[value_start..];
    let end = value.find('"')?;
    Some(&tag[value_start..value_start + end])
}

/// Parse a single CSV line handling quoted fields.
fn parse_csv_line(line: &str) -> Vec<String> {
    let mut fields = Vec::new();
    let mut current = String::new();
    let mut in_quotes = false;
    let chars: Vec<char> = line.chars().collect();
    let mut i = 0;

    while i < chars.len() {
        let c = chars[i];
        if c == '"' {
            in_quotes = !in_quotes;
        } else if c == ',' && !in_quotes {
            fields.push(current.trim().to_string());
            current.clear();
        } else {
            current.push(c);
        }
        i += 1;
    }
    fields.push(current.trim().to_string());
    fields
}

/// Ingest all links from a file into the knowledge base.
pub async fn ingest_file(path: &Path, store: &crate::store::Store) -> Result<ImportStats> {
    let links = parse(path)?;
    let total = links.len();
    let client = reqwest::Client::builder()
        .user_agent("Pliny/0.1 Importer")
        .build()?;

    let mut stats = ImportStats::default();
    stats.total = total;

    for link in &links {
        tracing::info!("Importing: {}", link.url);

        // Try extracting via the normal pipeline
        match crate::extractors::extract(&client, &link.url).await {
            Ok(Some(mut entry)) => {
                if !link.tags.is_empty() {
                    entry.tags.extend(link.tags.clone());
                }
                match store.insert(&entry) {
                    Ok(true) => stats.imported += 1,
                    Ok(false) => stats.duplicates += 1,
                    Err(e) => {
                        tracing::warn!("Store error [{}]: {e}", link.url);
                        stats.errors += 1;
                    }
                }
            }
            Ok(None) => {
                // No content extracted — try as a note with title
                let entry = crate::core::Entry {
                    id: crate::core::EntryId(format!("import-{}", link.url.replace(|c: char| !c.is_alphanumeric(), "-"))),
                    source_url: link.url.clone(),
                    title: link.title.clone(),
                    content: format!("Imported bookmark: {}", link.title),
                    source_type: crate::core::SourceType::Web,
                    tags: link.tags.clone(),
                    created_at: chrono::Utc::now(),
                };
                match store.insert(&entry) {
                    Ok(true) => stats.imported += 1,
                    Ok(false) => stats.duplicates += 1,
                    Err(e) => {
                        tracing::warn!("Store error [{}]: {e}", link.url);
                        stats.errors += 1;
                    }
                }
            }
            Err(e) => {
                tracing::warn!("Extract error [{}]: {e}", link.url);
                stats.errors += 1;
            }
        }

        // Rate limit — don't hammer servers
        tokio::time::sleep(std::time::Duration::from_millis(500)).await;
    }

    Ok(stats)
}

#[derive(Debug, Default)]
pub struct ImportStats {
    pub total: usize,
    pub imported: usize,
    pub duplicates: usize,
    pub errors: usize,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parse_bookmark_html() {
        let content = r#"<!DOCTYPE NETSCAPE-Bookmark-file-1>
<DT><A HREF="https://example.com/page" ADD_DATE="1234567890">Example Page</A>
<DT><A HREF="https://rust-lang.org" ADD_DATE="1234567891">Rust Lang</A>"#;

        let links = parse_bookmarks(content);
        assert_eq!(links.len(), 2);
        assert_eq!(links[0].url, "https://example.com/page");
        assert_eq!(links[1].title, "Rust Lang");
    }

    #[test]
    fn skips_javascript_links() {
        let content = r#"<DT><A HREF="javascript:void(0)">Bad</A>
<DT><A HREF="https://example.com">Good</A>"#;

        let links = parse_bookmarks(content);
        assert_eq!(links.len(), 1);
        assert_eq!(links[0].url, "https://example.com");
    }

    #[test]
    fn parse_raindrop_csv() {
        let content = "url,title,tags,created\nhttps://example.com,Example,\"rust, programming\",2024-01-01\nhttps://other.com,Other Site,,2024-02-01\n";

        let links = parse_raindrop(content);
        assert_eq!(links.len(), 2);
        assert_eq!(links[0].url, "https://example.com");
        assert_eq!(links[0].title, "Example");
        assert_eq!(links[0].tags, vec!["rust", "programming"]);
        assert_eq!(links[1].tags.len(), 0);
    }

    #[test]
    fn detect_format_bookmarks() {
        let content = "<!DOCTYPE NETSCAPE-Bookmark-file-1>\n<DT><A HREF=\"https://x.com\">X</A>";
        let format = detect_format(Path::new("bookmarks.html"), content);
        assert!(matches!(format, Format::Bookmarks));
    }

    #[test]
    fn detect_format_raindrop() {
        let content = "url,title,tags\nhttps://x.com,X,\"tech\"";
        let format = detect_format(Path::new("export.csv"), content);
        assert!(matches!(format, Format::Raindrop));
    }
}
