#!/bin/sh
# Set the repository's About on GitHub (its description, website and topics) from .github/repo.json, so what GitHub shows
# says what the README says. Run it once the repository is public, and again after repo.json changes:
#
#   sh .github/repo-meta.sh [owner/name]        # kanggu12/offerowl when none is given
set -eu

root=$(cd "$(dirname "$0")/.." && pwd)   # the repository, wherever this is run from
repo=${1:-kanggu12/offerowl}             # the repository to set
meta="$root/.github/repo.json"           # what to set

field() { python3 -c 'import json,sys; v = json.load(open(sys.argv[1]))[sys.argv[2]]; print(" ".join(v) if isinstance(v, list) else v)' "$meta" "$1"; }

description=$(field description)
homepage=$(field homepage)
topics=$(field topics)

# the topics GitHub has now that repo.json no longer names are taken off, so the list is exactly the file's
current=$(gh repo view "$repo" --json repositoryTopics --jq '.repositoryTopics[]?.name' 2>/dev/null || true)
set -- --description "$description" --homepage "$homepage"
for t in $topics; do set -- "$@" --add-topic "$t"; done
for t in $current; do
  case " $topics " in *" $t "*) ;; *) set -- "$@" --remove-topic "$t" ;; esac
done
gh repo edit "$repo" --enable-discussions "$@"   # the issue form's questions and ideas go to Discussions
gh api -X PUT "repos/$repo/private-vulnerability-reporting" >/dev/null   # SECURITY.md's "Report a vulnerability"
gh repo view "$repo" --json description,homepageUrl,repositoryTopics --jq '"description: \(.description)\nwebsite: \(.homepageUrl)\ntopics: \([.repositoryTopics[]?.name] | join(", "))"'
