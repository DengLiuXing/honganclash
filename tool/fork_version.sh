#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
upstream="$(tr -d '[:space:]' < "$root/.upstream-version")"
if [[ ! "$upstream" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Invalid upstream version in .upstream-version: $upstream" >&2
  exit 1
fi

version_line="$(grep -E '^version: .*\+[0-9]{10}$' "$root/pubspec.yaml" || true)"
if [[ -z "$version_line" ]]; then
  echo "No valid version line in pubspec.yaml" >&2
  exit 1
fi

build_number="${version_line##*+}"
today="$(date +%Y%m%d)"
build_date="${build_number:0:8}"
build_count="${build_number:8:2}"
if [[ "$build_date" == "$today" ]]; then
  count=$((10#$build_count + 1))
else
  count=1
fi
if (( count > 99 )); then
  echo "Build count for $today exceeds 99" >&2
  exit 1
fi
build="$(printf '%s%02d' "$today" "$count")"
new_version="$upstream-honganBeta+$build"

tmp_file="$(mktemp)"
sed "s/^version: .*/version: $new_version/" "$root/pubspec.yaml" > "$tmp_file"
mv "$tmp_file" "$root/pubspec.yaml"
echo "$version_line -> $new_version"
