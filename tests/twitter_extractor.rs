//! Integration tests for the X/Twitter extractor.
//!
//! Tests the og:meta primary extraction and fxtwitter enrichment.

use httpmock::prelude::*;
use reqwest::Client;
use url::Url;

use pliny::core::Extractor;
use pliny::extractors::XExtractor;

/// HTML of a typical X/Twitter status page (simplified).
fn tweet_page_html(og_description: &str, og_title: &str) -> String {
    format!(
        r#"<!DOCTYPE html>
<html>
<head>
    <meta property="og:description" content="{og_description}">
    <meta property="og:title" content="{og_title}">
</head>
<body><div id="react-root">tweet content here</div></body>
</html>"#
    )
}

#[tokio::test]
async fn extract_tweet_via_og_meta() {
    let server = MockServer::start();

    let tweet_mock = server.mock(|when, then| {
        when.method(GET)
            .path("/karpathy/status/1234567890");
        then.status(200)
            .header("content-type", "text/html")
            .body(tweet_page_html(
                "Andrej Karpathy: Just read this great paper on transformer architectures",
                "Andrej Karpathy on X",
            ));
    });

    let url = Url::parse(&server.url("/karpathy/status/1234567890")).unwrap();
    let client = Client::new();

    let result = XExtractor.extract(&client, &url).await.unwrap();
    tweet_mock.assert();

    let entry = result.expect("should extract tweet");
    assert!(entry.title.contains("Andrej Karpathy"));
    assert!(entry.content.contains("transformer architectures"));
    assert_eq!(entry.source_type, pliny::core::SourceType::X);
}

#[tokio::test]
async fn extract_unavailable_tweet_returns_none() {
    let server = MockServer::start();

    let mock = server.mock(|when, then| {
        when.method(GET).path("/user/status/999");
        then.status(200)
            .header("content-type", "text/html")
            .body(tweet_page_html(
                "This Tweet is unavailable",
                "X",
            ));
    });

    let url = Url::parse(&server.url("/user/status/999")).unwrap();
    let client = Client::new();

    let result = XExtractor.extract(&client, &url).await.unwrap();
    mock.assert();

    assert!(result.is_none(), "unavailable tweet should return None");
}

#[tokio::test]
async fn extract_no_og_description_returns_none() {
    let server = MockServer::start();

    let mock = server.mock(|when, then| {
        when.method(GET).path("/user/status/456");
        then.status(200)
            .header("content-type", "text/html")
            .body("<html><head></head><body>no meta tags</body></html>");
    });

    let url = Url::parse(&server.url("/user/status/456")).unwrap();
    let client = Client::new();

    let result = XExtractor.extract(&client, &url).await.unwrap();
    mock.assert();

    assert!(result.is_none(), "no og:description should return None");
}

#[tokio::test]
async fn extract_404_returns_none() {
    let server = MockServer::start();

    let mock = server.mock(|when, then| {
        when.method(GET).path("/user/status/404");
        then.status(404).body("Not Found");
    });

    let url = Url::parse(&server.url("/user/status/404")).unwrap();
    let client = Client::new();

    let result = XExtractor.extract(&client, &url).await.unwrap();
    mock.assert();

    assert!(result.is_none(), "404 should return None");
}

#[tokio::test]
async fn name_is_x() {
    assert_eq!(XExtractor.name(), "x");
}

#[tokio::test]
async fn can_handle_x_urls() {
    let extractor = XExtractor;
    assert!(extractor.can_handle(&Url::parse("https://x.com/user/status/123").unwrap()));
    assert!(extractor.can_handle(&Url::parse("https://twitter.com/user/status/456").unwrap()));
}

#[tokio::test]
async fn does_not_handle_non_x_urls() {
    let extractor = XExtractor;
    assert!(!extractor.can_handle(&Url::parse("https://youtube.com/watch?v=123").unwrap()));
    assert!(!extractor.can_handle(&Url::parse("https://example.com").unwrap()));
}
