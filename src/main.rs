use axum::{routing::get, Json, Router};
use serde_json::{json, Value as JsonValue};
use std::{env, io::ErrorKind, net::SocketAddr};
use tokio::net::TcpListener;
use tracing_subscriber::EnvFilter;

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

    let port_env: Option<u16> = env::var("PORT").ok().and_then(|v| v.parse::<u16>().ok());
    let requested_port: u16 = port_env.unwrap_or(3000);
    let requested_addr: SocketAddr = format!("0.0.0.0:{}", requested_port).parse()?;

    let tcp_listener: TcpListener = match TcpListener::bind(requested_addr).await {
        Ok(listener) => listener,
        Err(err) if err.kind() == ErrorKind::AddrInUse => {
            tracing::warn!(
                "port {} in use, falling back to ephemeral port (0)",
                requested_port
            );
            TcpListener::bind("0.0.0.0:0").await?
        }
        Err(err) => return Err(err.into()),
    };

    let actual_addr: SocketAddr = tcp_listener.local_addr()?;
    tracing::info!("listening on http://{}", actual_addr);

    axum::serve(tcp_listener, app_router).await?;
    Ok(())
}
