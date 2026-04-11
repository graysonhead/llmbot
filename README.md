# llmbot

An LLM Gateway for Discord that connects Discord users to Large Language Models via Ollama or the Claude API.

## What it does

`llmbot` is a Python CLI tool that provides two main functions:

1. **Direct CLI queries** - Send questions directly to an LLM backend from the command line
2. **Discord bot** - Run a Discord bot that forwards messages to an LLM, allowing Discord users to chat with it

### Features

- **Multiple backends** - Connect to a local Ollama instance or the Anthropic Claude API
- **Tool use** - Built-in tools for arithmetic, time, web search (via SearXNG), METAR weather data, and letter counting
- **Multi-channel support** - Responds when mentioned in servers/groups or to any message in DMs
- **Model selection** - Users can specify models per-message with `!model=<model_name>` syntax
- **User awareness** - Formats messages with usernames so the LLM can distinguish between users
- **Conversation context** - Maintains chat history per Discord channel with automatic token-based trimming
- **Long response handling** - Automatically splits responses longer than Discord's 2000 character limit

## Backends

### Ollama (default)

Connects to a local [Ollama](https://ollama.com) instance. Requires Ollama to be running with at least one model pulled.

```sh
ollama pull llama3.1:8b
```

### Claude API

Connects to Anthropic's Claude API. Requires an Anthropic API key.

Set the key via environment variable or `--api-key` flag:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

## Installation & Setup

### Environment Variables

```bash
export DISCORD_BOT_TOKEN="your-discord-bot-token"

# Required only for --backend claude:
export ANTHROPIC_API_KEY="sk-ant-..."
```

### Using Nix (Recommended)

```sh
nix develop
```

### NixOS Module

A system module is available for running llmbot as a systemd service. Import the module from the flake:

```nix
{
  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    llmbot.url = "github:graysonhead/llmbot";
  };

  outputs = { self, nixpkgs, llmbot }: {
    nixosConfigurations.yourhostname = nixpkgs.lib.nixosSystem {
      modules = [
        llmbot.nixosModules.default
        {
          services.llmbot = {
            enable = true;
            model = "llama3.1:8b";
            requestTimeout = 15.0;

            # Security: use file-based secrets (recommended)
            environmentFile = "/etc/llmbot/secrets.env";
          };
        }
      ];
    };
  };
}
```

`/etc/llmbot/secrets.env`:
```bash
DISCORD_BOT_TOKEN=your-discord-bot-token
```

## Usage

### CLI Query

```sh
# Ollama (default)
llmbot query "What is Python?"

# With a specific model
llmbot query --model llama3.1:70b "Explain quantum computing"

# Without tools
llmbot query --no-tools "Hello"

# Claude
llmbot query --backend claude "What is Python?"

# Claude with a specific model
llmbot query --backend claude --claude-model claude-opus-4-6 "Write a haiku"
```

### Discord Bot

```sh
# Ollama (default)
llmbot discord

# Ollama with options
llmbot discord --model llama3.1:70b --host http://my-ollama-server:11434 --context-length 8192

# Claude
ANTHROPIC_API_KEY=sk-ant-... llmbot discord --backend claude

# Claude with a specific model
llmbot discord --backend claude --claude-model claude-opus-4-6

# With a custom system message appended from a file
llmbot discord --system-message-file /path/to/extra-instructions.txt
```

### Discord Usage

Once the bot is running:

- **In DMs**: Send any message directly to the bot
- **In servers/groups**: Mention the bot (`@BotName your question`)
- **Model selection**: Add `!model=<name>` to your message to override the model for that query

Examples:
```
@LLMBot What is Python?
@LLMBot !model=llama3.1:70b Explain machine learning
```

### Available Options

#### `llmbot query`

| Flag | Default | Description |
|---|---|---|
| `--backend` | `ollama` | Backend to use: `ollama` or `claude` |
| `--host` | `http://localhost:11434` | Ollama server URL |
| `--model` | `llama3.1:8b` | Ollama model name |
| `--claude-model` | `claude-sonnet-4-6` | Claude model ID |
| `--api-key` | `$ANTHROPIC_API_KEY` | Anthropic API key |
| `--context-length` | `2048` | Ollama context window size |
| `--searxng-url` | `http://localhost:8080/search` | SearXNG URL for web search tool |
| `--no-tools` | off | Disable tool calling |

#### `llmbot discord`

Same backend/model flags as `query`, plus:

| Flag | Default | Description |
|---|---|---|
| `--timeout` | `15.0` | Request timeout in seconds |
| `--context-length` | `2048` | Max tokens for history trimming (also sets Ollama `num_ctx`) |
| `--system-message-file` | — | Path to file with extra system prompt content |
| `--no-tools` | off | Disable tool calling |

## Develop

```sh
nix develop
nox           # run all checks and tests
nox --list    # list available sessions
nox -s fix    # auto-fix formatting and lint issues
```

## Build

```sh
nix build
```
