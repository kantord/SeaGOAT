from mcp.server.fastmcp import FastMCP
from seagoat.utils.server import normalize_repo_path, get_server_info, get_servers_info
import requests


mcp = FastMCP("seagoat")



@mcp.tool()
def search_code(query:str, limit:int=10, repo_path:str="", contextAbove:int=3, contextBelow:int=3)->str:

    if not query:
        return "Error: query is required."
    try:
        repo = normalize_repo_path(repo_path)
    except Exception as e:
        return f"Error normalizing repo path: {str(e)}"
    
    try:
        server_info = get_server_info(repo)
    except Exception:
        return f"No server info found for repo: {repo}. Is the seagoat server running?"

    if server_info is None:
        return f"No server info found for repo: {repo}"
    
    address = server_info["address"]

    try:
        result = requests.post(
            f"{address}/lines/query",
            json={
                "queryText": query,
                "limitClue": str(limit),
                "contextAbove": str(contextAbove),
                "contextBelow": str(contextBelow),
            },
            timeout=10,
        )
        result.raise_for_status()
    except Exception as e:
        return f"Error querying server at {address} - {str(e)}"
    

    data = result.json()


    results = data.get("results", [])

    output_lines = []
    if not results:
        return "No results found."
    

    for res in results:
        file_path = res['path']
        output_lines.append(f"File: {file_path}\n")


        for block in res['blocks']:
            for line in block['lines']:
                line_num = line['line']
                content = line['lineText']
                output_lines.append(f"{line_num}: {content}\n")
            output_lines.append("\n") 

        
        

    return "\n".join(output_lines)


def main():
    mcp.run()


if __name__ == "__main__":
    main()

