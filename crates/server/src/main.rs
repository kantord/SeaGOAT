use axum::Router;
use clap::Parser;
use seagoat_server::{build_router, AppState, DatabasesConfig, initialize_databases_from_config};
use std::{io::ErrorKind, net::SocketAddr};
use tokio::net::TcpListener;
use tracing_subscriber::EnvFilter;

#[derive(Parser, Debug)]
#[command(name = "SeaGOAT Server", version, about = "SeaGOAT server", long_about = None)]
struct Cli {
    /// Interface to bind the HTTP server to
    #[arg(long, env = "HOST", default_value = "0.0.0.0")]
    host: String,

    /// Port to bind the HTTP server to
    #[arg(long, env = "PORT", default_value_t = 3000)]
    port: u16,

    /// Path to YAML config specifying databases to load
    #[arg(long, env = "CONFIG", default_value = "")]
    config: String,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt().with_env_filter(EnvFilter::from_default_env()).without_time().init();

    // Initialize databases from YAML config if provided
    let cli: Cli = Cli::parse();
    let dbs = if !cli.config.is_empty() {
        let cfg_text = if cli.config == "-" {
            use std::io::Read;
            let mut buf = String::new();
            std::io::stdin().read_to_string(&mut buf)?;
            buf
        } else {
            std::fs::read_to_string(&cli.config)?
        };
        let cfg: DatabasesConfig = serde_yaml::from_str(&cfg_text)?;
        initialize_databases_from_config(&cfg).await?
    } else {
        tracing::warn!("no CONFIG provided; starting with zero databases");
        std::sync::Arc::new(std::collections::HashMap::new())
    };
    let app_router: Router = build_router(AppState { dbs });

    let requested_addr: SocketAddr = format!("{}:{}", cli.host, cli.port).parse()?;

    let tcp_listener: TcpListener = match TcpListener::bind(requested_addr).await {
        Ok(listener) => listener,
        Err(err) if err.kind() == ErrorKind::AddrInUse => {
            tracing::warn!("port {} in use, falling back to ephemeral port (0)", cli.port);
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
