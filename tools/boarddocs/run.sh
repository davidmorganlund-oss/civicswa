#!/bin/bash
# Nightly: refresh the BoardDocs snapshot and push it to the boarddocs-data branch.
set -euo pipefail
# Wrapped in a function so bash reads it all before the reset below can change this file.
main() {
cd "$(dirname "$0")/../.."
echo "== $(date)"
git fetch -q origin main && git reset -q --hard origin/main
out=$(mktemp)
/usr/bin/python3 tools/boarddocs/snapshot.py pipeline/sources.yml "$out"
blob=$(git hash-object -w "$out")
tree=$(printf '100644 blob %s\tboarddocs.json\n' "$blob" | git mktree)
commit=$(git commit-tree "$tree" -m "BoardDocs snapshot $(date -u +%Y-%m-%dT%H:%MZ)")
git push -q -f origin "$commit:refs/heads/boarddocs-data"
rm -f "$out"
echo "pushed $commit"
}
main "$@"
