use clap::{Parser, ArgAction};

#[derive(Parser, Debug)]
#[command(name = "seagoat", about = "SeaGOAT CLI client", version)]
struct Cli {
    /// Server base URL (e.g., http://127.0.0.1:3000)
    #[arg(long, default_value = "http://127.0.0.1:3000")]
    server: String,

    /// Database path (logical id)
    #[arg(long, required = true)]
    db: String,

    /// Print raw JSON
    #[arg(long, action = ArgAction::SetTrue)]
    json: bool,

    /// Query text (positional)
    query: String,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    let cli = Cli::parse();
    let url = format!("{}/v1/query", cli.server.trim_end_matches('/'));
    let body = serde_json::json!({
        "type": "Search",
        "path": cli.db,
        "query": cli.query,
        "top_k": 5
    });

    let resp = reqwest::Client::new().post(url).json(&body).send().await?;
    if !resp.status().is_success() {
        eprintln!("error: status {}", resp.status());
        std::process::exit(1);
    }
    let json: serde_json::Value = resp.json().await?;
    if cli.json {
        println!("{}", serde_json::to_string_pretty(&json)?);
    } else {
        if let Some(hits) = json.get("hits").and_then(|v| v.as_array()) {
            for h in hits {
                let text = h.get("text").and_then(|t| t.as_str()).unwrap_or("");
                let score = h.get("score").and_then(|s| s.as_f64()).unwrap_or_default();
                println!("{:.3}\t{}", score, text);
            }
        } else {
            println!("{}", serde_json::to_string_pretty(&json)?);
        }
    }
    Ok(())
}
