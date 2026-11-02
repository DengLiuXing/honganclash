#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
upstream="$(tr -d '[:space:]' < "$root/.upstream-version")"
tag="${1:-}"
expected="v${upstream}-honganBeta"

case "$tag" in
  "$expected"|"$expected".*)
    exit 0
    ;;
esac

echo "Tag '$tag' must be $expected or $expected.N (upstream $upstream)" >&2
exit 1
