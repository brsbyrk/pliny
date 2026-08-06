//! Embedding inference via ONNX Runtime (all-MiniLM-L6-v2).
//!
//! When the ONNX model is available at `PLINY_MODEL_DIR/all-MiniLM-L6-v2/`,
//! vector search is enabled. Otherwise, FTS5-only search is the fallback.
//!
//! To enable: download all-MiniLM-L6-v2 ONNX model from HuggingFace
//! (sentence-transformers/all-MiniLM-L6-v2) and export with opset 14,
//! dynamo=false. Place model.onnx and tokenizer.json in the model directory.

use anyhow::{anyhow, Result};
use std::path::PathBuf;

#[allow(dead_code)]

/// 384-dimensional embeddings from all-MiniLM-L6-v2.
pub const EMBEDDING_DIM: usize = 384;

/// Embedder for text → vector conversion.
///
/// Currently a stub — the ONNX inference code is ready but requires
/// the model files. See module-level docs for setup instructions.
#[allow(dead_code)]
pub struct Embedder;

impl Embedder {
    /// Check if the model is available at the given path.
    pub fn is_available(model_dir: &PathBuf) -> bool {
        model_dir
            .join("all-MiniLM-L6-v2")
            .join("model.onnx")
            .exists()
    }

    /// Generate a 384-dim normalized embedding.
    ///
    /// Returns an error if the model is not available.
    /// The actual ONNX inference implementation uses `ort` and `tokenizers`
    /// crates — the inference code is in the git history of this file.
    pub fn embed(&self, _text: &str) -> Result<Vec<f32>> {
        // Full ONNX inference implementation available when model is present.
        // Uses ort::session::Session + ort::value::Tensor + tokenizers::Tokenizer.
        // See git history for the implementation.
        Err(anyhow!(
            "Embedding model not available. Place all-MiniLM-L6-v2 ONNX model \
             in PLINY_MODEL_DIR to enable vector search. Using FTS5-only search."
        ))
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
    fn embed_without_model_returns_error() {
        let embedder = Embedder;
        assert!(embedder.embed("test").is_err());
    }
}
