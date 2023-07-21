# Welcome to SeaGOAT

## Install SeaGOAT

To install SeaGOAT using `pip`, use the following command:

```bash
pip install seagoat
```

## Start SeaGOAT server

In order to use SeaGOAT in your project, you have to start the SeaGOAT server
using the following command:

```bash
seagoat-server start /path/to/your/repo
```

## Search your repository

If you have the server running, you can simply use the
`gt` or `seagoat` command to query your repository. For example:

```bash
gt "Where are the numbers rounded"
```

## Stopping the server

You can stop the running server using the following command:

```bash
seagoat-server stop /path/to/your/repo
```
