use std::process::{Command, Stdio};
use std::time::Duration;

use assert_cmd::prelude::*;
use reqwest::Client;

#[tokio::test]
async fn cli_e2e_binary_serves_query() -> anyhow::Result<()> {
    // pick a free port and run the binary with that port
    let port: u16 = portpicker::pick_unused_port().expect("no free port found");

    let mut cmd = Command::cargo_bin("seagoat")?;
    cmd.env("RUST_LOG", "info")
        .arg("--host").arg("127.0.0.1")
        .arg("--port").arg(port.to_string())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let mut child = cmd.spawn()?;

    // Wait until server responds
    let client = Client::new();
    let url = format!("http://127.0.0.1:{}/v1/query", port);

    let deadline = tokio::time::Instant::now() + Duration::from_secs(5);
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

        match client.post(&url).json(&serde_json::json!({"path": "/mock/db/alpha"})).send().await {
            Ok(resp) if resp.status().is_success() => {
                let json: serde_json::Value = resp.json().await?;
                assert_eq!(json["hello_count"], serde_json::json!(2));
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

        tokio::time::sleep(Duration::from_millis(50)).await;
    }
}
