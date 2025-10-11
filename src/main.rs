use axum::{routing::get, Json, Router};
use clap::Parser;
use serde_json::{json, Value as JsonValue};
use std::{io::ErrorKind, net::SocketAddr};
use tokio::net::TcpListener;
use tracing_subscriber::EnvFilter;

#[derive(Parser, Debug)]
#[command(name = "SeaGOAT", version, about = "SeaGOAT server", long_about = None)]
struct Cli {
    /// Interface to bind the HTTP server to
    #[arg(long, env = "HOST", default_value = "0.0.0.0")]
    host: String,

    /// Port to bind the HTTP server to
    #[arg(long, env = "PORT", default_value_t = 3000)]
    port: u16,
}

async fn query_handler() -> Json<JsonValue> {
    Json(json!({ "message": "Hello World" }))
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env())
        .without_time()
        .init();

    let app_router: Router = Router::new().route("/v1/query", get(query_handler));

    let cli: Cli = Cli::parse();
    let requested_addr: SocketAddr = format!("{}:{}", cli.host, cli.port).parse()?;

    let tcp_listener: TcpListener = match TcpListener::bind(requested_addr).await {
        Ok(listener) => listener,
        Err(err) if err.kind() == ErrorKind::AddrInUse => {
            tracing::warn!(
                "port {} in use, falling back to ephemeral port (0)",
                cli.port
            );
            let fallback_addr: SocketAddr = format!("{}:0", cli.host).parse()?;
            TcpListener::bind(fallback_addr).await?
        }
        Err(err) => return Err(err.into()),
    };

    let actual_addr: SocketAddr = tcp_listener.local_addr()?;
    tracing::info!("listening on http://{}", actual_addr);

    axum::serve(tcp_listener, app_router).await?;
    Ok(())
}
