//! Core types, traits, and identifiers shared across all modules.
//! This module depends on nothing except `serde` and `url`.

mod traits;
mod types;

pub use traits::Extractor;
pub use types::{Entry, EntryId, SourceType};
