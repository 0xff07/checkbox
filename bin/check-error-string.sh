#!/bin/bash

error_string="$1"

while read -r line
do
    bootidx=$(echo "$line" | cut -d " " -f1)
    if journalctl -k -b "$bootidx" | grep -q "$error_string"; then
        echo "Boot $line, found \"$error_string\""
        exit 1
    fi
done < <(journalctl --list-boots)

echo "No $error_string"
