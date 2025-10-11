use axum::{extract::{State, Query}, routing::get, Json, Router};
use lancedb::{connect, Connection};
use std::{collections::HashMap, sync::Arc};
use serde::Deserialize;
use serde_json::{json, Value as JsonValue};

pub mod embedder;

#[derive(Clone)]
pub struct AppState {
    pub dbs: Arc<HashMap<String, Arc<Connection>>>,
}

#[derive(Deserialize)]
struct QueryParams {
    /// Database ID (future: path on disk)
    path: String,
}

async fn query_handler(State(state): State<AppState>, Query(params): Query<QueryParams>) -> Json<JsonValue> {
    let Some(db) = state.dbs.get(&params.path) else {
        return Json(json!({
            "error": "unknown_database",
            "message": "database with given path not found",
            "path": params.path,
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
    Router::new().route("/v1/query", get(query_handler)).with_state(state)
}

pub async fn initialize_example_databases() -> anyhow::Result<Arc<HashMap<String, Arc<Connection>>>> {
    let mut map: HashMap<String, Arc<Connection>> = HashMap::new();

    let examples: Vec<(&str, &str)> = vec![
        ("/mock/db/alpha", ".lancedb/mock_alpha"),
        ("/mock/db/beta", ".lancedb/mock_beta"),
        ("/mock/db/gamma", ".lancedb/mock_gamma"),
    ];

    for (id, path) in examples {
        // Ensure directory exists before connecting
        if let Err(err) = std::fs::create_dir_all(path) {
            tracing::warn!("failed to create db dir {}: {:#}", path, err);
        }
        match connect(path).execute().await {
            Ok(db) => {
                if let Err(err) = ensure_hello_table_seeded(&db).await {
                    tracing::warn!("failed to seed {} at {}: {:#}", id, path, err);
                    continue;
                }
                map.insert(id.to_string(), Arc::new(db));
            }
            Err(err) => {
                tracing::warn!("failed to connect {} at {}: {:#}", id, path, err);
            }
        }
    }

    if map.is_empty() {
        anyhow::bail!("no example databases could be initialized")
    }

    Ok(Arc::new(map))
}

pub fn default_database_ids() -> &'static [&'static str] {
    &["/mock/db/alpha", "/mock/db/beta", "/mock/db/gamma"]
}

async fn ensure_hello_table_seeded(db: &Connection) -> anyhow::Result<()> {
    use arrow_array::{
        builder::{FixedSizeListBuilder, Float32Builder},
        ArrayRef, FixedSizeListArray, Int64Array, RecordBatch, RecordBatchIterator, StringArray,
    };
    use arrow_schema::{DataType, Field, Schema};
    use crate::embedder::Embedder;

    // Seed a tiny table with two rows if it doesn't exist yet.
    let table_name = "hello";
    let existing: Vec<String> = db.table_names().execute().await?;
    if existing.iter().any(|n| n == table_name) {
        // If table exists but is empty, seed it; otherwise nothing to do.
        match db.open_table(table_name).execute().await {
            Ok(table) => {
                let row_count = table.count_rows(None).await.unwrap_or(0) as i64;
                if row_count > 0 {
                    return Ok(());
                }
                // Derive dim from existing schema
                use arrow_schema::DataType as DT;
                let schema = table.schema().await?;
                let dim = schema
                    .fields()
                    .iter()
                    .find(|f| f.name() == "vector")
                    .and_then(|f| match f.data_type() {
                        DT::FixedSizeList(_, d) => Some(*d),
                        _ => None,
                    })
                    .unwrap_or_else(|| {
                        // Fallback to embedder's dim
                        let e = Embedder::default();
                        e.embed(&["probe"]).unwrap()[0].len() as i32
                    });

                // Build and append rows
                use arrow_array::builder::{FixedSizeListBuilder, Float32Builder};
                use arrow_array::{ArrayRef, FixedSizeListArray, Int64Array, RecordBatch, RecordBatchIterator, StringArray};
                let id_array = Int64Array::from(vec![1_i64, 2_i64]);
                let text_values = vec!["hello", "world"];
                let text_array = StringArray::from(text_values.clone());
                let embeddings = Embedder::default().embed(&text_values)?;
                let values_builder = Float32Builder::new();
                let mut list_builder = FixedSizeListBuilder::new(values_builder, dim);
                for emb in embeddings.iter() {
                    let vb = list_builder.values();
                    for &x in emb.iter() { vb.append_value(x); }
                    list_builder.append(true);
                }
                let embedding_array: FixedSizeListArray = list_builder.finish();
                let batch = RecordBatch::try_new(
                    schema.into(),
                    vec![
                        Arc::new(id_array) as ArrayRef,
                        Arc::new(text_array) as ArrayRef,
                        Arc::new(embedding_array) as ArrayRef,
                    ],
                )?;
                let batches = vec![Ok(batch)];
                let reader = RecordBatchIterator::new(batches.into_iter(), table.schema().await?.into());
                table.add(reader).execute().await?;
                return Ok(());
            }
            Err(_) => {
                // Fall through to create path below
            }
        }
    }

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
    let embeddings: Vec<Vec<f32>> = temp_embedder.embed(&text_values)?;

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
    Ok(())
}
