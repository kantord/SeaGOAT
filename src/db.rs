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

#[derive(Debug, serde::Deserialize)]
pub struct DbLocalConfig {
    pub tables: Vec<TableConfig>,
}

#[derive(Debug, serde::Deserialize, Clone)]
pub struct TableConfig {
    pub name: String,
    #[serde(default)]
    pub model: Option<String>,
    #[serde(default)]
    pub blob: Option<BlobConfig>,
}

#[derive(Debug, serde::Deserialize, Clone)]
pub struct BlobConfig {
    #[serde(default)]
    pub include: Vec<String>,
}

pub async fn initialize_databases_from_config(config: &DatabasesConfig) -> anyhow::Result<Arc<HashMap<String, Arc<Connection>>>> {
    let mut map: HashMap<String, Arc<Connection>> = HashMap::new();

    for id in &config.databases {
        // Validate that the configured path exists and contains a .seagoatdb.yaml marker file
        let configured_path = std::path::Path::new(id);
        let marker = configured_path.join(".seagoatdb.yaml");
        if !(configured_path.is_dir() && marker.exists()) {
            tracing::warn!("skipping db '{}': missing .seagoatdb.yaml in the exact folder", id);
            continue;
        }

        // Load local DB config to discover tables
        let local_cfg = match load_local_config(&marker) {
            Ok(cfg) => cfg,
            Err(err) => {
                tracing::warn!("skipping db '{}': failed to parse .seagoatdb.yaml: {:#}", id, err);
                continue;
            }
        };

        // Map logical path to LanceDB storage namespace under .lancedb
        let sanitized = id.trim_start_matches('/').replace('/', "_");
        let storage_path = format!(".lancedb/{}", sanitized);
        if let Err(err) = std::fs::create_dir_all(&storage_path) {
            tracing::warn!("failed to create storage dir {}: {:#}", storage_path, err);
        }
        match connect(&storage_path).execute().await {
            Ok(db) => {
                if let Err(err) = ensure_tables_seeded(&db, &local_cfg).await {
                    tracing::warn!("failed to seed tables for {} at {}: {:#}", id, storage_path, err);
                    continue;
                }
                map.insert(id.clone(), Arc::new(db));
            }
            Err(err) => {
                tracing::warn!("failed to connect {} at {}: {:#}", id, storage_path, err);
            }
        }
    }

    if map.is_empty() {
        tracing::warn!("config contained zero databases or all failed to initialize");
    }

    Ok(Arc::new(map))
}

pub fn default_database_ids() -> &'static [&'static str] { &[] }

async fn ensure_tables_seeded(db: &Connection, cfg: &DbLocalConfig) -> anyhow::Result<()> {
    // Seed each configured table with dummy rows if empty / not exists
    let embedder = Embedder::default();
    for table in &cfg.tables {
        let table_name = table.name.as_str();
        // Batch-embed seed texts in one call
        let seed_texts: Vec<&str> = vec!["hello", "world"];
        let vectors = embedder.embed(&seed_texts)?;
        ensure_vector_table(db, table_name, vectors[0].len() as i32).await?;
        if let Ok(t) = db.open_table(table_name).execute().await {
            let count = t.count_rows(None).await.unwrap_or(0);
            if count > 0 { continue; }
        }
        let ids: Vec<i64> = vec![1, 2];
        let texts: Vec<String> = seed_texts.into_iter().map(|s| s.to_string()).collect();
        add_embeddings_batch(db, table_name, &ids, &texts, &vectors).await?;
    }
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

// Single-row embedding insertion has been removed in favor of batch-only API

pub async fn add_embeddings_batch(
    db: &Connection,
    table_name: &str,
    ids: &[i64],
    texts: &[String],
    vectors: &[Vec<f32>],
) -> anyhow::Result<()> {
    assert_eq!(ids.len(), texts.len());
    assert_eq!(ids.len(), vectors.len());
    ensure_vector_table(db, table_name, vectors[0].len() as i32).await?;
    let table = db.open_table(table_name).execute().await?;

    // Build column arrays
    let id_array = Int64Array::from(ids.to_vec());
    let text_array = StringArray::from(texts.to_vec());

    let mut values_builder = Float32Builder::new();
    let dim = vectors[0].len() as i32;
    for vec in vectors {
        for &x in vec {
            values_builder.append_value(x);
        }
    }
    let mut list_builder = FixedSizeListBuilder::new(values_builder, dim);
    for _ in 0..vectors.len() {
        list_builder.append(true);
    }
    let embedding_array: FixedSizeListArray = list_builder.finish();

    let batch = RecordBatch::try_new(
        table.schema().await?.into(),
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

fn load_local_config(marker_path: &std::path::Path) -> anyhow::Result<DbLocalConfig> {
    let text = std::fs::read_to_string(marker_path)?;
    let cfg: DbLocalConfig = serde_yaml::from_str(&text)?;
    Ok(cfg)
}
