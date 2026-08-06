//! X/Twitter extractor via fxtwitter API.

use anyhow::Result;
use url::Url;

use crate::core::{Entry, Extractor};

pub struct XExtractor;

impl Extractor for XExtractor {
    fn can_handle(&self, url: &Url) -> bool {
        let host = url.host_str().unwrap_or("");
        host.contains("x.com") || host.contains("twitter.com")
    }

    fn extract(&self, _client: &reqwest::Client, _url: &Url) -> Result<Option<Entry>> {
        // TODO: fxtwitter API → extract tweet/thread → Entry
        Ok(None)
    }

    fn name(&self) -> &'static str {
        "x"
    }
}
