{
  description = "A Python Package";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs = { self, nixpkgs, flake-utils, ... }:
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
          propagatedBuildInputs = with pkgs.python3Packages; [
            click
            discordpy
            mcp
            ollama
            requests
          ];
        };

        ## Make our package editable:
        editablePackage = pkgs.python3.pkgs.mkPythonEditablePackage {
          pname = project.name;
          inherit (project) scripts version;
          root = "$PWD";
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
            ];
          };
        };
      });
}
