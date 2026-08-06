//! Application configuration — loaded from environment variables.

use std::path::PathBuf;

/// All tunable values live here. No hardcoded paths, ports, or constants
/// anywhere else in the application.
#[derive(Debug, Clone)]
pub struct Config {
    /// Directory for SQLite database and media files.
    pub data_dir: PathBuf,
    /// Port for the HTTP server.
    pub port: u16,
    /// Bind address (0.0.0.0 for LAN access, 127.0.0.1 for local only).
    pub bind_host: String,
    /// DeepSeek API key (optional — for synthesis, Q&A, summaries).
    pub deepseek_api_key: Option<String>,
    /// ONNX model directory for embeddings.
    pub model_dir: PathBuf,
}

impl Config {
    pub fn from_env() -> Self {
        let home = dirs_next().unwrap_or_else(|| PathBuf::from("."));
        let default_data = home.join(".pliny");

        Self {
            data_dir: env_path("PLINY_DATA_DIR", default_data),
            port: env_u16("PLINY_PORT", 3131),
            bind_host: env_str("PLINY_HOST", "0.0.0.0"),
            deepseek_api_key: std::env::var("DEEPSEEK_API_KEY").ok(),
            model_dir: env_path(
                "PLINY_MODEL_DIR",
                home.join(".pliny").join("models"),
            ),
        }
    }
}

fn env_str(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}

fn env_u16(key: &str, default: u16) -> u16 {
    std::env::var(key)
        .ok()
        .and_then(|v| v.parse().ok())
        .unwrap_or(default)
}

fn env_path(key: &str, default: PathBuf) -> PathBuf {
    std::env::var(key)
        .ok()
        .map(PathBuf::from)
        .unwrap_or(default)
}

fn dirs_next() -> Option<PathBuf> {
    std::env::var("HOME")
        .or_else(|_| std::env::var("USERPROFILE"))
        .ok()
        .map(PathBuf::from)
}
