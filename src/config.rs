//! Application configuration — loaded from environment variables.
//!
//! Default paths follow OS conventions via the `dirs` crate:
//!   macOS:   ~/Library/Application Support/pliny
//!   Linux:   ~/.local/share/pliny
//!   Windows: %APPDATA%/pliny
//!
//! Override with PLINY_DATA_DIR, PLINY_MODEL_DIR environment variables.

use std::path::PathBuf;

/// All tunable values. No hardcoded paths anywhere else.
#[derive(Debug, Clone)]
pub struct Config {
    pub data_dir: PathBuf,
    pub port: u16,
    pub bind_host: String,
    pub deepseek_api_key: Option<String>,
    pub model_dir: PathBuf,
}

impl Config {
    pub fn from_env() -> Self {
        let default_data = dirs::data_dir()
            .unwrap_or_else(|| PathBuf::from("."))
            .join("pliny");

        let default_models = default_data.join("models");

        Self {
            data_dir: env_path("PLINY_DATA_DIR", default_data),
            port: env_u16("PLINY_PORT", 3131),
            bind_host: env_str("PLINY_HOST", "0.0.0.0"),
            deepseek_api_key: std::env::var("DEEPSEEK_API_KEY").ok(),
            model_dir: env_path("PLINY_MODEL_DIR", default_models),
        }
    }
}

/// Resolve the model directory from env or default.
pub fn model_dir() -> Option<PathBuf> {
    let path = std::env::var("PLINY_MODEL_DIR")
        .map(PathBuf::from)
        .unwrap_or_else(|_| {
            dirs::data_dir()
                .unwrap_or_else(|| PathBuf::from("."))
                .join("pliny")
                .join("models")
        });
    Some(path)
}

fn env_str(key: &str, default: &str) -> String {
    std::env::var(key).unwrap_or_else(|_| default.to_string())
}

fn env_u16(key: &str, default: u16) -> u16 {
    std::env::var(key).ok().and_then(|v| v.parse().ok()).unwrap_or(default)
}

fn env_path(key: &str, default: PathBuf) -> PathBuf {
    std::env::var(key).ok().map(PathBuf::from).unwrap_or(default)
}
