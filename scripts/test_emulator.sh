#!/bin/bash
# Тестирование основных команд эмулятора (этап 5, вариант 18).

export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export PYTHONIOENCODING=utf-8

run_emulator() {
    local vfs_path="$1"
    local description="$2"
    echo "=== $description ==="
    if command -v winpty >/dev/null 2>&1; then
        winpty python3 main.py --vfs "$vfs_path" --script start_scripts/stage5_commands.txt
    else
        python3 main.py --vfs "$vfs_path" --script start_scripts/stage5_commands.txt
    fi
    echo ""
}

run_emulator ./vfs_samples/vfs_files   "VFS с несколькими файлами и subdir"
run_emulator ./vfs_samples/vfs_minimal "Минимальная VFS"
run_emulator ./vfs_samples/vfs_deep    "VFS с глубокой вложенностью"