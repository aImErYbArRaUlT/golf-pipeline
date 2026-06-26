{
  description = "Golf launch-monitor data pipeline - reproducible dev environment";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    { self, nixpkgs, flake-utils }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = import nixpkgs { inherit system; };

        # Google ships the MCP Toolbox as a prebuilt binary per platform.
        # We fetch the pinned release rather than building from source, so the
        # flake stays simple and fast. Update version + hashes together.
        toolboxVersion = "1.5.0";
        toolboxBySystem = {
          aarch64-darwin = {
            os = "darwin";
            arch = "arm64";
            sha256 = "0sbj167dbl5qc3qm6hbgapri25q2yxva7pj2hczhfwhh2syafbbk";
          };
          x86_64-darwin = {
            os = "darwin";
            arch = "amd64";
            sha256 = "14n2rl6g4zgjm1dba13nqzhwzkgykwy7cxalrmzv12kphrvlzbiy";
          };
          x86_64-linux = {
            os = "linux";
            arch = "amd64";
            sha256 = "02ansz92v3wkl0vvc45h8f2w6slzn84lxixc1spm6kp33jadkwkx";
          };
        };

        plat =
          toolboxBySystem.${system} or (throw
            "mcp-toolbox: no prebuilt binary for ${system} (supported: ${
              builtins.concatStringsSep ", " (builtins.attrNames toolboxBySystem)
            }). On linux/arm64 use WSL2-on-x86 or build from source."
          );

        # The toolbox is a static Go binary, so it runs as-is on NixOS - no
        # autoPatchelf needed. (If a future release links dynamically on Linux,
        # add pkgs.autoPatchelfHook to nativeBuildInputs.)
        toolbox = pkgs.stdenv.mkDerivation {
          pname = "mcp-toolbox";
          version = toolboxVersion;
          src = pkgs.fetchurl {
            url = "https://storage.googleapis.com/mcp-toolbox-for-databases/v${toolboxVersion}/${plat.os}/${plat.arch}/toolbox";
            sha256 = plat.sha256;
          };
          dontUnpack = true;
          installPhase = ''
            install -Dm755 $src $out/bin/toolbox
          '';
        };
      in
      {
        packages.toolbox = toolbox;

        devShells.default = pkgs.mkShell {
          # Reproducible toolchain. Docker and gcloud come from the host
          # (Docker Desktop / Google Cloud SDK), as is conventional. Python
          # tooling (ruff, black, pytest, pre-commit) is deliberately NOT here -
          # it's managed by uv in the project venv. Adding a Nix Python app like
          # pre-commit would export its 3.13 site-packages on PYTHONPATH and
          # shadow the venv's 3.12 (pytest would crash). Keep this list to
          # non-Python tools only.
          packages = [
            toolbox
            pkgs.uv
            pkgs.just
            pkgs.opentofu
            pkgs.nodejs_22
            pkgs.gitleaks
          ];

          # Defence in depth: ensure no Nix Python path leaks into uv's venv,
          # even if a Python tool sneaks into packages later.
          shellHook = ''
            unset PYTHONPATH
            echo "golf-pipeline dev shell - toolbox $(toolbox --version 2>/dev/null | head -1 || echo ${toolboxVersion})"
          '';
        };
      }
    );
}
