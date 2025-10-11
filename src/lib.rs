use axum::{routing::get, Json, Router};
use serde_json::{json, Value as JsonValue};

async fn query_handler() -> Json<JsonValue> {
    Json(json!({ "message": "Hello World" }))
}

pub fn build_router() -> Router {
    Router::new().route("/v1/query", get(query_handler))
}
