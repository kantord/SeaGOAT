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

client:
  # Connect the CLI to a remove server
  host: https://example.com/seagoat-instance/

```

## Available configuration options

### Server

Server-related configuration resides under the `server` attribute in your
config files.

The following values can be configured:

* `port`: The port number the server will run on

### Client

Configuration for the CLI (`gt` command) resides under the `client` attribute.

The following values can be configured:

* `host`: The URL of the SeaGOAT instance to connect to. This is only
needed when you are hosting your SeaGOAT server on a remote computer. *It is
recommended to set this value in your project configuration file, so that
you are still able to use the local server for different projects.*
