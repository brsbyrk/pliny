//! Axum HTTP server — API routes and static dashboard.

use anyhow::Result;
use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::Json,
    routing::{get, post},
    Router,
};
use serde::{Deserialize, Serialize};
use std::net::SocketAddr;
use std::sync::Arc;
use tower_http::services::ServeDir;

use crate::config::Config;
use crate::search::SearchResult;
use crate::store::Store;

/// Shared application state.
pub struct AppState {
    pub store: Store,
}

/// Build the Axum router with all API routes and static file serving.
pub fn router(state: Arc<AppState>) -> Router {
    Router::new()
        .route("/api/health", get(health))
        .route("/api/search", get(search))
        .route("/api/ingest", post(ingest))
        .route("/api/stats", get(stats))
        .nest_service("/", ServeDir::new("ui"))
        .with_state(state)
}

/// Start the server on the configured address.
pub async fn serve(config: &Config) -> Result<()> {
    let db_path = config.data_dir.join("pliny.db");
    let store = Store::open(&db_path)?;

    let count = store.count().unwrap_or(0);
    tracing::info!("Database: {} entries", count);

    let state = Arc::new(AppState { store });
    let app = router(state);

    let addr: SocketAddr = format!("{}:{}", config.bind_host, config.port).parse()?;
    tracing::info!("Pliny dashboard → http://{addr}");
    tracing::info!("API docs → http://{addr}/api/health");

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}

// ── Route handlers ─────────────────────────────────────────────

async fn health() -> Json<serde_json::Value> {
    Json(serde_json::json!({"status": "ok", "version": env!("CARGO_PKG_VERSION")}))
}

#[derive(Deserialize)]
struct SearchQuery {
    q: String,
    #[serde(default = "default_limit")]
    limit: usize,
}

fn default_limit() -> usize { 20 }

async fn search(
    State(state): State<Arc<AppState>>,
    Query(params): Query<SearchQuery>,
) -> Result<Json<Vec<SearchResult>>, StatusCode> {
    let results = state.store.search_fts(&params.q, params.limit)
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    Ok(Json(results))
}

#[derive(Deserialize)]
struct IngestRequest {
    url: String,
}

#[derive(Serialize)]
struct IngestResponse {
    status: String,
    entry_id: Option<String>,
}

async fn ingest(
    State(state): State<Arc<AppState>>,
    Json(body): Json<IngestRequest>,
) -> Result<Json<IngestResponse>, StatusCode> {
    let client = reqwest::Client::new();
    let entry = crate::extractors::extract(&client, &body.url)
        .await
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;

    match entry {
        Some(entry) => {
            let id = entry.id.to_string();
            state.store.insert(&entry)
                .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
            Ok(Json(IngestResponse {
                status: "ingested".into(),
                entry_id: Some(id),
            }))
        }
        None => Ok(Json(IngestResponse {
            status: "no_content".into(),
            entry_id: None,
        })),
    }
}

#[derive(Serialize)]
struct StatsResponse {
    total_entries: usize,
}

async fn stats(
    State(state): State<Arc<AppState>>,
) -> Result<Json<StatsResponse>, StatusCode> {
    let count = state.store.count()
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    Ok(Json(StatsResponse { total_entries: count }))
}
