use std::time::Duration;
use std::path::PathBuf;
use assert_fs::TempDir;
mod support;

fn make_db(tmp: &TempDir, name: &str) -> anyhow::Result<String> {
    let d = tmp.path().join(name);
    std::fs::create_dir_all(&d)?;
    std::fs::write(d.join(".seagoatdb.yaml"), b"tables:\n  - name: hello\n")?;
    Ok(d.to_string_lossy().to_string())
}

#[tokio::test]
async fn e2e_query_returns_hello_world() -> anyhow::Result<()> {
    // Create fixture DB folder with .seagoatdb marker
    let tmp = TempDir::new()?;
    let alpha_dir: PathBuf = tmp.path().join("alpha");
    std::fs::create_dir_all(&alpha_dir)?;
    std::fs::write(alpha_dir.join(".seagoatdb.yaml"), b"tables:\n  - name: hello\n")?;
    let alpha_path = alpha_dir.to_string_lossy().to_string();
    let cfg = seagoat::db::DatabasesConfig { databases: vec![alpha_path.clone()] };
    let dbs = seagoat::db::initialize_databases_from_config(&cfg).await.unwrap();
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
        match client.post(&url).json(&serde_json::json!({"type": "Overview", "path": alpha_path})).send().await {
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
    let tmp = TempDir::new()?;
    let alpha = make_db(&tmp, "alpha")?; let beta = make_db(&tmp, "beta")?; let gamma = make_db(&tmp, "gamma")?;
    let cfg = seagoat::db::DatabasesConfig { databases: vec![alpha.clone(), beta.clone(), gamma.clone()] };
    let dbs = seagoat::db::initialize_databases_from_config(&cfg).await?;
    let app = seagoat::build_router(seagoat::AppState { dbs });

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let addr = listener.local_addr()?;

    let server_task = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });

    let client = reqwest::Client::new();
    for id in [alpha.as_str(), beta.as_str(), gamma.as_str()].iter() {
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
    let tmp = TempDir::new()?;
    let alpha_dir = tmp.path().join("alpha");
    std::fs::create_dir_all(&alpha_dir)?; std::fs::write(alpha_dir.join(".seagoatdb.yaml"), b"tables:\n  - name: hello\n")?;
    let alpha_path = alpha_dir.to_string_lossy().to_string();
    let cfg = seagoat::db::DatabasesConfig { databases: vec![alpha_path.clone()] };
    let dbs = seagoat::db::initialize_databases_from_config(&cfg).await?;
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
        "path": alpha_path,
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
    let tmp = TempDir::new()?;
    let alpha = make_db(&tmp, "alpha")?; let beta = make_db(&tmp, "beta")?; let gamma = make_db(&tmp, "gamma")?;
    let cfg = seagoat::db::DatabasesConfig { databases: vec![alpha.clone(), beta.clone(), gamma.clone()] };
    let dbs = seagoat::db::initialize_databases_from_config(&cfg).await?;
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
                for id in [alpha.as_str(), beta.as_str(), gamma.as_str()].iter() {
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

#[tokio::test]
async fn e2e_cli_binary_works_with_stdin_config() -> anyhow::Result<()> {
    use std::process::{Command, Stdio};
    use assert_cmd::prelude::*;
    use reqwest::Client;
    use std::io::Write;

    let port: u16 = portpicker::pick_unused_port().expect("no free port found");
    // Build fixture
    let tmp = TempDir::new()?; let alpha_dir = tmp.path().join("alpha");
    std::fs::create_dir_all(&alpha_dir)?; std::fs::write(alpha_dir.join(".seagoatdb.yaml"), b"tables:\n  - name: hello\n")?;
    let alpha_path = alpha_dir.to_string_lossy().to_string();

    let mut cmd = Command::cargo_bin("seagoat")?;
    cmd.env("RUST_LOG", "info")
        .arg("--host").arg("127.0.0.1")
        .arg("--port").arg(port.to_string())
        .arg("--config").arg("-")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .stdin(Stdio::piped());

    let mut child = cmd.spawn()?;
    let yaml = format!("databases:\n  - {}\n", alpha_path);
    if let Some(mut stdin) = child.stdin.take() {
        stdin.write_all(yaml.as_bytes())?;
    }

    // Wait until server responds
    let client = Client::new();
    let url = format!("http://127.0.0.1:{}/v1/query", port);

    let deadline = tokio::time::Instant::now() + std::time::Duration::from_secs(5);
    let mut last_err: Option<anyhow::Error> = None;
    loop {
        if tokio::time::Instant::now() > deadline {
            // collect child output for debugging
            let _ = child.kill();
            let output = child.wait_with_output()?;
            let stdout = String::from_utf8_lossy(&output.stdout);
            let stderr = String::from_utf8_lossy(&output.stderr);
            return Err(anyhow::anyhow!(
                "server did not become ready: {:?}\nstdout:\n{}\nstderr:\n{}",
                last_err, stdout, stderr
            ));
        }

        match client
            .post(&url)
            .json(&serde_json::json!({"type": "Overview", "path": alpha_path}))
            .send()
            .await
        {
            Ok(resp) if resp.status().is_success() => {
                let json: serde_json::Value = resp.json().await?;
                assert!(json["hello_count"].as_i64().unwrap_or(0) >= 2);
                assert!(json["tables"].as_array().unwrap().contains(&serde_json::json!("hello")));
                child.kill()?;
                let _ = child.wait();
                return Ok(());
            }
            Ok(resp) => {
                last_err = Some(anyhow::anyhow!("status {}", resp.status()));
            }
            Err(err) => {
                last_err = Some(anyhow::Error::new(err));
            }
        }

        tokio::time::sleep(std::time::Duration::from_millis(50)).await;
    }
}

#[tokio::test]
async fn e2e_zero_databases() -> anyhow::Result<()> {
    let cfg = seagoat::db::DatabasesConfig { databases: vec![] };
    let dbs = seagoat::db::initialize_databases_from_config(&cfg).await?;
    let app = seagoat::build_router(seagoat::AppState { dbs });

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let addr = listener.local_addr()?;

    let server_task = tokio::spawn(async move {
        axum::serve(listener, app).await.unwrap();
    });

    let client = reqwest::Client::new();
    let url_dbs = format!("http://{}/v1/databases", addr);
    for _ in 0..100u32 {
        match client.get(&url_dbs).send().await {
            Ok(resp) if resp.status().is_success() => {
                let json: serde_json::Value = resp.json().await?;
                let arr = json.as_array().unwrap();
                assert_eq!(arr.len(), 0);
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

#[tokio::test]
async fn e2e_tables_created_from_config_single_db() -> anyhow::Result<()> {
    let tmp = TempDir::new()?;
    let alpha_dir = tmp.path().join("alpha");
    std::fs::create_dir_all(&alpha_dir)?;
    // Configure three tables
    let yaml = b"tables:\n  - name: hello\n  - name: notes\n  - name: chunks\n";
    std::fs::write(alpha_dir.join(".seagoatdb.yaml"), yaml)?;
    let alpha_path = alpha_dir.to_string_lossy().to_string();

    let cfg = seagoat::db::DatabasesConfig { databases: vec![alpha_path.clone()] };
    let dbs = seagoat::db::initialize_databases_from_config(&cfg).await?;
    let app = seagoat::build_router(seagoat::AppState { dbs });

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let addr = listener.local_addr()?;
    let server_task = tokio::spawn(async move { axum::serve(listener, app).await.unwrap(); });

    let client = reqwest::Client::new();
    let url = format!("http://{}/v1/query", addr);
    let resp = client.post(&url).json(&serde_json::json!({"type":"Overview","path": alpha_path})).send().await?;
    assert_eq!(resp.status(), 200);
    let json: serde_json::Value = resp.json().await?;
    let mut tables: Vec<String> = json["tables"].as_array().unwrap().iter().map(|v| v.as_str().unwrap().to_string()).collect();
    tables.sort();
    assert_eq!(tables, vec!["chunks", "hello", "notes"]);

    server_task.abort();
    Ok(())
}

#[tokio::test]
async fn e2e_tables_created_from_config_multiple_dbs() -> anyhow::Result<()> {
    let tmp = TempDir::new()?;
    // DB alpha with two tables
    let alpha_dir = tmp.path().join("alpha");
    std::fs::create_dir_all(&alpha_dir)?;
    std::fs::write(alpha_dir.join(".seagoatdb.yaml"), b"tables:\n  - name: hello\n  - name: notes\n")?;
    let alpha_path = alpha_dir.to_string_lossy().to_string();
    // DB beta with one table
    let beta_dir = tmp.path().join("beta");
    std::fs::create_dir_all(&beta_dir)?;
    std::fs::write(beta_dir.join(".seagoatdb.yaml"), b"tables:\n  - name: chunks\n")?;
    let beta_path = beta_dir.to_string_lossy().to_string();

    let cfg = seagoat::db::DatabasesConfig { databases: vec![alpha_path.clone(), beta_path.clone()] };
    let dbs = seagoat::db::initialize_databases_from_config(&cfg).await?;
    let app = seagoat::build_router(seagoat::AppState { dbs });

    let listener = tokio::net::TcpListener::bind("127.0.0.1:0").await?;
    let addr = listener.local_addr()?;
    let server_task = tokio::spawn(async move { axum::serve(listener, app).await.unwrap(); });

    let client = reqwest::Client::new();
    let url = format!("http://{}/v1/query", addr);

    // Alpha
    let resp_a = client.post(&url).json(&serde_json::json!({"type":"Overview","path": alpha_path})).send().await?;
    assert_eq!(resp_a.status(), 200);
    let mut tables_a: Vec<String> = resp_a.json::<serde_json::Value>().await?[
        "tables"
    ]
    .as_array()
    .unwrap()
    .iter()
    .map(|v| v.as_str().unwrap().to_string())
    .collect();
    tables_a.sort();
    assert_eq!(tables_a, vec!["hello", "notes"]);

    // Beta
    let resp_b = client.post(&url).json(&serde_json::json!({"type":"Overview","path": beta_path})).send().await?;
    assert_eq!(resp_b.status(), 200);
    let json_b: serde_json::Value = resp_b.json().await?;
    let tables_b: Vec<String> = json_b["tables"].as_array().unwrap().iter().map(|v| v.as_str().unwrap().to_string()).collect();
    assert_eq!(tables_b, vec!["chunks"]);

    server_task.abort();
    Ok(())
}
