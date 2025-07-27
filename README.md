# README

## Develop

Enter the Nix shell with:

```sh
nix develop
```

Then run the tests with:

```sh
nox
```

To see the available sessions, run:

```sh
nox --list
```

To format the codebase:

```sh
nox -s format -- --fix
```

## Build

To check and build the package, run:

```sh
nix build
```

## Run

To run the package, use:

```sh
nix run
```

... and with arguments:

```sh
nix run . -- --name=there --count=3
```
