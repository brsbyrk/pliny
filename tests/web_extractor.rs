//! Tests for the web extractor (readability-based HTML extraction).

use httpmock::prelude::*;
use reqwest::Client;
use url::Url;

use pliny::core::Extractor;
use pliny::extractors::WebExtractor;

/// A valid article HTML page that readability should extract.
const VALID_ARTICLE: &str = r#"<!DOCTYPE html>
<html>
<head><title>Test Article Title</title></head>
<body>
    <article>
        <h1>Main Heading</h1>
        <p>This is the first paragraph of the article. It contains enough text
        to be considered meaningful content by the readability algorithm.</p>
        <p>Second paragraph with more detail about the topic at hand.
        This paragraph provides additional context and information.</p>
        <p>A third paragraph that rounds out the article with concluding
        thoughts and final observations about the subject matter.</p>
    </article>
    <nav>Navigation sidebar (should be excluded)</nav>
    <footer>Copyright 2024 (should be excluded)</footer>
</body>
</html>"#;

/// A page with no meaningful content.
const EMPTY_PAGE: &str = r#"<!DOCTYPE html>
<html>
<head><title>Empty</title></head>
<body></body>
</html>"#;

#[test]
fn can_handle_any_url() {
    let extractor = WebExtractor;
    assert!(extractor.can_handle(&Url::parse("https://example.com").unwrap()));
    assert!(extractor.can_handle(&Url::parse("https://blog.com/post").unwrap()));
    assert!(extractor.can_handle(&Url::parse("https://any.domain.xyz/path?q=1").unwrap()));
}

#[test]
fn name_is_web() {
    assert_eq!(WebExtractor.name(), "web");
}

#[tokio::test]
async fn extract_valid_article() {
    let server = MockServer::start();

    let mock = server.mock(|when, then| {
        when.method(GET).path("/article");
        then.status(200)
            .header("content-type", "text/html; charset=utf-8")
            .body(VALID_ARTICLE);
    });

    let url = Url::parse(&server.url("/article")).unwrap();
    let client = Client::new();

    let result = WebExtractor.extract(&client, &url).await.unwrap();
    mock.assert();

    let entry = result.expect("should extract article");
    assert!(!entry.title.is_empty(), "title should not be empty");
    assert!(!entry.content.is_empty(), "content should not be empty");
    assert_eq!(entry.source_type, pliny::core::SourceType::Web);
}

#[tokio::test]
async fn extract_404_returns_none() {
    let server = MockServer::start();

    let mock = server.mock(|when, then| {
        when.method(GET).path("/gone");
        then.status(404).body("Not Found");
    });

    let url = Url::parse(&server.url("/gone")).unwrap();
    let client = Client::new();

    let result = WebExtractor.extract(&client, &url).await.unwrap();
    mock.assert();

    assert!(result.is_none(), "404 should return None");
}

#[tokio::test]
async fn extract_empty_page_returns_none() {
    let server = MockServer::start();

    let mock = server.mock(|when, then| {
        when.method(GET).path("/empty");
        then.status(200)
            .header("content-type", "text/html")
            .body(EMPTY_PAGE);
    });

    let url = Url::parse(&server.url("/empty")).unwrap();
    let client = Client::new();

    let result = WebExtractor.extract(&client, &url).await.unwrap();
    mock.assert();

    assert!(result.is_none(), "empty page should return None");
}

#[tokio::test]
async fn extract_non_html_content_returns_none() {
    let server = MockServer::start();

    let mock = server.mock(|when, then| {
        when.method(GET).path("/file.pdf");
        then.status(200)
            .header("content-type", "application/pdf")
            .body("%PDF-1.4 fake pdf content");
    });

    let url = Url::parse(&server.url("/file.pdf")).unwrap();
    let client = Client::new();

    let result = WebExtractor.extract(&client, &url).await.unwrap();
    mock.assert();

    assert!(result.is_none(), "non-HTML content should return None");
}
