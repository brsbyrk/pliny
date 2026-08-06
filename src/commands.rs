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

    store.insert(&entry)?;

    tracing::info!(
        "Ingested: {} [{}] ({} chars)",
        entry.id,
        entry.source_type.as_str(),
        entry.content.len()
    );

    Ok(())
}
