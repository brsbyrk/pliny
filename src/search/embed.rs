//! Embedding inference via ONNX Runtime (all-MiniLM-L6-v2).
//!
//! Requires model files at `PLINY_MODEL_DIR/all-MiniLM-L6-v2/`.
//! Run `python scripts/setup-model.py` to download and export the model.

use anyhow::{anyhow, Result};
use std::path::PathBuf;
use std::sync::Mutex;

/// 384-dimensional embeddings from all-MiniLM-L6-v2.
pub const EMBEDDING_DIM: usize = 384;
const MAX_LENGTH: usize = 256;

pub struct Embedder {
    session: Mutex<ort::session::Session>,
    tokenizer: tokenizers::Tokenizer,
}

impl Embedder {
    /// Load the ONNX model. Expects model.onnx and tokenizer.json.
    pub fn load(model_dir: &PathBuf) -> Result<Self> {
        let model_path = model_dir.join("all-MiniLM-L6-v2").join("model.onnx");
        let tokenizer_path = model_dir.join("all-MiniLM-L6-v2").join("tokenizer.json");

        if !model_path.exists() {
            return Err(anyhow!(
                "ONNX model not found at {}. Run: python scripts/setup-model.py",
                model_path.display()
            ));
        }

        let session = ort::session::Session::builder()?.commit_from_file(model_path)?;
        let tokenizer = tokenizers::Tokenizer::from_file(&tokenizer_path)
            .map_err(|e| anyhow!("Failed to load tokenizer: {e}"))?;

        tracing::info!("Embedder loaded: all-MiniLM-L6-v2 ({} dims)", EMBEDDING_DIM);
        Ok(Self { session: Mutex::new(session), tokenizer })
    }

    /// Generate a 384-dim L2-normalized embedding.
    pub fn embed(&self, text: &str) -> Result<Vec<f32>> {
        let encoding = self.tokenizer
            .encode(text, true)
            .map_err(|e| anyhow!("Tokenization failed: {e}"))?;

        let ids: Vec<i64> = encoding.get_ids().iter().map(|&id| id as i64).collect();
        let mask: Vec<i64> = encoding.get_attention_mask().iter().map(|&m| m as i64).collect();
        let len = ids.len().min(MAX_LENGTH);
        let ids = &ids[..len];
        let mask = &mask[..len];

        let input_ids = ort::value::Tensor::from_array(
            (vec![1i64, len as i64], ids.to_vec()),
        )?;
        let attn_mask = ort::value::Tensor::from_array(
            (vec![1i64, len as i64], mask.to_vec()),
        )?;
        let token_type_ids = ort::value::Tensor::from_array(
            (vec![1i64, len as i64], vec![0i64; len]),
        )?;

        let inputs = ort::inputs![
            "input_ids" => input_ids,
            "attention_mask" => attn_mask,
            "token_type_ids" => token_type_ids,
        ];

        let mut session = self.session.lock().unwrap();
        let outputs = session.run(inputs)?;

        // try_extract_tensor returns (&Shape, &[f32])
        let (_shape, data): (&ort::value::Shape, &[f32]) = outputs["last_hidden_state"]
            .try_extract_tensor()
            .map_err(|e| anyhow!("Failed to extract tensor: {e}"))?;

        let seq_len = _shape[1] as usize;
        let hidden_dim = _shape[2] as usize;

        // Mean pooling with attention mask + L2 normalize
        let mut embedding = vec![0.0f32; hidden_dim];
        let mut mask_sum = 0.0f32;

        for t in 0..seq_len {
            let m = mask[t] as f32;
            if m > 0.0 {
                mask_sum += m;
                for d in 0..hidden_dim {
                    embedding[d] += data[t * hidden_dim + d] * m;
                }
            }
        }

        if mask_sum > 0.0 {
            for d in 0..hidden_dim { embedding[d] /= mask_sum; }
        }

        let norm: f32 = embedding.iter().map(|x| x * x).sum::<f32>().sqrt();
        if norm > 0.0 {
            for d in 0..hidden_dim { embedding[d] /= norm; }
        }

        Ok(embedding)
    }

    /// Check if the model is available.
    pub fn is_available(model_dir: &PathBuf) -> bool {
        model_dir.join("all-MiniLM-L6-v2").join("model.onnx").exists()
    }

    /// Generate embedding for short text (title + first 500 chars of content).
    pub fn embed_entry(title: &str, content: &str) -> String {
        let preview: String = content.chars().take(500).collect();
        format!("{} {}", title, preview)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn embedder_not_available_without_model() {
        let temp = std::env::temp_dir().join("pliny-test-nonexistent");
        assert!(!Embedder::is_available(&temp));
    }

    #[test]
    fn embedding_dimension_is_384() {
        assert_eq!(EMBEDDING_DIM, 384);
    }

    #[test]
    fn embed_text_format() {
        let text = Embedder::embed_entry("Rust Guide", "How to write async code in Rust with Tokio...");
        assert!(text.contains("Rust Guide"));
        assert!(text.contains("Tokio"));
    }
}
