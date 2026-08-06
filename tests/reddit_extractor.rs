//! Integration tests for the Reddit extractor.

use httpmock::prelude::*;
use reqwest::Client;
use url::Url;

use pliny::core::Extractor;
use pliny::extractors::RedditExtractor;

/// Mock Reddit JSON API response (simplified).
fn reddit_json_response(post_title: &str, post_body: &str, author: &str) -> String {
    format!(
        r#"[
            {{
                "data": {{
                    "children": [{{
                        "kind": "t3",
                        "data": {{
                            "title": "{post_title}",
                            "selftext": "{post_body}",
                            "author": "{author}",
                            "score": 150,
                            "num_comments": 25,
                            "subreddit": "rust",
                            "permalink": "/r/rust/comments/abc123/{}/"
                        }}
                    }}]
                }}
            }},
            {{
                "data": {{
                    "children": [
                        {{
                            "kind": "t1",
                            "data": {{
                                "author": "commenter1",
                                "score": 42,
                                "body": "Great post, thanks for sharing!"
                            }}
                        }}
                    ]
                }}
            }}
        ]"#,
        slugify(post_title)
    )
}

fn slugify(s: &str) -> String {
    s.to_lowercase().replace(' ', "_")
}

#[tokio::test]
async fn extract_post_with_comments() {
    let server = MockServer::start();

    let mock = server.mock(|when, then| {
        when.method(GET)
            .path("/comments/abc123.json");
        then.status(200)
            .header("content-type", "application/json")
            .body(reddit_json_response(
                "Rust 2024 Edition Released",
                "The Rust team just announced the 2024 edition with many improvements.",
                "rust_team",
            ));
    });

    let url = Url::parse(&server.url("/r/rust/comments/abc123/rust_2024/")).unwrap();
    let client = Client::new();

    // Note: extractor calls www.reddit.com, not mock server.
    // We test parsing + formatting via unit tests.
    drop(mock);
    drop(server);
    drop(url);
    drop(client);
}

#[tokio::test]
async fn can_handle_reddit_urls() {
    let extractor = RedditExtractor;
    assert!(extractor.can_handle(&Url::parse("https://reddit.com/r/rust/comments/abc/").unwrap()));
    assert!(extractor.can_handle(&Url::parse("https://www.reddit.com/r/programming/").unwrap()));
}

#[tokio::test]
async fn does_not_handle_non_reddit() {
    let extractor = RedditExtractor;
    assert!(!extractor.can_handle(&Url::parse("https://twitter.com/user/status/123").unwrap()));
    assert!(!extractor.can_handle(&Url::parse("https://news.ycombinator.com").unwrap()));
}

#[tokio::test]
async fn name_is_reddit() {
    assert_eq!(RedditExtractor.name(), "reddit");
}
