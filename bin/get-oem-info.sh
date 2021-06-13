#!/bin/bash
set -e

oem=""
platform=""
usage() {
cat << EOF
usage: $0 options

    -h|--help print this message
    --oem-codename
    --platform-codename
    --get-platform-id
EOF
exit 1
}

prepare() {
    oem="$(grep -q sutton <(ubuntu-report show | grep DCD) && echo sutton)" ||\
    oem="$(grep -q stella <(ubuntu-report show | grep DCD) && echo stella)" ||\
    oem="$(grep -q somerville <(ubuntu-report show | grep DCD) && echo somerville)" ||\
    { >&2 echo "[ERROR][CODE]got an empty OEM codename in ${FUNCNAME[0]}"; }
    case "$oem" in
        "somerville")
            for pkg in $(dpkg-query -W -f='${Package}\n'  "oem-$oem*-meta"); do
                _code_name=$(echo "${pkg}" | awk -F"-" '{print $3}')
                if [ "$_code_name" == "factory" ] ||
                    [ "$_code_name" == "meta" ]; then
                    continue
                fi
                platform="$(echo "$pkg" | cut -d'-' -f3 )"
            done
            ;;
        "sutton"|"stella")
            for pkg in $(dpkg-query -W -f='${Package}\n'  "oem-$oem.*-meta"); do
                _code_name=$(echo "${pkg}" | awk -F"-" '{print $3}')
                if [ "$_code_name" == "factory" ] ||
                    [ "$_code_name" == "meta" ]; then
                    continue
                fi
                oem="$(echo "$pkg" | cut -d'-' -f2 )"
                platform="$(echo "$pkg" | cut -d'-' -f3 )"
            done
            ;;
        *)
            >&2 echo "[ERROR][CODE]we should not be here in ${FUNCNAME[0]} : ${LINENO}"
            ;;
    esac
}

get_platform_id() {
    vendor="$(cat < /sys/class/dmi/id/sys_vendor)"

    case "${vendor}" in
        'Dell Inc.'|'HP')
            platform_id="$(lspci -nnv -d ::0x0c05 | grep "Subsystem" | awk -F"[][]" '{print $2}' | cut -d ':' -f2)"
            ;;
       'LENOVO')
            platform_id="$(cat < /sys/class/dmi/id/bios_version | cut -c 1-3)"
            ;;
        *)
            platform_id="Unknown vendor"
            ;;
    esac

    echo "${platform_id}"
}

main() {
    while [ $# -gt 0 ]
    do
        case "$1" in
            -h | --help)
                usage 0
                exit 0
                ;;
            --oem-codename)
                [ -n "$oem" ] || prepare
                echo "$oem"
                ;;
            --platform-codename)
                [ -n "$platform" ] || prepare
                echo "$platform"
                ;;
            --get-platform-id)
                get_platform_id
                ;;
            *)
            usage
           esac
           shift
    done
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    main "$@"
fi
