use axum::{extract::State, routing::get, Json, Router};
use lancedb::{connect, Connection};
use std::sync::Arc;
use serde_json::{json, Value as JsonValue};

pub mod embedder;

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
        use arrow_array::{
            builder::{FixedSizeListBuilder, Float32Builder},
            ArrayRef, FixedSizeListArray, Int64Array, RecordBatch, RecordBatchIterator, StringArray,
        };
        use arrow_schema::{DataType, Field, Schema};
        use crate::embedder::Embedder;

        // Determine embedding dimension from implementation
        let temp_embedder = Embedder::default();
        let temp_dim = temp_embedder.embed(&["probe"]).unwrap()[0].len() as i32;

        let schema: Arc<Schema> = Arc::new(Schema::new(vec![
            Field::new("id", DataType::Int64, false),
            Field::new("text", DataType::Utf8, false),
            Field::new(
                "vector",
                DataType::FixedSizeList(
                    Arc::new(Field::new("item", DataType::Float32, false)),
                    temp_dim,
                ),
                false,
            ),
        ]));

        let table = db
            .create_empty_table(table_name, schema.clone())
            .execute()
            .await?;

        let id_array = Int64Array::from(vec![1_i64, 2_i64]);
        let text_values = vec!["hello", "world"];
        let text_array = StringArray::from(text_values.clone());

        // Compute embeddings for dummy data using the fallback embedder.
        let embedder = temp_embedder;
        let embeddings: Vec<Vec<f32>> = embedder.embed(&text_values)?;

        // Build a FixedSizeList<Float32> arrow array for embeddings
        let values_builder = Float32Builder::new();
        let mut list_builder = FixedSizeListBuilder::new(values_builder, temp_dim);
        for emb in embeddings.iter() {
            let vb = list_builder.values();
            for &x in emb.iter() {
                vb.append_value(x);
            }
            list_builder.append(true);
        }
        let embedding_array: FixedSizeListArray = list_builder.finish();
        let batch = RecordBatch::try_new(
            schema.clone(),
            vec![
                Arc::new(id_array) as ArrayRef,
                Arc::new(text_array) as ArrayRef,
                Arc::new(embedding_array) as ArrayRef,
            ],
        )?;

        let batches = vec![Ok(batch)];
        let reader = RecordBatchIterator::new(batches.into_iter(), schema.clone());
        table.add(reader).execute().await?;
    }

    Ok(Arc::new(db))
}
