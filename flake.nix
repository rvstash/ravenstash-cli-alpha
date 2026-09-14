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
          py = pkgs.python314Packages.overrideScope (_final: previous: {
            cryptography = previous.cryptography.overridePythonAttrs (_old: rec {
              version = "50.0.1";
              src = pkgs.fetchPypi {
                pname = "cryptography";
                inherit version;
                hash = "sha256-Xdm9ocErQWL2/1aO614P+VbCjRRAbodc/opjotQU/yA=";
              };
              cargoDeps = pkgs.rustPlatform.fetchCargoVendor {
                pname = "cryptography";
                inherit version src;
                hash = "sha256-aGokDcpVxfSolwEUOcEyP/8nrrLuRXC3YyrTT+Dv36I=";
              };
              patches = [ ];
              doCheck = false;
            });
            idna = previous.idna.overridePythonAttrs (_old: rec {
              version = "3.19";
              src = pkgs.fetchPypi {
                pname = "idna";
                inherit version;
                hash = "sha256-XggRpDg7IdxYOAafgBxPtiETt0R2Y9JTDSvW53tJvxU=";
              };
            });
          });
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
            disabledTests = [
              "test_encrypted_vault_round_trip_and_lock"
              # Release-infrastructure scripts require an FHS shell and are
              # exercised by source and release-policy CI, not the Nix package.
              "test_apt_publisher_uses_constant_number_of_storage_calls"
              "test_release_slot_check_fails_closed"
            ];
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
