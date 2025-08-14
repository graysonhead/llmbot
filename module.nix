{ config, lib, pkgs, ... }:

with lib;

let
  cfg = config.services.llmbot;
in
{
  options.services.llmbot = {
    enable = mkEnableOption "llmbot Discord LLM gateway service";

    package = mkOption {
      type = types.package;
      default = pkgs.python3Packages.buildPythonPackage {
        pname = "llmbot";
        version = "0.1.0";
        format = "pyproject";
        src = ./.;
        build-system = with pkgs.python3Packages; [ setuptools ];
        propagatedBuildInputs = with pkgs.python3Packages; [
          click
          discordpy
          openai
        ];
      };
      description = "The llmbot package to use.";
    };

    discordToken = mkOption {
      type = types.str;
      description = "Discord bot token. Consider using discordTokenFile for better security.";
      default = "";
    };

    discordTokenFile = mkOption {
      type = types.nullOr types.path;
      description = "Path to file containing Discord bot token.";
      default = null;
    };

    openwebuiApiKey = mkOption {
      type = types.str;
      description = "OpenWebUI API key. Consider using openwebuiApiKeyFile for better security.";
      default = "";
    };

    openwebuiApiKeyFile = mkOption {
      type = types.nullOr types.path;
      description = "Path to file containing OpenWebUI API key.";
      default = null;
    };

    environmentFile = mkOption {
      type = types.nullOr types.path;
      description = "Path to environment file containing DISCORD_BOT_TOKEN and OPENWEBUI_API_KEY variables.";
      default = null;
    };

    serverUrl = mkOption {
      type = types.str;
      description = "OpenWebUI server URL.";
      example = "http://localhost:11434/v1";
    };

    model = mkOption {
      type = types.str;
      description = "Default LLM model to use.";
      default = "llama3.1:8b";
    };

    requestTimeout = mkOption {
      type = types.float;
      description = "Request timeout in seconds.";
      default = 15.0;
    };

    searxngUrl = mkOption {
      type = types.str;
      description = "SearXNG instance URL for web search functionality.";
      default = "http://localhost:8080/search";
    };

    systemMessageFile = mkOption {
      type = types.nullOr types.path;
      description = "Path to file containing additional system message content to append to the default system message.";
      default = null;
    };

    user = mkOption {
      type = types.str;
      description = "User to run the service as.";
      default = "llmbot";
    };

    group = mkOption {
      type = types.str;
      description = "Group to run the service as.";
      default = "llmbot";
    };

    logLevel = mkOption {
      type = types.enum [ "DEBUG" "INFO" "WARNING" "ERROR" "CRITICAL" ];
      description = "Logging level.";
      default = "INFO";
    };
  };

  config = mkIf cfg.enable {
    assertions = [
      {
        assertion = cfg.discordToken != "" || cfg.discordTokenFile != null || cfg.environmentFile != null;
        message = "services.llmbot: either discordToken, discordTokenFile, or environmentFile must be set";
      }
      {
        assertion = cfg.openwebuiApiKey != "" || cfg.openwebuiApiKeyFile != null || cfg.environmentFile != null;
        message = "services.llmbot: either openwebuiApiKey, openwebuiApiKeyFile, or environmentFile must be set";
      }
    ];

    users.users.llmbot = mkIf (cfg.user == "llmbot") {
      description = "llmbot service user";
      group = cfg.group;
      isSystemUser = true;
    };

    users.groups.llmbot = mkIf (cfg.group == "llmbot") {};

    systemd.services.llmbot = {
      description = "llmbot Discord LLM gateway";
      wantedBy = [ "multi-user.target" ];
      after = [ "network.target" ];

      serviceConfig = {
        Type = "exec";
        User = cfg.user;
        Group = cfg.group;
        Restart = "always";
        RestartSec = 5;

        # Security options
        NoNewPrivileges = true;
        ProtectSystem = "strict";
        ProtectHome = true;
        ProtectKernelTunables = true;
        ProtectKernelModules = true;
        ProtectControlGroups = true;
        RestrictRealtime = true;
        RestrictNamespaces = true;
        LockPersonality = true;
        MemoryDenyWriteExecute = true;
        RestrictAddressFamilies = [ "AF_INET" "AF_INET6" ];
        SystemCallFilter = [ "@system-service" "~@privileged" ];

        # Environment variables
        Environment = [
          "PYTHONUNBUFFERED=1"
        ] ++ optionals (cfg.discordToken != "") [
          "DISCORD_BOT_TOKEN=${cfg.discordToken}"
        ] ++ optionals (cfg.openwebuiApiKey != "") [
          "OPENWEBUI_API_KEY=${cfg.openwebuiApiKey}"
        ];

        # Load secrets from files
        EnvironmentFile = mkIf (cfg.environmentFile != null) cfg.environmentFile;
        
        # Load credentials from files using systemd's LoadCredential
        LoadCredential = mkMerge [
          (mkIf (cfg.discordTokenFile != null) [
            "discord-token:${cfg.discordTokenFile}"
          ])
          (mkIf (cfg.openwebuiApiKeyFile != null) [
            "openwebui-key:${cfg.openwebuiApiKeyFile}"
          ])
        ];
      };

      script = let
        args = [
          "--host=${cfg.serverUrl}"
          "--model=${cfg.model}"
          "--timeout=${toString cfg.requestTimeout}"
          "--searxng-url=${cfg.searxngUrl}"
        ] ++ optionals (cfg.systemMessageFile != null) [
          "--system-message-file=${cfg.systemMessageFile}"
        ];
        
        credentialSetup = ''
          ${optionalString (cfg.discordTokenFile != null) ''
            export DISCORD_BOT_TOKEN="$(cat "$CREDENTIALS_DIRECTORY/discord-token")"
          ''}
          ${optionalString (cfg.openwebuiApiKeyFile != null) ''
            export OPENWEBUI_API_KEY="$(cat "$CREDENTIALS_DIRECTORY/openwebui-key")"
          ''}
        '';
      in ''
        ${credentialSetup}
        exec ${cfg.package}/bin/llmbot discord ${concatStringsSep " " args}
      '';
    };
  };
}