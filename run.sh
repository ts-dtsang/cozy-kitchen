#!/usr/bin/env bash
#
# Run the cozy-kitchen data pipeline.
#
#   1. build      build_image_bundles.py    builds the image bundles from catalog.bin
#   2. download   download_bundles.py       downloads the bundles
#   3. extract    extract_cozy_kitchen.py   extracts the game data to JSON files and images
#
# Usage:  ./run.sh [step ...]     steps: build, download, extract (default: all three, in this order)
#         ./run.sh --help
#
# Settings (environment variables, all optional):
#   PYTHON         Python command to use                                  (default: python3)
#   DATA_FILE      the game's .data.br file                               (default: data/src/cozy-kitchen.data.br)
#   BUNDLES_DIR    folder with the downloaded bundles, given to
#                  extract_cozy_kitchen.py as --bundles-dir               (default: data/bundles)
#   BUILD_ARGS     extra arguments for build_image_bundles.py
#   DOWNLOAD_ARGS  extra arguments for download_bundles.py
#   EXTRACT_ARGS   extra arguments for extract_cozy_kitchen.py
#
# BUNDLES_DIR must be the folder where download_bundles.py saves the bundles. If that script has an option for
# its output folder, pass it in DOWNLOAD_ARGS, for example:
#   DOWNLOAD_ARGS="--<output option> data/bundles" ./run.sh

set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

PYTHON="${PYTHON:-python3}"
DATA_FILE="${DATA_FILE:-data/src/cozy-kitchen.data.br}"
BUNDLES_DIR="${BUNDLES_DIR:-data/bundles}"
BUILD_ARGS="${BUILD_ARGS:-}"
DOWNLOAD_ARGS="${DOWNLOAD_ARGS:-}"
EXTRACT_ARGS="${EXTRACT_ARGS:-}"

ALL_STEPS=(build download extract)

die() {
  echo "Error: $*" >&2
  exit 1
}

log() {
  printf '\n==> %s\n' "$*"
}

usage() {
  cat <<'EOF'
Usage: ./run.sh [step ...]

Steps (default: all three, in this order):
  build      build_image_bundles.py    build the image bundles from catalog.bin
  download   download_bundles.py       download the bundles
  extract    extract_cozy_kitchen.py   extract the game data to JSON files and images

Environment variables (optional):
  PYTHON, DATA_FILE, BUNDLES_DIR, BUILD_ARGS, DOWNLOAD_ARGS, EXTRACT_ARGS

Examples:
  ./run.sh
  ./run.sh extract
  EXTRACT_ARGS="--out-dir data/output" ./run.sh extract
EOF
}

# run_script <script> <extra arguments as one string> [fixed arguments ...]
run_script() {
  local script="$1" extra_string="$2"
  shift 2
  [[ -f "$script" ]] || die "$script not found (run ./run.sh from the project folder)"

  local -a extra=()
  read -r -a extra <<<"$extra_string" || true

  log "$script"
  # ${extra[@]+...} keeps an empty array working with "set -u" on the old bash that ships with macOS
  "$PYTHON" "$script" "$@" ${extra[@]+"${extra[@]}"}
}

step_build() {
  run_script build_image_bundles.py "$BUILD_ARGS"
}

step_download() {
  run_script download_bundles.py "$DOWNLOAD_ARGS"
}

step_extract() {
  [[ -f "$DATA_FILE" ]] || die "$DATA_FILE not found. Save the game's .data.br file there first (see README.md)."
  "$PYTHON" -c "import brotli, UnityPy" 2>/dev/null || die "Missing packages. Run: pip install brotli UnityPy"

  local -a args=("$DATA_FILE")
  if [[ -d "$BUNDLES_DIR" && -n "$(ls -A "$BUNDLES_DIR")" ]]; then
    args+=(--bundles-dir "$BUNDLES_DIR")
  else
    echo "Warning: $BUNDLES_DIR is missing or empty, so the recipe and menu images will be skipped." >&2
  fi
  run_script extract_cozy_kitchen.py "$EXTRACT_ARGS" "${args[@]}"
}

main() {
  local -a steps=("$@")
  if [[ ${#steps[@]} -eq 0 ]]; then
    steps=("${ALL_STEPS[@]}")
  fi

  # Check every argument before running anything, so a typo does not stop the pipeline halfway
  local step
  for step in "${steps[@]}"; do
    case "$step" in
      -h | --help)
        usage
        exit 0
        ;;
      build | download | extract) ;;
      *) die "Unknown step '$step' (use: build, download, extract)" ;;
    esac
  done

  "$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' ||
    die "Python 3.10 or newer is required (set PYTHON to another command if needed)"

  for step in "${steps[@]}"; do
    "step_$step"
  done

  echo
  echo "Done in ${SECONDS}s."
}

main "$@"
