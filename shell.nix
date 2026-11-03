# Development shell: `nix-shell` gives you every tool the Makefile needs.
{ pkgs ? import <nixpkgs> { } }:

let
  python = pkgs.python312;
in
pkgs.mkShell {
  packages = [
    python
    pkgs.uv
    pkgs.nodejs_22
    pkgs.pnpm
    pkgs.gnumake
    pkgs.git
  ];

  shellHook = ''
    # Use the Python from this shell instead of letting uv download one.
    export UV_PYTHON="${python}/bin/python"
    export UV_PYTHON_DOWNLOADS=never
  '';
}
