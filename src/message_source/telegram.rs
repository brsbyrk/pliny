//! Telegram bot via long polling.

use anyhow::{anyhow, Result};
use reqwest::Client;
use serde::Deserialize;
use std::sync::Arc;
use std::time::Duration;
use tokio::sync::Mutex as TokioMutex;

use super::IncomingMessage;
use crate::store::Store;

/// Telegram bot using long polling (no webhook needed).
pub struct TelegramBot {
    token: String,
    client: Client,
    store: Arc<Store>,
    offset: TokioMutex<i64>,
}

#[derive(Debug, Deserialize)]
struct TgResponse {
    ok: bool,
    result: Option<Vec<TgUpdate>>,
}

#[derive(Debug, Deserialize)]
struct TgUpdate {
    update_id: i64,
    message: Option<TgMessage>,
    channel_post: Option<TgMessage>,
}

#[derive(Debug, Deserialize)]
struct TgMessage {
    message_id: i64,
    chat: TgChat,
    text: Option<String>,
    caption: Option<String>,
    #[serde(default)]
    entities: Vec<TgEntity>,
}

#[derive(Debug, Deserialize)]
struct TgChat {
    id: i64,
}

#[derive(Debug, Deserialize)]
struct TgEntity {
    #[serde(rename = "type")]
    kind: String,
    url: Option<String>,
    offset: i64,
    length: i64,
}

#[derive(Deserialize)]
struct TgSendResponse {
    ok: bool,
}

impl TelegramBot {
    pub fn new(token: String, store: Arc<Store>) -> Self {
        Self {
            token,
            client: Client::new(),
            store,
            offset: TokioMutex::new(-1),
        }
    }

    /// Poll for updates and process them. Returns processed count.
    async fn poll_updates(&self) -> Result<usize> {
        let offset = *self.offset.lock().await + 1;
        let url = format!(
            "https://api.telegram.org/bot{}/getUpdates?timeout=10&offset={}",
            self.token, offset
        );
        let resp = self.client.get(&url).send().await?.json::<TgResponse>().await?;
        if !resp.ok { return Err(anyhow!("Telegram API returned ok=false")); }

        let updates = resp.result.unwrap_or_default();
        let count = updates.len();

        for upd in &updates {
            if upd.update_id + 1 > *self.offset.lock().await {
                *self.offset.lock().await = upd.update_id;
            }
            let msg = upd.message.as_ref().or(upd.channel_post.as_ref());
            if let Some(msg) = msg {
                self.process_message(msg).await;
            }
        }
        Ok(count)
    }

    async fn process_message(&self, msg: &TgMessage) {
        let text = msg.text.as_deref().or(msg.caption.as_deref()).unwrap_or("");
        let chat_id = msg.chat.id.to_string();

        // Extract URLs from text and entities
        let urls: Vec<&str> = {
            let entity_urls: Vec<&str> = msg.entities.iter()
                .filter(|e| e.kind == "url" || e.kind == "text_link")
                .filter_map(|e| e.url.as_deref())
                .collect();

            if entity_urls.is_empty() {
                // Fallback: extract URLs from text via simple regex
                text.split_whitespace()
                    .filter(|w| w.starts_with("http://") || w.starts_with("https://"))
                    .collect()
            } else {
                entity_urls
            }
        };

        if urls.is_empty() {
            // Plain text without URLs — save as a note
            if !text.is_empty() {
                let entry = crate::core::Entry {
                    id: crate::core::EntryId(format!("tg-{}", msg.message_id)),
                    source_url: String::new(),
                    title: text.chars().take(80).collect(),
                    content: text.to_string(),
                    source_type: crate::core::SourceType::Note,
                    tags: vec!["telegram".into()],
                    created_at: chrono::Utc::now(),
                };
                let inserted = self.store.insert(&entry).unwrap_or(false);
                if inserted {
                    let _ = self.reply(&chat_id, "Saved your note.").await;
                }
            }
            return;
        }

        let ingest_client = reqwest::Client::builder()
            .user_agent("Pliny/0.1")
            .build()
            .unwrap_or_else(|_| reqwest::Client::new());

        for url in urls {
            let result = crate::extractors::extract(&ingest_client, url).await;
            match result {
                Ok(Some(entry)) => {
                    let title = entry.title.clone();
                    let source = entry.source_type.as_str().to_string();
                    let inserted = self.store.insert(&entry).unwrap_or(false);
                    if inserted {
                        let _ = self.reply(&chat_id, &format!("Saved: {} [{}]", title, source)).await;
                    } else {
                        let _ = self.reply(&chat_id, "Already saved.").await;
                    }
                }
                Ok(None) => {
                    let _ = self.reply(&chat_id, &format!("Could not extract: {}", url)).await;
                }
                Err(e) => {
                    let _ = self.reply(&chat_id, &format!("Error: {}", e)).await;
                }
            }
        }
    }

    /// Run the polling loop forever.
    pub async fn run_loop(&self) {
        loop {
            match self.poll_updates().await {
                Ok(_) => tokio::time::sleep(Duration::from_secs(2)).await,
                Err(e) => {
                    tracing::warn!("Telegram poll error: {e}, retrying in 5s");
                    tokio::time::sleep(Duration::from_secs(5)).await;
                }
            }
        }
    }

    /// Send a text reply.
    pub async fn reply(&self, chat_id: &str, text: &str) -> Result<()> {
        let url = format!(
            "https://api.telegram.org/bot{}/sendMessage",
            self.token
        );
        let resp = self.client
            .post(&url)
            .json(&serde_json::json!({
                "chat_id": chat_id,
                "text": text,
                "disable_notification": true,
            }))
            .send()
            .await?;
        let body: TgSendResponse = resp.json().await?;
        if !body.ok {
            Err(anyhow!("sendMessage returned ok=false"))
        } else {
            Ok(())
        }
    }
}
