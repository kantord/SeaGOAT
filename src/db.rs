use std::{collections::HashMap, sync::Arc};

use lancedb::{connect, Connection};

use crate::embedder::Embedder;

#[derive(Debug, serde::Serialize)]
pub struct DbOverviewResponse {
    pub tables: Vec<String>,
    pub hello_count: i64,
}

pub async fn db_overview(db: &Connection) -> anyhow::Result<DbOverviewResponse> {
    let tables = db.table_names().execute().await.unwrap_or_default();
    let hello_count: i64 = match db.open_table("hello").execute().await {
        Ok(table) => match table.count_rows(None).await {
            Ok(c) => c as i64,
            Err(_) => 0,
        },
        Err(_) => 0,
    };
    Ok(DbOverviewResponse { tables, hello_count })
}

#[derive(Debug, serde::Serialize)]
pub struct SearchHit {
    pub id: i64,
    pub text: String,
    pub score: f32,
}

#[derive(Debug, serde::Serialize)]
pub struct SemanticSearchResponse {
    pub hits: Vec<SearchHit>,
}

pub async fn semantic_search(_db: &Connection, query_text: &str, top_k: usize) -> anyhow::Result<SemanticSearchResponse> {
    // Temporary: compute against seeded strings; next step will iterate Lance rows
    let candidates: Vec<(i64, &str)> = vec![(1, "hello"), (2, "world")];
    let embedder = Embedder::default();
    let query_vec = embedder.embed(&[query_text])?.remove(0);
    let mut hits: Vec<SearchHit> = candidates
        .into_iter()
        .map(|(id, text)| {
            let vec = embedder.embed(&[text]).unwrap().remove(0);
            let score = cosine_similarity(&query_vec, &vec);
            SearchHit { id, text: text.to_string(), score }
        })
        .collect();
    hits.sort_by(|a, b| b.score.total_cmp(&a.score));
    hits.truncate(top_k);
    Ok(SemanticSearchResponse { hits })
}

fn cosine_similarity(a: &[f32], b: &[f32]) -> f32 {
    let mut dot = 0.0f64;
    let mut na = 0.0f64;
    let mut nb = 0.0f64;
    let len = a.len().min(b.len());
    for i in 0..len {
        let x = a[i] as f64;
        let y = b[i] as f64;
        dot += x * y;
        na += x * x;
        nb += y * y;
    }
    if na == 0.0 || nb == 0.0 { return 0.0; }
    (dot / (na.sqrt() * nb.sqrt())) as f32
}

#[derive(Debug, serde::Deserialize)]
pub struct DatabasesConfig {
    pub databases: Vec<String>,
}

pub async fn initialize_databases_from_config(config: &DatabasesConfig) -> anyhow::Result<Arc<HashMap<String, Arc<Connection>>>> {
    let mut map: HashMap<String, Arc<Connection>> = HashMap::new();

    for id in &config.databases {
        // Map id to on-disk location (namespace under .lancedb)
        let sanitized = id.trim_start_matches('/').replace('/', "_");
        let path = format!(".lancedb/{}", sanitized);
        // Ensure directory exists before connecting
        if let Err(err) = std::fs::create_dir_all(&path) {
            tracing::warn!("failed to create db dir {}: {:#}", sanitized, err);
        }
        match connect(&path).execute().await {
            Ok(db) => {
                if let Err(err) = ensure_hello_table_seeded(&db).await {
                    tracing::warn!("failed to seed {} at {}: {:#}", id, path, err);
                    continue;
                }
                map.insert(id.clone(), Arc::new(db));
            }
            Err(err) => {
                tracing::warn!("failed to connect {} at {}: {:#}", id, path, err);
            }
        }
    }

    if map.is_empty() {
        tracing::warn!("config contained zero databases or all failed to initialize");
    }

    Ok(Arc::new(map))
}

pub fn default_database_ids() -> &'static [&'static str] { &[] }

async fn ensure_hello_table_seeded(db: &Connection) -> anyhow::Result<()> {
    // Seed a tiny table using the generic add_embedding API.
    let embedder = Embedder::default();
    let hello_vec = embedder.embed(&["hello"])?.remove(0);
    let world_vec = embedder.embed(&["world"])?.remove(0);
    ensure_vector_table(db, "hello", hello_vec.len() as i32).await?;
    // If already seeded, skip
    if let Ok(table) = db.open_table("hello").execute().await {
        let count = table.count_rows(None).await.unwrap_or(0);
        if count > 0 {
            return Ok(());
        }
    }
    add_embedding(db, "hello", 1, "hello", &hello_vec).await?;
    add_embedding(db, "hello", 2, "world", &world_vec).await?;
    Ok(())
}

// keep Arc imported above
use arrow_array::{
    builder::{FixedSizeListBuilder, Float32Builder},
    ArrayRef, FixedSizeListArray, Int64Array, RecordBatch, RecordBatchIterator, StringArray,
};
use arrow_schema::{DataType, Field, Schema};

pub async fn ensure_vector_table(db: &Connection, table_name: &str, dim: i32) -> anyhow::Result<()> {
    let existing: Vec<String> = db.table_names().execute().await?;
    if existing.iter().any(|n| n == table_name) {
        return Ok(());
    }
    let schema: Arc<Schema> = Arc::new(Schema::new(vec![
        Field::new("id", DataType::Int64, false),
        Field::new("text", DataType::Utf8, false),
        Field::new(
            "vector",
            DataType::FixedSizeList(
                Arc::new(Field::new("item", DataType::Float32, true)),
                dim,
            ),
            false,
        ),
    ]));
    let _ = db.create_empty_table(table_name, schema).execute().await?;
    Ok(())
}

pub async fn add_embedding(
    db: &Connection,
    table_name: &str,
    id: i64,
    text: &str,
    vector: &[f32],
) -> anyhow::Result<()> {
    // Ensure table exists
    ensure_vector_table(db, table_name, vector.len() as i32).await?;
    let table = db.open_table(table_name).execute().await?;

    // Build single-row batch
    let id_array = Int64Array::from(vec![id]);
    let text_array = StringArray::from(vec![text]);
    let mut values_builder = Float32Builder::new();
    for &x in vector {
        values_builder.append_value(x);
    }
    let mut list_builder = FixedSizeListBuilder::new(values_builder, vector.len() as i32);
    // we already appended values, now mark one list entry
    list_builder.append(true);
    let embedding_array: FixedSizeListArray = list_builder.finish();

    let batch_schema: Arc<Schema> = table.schema().await?.into();
    let batch = RecordBatch::try_new(
        batch_schema,
        vec![
            Arc::new(id_array) as ArrayRef,
            Arc::new(text_array) as ArrayRef,
            Arc::new(embedding_array) as ArrayRef,
        ],
    )?;

    let reader = RecordBatchIterator::new(vec![Ok(batch)].into_iter(), table.schema().await?.into());
    table.add(reader).execute().await?;
    Ok(())
}
