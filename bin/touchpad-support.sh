#!/bin/bash

export LANG=C
set -euo pipefail

print_help()
{
    cat <<ENDLINE
$0 [OPTIONS]

OPTIONS:
    -p | --pressure        Check if touchpad support pressure event.
    -h | --help            Print the help manual.
ENDLINE
}

touchpad_pressure_support()
{
    touchpad=0
    while read -r line;
    do
        if [ -z "$line" ]; then
            touchpad=0
        fi

        if echo "$line" | grep -q "Touchpad"; then
            name="${line:9:-1}"
            touchpad=1
        fi

        if [ $touchpad -eq 1 ]; then
            if [ "${line:3:3}" = "ABS" ]; then
                abs_caps="${line:7:15}"
                abs_caps_hex=$((16#"$abs_caps"))
                pressure_bit=$((abs_caps_hex >> 24))
                mt_pressure_bit=$((abs_caps_hex >> 58))
                support=$((pressure_bit & mt_pressure_bit & 1))

                if [ $support -eq 1 ]; then
                    echo "$name pressure bit and mt pressure bit are set"
                    exit 1
                else
                    echo "$name has no pressure capability"
                    exit 0
                fi
            fi
        fi
    done <"/proc/bus/input/devices"

    echo "Touchpad not found."
    exit 1
}

OPTS="$(getopt -o ph --long pressure,help -n 'touchpad-support.sh' -- "$@")"
eval set -- "${OPTS}"
while :; do
    case "$1" in
        ('-p'|'--pressure')
            touchpad_pressure_support
            exit ;;
        ('-h'|'--help')
            print_help
            exit ;;
        (*)
            print_help
            exit ;;
    esac
done
