//! Integration tests for the YouTube extractor.

use url::Url;

use pliny::core::Extractor;
use pliny::extractors::YouTubeExtractor;

#[tokio::test]
async fn can_handle_youtube_urls() {
    let extractor = YouTubeExtractor;
    assert!(extractor.can_handle(&Url::parse("https://www.youtube.com/watch?v=dQw4w9WgXcQ").unwrap()));
    assert!(extractor.can_handle(&Url::parse("https://youtu.be/dQw4w9WgXcQ").unwrap()));
    assert!(extractor.can_handle(&Url::parse("https://www.youtube.com/shorts/abc123").unwrap()));
}

#[tokio::test]
async fn does_not_handle_non_youtube() {
    let extractor = YouTubeExtractor;
    assert!(!extractor.can_handle(&Url::parse("https://vimeo.com/12345").unwrap()));
    assert!(!extractor.can_handle(&Url::parse("https://example.com/video").unwrap()));
}

#[tokio::test]
async fn name_is_youtube() {
    assert_eq!(YouTubeExtractor.name(), "youtube");
}
