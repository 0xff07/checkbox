#!/usr/bin/env bats

# execute this test file by `bats test/test-check-nvidia.bats`
BIN_FOLDER="bin"

function setup() {
    # shellcheck source=/dev/null
    source "$BIN_FOLDER"/check-nvidia.sh
}

@test "recognize current mode" {
    set -e
    function prime-select() {
        echo "$current_mode"
    }
    function check_ondemand_mode() {
        return "$on_demand_mode"
    }
    function check_nvidia_mode() {
        return "$nvidia_mode"
    }
    function check_intel_mode() {
        return "$intel_mode"
    }
    on_demand_mode=1
    nvidia_mode=2
    intel_mode=3

    echo "testing recognizing on-demand mode"
    current_mode="on-demand"
    run check_behavior_of_current_mode
    [ "$status" -eq $on_demand_mode ]
    echo "testing recognizing nvidia mode"
    current_mode="nvidia"
    run check_behavior_of_current_mode
    [ "$status" -eq $nvidia_mode ]
    echo "testing recognizing intel mode"
    current_mode="intel"
    run check_behavior_of_current_mode
    [ "$status" -eq $intel_mode ]

}

@test "Check renderer when OpenGL renderer string: Mesa Intel(R)" {
    set -e
    glxinfo_string="OpenGL renderer string: Mesa Intel(R)"
    function glxinfo() {
        echo "$glxinfo_string"
    }
    echo run check_renderer intel
    run check_renderer intel
    [ "$status" -eq 0 ]

    echo run check_renderer on-demand-default
    run check_renderer on-demand-default
    [ "$status" -eq 0 ]

    echo run check_renderer on-demand-nvidia
    run check_renderer on-demand-nvidia
    [ "$status" -eq 1 ]
    echo run check_renderer on-nvidia
    run check_renderer nvidia
    [ "$status" -eq 1 ]
}

@test "Check renderer when OpenGL renderer string: GeForce GTX" {
    set -e
    glxinfo_string="OpenGL renderer string: GeForce GTX"
    function glxinfo() {
        echo "$glxinfo_string"
    }
    echo run check_renderer intel
    run check_renderer intel
    [ "$status" -eq 1 ]

    echo run check_renderer on-demand-default
    run check_renderer on-demand-default
    [ "$status" -eq 1 ]

    echo run check_renderer on-demand-nvidia
    run check_renderer on-demand-nvidia
    [ "$status" -eq 0 ]
    echo run check_renderer on-nvidia
    run check_renderer nvidia
    [ "$status" -eq 0 ]
}
@test "Check renderer when OpenGL renderer string: llvmpipe (LLVM 10.0.0, 256 bits)" {
    set -e
    glxinfo_string="OpenGL renderer string: llvmpipe (LLVM 10.0.0, 256 bits)"
    function glxinfo() {
        echo "$glxinfo_string"
    }
    echo run check_renderer intel
    run check_renderer intel
    [ "$status" -eq 1 ]

    echo run check_renderer on-demand-default
    run check_renderer on-demand-default
    [ "$status" -eq 1 ]

    echo run check_renderer on-demand-nvidia
    run check_renderer on-demand-nvidia
    [ "$status" -eq 1 ]
    echo run check_renderer on-nvidia
    run check_renderer nvidia
    [ "$status" -eq 1 ]
}

@test "Check Nvidia sleep in on-demand and Intel mode" {
    set -e
    OUTPUT_FOLDER="$(mktemp -d)"

    function get_powertop_report() {
        rm -f "$OUTPUT_FOLDER"/"$1"
        echo "$powertop_str1" > "$OUTPUT_FOLDER"/"$1"
        echo "$powertop_str2" >> "$OUTPUT_FOLDER"/"$1"
    }

    # the string will show by checkbox process
    powertop_str1="100.0%;checkbox nvidia"

    echo "When Nvidia not sleep deep to 0%, it should be failed."
    powertop_str2="30.0%;PCI Device: NVIDIA"
    run check_nvidia_sleep ondemand_
    run check_nvidia_sleep intel_
    [ "$status" -eq 1 ]
    echo "When Nvidia sleep deep to 0%, it should be pass."
    powertop_str2="0.0%;PCI Device: NVIDIA"
    run check_nvidia_sleep ondemand_
    run check_nvidia_sleep intel_
    [ "$status" -eq 0 ]
}

