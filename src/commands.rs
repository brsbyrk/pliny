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

/// Show knowledge base statistics.
pub async fn stats(config: &pliny::config::Config) -> Result<()> {
    let db_path = config.data_dir.join("pliny.db");
    let store = pliny::store::Store::open(&db_path)?;

    let s = store.stats()?;

    println!("Pliny — Knowledge Base Stats\n");
    println!("  Total entries:  {}", s.total);
    println!("  Database:       {} MB", s.db_size_mb);
    println!();

    if s.total == 0 {
        println!("  No entries yet. Start with: pliny ingest <url>");
        return Ok(());
    }

    println!("  By source:");
    let max_label = s.by_source.keys().map(|k| k.len()).max().unwrap_or(0);
    for (source, count) in &s.by_source {
        let bar = "█".repeat(*count as usize);
        println!("    {:<width$}  {:>4}  {}", source, count, bar, width = max_label);
    }

    if !s.top_tags.is_empty() {
        println!("\n  Top tags:");
        for (tag, count) in &s.top_tags {
            println!("    {:<20}  {:>4}", tag, count);
        }
    }

    if let Some(last) = &s.last_ingested {
        println!("\n  Last ingested:  {} [{}]", last.title, last.source_type);
        println!("                  {}", last.created_at);
    }

    Ok(())
}

/// Import bookmarks from a file (browser export, Pocket, Raindrop).
pub async fn import_file(config: &pliny::config::Config, path: &str) -> Result<()> {
    let db_path = config.data_dir.join("pliny.db");
    let store = pliny::store::Store::open(&db_path)?;
    let file_path = std::path::Path::new(path);

    if !file_path.exists() {
        anyhow::bail!("File not found: {path}");
    }

    println!("Importing from: {path}");
    println!("This may take a while (rate-limited at 2 URLs/second)...\n");

    let stats = pliny::import::ingest_file(file_path, &store).await?;

    println!("\nImport complete:");
    println!("  Total:     {}", stats.total);
    println!("  Imported:  {}", stats.imported);
    println!("  Duplicates: {}", stats.duplicates);
    if stats.errors > 0 {
        println!("  Errors:    {}", stats.errors);
    }

    Ok(())
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
        .filter(|c| c.is_alphanumeric() || c.is_whitespace() || *c == '-')
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
