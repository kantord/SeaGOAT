#[test]
fn snapshot_single_and_batch_embeddings() {
    let emb = seagoat::embedder::Embedder::default();

    // single
    let v1 = emb.embed(&["hello world"]).unwrap();
    let v2 = emb.embed(&["SeaGOAT rocks!"]).unwrap();

    // batch
    let batch = emb
        .embed(&["hello world", "SeaGOAT rocks!", "rust axum lancedb"])
        .unwrap();

    assert_eq!(v1.len(), 1);
    assert_eq!(v2.len(), 1);
    assert_eq!(batch.len(), 3);

    // Basic deterministic properties
    assert_eq!(v1[0].len(), v2[0].len());
    assert_eq!(v1[0].len(), batch[0].len());

    // Snapshot vector norms and first/last few elements for stability across platforms
    let summarize = |v: &Vec<f32>| -> serde_json::Value {
        let len = v.len();
        let head: Vec<f32> = v.iter().cloned().take(4).collect();
        let tail: Vec<f32> = v.iter().cloned().rev().take(4).collect::<Vec<_>>().into_iter().rev().collect();
        let norm: f64 = v.iter().map(|x| (*x as f64) * (*x as f64)).sum::<f64>().sqrt();
        serde_json::json!({
            "len": len,
            "head": head,
            "tail": tail,
            "l2_norm": norm,
        })
    };

    let snapshot = serde_json::json!({
        "single_hello": summarize(&v1[0]),
        "single_seagoat": summarize(&v2[0]),
        "batch_0": summarize(&batch[0]),
        "batch_1": summarize(&batch[1]),
        "batch_2": summarize(&batch[2]),
    });

    insta::assert_snapshot!(
        "embedder_single_and_batch",
        serde_json::to_string_pretty(&snapshot).unwrap()
    );
}

#[test]
fn snapshot_parametric_inputs() {
    let emb = seagoat::embedder::Embedder::default();
    let inputs = vec![
        "",
        "a",
        "The quick brown fox jumps over the lazy dog.",
        "🚀 Unicode test: café naïve coöperate – emojis 👍",
        "Newlines\nare handled\tand tabs too",
    ];

    let outputs = emb.embed(&inputs).unwrap();

    let summary: Vec<serde_json::Value> = outputs
        .iter()
        .map(|v| {
            let head: Vec<f32> = v.iter().cloned().take(3).collect();
            let tail: Vec<f32> = v.iter().cloned().rev().take(3).collect::<Vec<_>>().into_iter().rev().collect();
            let norm: f64 = v.iter().map(|x| (*x as f64) * (*x as f64)).sum::<f64>().sqrt();
            serde_json::json!({
                "len": v.len(),
                "head": head,
                "tail": tail,
                "l2_norm": norm,
            })
        })
        .collect();

    insta::assert_snapshot!(
        "embedder_parametric_inputs",
        serde_json::to_string_pretty(&serde_json::json!({
            "inputs": inputs,
            "summaries": summary,
        })).unwrap()
    );
}
