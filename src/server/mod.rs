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
use serde::Deserialize;
use std::net::SocketAddr;
use std::sync::Arc;

use crate::config::Config;
use crate::store::Store;

/// Embedded React frontend (ui/dist/).
#[derive(RustEmbed)]
#[folder = "ui/dist/"]
struct Assets;

/// Shared application state.
pub struct AppState {
    pub store: Arc<Store>,
    pub embedder: Option<crate::search::Embedder>,
}

/// Build the Axum router.
pub fn router(state: Arc<AppState>) -> Router {
    Router::new()
        // API
        .route("/api/health", get(health))
        .route("/api/entries", get(search))
        .route("/api/entry/{id}", get(get_entry))
        .route("/api/entry/{id}/star", post(toggle_star))
        .route("/api/entry/{id}/related", get(related_entries))
        .route("/api/ingest/add-url", post(ingest))
        .route("/api/notes", post(create_note))
        .route("/api/stats", get(stats))
        .route("/api/collections", get(list_collections).post(create_collection))
        .route("/api/collection/{id}/add", post(add_to_collection))
        .route("/api/random", get(random))
        .route("/api/on-this-day", get(on_this_day))
        // Serve embedded frontend (SPA fallback)
        .route("/", get(serve_index))
        .fallback(serve_frontend)
        .with_state(state)
}

/// Start the server.
pub async fn serve(config: &Config) -> Result<()> {
    let db_path = config.data_dir.join("pliny.db");
    let store = Arc::new(Store::open(&db_path)?);
    let count = store.count().unwrap_or(0);
    tracing::info!("Database: {} entries", count);

    // Try loading embedding model
    let embedder = crate::config::model_dir().and_then(|d| {
        if crate::search::Embedder::is_available(&d) {
            crate::search::Embedder::load(&d).ok()
        } else {
            None
        }
    });

    if embedder.is_some() {
        tracing::info!("Embeddings enabled (384-dim)");
    }

    let state = Arc::new(AppState { store: store.clone(), embedder });

    // Start Telegram bot if token is set
    crate::message_source::start_bots(state.store.clone());

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
    #[serde(default)]
    from: Option<String>,
    #[serde(default)]
    to: Option<String>,
    #[serde(default)]
    starred: Option<bool>,
}

fn default_limit() -> usize { 24 }

