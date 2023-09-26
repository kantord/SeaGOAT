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
```

## Available configuration options

### Server

Server-related configuration resides under the `server` attribute in your
config files.

The following values can be configured:

* `port`: The port number the server will run on
