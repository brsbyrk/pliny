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
    /// Save a manual note
    Note {
        /// Note content
        content: String,
        /// Optional title (default: first line)
        #[arg(short, long)]
        title: Option<String>,
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
    /// Import bookmarks from browser/Pocket/Raindrop export
    Import {
        /// Path to import file
        file: String,
    },
    /// Show knowledge base statistics
    Stats,
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
        Command::Note { content, title } => {
            let config = pliny::config::Config::from_env();
            commands::note(&config, &content, title.as_deref()).await?;
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
            let config = pliny::config::Config::from_env();
            commands::rss(&config, &file).await?;
        }
        Command::Import { file } => {
            let config = pliny::config::Config::from_env();
            commands::import_file(&config, &file).await?;
        }
        Command::Stats => {
            let config = pliny::config::Config::from_env();
            commands::stats(&config).await?;
        }
    }

    Ok(())
}