async fn search(
    State(state): State<Arc<AppState>>,
    Query(params): Query<SearchQuery>,
) -> Result<Json<serde_json::Value>, StatusCode> {
    let query = params.q.unwrap_or_default();
    let page = params.page.max(1);

    if query.is_empty() {
        // Use date filter if provided, else recent
        let results = if params.from.is_some() || params.to.is_some() {
            state.store.list_by_date(params.from.as_deref(), params.to.as_deref(), params.limit)
                .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?
        } else {
            state.store.list_recent(params.limit)
                .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?
        };
        let total = state.store.count().unwrap_or(0);
        let entries: Vec<_> = results.into_iter()
            .filter(|e| !params.starred.unwrap_or(false) || e.starred)
            .collect();
        return Ok(Json(serde_json::json!({
            "entries": entries,
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
            let inserted = if let Some(ref embedder) = state.embedder {
                let text = crate::search::Embedder::embed_entry(&entry.title, &entry.content);
                if let Ok(emb) = embedder.embed(&text) {
                    state.store.insert_with_embedding(&entry, &emb)
                } else {
                    state.store.insert(&entry)
                }
            } else {
                state.store.insert(&entry)
            }
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

#[derive(Deserialize)]
struct NoteRequest {
    content: String,
    #[serde(default)]
    title: Option<String>,
}

async fn create_note(
    State(state): State<Arc<AppState>>,
    Json(body): Json<NoteRequest>,
) -> Result<Json<serde_json::Value>, StatusCode> {
    let title = body.title.unwrap_or_else(|| {
        body.content.lines().next()
            .unwrap_or("Untitled")
            .chars().take(80).collect()
    });

    let slug = title.to_lowercase()
        .chars()
        .filter(|c| c.is_alphanumeric() || c.is_whitespace() || *c == '-')
        .collect::<String>()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join("-");

    let id = format!("note-{}-{}", slug, chrono::Utc::now().timestamp() % 100000);

    let entry = crate::core::Entry {
        id: crate::core::EntryId(id.clone()),
        source_url: String::new(),
        title,
        content: body.content,
        source_type: crate::core::SourceType::Note,
        tags: Vec::new(),
        created_at: chrono::Utc::now(),
    };

    state.store.insert(&entry)
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;

    // Embed in background if model available
    if let Some(ref embedder) = state.embedder {
        let text = crate::search::Embedder::embed_entry(&entry.title, &entry.content);
        if let Ok(emb) = embedder.embed(&text) {
            let _ = state.store.insert_embedding(&id, &emb);
        }
    }

    Ok(Json(serde_json::json!({"status": "created", "entry_id": id})))
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
        None => Ok(Json(serde_json::json!({"error": "not_found"}))),
    }
}

async fn toggle_star(
    State(state): State<Arc<AppState>>,
    axum::extract::Path(id): axum::extract::Path<String>,
) -> Result<Json<serde_json::Value>, StatusCode> {
    let starred = state.store.toggle_star(&id)
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    Ok(Json(serde_json::json!({"starred": starred})))
}

async fn random(
    State(state): State<Arc<AppState>>,
) -> Result<Json<serde_json::Value>, StatusCode> {
    let entry = state.store.random_entry()
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    match entry {
        Some(e) => Ok(Json(serde_json::json!({
            "id": e.id.to_string(), "title": e.title, "source_url": e.source_url,
            "source_type": e.source_type.as_str(), "created_at": e.created_at.to_rfc3339(),
        }))),
        None => Err(StatusCode::NOT_FOUND),
    }
}

async fn on_this_day(
    State(state): State<Arc<AppState>>,
) -> Result<Json<serde_json::Value>, StatusCode> {
    let entries = state.store.on_this_day()
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    Ok(Json(serde_json::json!({ "entries": entries })))
}

async fn related_entries(
    State(state): State<Arc<AppState>>,
    axum::extract::Path(id): axum::extract::Path<String>,
) -> Result<Json<serde_json::Value>, StatusCode> {
    let entry = state.store.get_entry(&id)
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;

    let Some(entry) = entry else {
        return Ok(Json(serde_json::json!({"related": []})));
    };

    // Use vector search if model available, else FTS5 with title
    let model_dir = std::env::var("PLINY_MODEL_DIR")
        .map(std::path::PathBuf::from)
        .unwrap_or_else(|_| {
            dirs::data_dir()
                .unwrap_or_else(|| std::path::PathBuf::from("."))
                .join("pliny")
                .join("models")
        });

    if crate::search::Embedder::is_available(&model_dir) {
        let embedder = crate::search::Embedder::load(&model_dir)
            .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
        let text = crate::search::Embedder::embed_entry(&entry.title, &entry.content);
        let embedding = embedder.embed(&text)
            .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
        let related = state.store.search_vec(&embedding, 6)
            .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
        let ids: Vec<String> = related.into_iter()
            .filter(|(rid, _)| rid != &id)
            .take(5)
            .map(|(rid, _)| rid)
            .collect();
        return Ok(Json(serde_json::json!({"related": ids})));
    }

    // Fallback: FTS5 search on title keywords
    let keywords: String = entry.title.split_whitespace().take(3).collect::<Vec<_>>().join(" OR ");
    if keywords.is_empty() {
        return Ok(Json(serde_json::json!({"related": []})));
    }
    let results = state.store.search_fts(&keywords, 6)
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    let ids: Vec<String> = results.into_iter()
        .filter(|r| r.id != id)
        .take(5)
        .map(|r| r.id)
        .collect();
    Ok(Json(serde_json::json!({"related": ids})))
}

// ── Static file serving ────────────────────────────────────────

#[derive(Deserialize)]
struct CollectionBody { name: Option<String>, entry_id: Option<String> }

async fn list_collections(
    State(state): State<Arc<AppState>>,
) -> Result<Json<serde_json::Value>, StatusCode> {
    let cols = state.store.list_collections()
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    let items: Vec<_> = cols.into_iter().map(|(id, name, count)| {
        serde_json::json!({"id": id, "name": name, "count": count})
    }).collect();
    Ok(Json(serde_json::json!({"collections": items})))
}

async fn create_collection(
    State(state): State<Arc<AppState>>,
    Json(body): Json<CollectionBody>,
) -> Result<Json<serde_json::Value>, StatusCode> {
    let name = body.name.ok_or(StatusCode::BAD_REQUEST)?;
    let id = state.store.create_collection(&name)
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    Ok(Json(serde_json::json!({"id": id, "name": name})))
}

async fn add_to_collection(
    State(state): State<Arc<AppState>>,
    axum::extract::Path(id): axum::extract::Path<String>,
    Json(body): Json<CollectionBody>,
) -> Result<Json<serde_json::Value>, StatusCode> {
    let entry_id = body.entry_id.ok_or(StatusCode::BAD_REQUEST)?;
    let added = state.store.add_to_collection(&id, &entry_id)
        .map_err(|_| StatusCode::INTERNAL_SERVER_ERROR)?;
    Ok(Json(serde_json::json!({"added": added})))
}

async fn serve_index() -> impl IntoResponse {
    serve_asset("index.html")
}

async fn serve_frontend(
    req: axum::http::Request<axum::body::Body>,
) -> impl IntoResponse {
    serve_asset(req.uri().path())
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
