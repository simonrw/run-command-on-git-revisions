{ pkgs ? import <nixpkgs> { } }:
pkgs.mkShell {
  buildInputs = with pkgs; [
    python310
    python310Packages.poetry
  ];
}
