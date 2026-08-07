//! Message source trait + dispatcher — pluggable chat platforms.

/// A parsed incoming message from any platform.
#[derive(Debug, Clone)]
pub struct IncomingMessage {
    pub chat_id: String,
    pub text: String,
    pub sender: Option<String>,
}

/// All chat platforms implement this trait.
#[async_trait::async_trait]
pub trait MessageSource: Send + Sync {
    fn name(&self) -> &str;
    async fn start(&self) -> anyhow::Result<()>;
    async fn reply(&self, chat_id: &str, text: &str) -> anyhow::Result<()>;
}

mod telegram;

use anyhow::Result;
use std::sync::Arc;
use crate::store::Store;

/// Start all configured message sources as background tasks.
pub fn start_bots(store: Arc<Store>) {
    if let Ok(token) = std::env::var("PLINY_TELEGRAM_TOKEN") {
        if !token.is_empty() {
            let bot = telegram::TelegramBot::new(token, Arc::clone(&store));
            tokio::spawn(async move {
                tracing::info!("Telegram bot started");
                bot.run_loop().await;
            });
        }
    }
}
