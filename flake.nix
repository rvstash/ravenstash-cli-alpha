{
  description = "Ravenstash developer CLI";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";

  outputs = { self, nixpkgs }:
    let
      systems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
      forAllSystems = nixpkgs.lib.genAttrs systems;
    in {
      packages = forAllSystems (system:
        let
          pkgs = import nixpkgs { inherit system; };
          py = pkgs.python314Packages;
          rvs = py.buildPythonApplication {
            pname = "ravenstash-cli";
            version = (builtins.fromTOML (builtins.readFile ./pyproject.toml)).project.version;
            src = pkgs.lib.cleanSourceWith {
              src = self;
              filter = path: _type:
                let name = builtins.baseNameOf path;
                in !(builtins.elem name [ ".git" ".venv" "build" "dist" ]
                  || pkgs.lib.hasSuffix ".egg-info" name);
            };
            pyproject = true;
            build-system = [ py.setuptools ];
            dependencies = [
              py.cryptography
              py.httpx
              py.keyring
              py.pyyaml
              py.rich
              py.tomli-w
              py.typer
            ];
            pythonImportsCheck = [ "rvs" ];
            nativeCheckInputs = [ py.pytestCheckHook py.pytest-httpx ];
            # The vault round-trip forks a long-lived Unix-socket agent. Nix's
            # isolated build sandbox cannot host that session process; native
            # Linux CI continues to exercise the test.
            disabledTests = [ "test_encrypted_vault_round_trip_and_lock" ];
          };
        in {
          default = rvs;
          inherit rvs;
        });

      checks = forAllSystems (system: {
        inherit (self.packages.${system}) rvs;
      });
    };
}
