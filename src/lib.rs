use axum::{extract::State, routing::post, Json, Router};
use lancedb::Connection;
use std::{collections::HashMap, sync::Arc};
use serde::Deserialize;
use serde_json::{json, Value as JsonValue};

pub mod embedder;
pub mod db;
pub use db::{default_database_ids, initialize_example_databases};

#[derive(Clone)]
pub struct AppState {
    pub dbs: Arc<HashMap<String, Arc<Connection>>>,
}

#[derive(Deserialize)]
struct QueryBody {
    /// Database ID (future: path on disk)
    path: String,
}

async fn query_handler(State(state): State<AppState>, Json(body): Json<QueryBody>) -> Json<JsonValue> {
    let Some(db) = state.dbs.get(&body.path) else {
        return Json(json!({
            "error": "unknown_database",
            "message": "database with given path not found",
            "path": body.path,
        }));
    };

    // Basic query against selected DB: list tables and count rows in "hello"
    let tables = match db.table_names().execute().await {
        Ok(names) => names,
        Err(_) => Vec::new(),
    };

    let hello_count: i64 = match db.open_table("hello").execute().await {
        Ok(table) => match table.count_rows(None).await {
            Ok(c) => c as i64,
            Err(_) => 0,
        },
        Err(_) => 0,
    };

    Json(json!({
        "tables": tables,
        "hello_count": hello_count,
    }))
}

pub fn build_router(state: AppState) -> Router {
    Router::new().route("/v1/query", post(query_handler)).with_state(state)
}
