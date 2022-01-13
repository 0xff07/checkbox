#!/bin/bash

set -e

result=0

# Available driver check in each GPU
for gpu in $(lspci -n -d ::0x0300| awk '{print $1}') \
           $(lspci -n -d ::0x0302| awk '{print $1}'); do
    vendor=$(cat /sys/bus/pci/devices/"${gpu}"/vendor)
    device=$(cat /sys/bus/pci/devices/"${gpu}"/device)
    if [ ! -d "/sys/bus/pci/devices/${gpu}/driver" ]; then
        echo "E: Your GPU ${gpu} (${vendor}:${device}) haven't driver."
        sudo lspci -nnvk -s "$gpu"
        result=255
    else
        driver=$(basename "$(readlink /sys/bus/pci/devices/"${gpu}"/driver)")
        echo "Your GPU ${gpu} is using ${driver}."
    fi
done

# Nvidia driver check
for pkg in $(dpkg-query -W -f='${Package}\n' "nvidia-driver-???"); do
    if [ "$(dpkg-query -W -f='${Status}' "$pkg")" != "install ok installed" ]; then
        continue
    fi
    echo "${pkg} is installed:"
    SUPPORT=$(apt show "$pkg" 2>/dev/null| grep "^Support:"| awk '{print $2}')
    if [ "$SUPPORT" != "LTSB" ]; then
        echo "E: Your $pkg is not LTS version, please check."
        apt-cache madison "$pkg"
        result=255
    else
        echo "Your $pkg is LTS version."
    fi

    VERSION=${pkg##*-}
    if [ "$(dpkg-query -W -f='${Status}\n' "linux-modules-nvidia-${VERSION}-$(uname -r)")" \
            != "install ok installed" ]; then
        echo "E: Your $pkg is not pre-signed driver."
        echo "E: Expecting linux-modules-nvidia-${VERSION}-$(uname -r)."
        result=255
    else
        echo "Your $pkg is pre-signed linux-modules-nvidia-${VERSION}-$(uname -r)."
    fi

    if [ "$(dpkg-query -W -f='${Status}\n' "nvidia-dkms-${VERSION}")" \
            = "install ok installed" ]; then
        echo "E: Your $pkg shouldn't use dkms version but pre-signed."
        echo "E: Expecting linux-modules-nvidia-${VERSION}-$(uname -r)."
        result=255
    fi
done

exit $result
