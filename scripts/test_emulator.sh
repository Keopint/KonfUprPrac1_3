#!/bin/bash
# Тестирование основных команд эмулятора (этап 4, вариант 18).

export LANG=C.UTF-8
export LC_ALL=C.UTF-8
export PYTHONIOENCODING=utf-8

run_emulator() {
    local vfs_path="$1"
    local description="$2"
    echo "=== $description ==="
    if command -v winpty >/dev/null 2>&1; then
        winpty python3 main.py --vfs "$vfs_path" --script start_scripts/stage4_commands.txt
    else
        python3 main.py --vfs "$vfs_path" --script start_scripts/stage4_commands.txt
    fi
    echo ""
}

run_emulator ./vfs_samples/vfs_minimal "1. Минимальная VFS"
run_emulator ./vfs_samples/vfs_files   "2. VFS с несколькими файлами"
run_emulator ./vfs_samples/vfs_deep    "3. VFS с глубокой вложенностью"

echo "=== 4. Обработка ошибки: несуществующий путь ==="
if command -v winpty >/dev/null 2>&1; then
    winpty python3 main.py --vfs ./nonexistent_path --script start_scripts/stage4_commands.txt
else
    python3 main.py --vfs ./nonexistent_path --script start_scripts/stage4_commands.txt
fi