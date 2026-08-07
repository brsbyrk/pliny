//! CLI command implementations.

use anyhow::Result;

/// Ingest a single URL into the knowledge base.
pub async fn ingest(config: &pliny::config::Config, url: &str) -> Result<()> {
    let client = reqwest::Client::builder()
        .user_agent("Pliny/0.1")
        .build()?;

    tracing::info!("Extracting: {url}");

    let entry = match pliny::extractors::extract(&client, url).await? {
        Some(e) => e,
        None => {
            tracing::warn!("No content extracted from: {url}");
            return Ok(());
        }
    };

    let db_path = config.data_dir.join("pliny.db");
    let store = pliny::store::Store::open(&db_path)?;

    let inserted = store.insert(&entry)?;
    tracing::info!(
        "{}: {} [{}] ({} chars)",
        if inserted { "Ingested" } else { "Already saved" },
        entry.id,
        entry.source_type.as_str(),
        entry.content.len()
    );

    Ok(())
}

/// Search the knowledge base.
pub async fn search(config: &pliny::config::Config, query: &str) -> Result<()> {
    let db_path = config.data_dir.join("pliny.db");
    let store = pliny::store::Store::open(&db_path)?;

    let results = store.search_fts(query, 20)?;

    if results.is_empty() {
        println!("No results for: {query}");
        return Ok(());
    }

    println!("{} result(s) for: {query}\n", results.len());
    for r in &results {
        println!("  [{}] {}", r.source_type, r.title);
        println!("    {}…\n", &r.snippet[..r.snippet.len().min(120)]);
    }

    Ok(())
}

/// Monitor RSS/Atom feeds.
pub async fn rss(config: &pliny::config::Config, file: &str) -> Result<()> {
    let db_path = config.data_dir.join("pliny.db");
    let store = pliny::store::Store::open(&db_path)?;

    let monitor = pliny::feed::FeedMonitor::from_file(
        std::path::Path::new(file),
        3600,
    )?;

    monitor.run_loop(store).await
}

/// Save a manual note.
pub async fn note(config: &pliny::config::Config, content: &str, title: Option<&str>) -> Result<()> {
    use pliny::core::{Entry, EntryId, SourceType};

    let title = title
        .map(|t| t.to_string())
        .unwrap_or_else(|| {
            content.lines().next()
                .unwrap_or("Untitled")
                .chars().take(80).collect()
        });

    let slug = title
        .to_lowercase()
        .chars()
        .filter(|c| c.is_alphanumeric() || *c == ' ' || *c == '-')
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join("-");

    let id = format!("note-{}-{}", slug, &chrono::Utc::now().timestamp() % 100000);

    let entry = Entry {
        id: EntryId(id),
        source_url: String::new(),
        title,
        content: content.to_string(),
        source_type: SourceType::Note,
        tags: Vec::new(),
        created_at: chrono::Utc::now(),
    };

    let db_path = config.data_dir.join("pliny.db");
    let store = pliny::store::Store::open(&db_path)?;

    let inserted = store.insert(&entry)?;
    println!(
        "{} note: {} ({} chars)",
        if inserted { "Saved" } else { "Already exists" },
        entry.title,
        entry.content.len()
    );

    Ok(())
}
