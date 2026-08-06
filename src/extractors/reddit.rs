//! Reddit extractor via .json API.

use anyhow::Result;
use url::Url;

use crate::core::{Entry, Extractor};

pub struct RedditExtractor;

impl Extractor for RedditExtractor {
    fn can_handle(&self, url: &Url) -> bool {
        url.host_str().unwrap_or("").contains("reddit.com")
    }

    fn extract(&self, _client: &reqwest::Client, _url: &Url) -> Result<Option<Entry>> {
        // TODO: reddit.com/.json → extract post + comments → Entry
        Ok(None)
    }

    fn name(&self) -> &'static str {
        "reddit"
    }
}
