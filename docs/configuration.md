# Configuring SeaGOAT

## Introduction

Some features of SeaGOAT can be configured through config files.
All configuration files are written in the *YAML* format.

There are two types of configuration files:

* **Global configuration files**. Use `seagoat-server server-info` to find the
location of this file on your system.
[Learn more](server.md#retrieving-server-information).
* **Project configuration files**. Located in a file called
`seagoat.yml` in the root folder of your repository.

Both of these types of configuration files have the exact same format, and
your project-wide configuration files are merged with the global
configuration. Whenever both your local as well as global configuration
files define a value, the local value takes precedence.

This is an example of a configuration file:

```yaml
# .seagoat.yml

server:
  port: 31134  # A port number to run the server on
  # Increase number of commits used for computing frecency score
  # Default is `5000`, set to `null` to read all history
  readMaxCommits: 5000

  # globs to ignore in addition to .gitignore
  ignorePatterns:
    - "**/locales/*" # Ignore all files inside 'locales' directories
    - "**/*.po"     # Ignore all gettext translation files

  # ChromaDB vector search configuration
  chroma:
    embeddingFunction:
      name: "DefaultEmbeddingFunction"
      arguments: {}
    maxVectorDistance: 1.5  # Maximum vector distance for results (0.1-10.0)
    maxChunksToFetch: 100   # Maximum chunks to fetch from vector DB (10-1000)
    nResultsMultiplier: 2   # Multiplier for over-fetching results (1.0-10.0)

  # Ripgrep text search configuration
  ripgrep:
    maxFileSize: 200        # Maximum file size to cache in KB (1KB-10MB)
    maxMmapSize: 500        # Maximum memory-mapped cache size in MB (10MB-10GB)

  # Engine processing configuration
  engine:
    minChunksToAnalyze:
      minValue: 40          # Minimum chunks to analyze (1-1000)
      percentage: 0.2       # Percentage of total chunks to analyze (0.01-1.0)
    maxWorkers: 1           # Maximum worker threads (1-32)

  # Query defaults
  query:
    defaultLimitClue: 500   # Default result limit (10-10000)
    defaultContextAbove: 3  # Default context lines above results (0-50)
    defaultContextBelow: 3  # Default context lines below results (0-50)

client:
  # Connect the CLI to a remote server
  host: https://example.com/seagoat-instance/

```

## Available configuration options

### Server

Server-related configuration resides under the `server` attribute in your
config files.

The following values can be configured:

* `port`: The port number the server will run on
* `ignorePatterns`: A list of glob patterns to ignore. Keep in mind that all
files ignored by `.gitignore` are already ignored. You probably should not
need to configure this value. It is only useful if there are some files that
you wish to keep in git, but you wish to hide from SeaGOAT.
[Learn more about globs](https://en.wikipedia.org/wiki/Glob_(programming))
* `chroma`: Configurations for the ChromaDB based features.
  Has the following attributes:
  * `embeddingFunction`:
    * `name`: Name of the embedding function to use.
    See [ChromaDB's docs for more](https://docs.trychroma.com/embeddings)
    * `arguments`: Arguments to pass to the embedding function.
  * `maxVectorDistance`: Maximum vector distance for results (default: 1.5, range: 0.1-10.0)
  * `maxChunksToFetch`: Maximum chunks to fetch from vector database (default: 100, range: 10-1000)
  * `nResultsMultiplier`: Multiplier for over-fetching results (default: 2.0, range: 1.0-10.0)
      * If you wanted to use the `ONNXMiniLM_L6_V2` embedding model with TensorRT

        ```yaml
        server:
        ...
        chroma:
          embeddingFunction:
            name: "ONNXMiniLM_L6_V2"
            arguments:
              preferred_providers: ["TensorrtExecutionProvider"]
          maxVectorDistance: 1.2
          maxChunksToFetch: 150
          nResultsMultiplier: 2.5
        ```

* `ripgrep`: Configurations for the ripgrep text search engine.
  Has the following attributes:
  * `maxFileSize`: Maximum file size to cache in KB (default: 200, range: 1-10240 KB)
  * `maxMmapSize`: Maximum memory-mapped cache size in MB (default: 500, range: 10MB-10GB)

* `engine`: Configurations for the search engine processing.
  Has the following attributes:
  * `minChunksToAnalyze`:
    * `minValue`: Minimum number of chunks to analyze (default: 40, range: 1-1000)
    * `percentage`: Percentage of total chunks to analyze (default: 0.2, range: 0.01-1.0)
  * `maxWorkers`: Maximum worker threads for parallel processing (default: 1, range: 1-32)

* `query`: Default values for query parameters.
  Has the following attributes:
  * `defaultLimitClue`: Default result limit (default: 500, range: 10-10000)
  * `defaultContextAbove`: Default context lines above results (default: 3, range: 0-50)
  * `defaultContextBelow`: Default context lines below results (default: 3, range: 0-50)

### Client

Configuration for the CLI (`gt` command) resides under the `client` attribute.

The following values can be configured:

* `host`: The URL of the SeaGOAT instance to connect to. This is only
needed when you are hosting your SeaGOAT server on a remote computer. *It is
recommended to set this value in your project configuration file, so that
you are still able to use the local server for different projects.*

## Performance Tuning

### For Large Repositories

For repositories with many files or large codebases, consider these optimizations:

```yaml
server:
  # Increase file size limit to include larger files
  ripgrep:
    maxFileSize: 1024     # 1MB instead of 200KB
    maxMmapSize: 2000     # 2GB instead of 500MB

  # Increase processing capacity
  engine:
    maxWorkers: 4         # Use more CPU cores
    minChunksToAnalyze:
      minValue: 100       # Analyze more chunks initially
      percentage: 0.3     # Analyze 30% of chunks instead of 20%

  # Optimize vector search
  chroma:
    maxChunksToFetch: 200 # Fetch more results for better recall
    nResultsMultiplier: 3 # Over-fetch more aggressively
```

### For Faster Initial Analysis

To speed up the initial codebase analysis:

```yaml
server:
  engine:
    minChunksToAnalyze:
      minValue: 20        # Lower minimum for faster startup
      percentage: 0.1     # Analyze fewer chunks initially
```

### For Better Search Quality

To improve search result quality at the cost of some performance:

```yaml
server:
  chroma:
    maxVectorDistance: 2.0    # Accept more distant matches
    maxChunksToFetch: 300     # Fetch more candidates
    nResultsMultiplier: 4     # Over-fetch more results

  query:
    defaultLimitClue: 1000    # Return more results by default
    defaultContextAbove: 5    # More context lines
    defaultContextBelow: 5
```

### For Memory-Constrained Systems

To reduce memory usage:

```yaml
server:
  ripgrep:
    maxFileSize: 100      # 100KB instead of 200KB
    maxMmapSize: 200      # 200MB instead of 500MB

  engine:
    maxWorkers: 1         # Single-threaded processing
    minChunksToAnalyze:
      minValue: 20        # Analyze fewer chunks
      percentage: 0.1

  chroma:
    maxChunksToFetch: 50  # Fetch fewer results
    nResultsMultiplier: 1.5
```
