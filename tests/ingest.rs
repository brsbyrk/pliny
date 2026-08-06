//! Integration tests for the ingest pipeline (extract + store).

use httpmock::prelude::*;
use pliny::core::Extractor;
use pliny::store::Store;

const VALID_ARTICLE: &str = r#"<!DOCTYPE html>
<html>
<head><title>Integration Test Article</title></head>
<body>
    <article>
        <h1>Test Article</h1>
        <p>This article contains enough text to be considered meaningful
        content by the readability extraction algorithm. It discusses
        important topics and provides substantial information for the reader.</p>
        <p>Additional paragraph with more detail and depth about the subject
        matter, ensuring the content exceeds the minimum threshold for extraction.</p>
    </article>
</body>
</html>"#;

#[tokio::test]
async fn ingest_web_article_stores_entry() {
    let server = MockServer::start();

    let mock = server.mock(|when, then| {
        when.method(GET).path("/article");
        then.status(200)
            .header("content-type", "text/html")
            .body(VALID_ARTICLE);
    });

    let client = reqwest::Client::new();
    let url = server.url("/article");

    let entry = pliny::extractors::WebExtractor
        .extract(&client, &url.parse().unwrap())
        .await
        .unwrap();
    mock.assert();

    let entry = entry.expect("should extract article");

    let store = Store::open_in_memory().unwrap();
    store.insert(&entry).unwrap();

    assert_eq!(store.count().unwrap(), 1);
    assert_eq!(entry.source_type, pliny::core::SourceType::Web);
    assert!(!entry.title.is_empty());
}

#[tokio::test]
async fn ingest_nonexistent_url_returns_none() {
    let server = MockServer::start();

    let mock = server.mock(|when, then| {
        when.method(GET).path("/404");
        then.status(404).body("Not Found");
    });

    let client = reqwest::Client::new();
    let url = server.url("/404");

    let result = pliny::extractors::WebExtractor
        .extract(&client, &url.parse().unwrap())
        .await
        .unwrap();
    mock.assert();

    assert!(result.is_none(), "404 should return None");
}

#[tokio::test]
async fn store_persists_entry() {
    use pliny::core::{Entry, EntryId, SourceType};

    let store = Store::open_in_memory().unwrap();

    let entry = Entry {
        id: EntryId("test-entry".into()),
        source_url: "https://example.com".into(),
        title: "Test".into(),
        content: "Content".into(),
        source_type: SourceType::Web,
        tags: vec!["test".into()],
        created_at: chrono::Utc::now(),
    };

    store.insert(&entry).unwrap();
    assert_eq!(store.count().unwrap(), 1);
}
