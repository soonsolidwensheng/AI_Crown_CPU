#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <native-library> <output-directory>" >&2
    exit 2
fi

if [[ ${EUID} -eq 0 ]]; then
    echo "Do not run copylibs.sh with sudo. Use the normal build user so " \
         "crown/libs remains writable by subsequent CMake builds." >&2
    exit 2
fi

library_path="$1"
output_directory="$2"

if [[ ! -f "$library_path" ]]; then
    echo "Native library does not exist: $library_path" >&2
    exit 2
fi

mkdir -p "$output_directory"

if [[ ! -w "$output_directory" ]]; then
    echo "Output directory is not writable: $output_directory" >&2
    exit 1
fi

ldd_output="$(LD_LIBRARY_PATH="$output_directory${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" \
    ldd "$library_path" 2>&1)" || {
    echo "Failed to inspect native dependencies: $library_path" >&2
    printf '%s\n' "$ldd_output" >&2
    exit 1
}

mapfile -t missing_dependencies < <(
    printf '%s\n' "$ldd_output" | awk '/not found/ { print $1 }' | sort -u)
if (( ${#missing_dependencies[@]} > 0 )); then
    echo "Unresolved native dependencies for $library_path:" >&2
    printf '  %s\n' "${missing_dependencies[@]}" >&2
    exit 1
fi

printf '%s\n' "$ldd_output" \
    | awk '/=> \/.* / { print $3 } /^\// { print $1 }' \
    | sort -u \
    | while IFS= read -r dependency; do
        [[ -f "$dependency" ]] || continue
        soname="$(readelf -d "$dependency" 2>/dev/null \
            | awk '/SONAME/ { gsub(/[][]/, "", $NF); print $NF; exit }')"
        destination_name="${soname:-$(basename "$dependency")}"
        destination_path="$output_directory/$destination_name"
        if [[ -e "$destination_path" && "$dependency" -ef "$destination_path" ]]; then
            continue
        fi
        cp -Lf -- "$dependency" "$destination_path"
    done
