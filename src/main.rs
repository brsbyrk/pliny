//! Pliny CLI — single binary for capture, search, and serving.

use clap::{Parser, Subcommand};

mod commands;

#[derive(Parser)]
#[command(name = "pliny", about = "Personal knowledge engine", version)]
struct Cli {
    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Ingest a URL into your knowledge base
    Ingest {
        /// URL to capture
        url: String,
    },
    /// Start the dashboard server
    Serve,
    /// Search your knowledge base
    Search {
        /// Search query
        query: String,
    },
    /// Monitor RSS/Atom feeds
    Rss {
        /// Path to feeds file (one URL per line)
        file: String,
    },
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "pliny=info".into()),
        )
        .init();

    let cli = Cli::parse();

    match cli.command {
        Command::Ingest { url } => {
            let config = pliny::config::Config::from_env();
            commands::ingest(&config, &url).await?;
        }
        Command::Serve => {
            let config = pliny::config::Config::from_env();
            pliny::server::serve(&config).await?;
        }
        Command::Search { query } => {
            let config = pliny::config::Config::from_env();
            commands::search(&config, &query).await?;
        }
        Command::Rss { file } => {
            tracing::info!("Monitoring feeds from: {file}");
            // TODO: feed monitor loop
        }
    }

    Ok(())
}
