use std::time::Duration;

#[tokio::test]
async fn snapshot_v1_query_minimal() -> anyhow::Result<()> {
    // Boot the app on an ephemeral port
    let dbs = seagoat::initialize_example_databases().await?;
    let app = seagoat::build_router(seagoat::AppState { dbs });

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let addr = listener.local_addr()?;

    let server_task = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });

    // Wait for readiness and fetch JSON
    let client = reqwest::Client::new();
    let url = format!("http://{}/v1/query?path=%2Fmock%2Fdb%2Falpha", addr);

    let deadline = tokio::time::Instant::now() + Duration::from_secs(5);
    let json = loop {
        if tokio::time::Instant::now() > deadline {
            server_task.abort();
            anyhow::bail!("server did not respond in time");
        }
        match client.get(&url).send().await {
            Ok(resp) if resp.status().is_success() => {
                let json: serde_json::Value = resp.json().await?;
                break json;
            }
            _ => tokio::time::sleep(Duration::from_millis(20)).await,
        }
    };

    // Normalize for stable snapshotting
    let contains_hello = json
        .get("tables")
        .and_then(|v| v.as_array())
        .map(|arr| arr.iter().any(|v| v == "hello"))
        .unwrap_or(false);
    let hello_count = json
        .get("hello_count")
        .and_then(|v| v.as_i64())
        .unwrap_or(0);

    let normalized = serde_json::json!({
        "contains_hello": contains_hello,
        "hello_count": hello_count,
    });

    insta::assert_snapshot!(
        "v1_query_minimal",
        serde_json::to_string_pretty(&normalized).unwrap()
    );

    server_task.abort();
    Ok(())
}
