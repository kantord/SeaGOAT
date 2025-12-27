#[tokio::test]
async fn e2e_list_databases_includes_paths() -> anyhow::Result<()> {
    let tmp = assert_fs::TempDir::new()?;
    let make = |name: &str| -> anyhow::Result<String> { let d = tmp.path().join(name); std::fs::create_dir_all(&d)?; std::fs::write(d.join(".seagoatdb.yaml"), b"tables:\n  - name: hello\n")?; Ok(d.to_string_lossy().to_string()) };
    let alpha = make("alpha")?; let beta = make("beta")?; let gamma = make("gamma")?;

    let cfg = seagoat_server::DatabasesConfig { databases: vec![alpha.clone(), beta.clone(), gamma.clone()] };
    let dbs = seagoat_server::initialize_databases_from_config(&cfg).await?;
    let app = seagoat_server::build_router(seagoat_server::AppState { dbs });

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let addr = listener.local_addr()?;

    let server_task = tokio::spawn(async move { axum::serve(listener, app).await.unwrap(); });

    let client = reqwest::Client::new();
    let url = format!("http://{}/v1/databases", addr);
    let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(5);
    let arr = loop {
        if tokio::time::Instant::now() > deadline { server_task.abort(); anyhow::bail!("timeout"); }
        match client.get(&url).send().await {
            Ok(resp) if resp.status().is_success() => {
                let json: serde_json::Value = resp.json().await?;
                break json.as_array().cloned().unwrap_or_default();
            }
            _ => tokio::time::sleep(std::time::Duration::from_millis(20)).await,
        }
    };

    let paths: Vec<String> = arr.into_iter().map(|d| d["path"].as_str().unwrap().to_string()).collect();
    for id in [alpha, beta, gamma] { assert!(paths.contains(&id)); }

    server_task.abort();
    Ok(())
}
