use clap::Parser;
use surf::http::convert::{Deserialize, Serialize};

#[derive(Serialize, Deserialize)]
struct QueryArgs {
    query_text: String,
}

struct ServerConnection {
    server_path: String,
}

struct QueryResult {}

#[derive(Serialize, Deserialize, Debug)]
struct ResultLine {
    score: f32,
    line: i32,
    lineText: String,
}

#[derive(Serialize, Deserialize, Debug)]
struct ResultBlock {
    score: f32,
    lines: Vec<ResultLine>,
}

#[derive(Serialize, Deserialize, Debug)]
struct ResultItems {
    path: String,
    fullPath: String,
    blocks: Vec<ResultBlock>,
}

#[derive(Serialize, Deserialize)]
struct ResultsResponse {
    results: Vec<ResultItems>,
    version: String,
}

impl ServerConnection {
    async fn query(&self, args: &QueryArgs) -> ResultsResponse {
        let server_path = &self.server_path;
        return surf::post(format!("{server_path}/lines/query"))
            .body_json(args)
            .expect("Invalid JSON payload")
            .recv_json()
            .await
            .expect("Could not reach `seagoat-server`. Make sure it is running.");
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
                    result_item.path, result_line.line, result_line.lineText
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
    };
    let server_connection = ServerConnection {
        server_path: "http://localhost:41481/".to_string(),
    };

    let result = server_connection.query(query_args).await;
    display_results(result);
}
