#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$script_dir/.." && pwd)"
cd "$root"

mode=""
want_version=""
do_push=0
assume_yes=0
dry_run=0

usage() {
  cat <<'EOF'
Usage: tool/release.sh <pre|stable> [options]

  pre                Tag the next vX.Y.Z-honganBeta.0.0.N prerelease.
  stable             Write the changelog, commit it, and tag vX.Y.Z-honganBeta.

Options:
  --version X.Y.Z    Target app version. Defaults to the pubspec version, and
                     must match .upstream-version.
  --push             Push the branch and the tag once the local steps pass.
  --yes              Skip the confirmation prompt.
  --dry-run          Report the plan and exit without changing anything.
  -h, --help         Show this help.

Examples:
  tool/release.sh pre --push          # v0.9.2-honganBeta.0.0.3, notes rendered by CI
  tool/release.sh stable --push       # v0.9.2-honganBeta with a release commit
EOF
}

die() {
  echo "error: $*" >&2
  exit 1
}

while (($#)); do
  case "$1" in
    pre | stable)
      [[ -z "$mode" ]] || die "mode given twice: $mode and $1"
      mode="$1"
      ;;
    --version)
      shift || die "--version needs a value"
      want_version="$1"
      ;;
    --version=*) want_version="${1#*=}" ;;
    --push) do_push=1 ;;
    --yes | -y) assume_yes=1 ;;
    --dry-run) dry_run=1 ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      usage >&2
      die "unknown argument: $1"
      ;;
  esac
  shift
done

[[ -n "$mode" ]] || {
  usage >&2
  exit 64
}

if [[ -n "$want_version" && ! "$want_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  die "--version must look like 0.8.97, got: $want_version"
fi

pubspec_version() {
  sed -n 's/^version: \([0-9]*\.[0-9]*\.[0-9]*\).*/\1/p' pubspec.yaml
}

if ! git diff --quiet || ! git diff --cached --quiet; then
  die "working tree has uncommitted changes; commit or stash them first"
fi

branch="$(git rev-parse --abbrev-ref HEAD)"
[[ "$branch" != "HEAD" ]] || die "detached HEAD; check out a branch first"
if [[ "$branch" != "main" ]]; then
  echo "note: releasing from '$branch', not main. CI triggers on the tag, so"
  echo "      this publishes '$branch' while main stays behind."
fi

current="$(pubspec_version)"
[[ -n "$current" ]] || die "could not read the version from pubspec.yaml"

# The app version tracks the imported upstream snapshot, and the release build
# rejects any tag whose version differs from it, so a release starts by bumping
# .upstream-version (see tool/fork_version.sh) rather than this script.
upstream="$(tr -d '[:space:]' <"$root/.upstream-version")"
version="${want_version:-$current}"
[[ "$version" == "$upstream" ]] ||
  die "app version $version must equal .upstream-version ($upstream); tool/check_fork_version.sh would reject the tag"

base="v$version-honganBeta"
if [[ "$mode" == "pre" ]]; then
  # The beta counter is three-part and only its last number moves, so the first
  # prerelease of a series is .0.0.2 and the ones after it .0.0.3, .0.0.4, ...
  last="$(git tag --list "$base.[0-9]*.[0-9]*.[0-9]*" |
    sed -n 's/.*\.\([0-9][0-9]*\)$/\1/p' | sort -n | tail -1)"
  tag="$base.0.0.$(((${last:-1}) + 1))"
else
  git rev-parse -q --verify "refs/tags/$base" >/dev/null &&
    die "$base is already tagged; bump .upstream-version for a new release"
  tag="$base"
fi

echo
echo "mode      : $mode"
echo "branch    : $branch"
echo "version   : $version"
echo "tag       : $tag"
if [[ "$mode" == "pre" ]]; then
  echo "changelog : rendered by CI from build --unreleased; nothing committed"
else
  echo "changelog : CHANGELOG.md + changelog.json regenerated and committed"
fi
echo "publishes : GitHub prerelease with artifacts and SHA256SUMS"
echo "push      : $([[ $do_push == 1 ]] && echo yes || echo 'no (printed at the end)')"
echo

committed=0
restore() {
  ((committed)) && return 0
  git checkout -- pubspec.yaml changelog.json CHANGELOG.md 2>/dev/null || true
}
trap restore EXIT

tool/bump_version.sh minor

echo "--- release notes for $tag ---"
if dart run tool/changelog.dart build --unreleased >/dev/null 2>&1; then
  dart run tool/changelog.dart render release 2>/dev/null |
    sed -n '/changelog:begin/,/changelog:end/p' | sed '1d;$d'
else
  echo "(preview unavailable: 'build --unreleased' found nothing to collect)"
fi
git checkout -- changelog.json 2>/dev/null || true
echo "--- end of notes ---"
echo

if ((dry_run)); then
  echo "dry run: nothing was changed."
  exit 0
fi

if ((assume_yes == 0)); then
  if [[ ! -r /dev/tty ]]; then
    die "no terminal to confirm on; pass --yes to run unattended"
  fi
  while true; do
    read -r -p "Proceed with $tag? [y/n] " reply </dev/tty ||
      die "no answer read; pass --yes to run unattended"
    case "$reply" in
      [yY] | [yY][eE][sS]) break ;;
      [nN] | [nN][oO])
        echo "Cancelled. Nothing was changed."
        exit 0
        ;;
      *) echo "Please answer y or n." ;;
    esac
  done
fi

if [[ "$mode" == "stable" ]]; then
  dart run tool/changelog.dart release --version "$version"
  echo
  git --no-pager diff --stat -- CHANGELOG.md changelog.json pubspec.yaml
  echo
  git add CHANGELOG.md changelog.json pubspec.yaml
  git commit -m "chore(release): v$version"
  committed=1
  dart run tool/changelog.dart verify
elif ! git diff --quiet -- pubspec.yaml; then
  git add pubspec.yaml
  git commit -m "chore: bump version to $(sed -n 's/^version: //p' pubspec.yaml)"
  committed=1
else
  committed=1
fi

git tag "$tag"
echo "tagged $tag at $(git rev-parse --short HEAD)"

if ((do_push)); then
  git push origin "$branch"
  git push origin "$tag"
  echo "pushed $branch and $tag"
else
  echo
  echo "Nothing was pushed. To publish:"
  echo "  git push origin $branch && git push origin $tag"
fi
