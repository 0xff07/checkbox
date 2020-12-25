#!/bin/bash
OUT="$PWD"
usage() {
cat << EOF
usage: $0 options

    -h|--help print this message
    --out     The folder you for generated json file. Default is \$PWD
EOF
exit 0
}

prepare() {
# https://github.com/canonical/sec-cvescan
    for pkg in python3-apt python3-pip git jq; do
        [ "$(dpkg-query -W -f='${Status}' "$pkg")" = "install ok installed" ] || (sudo apt-get update && DEBIAN_FRONTEND=noninteractive sudo apt install -y "$pkg")
    done
    git clone https://github.com/canonical/sec-cvescan
    export PATH=$HOME/.local/bin/:$PATH
    pip3 install --user sec-cvescan/ > /dev/null
    rm -rf sec-cvescan
}
main() {
    while [ $# -gt 0 ]
    do
        case "$1" in
            -h | --help)
                usage 0
                exit 0
                ;;
            --out)
                shift
                OUT="$1";
                ;;
            *)
            usage
           esac
           shift
    done

    prepare
    get_cvescan_json  "$OUT/cvescan.json"
    parse_cvescan_json "$OUT/cvescan.json"
}

get_cvescan_json() {
    [ -n "$1" ] || exit 1
    command -v cvescan || exit 1
    cvescan --json > "$1"
}

parse_cvescan_json() {
    [ -n "$1" ] || exit 1
    command -v jq || exit 1
    if [ "$(jq -r '.summary.num_cves' < "$1")" != "0" ]; then
        echo "You have some packages that need an update for CVE."
        echo "Please check $1 for details"
        exit 1
    fi
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi

