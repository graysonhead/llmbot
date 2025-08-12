# llmbot

An LLM Gateway for Discord that connects Discord users to Large Language Models via OpenWebUI.

## What it does

`llmbot` is a Python CLI tool that provides two main functions:

1. **Direct CLI queries** - Send questions directly to an OpenWebUI server from the command line
2. **Discord bot** - Run a Discord bot that forwards messages to OpenWebUI, allowing Discord users to chat with LLMs

### Discord Bot Features

- **Multi-channel support** - Responds when mentioned in servers/groups or to any message in DMs
- **Model selection** - Users can specify models with `!model=<model_name>` syntax
- **User awareness** - Formats messages with usernames so the LLM can distinguish between users
- **Long response handling** - Automatically splits responses longer than Discord's 2000 character limit
- **Conversation context** - Maintains chat context per Discord channel

## Installation & Setup

### Environment Variables

Set these required environment variables:

```bash
export OPENWEBUI_API_KEY="your-openwebui-api-key"
export DISCORD_BOT_TOKEN="your-discord-bot-token"
```

### Using Nix (Recommended)

Enter the development environment:

```sh
nix develop
```

### NixOS Module

For NixOS users, a system module is available for running llmbot as a systemd service. Import the module from the flake:

```nix
# In your flake.nix inputs
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
            serverUrl = "https://your-openwebui-server.com";
            model = "llama3.1:8b";  # Optional, defaults to llama3.1:8b
            requestTimeout = 15.0;  # Optional, defaults to 15.0
            
            # Security: Use file-based secrets (recommended)
            environmentFile = "/etc/llmbot/secrets.env";
            # OR use individual credential files:
            # discordTokenFile = "/etc/llmbot/discord-token";
            # openwebuiApiKeyFile = "/etc/llmbot/openwebui-key";
          };
        }
      ];
    };
  };
}
```

Create `/etc/llmbot/secrets.env`:
```bash
DISCORD_BOT_TOKEN=your-discord-bot-token
OPENWEBUI_API_KEY=your-openwebui-api-key
```

## Usage

### CLI Query Mode

Send a direct query to an OpenWebUI server:

```sh
nix run . -- query --server-url "https://your-openwebui-server.com" "What is the weather like?"
```

With custom model:

```sh
nix run . -- query --server-url "https://your-openwebui-server.com" --model "gpt-4" "Explain quantum computing"
```

### Discord Bot Mode

Start the Discord bot:

```sh
nix run . -- discord --server-url "https://your-openwebui-server.com"
```

With custom model and timeout:

```sh
nix run . -- discord --server-url "https://your-openwebui-server.com" --model "llama3.1:70b" --timeout 30
```

### Discord Usage

Once the bot is running:

- **In DMs**: Just send any message to the bot
- **In servers/groups**: Mention the bot (`@BotName your question`)
- **Model selection**: Add `!model=model_name` to your message

Examples:
```
@LLMBot What is Python?
@LLMBot !model=gpt-4 Explain machine learning
```

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
