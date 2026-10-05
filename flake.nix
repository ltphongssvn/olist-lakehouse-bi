{
  # THE TOOLCHAIN THIS PROJECT NEEDS, DECLARED.
  #
  # Nix was installed by `curl | sh` and captured by scripts/nix_contract.py.
  # This is what that installation is FOR: the nine tools mise pins, resolved
  # from a locked nixpkgs and reproducible on any supported platform.
  #
  # TWO NAMES DIFFER FROM THE mise REGISTRY, both found by searching nixpkgs
  # rather than assuming:
  #   opa  -> open-policy-agent  (the binary is still `opa`)
  #   java -> temurin-bin-17     (NOT jdk17. mise defaults to OpenJDK and the
  #                               vendor prefix is mandatory there for the same
  #                               reason: a different build is a different tool)
  description = "cscie103-data-engineering toolchain";

  inputs = {
    # UNSTABLE, WHICH IS THE RIGHT BRANCH FOR A DEV TOOLCHAIN.
    #
    # This was pinned to nixos-26.05 on the reasoning that "a gate must not
    # change because upstream moved". That reasoning was wrong twice over.
    #
    # A release branch is FROZEN at release and receives only security
    # backports, so by September its packages are four months stale by design:
    # uv 0.11.21 against the 0.12.5 this project pins, regal 0.40 against 0.42,
    # zizmor 1.25 against 1.29. Choosing it bought staleness, not safety.
    #
    # And the safety it was chosen for comes from flake.lock, not the branch:
    # the lock "records the exact Git commit hash... all ambiguity is gone".
    # The branch only decides where `nix flake update` moves TO. Nothing here
    # changes until someone updates the lock deliberately.
    #
    # The guidance splits exactly on this: unstable "is fine for dev machines.
    # For production or CI, pin to a release branch". This is a toolchain of
    # linters, formatters and CLIs -- a dev machine's toolbox, not a system
    # whose uptime depends on conservative packages.
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
  };

  outputs = { self, nixpkgs }:
    let
      inherit (nixpkgs) lib;

      # THE FOUR DOUBLES, matching the set policies/machine/nix/nix.rego
      # validates against, so the flake and the policy agree on what
      # "supported" means.
      #
      # x86_64-darwin IS GONE, AND THE SHELF LIFE RAN OUT DURING THIS CHANGE.
      #
      # 26.05 warned it "will be the last release to support x86_64-darwin",
      # following Apple's announcement that macOS 26 is the final version for
      # Intel Macs. Switching to unstable -- now 26.11-dev -- crossed that line:
      # evaluation fails outright with "Nixpkgs 26.11 has dropped support for
      # x86_64-darwin", not a warning.
      #
      # THE COMMENT PREDICTING THIS WAS WRITTEN AN HOUR BEFORE IT HAPPENED, and
      # said the double "leaves both this list and the policy together". This is
      # that: three systems here, and the policy's supported set narrowed to
      # match in the same change.
      #
      # NOT a nixpkgs-26.05-darwin input to keep it alive. That would pin one
      # platform to a frozen branch to serve hardware Apple has stopped
      # supporting -- reintroducing the staleness this project just removed, for
      # a machine nobody here uses.
      systems = [ "aarch64-darwin" "aarch64-linux" "x86_64-linux" ];

      # ONE UNFREE PACKAGE, NAMED, AND NOTHING ELSE.
      #
      # databricks-cli carries the proprietary `databricks` licence, so nixpkgs
      # refuses to REALISE it. `nix flake check --no-build` never noticed,
      # because --no-build means "do not build checks" -- it proves the flake
      # EVALUATES and nothing more. The refusal appeared on the first real
      # `nix develop`, after the gate had reported four green platforms.
      #
      # NOT allowUnfree = true, and NOT NIXPKGS_ALLOW_UNFREE. The blanket flag
      # permits every unfree package present and future, so a dependency
      # acquiring one later would pass silently. The environment variable is
      # worse: it requires --impure, reintroducing exactly the ambient state
      # the pure-eval hardening in nix_contract.py exists to exclude.
      #
      # The predicate names ONE package. Anything else unfree still fails, and
      # says which -- so a second is a deliberate edit here, not something a
      # flag already allowed.
      pkgsFor = lib.genAttrs systems (system:
        import nixpkgs {
          inherit system;
          config.allowUnfreePredicate = pkg: lib.getName pkg == "databricks-cli";

          overlays = [
            (_final: prev: {
              # OPA'S VENDORED TESTS DO NOT COMPILE IN NIXPKGS 26.05.
              #
              # There is no aarch64-darwin substitute, so Nix builds from source
              # and runs the upstream suite, which fails at
              # "v1/server/compile_handler_test.go:43:50: undefined: fixture".
              # A defect in the packaged source, not in this flake --
              # `nix build --dry-run` shows only this and databricks-cli need
              # building; the other seven come from the cache.
              #
              # doCheck = false IS THE DOCUMENTED MECHANISM, not a hack:
              # overrideAttrs "overrides the doCheck attribute while leaving
              # other attributes unchanged", and nixpkgs' own guidance disables
              # checks this way when a patch breaks a vendored suite.
              #
              # AND IT COSTS THIS PROJECT NOTHING. Whether OPA's own tests
              # compile is nixpkgs' concern. The check that matters here already
              # runs on every gate: `opa test policies/ --fail-on-empty` against
              # THIS repository's 33 policy tests, which is a stronger signal
              # about the binary being usable than the vendor's suite.
              open-policy-agent = prev.open-policy-agent.overrideAttrs (_: {
                doCheck = false;
              });
            })
          ];
        });

      # genAttrs rather than flake-utils: one fewer input to lock and update,
      # for a function that is three lines.
      forAllSystems = f: lib.genAttrs systems (system: f pkgsFor.${system});
    in
    {
      devShells = forAllSystems (pkgs: {
        default = pkgs.mkShell {
          # THE SAME NINE mise.toml PINS. Two declarations of one toolchain is
          # the drift this project exists to remove, and Phase 4 deletes the
          # mise [tools] block. Until then scripts/check_toolchain_parity.py
          # fails when they disagree, rather than trusting them to agree.
          packages = with pkgs; [
            betterleaks
            databricks-cli
            lefthook
            open-policy-agent
            osv-scanner
            regal
            temurin-bin-17
            uv
            zizmor
          ];
        };
      });

      # SOMETHING FOR `nix flake check` TO VERIFY, so the flake is more than
      # parseable. Building the shell's inputs proves every package above
      # actually resolves on that platform -- a name that exists on Linux and
      # not Darwin fails here rather than on someone's laptop.
      checks = forAllSystems (pkgs: {
        toolchain-resolves = pkgs.runCommand "toolchain-resolves"
          { buildInputs = self.devShells.${pkgs.stdenv.hostPlatform.system}.default.buildInputs; }
          "echo ${pkgs.stdenv.hostPlatform.system} > $out";
      });
    };
}
