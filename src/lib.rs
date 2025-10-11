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
#[serde(tag = "type")]
enum QueryBody {
    Overview { path: String },
    Search { path: String, query: String, #[serde(default = "default_top_k")] top_k: usize },
}

fn default_top_k() -> usize { 5 }

async fn query_handler(State(state): State<AppState>, Json(body): Json<QueryBody>) -> Json<JsonValue> {
    let path = match &body {
        QueryBody::Overview { path } | QueryBody::Search { path, .. } => path,
    };
    let Some(db) = state.dbs.get(path) else {
        return Json(json!({
            "error": "unknown_database",
            "message": "database with given path not found",
            "path": path,
        }));
    };

    match body {
        QueryBody::Overview { .. } => match crate::db::db_overview(db).await {
            Ok(resp) => Json(serde_json::to_value(resp).unwrap()),
            Err(err) => Json(json!({ "error": "internal_error", "message": err.to_string() })),
        },
        QueryBody::Search { query, top_k, .. } => match crate::db::semantic_search(db, &query, top_k).await {
            Ok(resp) => Json(serde_json::to_value(resp).unwrap()),
            Err(err) => Json(json!({ "error": "internal_error", "message": err.to_string() })),
        },
    }
}

pub fn build_router(state: AppState) -> Router {
    Router::new().route("/v1/query", post(query_handler)).with_state(state)
}
