use std::time::Duration;

#[tokio::test]
async fn snapshot_overview_json() -> anyhow::Result<()> {
    let tmp = assert_fs::TempDir::new()?;
    let alpha = tmp.path().join("alpha");
    std::fs::create_dir_all(&alpha)?;
    std::fs::write(alpha.join(".seagoatdb.yaml"), b"tables:\n  - name: hello\n")?;
    let alpha_path = alpha.to_string_lossy().to_string();

    let cfg = seagoat_server::DatabasesConfig { databases: vec![alpha_path.clone()] };
    let dbs = seagoat_server::initialize_databases_from_config(&cfg).await?;
    let app = seagoat_server::build_router(seagoat_server::AppState { dbs });

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let addr = listener.local_addr()?;

    let server_task = tokio::spawn(async move { axum::serve(listener, app).await.unwrap(); });

    let client = reqwest::Client::new();
    let url = format!("http://{}/v1/query", addr);

    let deadline = tokio::time::Instant::now() + Duration::from_secs(5);
    let json = loop {
        if tokio::time::Instant::now() > deadline { server_task.abort(); anyhow::bail!("timeout"); }
        match client.post(&url).json(&serde_json::json!({"type": "Overview", "path": alpha_path})).send().await {
            Ok(resp) if resp.status().is_success() => {
                let json: serde_json::Value = resp.json().await?;
                break json;
            }
            _ => tokio::time::sleep(Duration::from_millis(20)).await,
        }
    };

    let contains_hello = json["tables"].as_array().unwrap().iter().any(|v| v == "hello");
    let hello_count = json["hello_count"].as_i64().unwrap_or(0);

    let normalized = serde_json::json!({
        "contains_hello": contains_hello,
        "hello_count": hello_count,
    });

    insta::assert_snapshot!(
        "overview_normalized",
        serde_json::to_string_pretty(&normalized).unwrap()
    );

    server_task.abort();
    Ok(())
}
