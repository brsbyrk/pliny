//! Source types that Pliny can handle.

use serde::{Deserialize, Serialize};

/// Classification of a URL's source.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum SourceType {
    /// X/Twitter — tweets, threads, articles
    X,
    /// YouTube — videos with transcripts
    YouTube,
    /// GitHub — repository README or API metadata
    GitHub,
    /// Reddit — posts with comments
    Reddit,
    /// Generic web page — readability-based extraction
    Web,
    /// RSS/Atom feed entry
    Feed,
    /// Manual note — user-written text, no URL
    Note,
}

impl SourceType {
    /// Classify a URL into its source type.
    pub fn from_url(url: &url::Url) -> Self {
        let host = url.host_str().unwrap_or("").to_lowercase();

        if host.contains("x.com") || host.contains("twitter.com") {
            return Self::X;
        }
        if host.contains("youtube.com") || host.contains("youtu.be") {
            return Self::YouTube;
        }
        if host.contains("github.com") {
            return Self::GitHub;
        }
        if host.contains("reddit.com") {
            return Self::Reddit;
        }
        Self::Web
    }

    /// Human-readable label for stats/logging.
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::X => "x",
            Self::YouTube => "youtube",
            Self::GitHub => "github",
            Self::Reddit => "reddit",
            Self::Web => "web",
            Self::Feed => "feed",
            Self::Note => "note",
        }
    }
}

/// Unique identifier for an entry (slug derived from title + hash).
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct EntryId(pub String);

impl std::fmt::Display for EntryId {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.0)
    }
}

/// A captured knowledge entry — the central data type.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Entry {
    pub id: EntryId,
    pub source_url: String,
    pub title: String,
    pub content: String,
    pub source_type: SourceType,
    pub tags: Vec<String>,
    pub created_at: chrono::DateTime<chrono::Utc>,
}
