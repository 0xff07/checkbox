#!/bin/bash

PARA=$1

help()
{
    echo "Execute the script directly by running"
    echo "./get-tp-fw-ver.sh"
}

case $PARA in
-h)
    help
    exit 1
    ;;
*)
    ;;
esac

nodes=$(ls /sys/bus/i2c/drivers/i2c_hid)

for node in $nodes
do
    if [ "${node:0:3}" = "i2c" ]; then
        device="$node"
    fi
done

tp_path=$(udevadm info /sys/bus/i2c/devices/"$device" | grep "P:" | cut -d " " -f2)
sub=$(echo "$tp_path" | sed -E 's/\/i2c-[A-Z].*//')
bus=$(basename "$sub")
id=$(echo "$bus" | sed -E 's/i2c-//')
hid_desc=$(sudo i2ctransfer -f -y "$id" w2@0x2c 0x20 0x00 r26)

major=$(echo "$hid_desc" | cut -d " " -f26)
minor=$(echo "$hid_desc" | cut -d " " -f25)
major_hex=$(echo "$major" | sed -E 's/0x0?//')
minor_hex=$(echo "$minor" | sed -E 's/0x//')
version="$major_hex.$minor_hex"

echo "major: $major, minor: $minor, version: $version"
