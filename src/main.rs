use clap::Parser;
use serde::{Deserialize, Serialize};

#[derive(Serialize, Deserialize, Debug)]
#[serde(rename_all = "camelCase")]
struct QueryArgs {
    query_text: String,
    limit_clue: u32,
    context_above: u32,
    context_below: u32,
}

#[derive(Serialize, Deserialize, Debug)]
#[serde(rename_all = "camelCase")]
struct ServerConnection {
    server_path: String,
}

#[derive(Serialize, Deserialize, Debug)]
#[serde(rename_all = "camelCase")]
struct QueryResult {}

#[derive(Serialize, Deserialize, Debug)]
#[serde(rename_all = "camelCase")]
struct ResultLine {
    score: f32,
    line: i32,
    line_text: String,
}

#[derive(Serialize, Deserialize, Debug)]
#[serde(rename_all = "camelCase")]
struct ResultBlock {
    score: f32,
    lines: Vec<ResultLine>,
}

#[derive(Serialize, Deserialize, Debug)]
#[serde(rename_all = "camelCase")]
struct ResultItems {
    path: String,
    full_path: String,
    blocks: Vec<ResultBlock>,
}

#[derive(Serialize, Deserialize, Debug)]
#[serde(rename_all = "camelCase")]
struct ResultsResponse {
    results: Vec<ResultItems>,
    version: String,
}

impl ServerConnection {
    async fn query(&self, args: &QueryArgs) -> ResultsResponse {
        let server_path = &self.server_path;
        let client = reqwest::Client::builder().build().unwrap();
        let results = client
            .post(format!("{}/lines/query", server_path))
            .json(args)
            .send()
            .await
            .expect("Could not reach seagoat-server");

        results.json().await.expect("Invalid JSON response")
    }
}

#[derive(Parser, Debug)]
#[command(author, version, about, long_about = None)]
struct Args {
    query_text: String,
}

fn display_results(result: ResultsResponse) {
    for result_item in result.results {
        for result_block in result_item.blocks {
            for result_line in result_block.lines {
                println!(
                    "{}:{}:0:{}",
                    result_item.path, result_line.line, result_line.line_text
                );
            }
        }
    }
}

#[tokio::main]
async fn main() {
    let args = Args::parse();
    let query_args = &QueryArgs {
        query_text: args.query_text,
        limit_clue: 100,
        context_above: 0,
        context_below: 0,
    };
    let server_connection = ServerConnection {
        server_path: "http://localhost:4444/".to_string(),
    };

    let result = server_connection.query(query_args).await;
    display_results(result);
}
