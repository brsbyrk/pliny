//! Integration tests for server API endpoints.

use httpmock::prelude::*;
use pliny::store::Store;
use tower::ServiceExt;

const ARTICLE_HTML: &str = r#"<!DOCTYPE html>
<html><head><title>Test Article</title></head>
<body><article><p>This is a test article about Rust programming and async patterns.</p></article></body></html>"#;

async fn req_json(app: &axum::Router, method: &str, uri: &str, body: Option<String>) -> (u16, serde_json::Value) {
    let mut builder = axum::http::Request::builder().method(method).uri(uri);
    let req = if let Some(b) = body {
        builder = builder.header("content-type", "application/json");
        builder.body(axum::body::Body::from(b)).unwrap()
    } else {
        builder.body(axum::body::Body::empty()).unwrap()
    };
    let r = app.clone().oneshot(req).await.unwrap();
    let status = r.status().as_u16();
    let bytes = axum::body::to_bytes(r.into_body(), usize::MAX).await.unwrap_or_default();
    let json: serde_json::Value = serde_json::from_slice(&bytes).unwrap_or_default();
    (status, json)
}

fn make_app() -> axum::Router {
    let store = Store::open_in_memory().unwrap();
    let state = std::sync::Arc::new(pliny::server::AppState { store, embedder: None });
    pliny::server::router(state)
}

#[tokio::test]
async fn health_check() {
    let (s, j) = req_json(&make_app(), "GET", "/api/health", None).await;
    assert_eq!(s, 200);
    assert_eq!(j["status"], "ok");
}

#[tokio::test]
async fn stats_returns_zero() {
    let (s, j) = req_json(&make_app(), "GET", "/api/stats", None).await;
    assert_eq!(s, 200);
    assert_eq!(j["total_entries"], 0);
}

#[tokio::test]
async fn entries_empty() {
    let (s, j) = req_json(&make_app(), "GET", "/api/entries", None).await;
    assert_eq!(s, 200);
    assert!(j["entries"].as_array().unwrap().is_empty());
}

#[tokio::test]
async fn ingest_web_url() {
    let server = MockServer::start();
    let m = server.mock(|when, then| {
        when.method(GET).path("/a");
        then.status(200).header("content-type", "text/html").body(ARTICLE_HTML);
    });
    let app = make_app();
    let url = format!("{}/a", server.base_url().trim_end_matches('/'));
    let (s, j) = req_json(&app, "POST", "/api/ingest/add-url", Some(serde_json::json!({"url":url}).to_string())).await;
    assert_eq!(s, 200);
    assert_eq!(j["status"], "ingested");
    m.assert();
}

#[tokio::test]
async fn ingest_duplicate() {
    let server = MockServer::start();
    let _m = server.mock(|when, then| {
        when.method(GET).path("/dup");
        then.status(200).header("content-type", "text/html").body(ARTICLE_HTML);
    });
    let app = make_app();
    let url = format!("{}/dup", server.base_url().trim_end_matches('/'));
    let body = serde_json::json!({"url":url}).to_string();
    let (_, j1) = req_json(&app, "POST", "/api/ingest/add-url", Some(body.clone())).await;
    assert_eq!(j1["status"], "ingested");
    let (_, j2) = req_json(&app, "POST", "/api/ingest/add-url", Some(body)).await;
    assert_eq!(j2["status"], "duplicate");
}
