use std::time::Duration;

#[tokio::test]
async fn e2e_queries_across_multiple_dbs() -> anyhow::Result<()> {
    let tmp = assert_fs::TempDir::new()?;
    let make = |name: &str| -> anyhow::Result<String> { let d = tmp.path().join(name); std::fs::create_dir_all(&d)?; std::fs::write(d.join(".seagoatdb.yaml"), b"tables:\n  - name: hello\n")?; Ok(d.to_string_lossy().to_string()) };
    let alpha = make("alpha")?; let beta = make("beta")?; let gamma = make("gamma")?;

    let cfg = seagoat_server::DatabasesConfig { databases: vec![alpha.clone(), beta.clone(), gamma.clone()] };
    let dbs = seagoat_server::initialize_databases_from_config(&cfg).await?;
    let app = seagoat_server::build_router(seagoat_server::AppState { dbs });

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let addr = listener.local_addr()?;

    let server_task = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });

    let client = reqwest::Client::new();
    let url = format!("http://{}/v1/query", addr);

    for path in [alpha, beta, gamma] {
        let deadline = tokio::time::Instant::now() + Duration::from_secs(5);
        let json = loop {
            if tokio::time::Instant::now() > deadline {
                server_task.abort();
                anyhow::bail!("server did not respond in time for {}", path);
            }
            match client.post(&url).json(&serde_json::json!({"type": "Overview", "path": path})).send().await {
                Ok(resp) if resp.status().is_success() => {
                    let json: serde_json::Value = resp.json().await?;
                    break json;
                }
                _ => tokio::time::sleep(Duration::from_millis(20)).await,
            }
        };
        assert!(json["hello_count"].as_i64().unwrap_or(0) >= 2);
        assert!(json["tables"].as_array().unwrap().contains(&serde_json::json!("hello")));
    }

    server_task.abort();
    Ok(())
}
