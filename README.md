<!-- markdownlint-disable MD033 -->

<h1>
  <p align="center">
    <img src="assets/logo-small.png" alt="Logo" width="200"/>
    <font size="8"><b>SeaGOAT</b></font>
  </p>
</h1>

A code search engine for the AI age. SeaGOAT is a local search tool that
leverages vector embeddings to enable to search your codebase semantically.

<p align="center">
  <img src="assets/demo-slideshow.gif" alt="" />
</p>

## Getting started

### Install SeaGOAT

In order to install SeaGOAT, you need to have the following
dependencies already installed on your computer:

- Python 3.11 or newer
- ripgrep
- [https://github.com/sharkdp/bat](bat) (**optional**, highly recommended)

When `bat` is [installed](https://github.com/sharkdp/bat#on-ubuntu-using-apt),
it is used to display results as long as color is enabled. When SeaGOAT is
used as part of a pipeline, a grep-line output format is used. When color is
enabled, but `bat` is not installed, SeaGOAT will highlight the output using
pygments. Using `bat` is recommended.

To install SeaGOAT using `pipx`, use the following command:

```bash
pipx install seagoat
```

### System requirements

#### Hardware

Should work on any decent laptop.

#### Oporating system

SeaGOAT is designed to work on Linux (*tested* ✅),
macOS ([partly tested, **help**](https://github.com/kantord/SeaGOAT/issues/178) 🙏)
and Windows ([**help needed**](https://github.com/kantord/SeaGOAT/issues/179) 🙏).

### Start SeaGOAT server

In order to use SeaGOAT in your project, you have to start the SeaGOAT server
using the following command:

```bash
seagoat-server start /path/to/your/repo
```

### Search your repository

If you have the server running, you can simply use the
`gt` or `seagoat` command to query your repository. For example:

```bash
gt "Where are the numbers rounded"
```

You can also use
[Regular Expressions](https://en.wikipedia.org/wiki/Regular_expression)
in your queries, for example

```bash
gt "function calc_.* that deals with taxes"
```

### Stopping the server

You can stop the running server using the following command:

```bash
seagoat-server stop /path/to/your/repo
```

## Development

**Requirements**:

- [Poetry](https://python-poetry.org/)
- Python 3.11 or newer
- [ripgrep](https://github.com/BurntSushi/ripgrep)

### Install dependencies

After cloning the repository, install dependencies using the following command:

```bash
poetry install
```

### Running tests

#### Watch mode (recommended)

```bash
poetry run ptw
```

#### Test changed files

```bash
poetry run pytest .  --testmon
```

#### Test all files

```bash
poetry run pytest .
```

### Manual testing

You can test any SeaGOAT command manually in your local development
environment. For example to test the development version of the
`seagoat-server` command, you can run:

```bash
poetry run seagoat-server ~/path/an/example/repository
```

## FAQ

The points in this FAQ are indications of how SeaGOAT works, but are not
a legal contract. SeaGOAT is licensed under an open source license and if you
are in doubt about the privacy/safety/etc implications of SeaGOAT, you are
welcome to examine the source code,
[raise your concerns](https://github.com/kantord/SeaGOAT/issues/new),
or create a pull request to fix a problem.

### How does SeaGOAT work? Does it send my data to ChatGPT?

SeaGOAT does not rely on 3rd party APIs or any remote APIs and executes all
functionality locally using the SeaGOAT server that you are able to run on
your own machine.

Instead of relying on APIs or "connecting to ChatGPT", it uses the vector
database called ChromaDB, with a local vector embedding engine and
telemetry disabled by default.

Apart from that, SeaGOAT also uses ripgrep, a regular-expression based code
search engine in order to provider regular expression/keyword based matches
in addition to the "AI-based" matches.

While the current version of SeaGOAT does not send your data to remote
servers, it might be possible that in the future there will be **optional**
features that do so, if any further improvement can be gained from that.

### Why does SeaGOAT need a server?

SeaGOAT needs a server in order to provide a speedy response. SeaGOAT heavily
relies on vector embeddings and vector databases, which at the moment cannot
be replace with an architecture that processes files on the fly.

It's worth noting that *you are able to run SeaGOAT server entirely locally*,
and it works even if you don't have an internet connection. This use case
does not require you to share data with a remote server, you are able to use
your own SeaGOAT server locally, albeit it's also possible to run a SeaGOAT
server and allow other computers to connect to it, if you so wish.

### Does SeaGOAT create AI-derived work? Is SeaGOAT ethical?

If you are concerned about the ethical implications of using AI tools keep in
mind that SeaGOAT is not a code generator but a code search engine, therefore
it does not create AI derived work.

That being said, a language model *is* being used to generate vector
embeddings. At the moment SeaGOAT uses ChromaDB's default model for
calculating vector embeddings, and I am not aware of this being an ethical
concern.
