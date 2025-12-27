use std::time::Duration;

#[tokio::test]
async fn e2e_query_overview_and_search() -> anyhow::Result<()> {
    // Build fixture DB folder with .seagoatdb.yaml
    let tmp = assert_fs::TempDir::new()?;
    let alpha = tmp.path().join("alpha");
    std::fs::create_dir_all(&alpha)?;
    std::fs::write(alpha.join(".seagoatdb.yaml"), b"tables:\n  - name: hello\n")?;
    let alpha_path = alpha.to_string_lossy().to_string();

    // Initialize router directly
    let cfg = seagoat_server::DatabasesConfig { databases: vec![alpha_path.clone()] };
    let dbs = seagoat_server::initialize_databases_from_config(&cfg).await?;
    let app = seagoat_server::build_router(seagoat_server::AppState { dbs });

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let addr = listener.local_addr()?;

    let server_task = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });

    let client = reqwest::Client::new();
    let url = format!("http://{}/v1/query", addr);

    // Overview
    let deadline = tokio::time::Instant::now() + Duration::from_secs(5);
    let json = loop {
        if tokio::time::Instant::now() > deadline {
            server_task.abort();
            anyhow::bail!("server did not respond in time");
        }
        match client.post(&url).json(&serde_json::json!({"type": "Overview", "path": alpha_path})).send().await {
            Ok(resp) if resp.status().is_success() => {
                let json: serde_json::Value = resp.json().await?;
                break json;
            }
            _ => tokio::time::sleep(Duration::from_millis(20)).await,
        }
    };
    assert!(json["hello_count"].as_i64().unwrap_or(0) >= 2);

    // Search
    let resp = client.post(&url)
        .json(&serde_json::json!({"type": "Search", "path": alpha_path, "query": "hello", "top_k": 2}))
        .send().await?;
    assert_eq!(resp.status(), 200);
    let hits = resp.json::<serde_json::Value>().await?["hits"].as_array().cloned().unwrap_or_default();
    assert!(!hits.is_empty());

    server_task.abort();
    Ok(())
}
