use std::net::SocketAddr;

use anyhow::Result;
use assert_fs::TempDir;
use axum::Router;
use reqwest::Client;
use tokio::task::JoinHandle;

pub fn make_db(tmp: &TempDir, name: &str) -> Result<String> {
    let dir = tmp.path().join(name);
    std::fs::create_dir_all(&dir)?;
    std::fs::write(dir.join(".seagoatdb.yaml"), b"")?;
    Ok(dir.to_string_lossy().to_string())
}

pub fn make_dbs(tmp: &TempDir, names: &[&str]) -> Result<Vec<String>> {
    names.iter().map(|n| make_db(tmp, n)).collect()
}

pub async fn start_app_with_dbs(db_paths: Vec<String>) -> Result<(SocketAddr, JoinHandle<()>)> {
    let cfg = seagoat::db::DatabasesConfig { databases: db_paths.clone() };
    let dbs = seagoat::db::initialize_databases_from_config(&cfg).await?;
    let app: Router = seagoat::build_router(seagoat::AppState { dbs });

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let addr = listener.local_addr()?;

    let server_task = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });

    // Readiness: if we have a DB, poll overview for the first path; else poll /v1/databases
    let client = Client::new();
    if let Some(first_path) = db_paths.get(0) {
        let url = format!("http://{}/v1/query", addr);
        let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(5);
        loop {
            if tokio::time::Instant::now() > deadline {
                break;
            }
            if let Ok(resp) = client
                .post(&url)
                .json(&serde_json::json!({"type": "Overview", "path": first_path}))
                .send()
                .await
            {
                if resp.status().is_success() {
                    break;
                }
            }
            tokio::time::sleep(std::time::Duration::from_millis(20)).await;
        }
    } else {
        let url = format!("http://{}/v1/databases", addr);
        let _ = client.get(&url).send().await; // best-effort
    }

    Ok((addr, server_task))
}

pub async fn post_overview(addr: SocketAddr, path: &str) -> Result<serde_json::Value> {
    let client = Client::new();
    let url = format!("http://{}/v1/query", addr);
    let resp = client
        .post(&url)
        .json(&serde_json::json!({"type": "Overview", "path": path}))
        .send()
        .await?;
    let json: serde_json::Value = resp.json().await?;
    Ok(json)
}
