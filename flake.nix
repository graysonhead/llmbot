{
  description = "A Python Package";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    pre-commit-hooks.url = "github:cachix/pre-commit-hooks.nix";
  };

  outputs = { self, nixpkgs, flake-utils, pre-commit-hooks, ... }:
    {
      # Export the NixOS module
      nixosModules.default = import ./module.nix;
      nixosModule = self.nixosModules.default;
    } //
    flake-utils.lib.eachDefaultSystem (system:
      let
        ## Import nixpkgs:
        pkgs = import nixpkgs { inherit system; };

        ## Read pyproject.toml file:
        pyproject = builtins.fromTOML (builtins.readFile ./pyproject.toml);

        ## Get project specification:
        project = pyproject.project;

        ## Create openwebui-chat-client package:
        openwebui-chat-client = pkgs.python3Packages.buildPythonPackage rec {
          pname = "openwebui_chat_client";
          version = "0.1.15";
          format = "pyproject";

          src = pkgs.python3Packages.fetchPypi {
            inherit pname version;
            sha256 = "330ea41d58db1c1f9e018fb576287c1e84ee3945cc32c1f6c81dafadb97e0bf5";
          };

          build-system = with pkgs.python3Packages; [
            setuptools
            wheel
          ];

          propagatedBuildInputs = with pkgs.python3Packages; [
            requests
            pydantic
            typing-extensions
            python-dotenv
          ];

          # Skip tests as they may require network access or OpenWebUI server
          doCheck = false;

          pythonImportsCheck = [ "openwebui_chat_client" ];

          meta = with pkgs.lib; {
            description = "A comprehensive Python client for the Open WebUI API";
            homepage = "https://pypi.org/project/openwebui-chat-client/";
            license = licenses.gpl3Only;
            maintainers = [ ];
          };
        };

        ## Get the package:
        package = pkgs.python3Packages.buildPythonPackage {
          ## Set the package name:
          pname = project.name;

          ## Inherit the package version:
          inherit (project) version;

          ## Set the package format:
          format = "pyproject";

          ## Set the package source:
          src = ./.;

          ## Specify the build system to use:
          build-system = with pkgs.python3Packages; [
            setuptools
          ];

          ## Specify test dependencies:
          nativeCheckInputs = [
            ## Python dependencies:
            pkgs.python3Packages.mypy
            pkgs.python3Packages.nox
            pkgs.python3Packages.pytest
            pkgs.python3Packages.ruff

            ## Non-Python dependencies:
            pkgs.taplo
          ];

          ## Define the check phase:
          checkPhase = ''
            runHook preCheck
            nox
            runHook postCheck
          '';

          ## Specify production dependencies:
          propagatedBuildInputs = [
            pkgs.python3Packages.click
            pkgs.python3Packages.discordpy
            openwebui-chat-client
          ];
        };

        ## Make our package editable:
        editablePackage = pkgs.python3.pkgs.mkPythonEditablePackage {
          pname = project.name;
          inherit (project) scripts version;
          root = "$PWD";
        };

        ## Configure pre-commit hooks:
        pre-commit-check = pre-commit-hooks.lib.${system}.run {
          src = ./.;
          hooks = {
            # Run linting
            ruff-check = {
              enable = true;
              name = "ruff-check";
              entry = "${pkgs.python3Packages.nox}/bin/nox -s check";
              language = "system";
              pass_filenames = false;
            };
            
            # Run formatting
            ruff-format = {
              enable = true;
              name = "ruff-format";
              entry = "${pkgs.python3Packages.nox}/bin/nox -s format -- --fix";
              language = "system";
              pass_filenames = false;
            };
            
            # Format TOML files
            taplo-format = {
              enable = true;
              name = "taplo-format";
              entry = "${pkgs.python3Packages.nox}/bin/nox -s taplo -- --fix";
              language = "system";
              files = "\\.toml$";
              pass_filenames = false;
            };
          };
        };
      in
      {
        ## Project packages output:
        packages = {
          "${project.name}" = package;
          default = self.packages.${system}.${project.name};
        };

        ## Project development shell output:
        devShells = {
          default = pkgs.mkShell {
            inherit (pre-commit-check) shellHook;
            inputsFrom = [
              package
            ];

            buildInputs = [
              #################
              ## OUR PACKAGE ##
              #################

              editablePackage

              #################
              # VARIOUS TOOLS #
              #################

              pkgs.python3Packages.build
              pkgs.python3Packages.ipython

              ####################
              # EDITOR/LSP TOOLS #
              ####################

              # LSP server:
              pkgs.python3Packages.python-lsp-server

              # LSP server plugins of interest:
              pkgs.python3Packages.pylsp-mypy
              pkgs.python3Packages.pylsp-rope
              pkgs.python3Packages.python-lsp-ruff
            ] ++ pre-commit-check.enabledPackages;
          };
        };
      });
}
