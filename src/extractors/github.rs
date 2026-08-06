//! GitHub extractor via API + raw README.

use anyhow::Result;
use url::Url;

use crate::core::{Entry, Extractor};

pub struct GitHubExtractor;

impl Extractor for GitHubExtractor {
    fn can_handle(&self, url: &Url) -> bool {
        url.host_str().unwrap_or("").contains("github.com")
    }

    fn extract(&self, _client: &reqwest::Client, _url: &Url) -> Result<Option<Entry>> {
        // TODO: raw README → GitHub API fallback → Entry
        Ok(None)
    }

    fn name(&self) -> &'static str {
        "github"
    }
}
