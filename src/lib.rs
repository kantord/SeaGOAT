use axum::{extract::State, routing::get, Json, Router};
use lancedb::{connect, Connection};
use std::sync::Arc;
use serde_json::{json, Value as JsonValue};

#[derive(Clone)]
pub struct AppState {
    pub db: Arc<Connection>,
}

async fn query_handler(State(state): State<AppState>) -> Json<JsonValue> {
    // Basic query against dummy DB: list tables and count rows in "hello"
    let tables = match state.db.table_names().execute().await {
        Ok(names) => names,
        Err(_) => Vec::new(),
    };

    let hello_count: i64 = match state.db.open_table("hello").execute().await {
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
    Router::new().route("/v1/query", get(query_handler)).with_state(state)
}

pub async fn initialize_dummy_lancedb() -> anyhow::Result<Arc<Connection>> {
    // Open or create a local LanceDB directory in the project root.
    let db: Connection = connect(".lancedb").execute().await?;

    // Seed a tiny table with two rows if it doesn't exist yet.
    let table_name = "hello";
    let existing: Vec<String> = db.table_names().execute().await?;
    if !existing.iter().any(|n| n == table_name) {
        use arrow_array::{ArrayRef, Int64Array, RecordBatch, RecordBatchIterator, StringArray};
        use arrow_schema::{DataType, Field, Schema};

        let schema: Arc<Schema> = Arc::new(Schema::new(vec![
            Field::new("id", DataType::Int64, false),
            Field::new("text", DataType::Utf8, false),
        ]));

        let table = db
            .create_empty_table(table_name, schema.clone())
            .execute()
            .await?;

        let id_array = Int64Array::from(vec![1_i64, 2_i64]);
        let text_array = StringArray::from(vec!["hello", "world"]);
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![Arc::new(id_array) as ArrayRef, Arc::new(text_array) as ArrayRef],
        )?;

        let batches = vec![Ok(batch)];
        let reader = RecordBatchIterator::new(batches.into_iter(), schema.clone());
        table.add(reader).execute().await?;
    }

    Ok(Arc::new(db))
}
