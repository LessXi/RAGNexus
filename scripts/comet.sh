#!/usr/bin/env bash
# Comet wrapper — fixes Git Bash path resolution on Windows
# Usage: bash scripts/comet.sh <script> <args...>
#   bash scripts/comet.sh state check kb-retrieve-pages build
#   bash scripts/comet.sh guard kb-retrieve-pages build --apply
#   bash scripts/comet.sh archive kb-retrieve-pages

set -euo pipefail

# Must use Git Bash on Windows (WSL bash rejected by comet-env)
COMET_BASH="${COMET_BASH:-C:/Program Files/Git/bin/bash.exe}"
export COMET_BASH

COMET_DIR="C:/Users/hj/.config/opencode/skills/comet/scripts"
export COMET_STATE="${COMET_STATE:-${COMET_DIR}/comet-state.sh}"
export COMET_GUARD="${COMET_GUARD:-${COMET_DIR}/comet-guard.sh}"
export COMET_HANDOFF="${COMET_HANDOFF:-${COMET_DIR}/comet-handoff.sh}"
export COMET_ARCHIVE="${COMET_ARCHIVE:-${COMET_DIR}/comet-archive.sh}"
export COMET_YAML_VALIDATE="${COMET_YAML_VALIDATE:-${COMET_DIR}/comet-yaml-validate.sh}"

if [ $# -lt 1 ]; then
  echo "Usage: $0 <state|guard|handoff|archive|yaml-validate> [args...]"
  exit 1
fi

SUBCOMMAND="$1"
shift

case "$SUBCOMMAND" in
  state)          TARGET="$COMET_STATE" ;;
  guard)          TARGET="$COMET_GUARD" ;;
  handoff)        TARGET="$COMET_HANDOFF" ;;
  archive)        TARGET="$COMET_ARCHIVE" ;;
  yaml-validate)  TARGET="$COMET_YAML_VALIDATE" ;;
  *)
    echo "Unknown subcommand: $SUBCOMMAND"
    echo "Valid: state, guard, handoff, archive, yaml-validate"
    exit 1
    ;;
esac
exec "$COMET_BASH" "$TARGET" "$@"
