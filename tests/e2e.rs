use std::time::Duration;

#[tokio::test]
async fn e2e_query_returns_hello_world() -> anyhow::Result<()> {
    let dbs = seagoat::initialize_example_databases().await.unwrap();
    let app = seagoat::build_router(seagoat::AppState { dbs });

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let addr = listener.local_addr()?;

    let server_task = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });

    let client = reqwest::Client::new();
    let url = format!("http://{}/v1/query", addr);

    let mut last_err: Option<reqwest::Error> = None;
    for _ in 0..50u32 {
        match client.post(&url).json(&serde_json::json!({"type": "Overview", "path": "/mock/db/alpha"})).send().await {
            Ok(resp) => {
                assert_eq!(resp.status(), 200);
                let json: serde_json::Value = resp.json().await?;
                assert!(json["hello_count"].as_i64().unwrap_or(0) >= 2);
                assert!(json["tables"].as_array().unwrap().contains(&serde_json::json!("hello")));
                server_task.abort();
                return Ok(());
            }
            Err(err) => {
                last_err = Some(err);
                tokio::time::sleep(Duration::from_millis(20)).await;
            }
        }
    }

    server_task.abort();
    Err(anyhow::anyhow!("server did not respond: {:?}", last_err))
}

#[tokio::test]
async fn e2e_queries_across_multiple_dbs() -> anyhow::Result<()> {
    let dbs = seagoat::initialize_example_databases().await?;
    let app = seagoat::build_router(seagoat::AppState { dbs });

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let addr = listener.local_addr()?;

    let server_task = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });

    let client = reqwest::Client::new();
    for id in seagoat::default_database_ids() {
        let url = format!("http://{}/v1/query", addr);

        // poll a few times in case server not ready yet
        let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(3);
        let json = loop {
            if tokio::time::Instant::now() > deadline {
                server_task.abort();
                anyhow::bail!("server did not respond in time for {}", id);
            }
            match client.post(&url).json(&serde_json::json!({"type": "Overview", "path": id})).send().await {
                Ok(resp) if resp.status().is_success() => {
                    let json: serde_json::Value = resp.json().await?;
                    break json;
                }
                _ => tokio::time::sleep(std::time::Duration::from_millis(20)).await,
            }
        };

        assert!(json["hello_count"].as_i64().unwrap_or(0) >= 2, "db={}", id);
        assert!(json["tables"].as_array().unwrap().contains(&serde_json::json!("hello")), "db={}", id);
    }

    server_task.abort();
    Ok(())
}

#[tokio::test]
async fn e2e_search_returns_embedded_texts() -> anyhow::Result<()> {
    let dbs = seagoat::initialize_example_databases().await?;
    let app = seagoat::build_router(seagoat::AppState { dbs });

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let addr = listener.local_addr()?;

    let server_task = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });

    let client = reqwest::Client::new();
    let url = format!("http://{}/v1/query", addr);

    let body = serde_json::json!({
        "type": "Search",
        "path": "/mock/db/alpha",
        "query": "hello",
        "top_k": 2
    });

    let mut last_err: Option<reqwest::Error> = None;
    for _ in 0..50u32 {
        match client.post(&url).json(&body).send().await {
            Ok(resp) if resp.status().is_success() => {
                let json: serde_json::Value = resp.json().await?;
                let texts: Vec<String> = json["hits"]
                    .as_array()
                    .unwrap_or(&vec![])
                    .iter()
                    .filter_map(|h| h.get("text").and_then(|t| t.as_str()).map(|s| s.to_string()))
                    .collect();
                assert!(texts.iter().any(|t| t == "hello"));
                assert!(texts.iter().any(|t| t == "world"));
                server_task.abort();
                return Ok(());
            }
            Ok(_resp) => {}
            Err(err) => {
                last_err = Some(err);
            }
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    }

    server_task.abort();
    Err(anyhow::anyhow!("server did not respond: {:?}", last_err))
}

#[tokio::test]
async fn e2e_list_databases_includes_paths() -> anyhow::Result<()> {
    let dbs = seagoat::initialize_example_databases().await?;
    let app = seagoat::build_router(seagoat::AppState { dbs });

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let addr = listener.local_addr()?;

    let server_task = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });

    let client = reqwest::Client::new();
    let url = format!("http://{}/v1/databases", addr);

    for _ in 0..100u32 {
        match client.get(&url).send().await {
            Ok(resp) if resp.status().is_success() => {
                let json: serde_json::Value = resp.json().await?;
                let arr = json.as_array().unwrap();
                assert!(arr.len() >= 3);
                let paths: Vec<String> = arr.iter().map(|d| d["path"].as_str().unwrap().to_string()).collect();
                for id in seagoat::default_database_ids() {
                    assert!(paths.contains(&id.to_string()));
                }
                server_task.abort();
                return Ok(());
            }
            _ => {}
        }
        tokio::time::sleep(std::time::Duration::from_millis(20)).await;
    }

    server_task.abort();
    Err(anyhow::anyhow!("server did not respond in time"))
}
