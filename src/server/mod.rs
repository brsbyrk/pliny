//! Axum HTTP server — API routes + embedded React dashboard.

use anyhow::Result;
use axum::{
    extract::{Query, State},
    http::{header, StatusCode},
    response::{IntoResponse, Json, Response},
    routing::{get, post},
    Router,
};
use rust_embed::RustEmbed;
use serde::{Deserialize, Serialize};
use std::net::SocketAddr;
use std::sync::Arc;

use crate::config::Config;
use crate::search::SearchResult;
use crate::store::Store;

/// Embedded React frontend (ui/dist/).
#[derive(RustEmbed)]
#[folder = "ui/dist/"]
struct Assets;

/// Shared application state.
pub struct AppState {
    pub store: Store,
}

/// Build the Axum router.
pub fn router(state: Arc<AppState>) -> Router {
    Router::new()
        // API
        .route("/api/health", get(health))
        .route("/api/entries", get(search))
        .route("/api/entry/{id}", get(get_entry))
        .route("/api/ingest/add-url", post(ingest))
        .route("/api/stats", get(stats))
        // Serve embedded frontend
        .route("/{*path}", get(serve_frontend))
        .route("/", get(serve_index))
        .with_state(state)
}

/// Start the server.
pub async fn serve(config: &Config) -> Result<()> {
    let db_path = config.data_dir.join("pliny.db");
    let store = Store::open(&db_path)?;
    let count = store.count().unwrap_or(0);
    tracing::info!("Database: {} entries", count);

    let state = Arc::new(AppState { store });
    let app = router(state);

    let addr: SocketAddr = format!("{}:{}", config.bind_host, config.port).parse()?;
    tracing::info!("Pliny → http://{addr}");

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
    q: Option<String>,
    #[serde(default = "default_limit")]
    limit: usize,
    #[serde(default)]
    page: usize,
}

fn default_limit() -> usize { 24 }

async fn search(
    State(state): State<Arc<AppState>>,
    Query(params): Query<SearchQuery>,
) -> Result<Json<serde_json::Value>, StatusCode> {
    let query = params.q.unwrap_or_default();
    let page = params.page.max(1);

    if query.is_empty() {
        // List recent with pagination
        let offset = (page - 1) * params.limit;
        let results = state.store.list_recent(params.limit)
            .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
        let total = state.store.count().unwrap_or(0);
        return Ok(Json(serde_json::json!({
            "entries": results,
            "total": total,
            "page": page,
        })));
    }

    let results = state.store.search_fts(&query, params.limit)
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;

    Ok(Json(serde_json::json!({
        "entries": results,
        "total": results.len(),
        "page": page,
    })))
}

#[derive(Deserialize)]
struct IngestRequest {
    url: String,
}

async fn ingest(
    State(state): State<Arc<AppState>>,
    Json(body): Json<IngestRequest>,
) -> Result<Json<serde_json::Value>, StatusCode> {
    let client = reqwest::Client::new();
    let entry = crate::extractors::extract(&client, &body.url)
        .await
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;

    match entry {
        Some(entry) => {
            let id = entry.id.to_string();
            let inserted = state.store.insert(&entry)
                .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
            Ok(Json(serde_json::json!({
                "status": if inserted { "ingested" } else { "duplicate" },
                "entry_id": id,
            })))
        }
        None => Ok(Json(serde_json::json!({
            "status": "no_content",
        }))),
    }
}

async fn stats(
    State(state): State<Arc<AppState>>,
) -> Result<Json<serde_json::Value>, StatusCode> {
    let count = state.store.count()
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    Ok(Json(serde_json::json!({"total_entries": count})))
}

async fn get_entry(
    State(state): State<Arc<AppState>>,
    axum::extract::Path(id): axum::extract::Path<String>,
) -> Result<Json<serde_json::Value>, StatusCode> {
    let entry = state.store.get_entry(&id)
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;

    match entry {
        Some(e) => Ok(Json(serde_json::json!({
            "id": e.id.to_string(),
            "title": e.title,
            "source_url": e.source_url,
            "source_type": e.source_type.as_str(),
            "content": e.content,
            "tags": e.tags,
            "created_at": e.created_at.to_rfc3339(),
        }))),
        None => Err(StatusCode::NOT_FOUND),
    }
}

// ── Static file serving ────────────────────────────────────────

async fn serve_index() -> impl IntoResponse {
    serve_asset("index.html")
}

async fn serve_frontend(
    axum::extract::Path(path): axum::extract::Path<String>,
) -> impl IntoResponse {
    serve_asset(&path)
}

fn serve_asset(path: &str) -> Response {
    let path = path.trim_start_matches('/');

    match Assets::get(path) {
        Some(file) => {
            let content_type = match path.rsplit('.').next() {
                Some("html") => "text/html",
                Some("css") => "text/css",
                Some("js") => "application/javascript",
                Some("json") => "application/json",
                Some("png") => "image/png",
                Some("svg") => "image/svg+xml",
                Some("woff2") => "font/woff2",
                _ => "application/octet-stream",
            };
            let mut response = Response::new(axum::body::Body::from(file.data));
            response.headers_mut().insert(
                header::CONTENT_TYPE,
                header::HeaderValue::from_static(content_type),
            );
            response
        }
        None => {
            // SPA fallback: serve index.html for client-side routing
            if let Some(file) = Assets::get("index.html") {
                let mut response = Response::new(axum::body::Body::from(file.data));
                response.headers_mut().insert(
                    header::CONTENT_TYPE,
                    header::HeaderValue::from_static("text/html"),
                );
                response
            } else {
                Response::builder()
                    .status(StatusCode::NOT_FOUND)
                    .body(axum::body::Body::from("Not Found"))
                    .unwrap()
            }
        }
    }
}
