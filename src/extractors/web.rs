//! Web article extractor using readability.

use anyhow::Result;
use url::Url;

use crate::core::{Entry, Extractor};

pub struct WebExtractor;

impl Extractor for WebExtractor {
    fn can_handle(&self, _url: &Url) -> bool {
        // Web is the catch-all — always returns true.
        // It must be registered LAST in the extractor chain.
        true
    }

    fn extract(&self, _client: &reqwest::Client, _url: &Url) -> Result<Option<Entry>> {
        // TODO: fetch HTML → readability → clean text → Entry
        Ok(None)
    }

    fn name(&self) -> &'static str {
        "web"
    }
}
