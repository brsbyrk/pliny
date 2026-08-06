//! YouTube extractor via oembed + yt-dlp captions.

use anyhow::Result;
use async_trait::async_trait;
use url::Url;

use crate::core::{Entry, Extractor};

pub struct YouTubeExtractor;

#[async_trait]
impl Extractor for YouTubeExtractor {
    fn can_handle(&self, url: &Url) -> bool {
        let host = url.host_str().unwrap_or("");
        host.contains("youtube.com") || host.contains("youtu.be")
    }

    async fn extract(&self, _client: &reqwest::Client, _url: &Url) -> Result<Option<Entry>> {
        // TODO: oembed metadata + yt-dlp captions → Entry
        Ok(None)
    }

    fn name(&self) -> &'static str {
        "youtube"
    }
}
