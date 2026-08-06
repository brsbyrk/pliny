//! Axum HTTP server — API routes and static dashboard.

use anyhow::Result;
use axum::{routing::get, Router};
use tower_http::services::ServeDir;
use std::net::SocketAddr;

/// Build the Axum router with all API routes and static file serving.
pub fn router() -> Router {
    Router::new()
        .route("/api/health", get(health))
        .nest_service("/", ServeDir::new("ui"))
}

/// Start the server on the configured address.
pub async fn serve(host: &str, port: u16) -> Result<()> {
    let addr: SocketAddr = format!("{host}:{port}").parse()?;
    let app = router();

    tracing::info!("Pliny dashboard → http://{addr}");
    tracing::info!("API docs → http://{addr}/api/health");

    let listener = tokio::net::TcpListener::bind(addr).await?;
    axum::serve(listener, app).await?;
    Ok(())
}

async fn health() -> &'static str {
    "ok"
}
