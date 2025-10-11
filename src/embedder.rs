use sha2::{Digest, Sha256};

/// Represents a generic text embedder.
/// The current implementation provides a deterministic CPU fallback based on SHA-256
/// so tests are reproducible without pulling large ML models.
/// Later, enable feature `embed-qwen3` to integrate real Qwen3 embeddings via Candle/hf-hub.
#[derive(Debug, Clone)]
pub struct Embedder {
    /// Optional model identifier for future use (e.g., "Qwen/Qwen2.5-0.5B-Instruct")
    model_id: String,
}

impl Default for Embedder {
    fn default() -> Self {
        Self {
            model_id: "Qwen3-Embedding".to_string(),
        }
    }
}

impl Embedder {
    pub fn new(model_id: impl Into<String>) -> Self {
        Self {
            model_id: model_id.into(),
        }
    }

    pub fn model_id(&self) -> &str {
        &self.model_id
    }

    /// Produce a fixed-size embedding for each input string.
    /// - In fallback mode (no `embed-qwen3`), returns a 384-dim vector derived from SHA-256
    ///   expanded deterministically per item.
    /// - With `embed-qwen3` feature, this should call the actual model.
    pub fn embed(&self, inputs: &[impl AsRef<str>]) -> anyhow::Result<Vec<Vec<f32>>> {
        #[cfg(feature = "embed-qwen3")]
        {
            // Placeholder: in a future step, wire up Candle + hf-hub here.
            // For now, keep the same deterministic behavior to ease integration.
            Ok(inputs.iter().map(|s| fallback_embed(s.as_ref())).collect())
        }

        #[cfg(not(feature = "embed-qwen3"))]
        {
            Ok(inputs.iter().map(|s| fallback_embed(s.as_ref())).collect())
        }
    }
}

const FALLBACK_DIM: usize = 384;

fn fallback_embed(text: &str) -> Vec<f32> {
    // Hash the text to 32 bytes, then expand deterministically to FALLBACK_DIM
    let mut hasher = Sha256::new();
    hasher.update(text.as_bytes());
    let seed = hasher.finalize();

    let mut output = Vec::with_capacity(FALLBACK_DIM);
    let mut state = [0u8; 32];
    state.copy_from_slice(&seed);

    let mut block_id: u32 = 0;
    while output.len() < FALLBACK_DIM {
        let mut h = Sha256::new();
        h.update(&state);
        h.update(block_id.to_le_bytes());
        let block = h.finalize();
        // convert chunks of 4 bytes into f32 in a stable range
        for chunk in block.chunks_exact(4) {
            if output.len() == FALLBACK_DIM {
                break;
            }
            let u = u32::from_le_bytes([chunk[0], chunk[1], chunk[2], chunk[3]]);
            // map to [-1, 1]
            let f = (u as f32 / u32::MAX as f32) * 2.0 - 1.0;
            output.push(f);
        }
        block_id = block_id.wrapping_add(1);
    }

    output
}
