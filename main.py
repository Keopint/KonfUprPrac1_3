#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Эмулятор командной оболочки UNIX-подобной ОС.
Этап 5: команда chmod (изменение прав доступа в памяти).
Вариант 18.
"""

import argparse
import re
import shlex
import sys
import os
import time
import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


# ============================================================
#  Утилиты для работы с правами доступа
# ============================================================

def mode_to_string(mode: int) -> str:
    """Преобразует числовой режим (0o755) в строку 'rwxr-xr-x'."""
    chars = []
    for shift in (6, 3, 0):
        bits = (mode >> shift) & 0b111
        chars.append("r" if bits & 4 else "-")
        chars.append("w" if bits & 2 else "-")
        chars.append("x" if bits & 1 else "-")
    return "".join(chars)


def parse_symbolic_mode(current: int, mode_str: str):
    """
    Применяет символьный режим (u+x, go-w, a=r, ...) к текущему числу.
    Возвращает новое число или None, если режим некорректен.
    """
    result = current

    for clause in mode_str.split(","):
        m = re.match(r"^([ugoa]*)([+\-=])([rwx]*)$", clause)
        if not m:
            return None
        who, op, perm_chars = m.groups()
        if not who:
            who = "a"

        # Определяем затрагиваемые разряды
        if "a" in who:
            shifts = [6, 3, 0]
        else:
            shifts = []
            for c in who:
                if c == "u":
                    shifts.append(6)
                elif c == "g":
                    shifts.append(3)
                elif c == "o":
                    shifts.append(0)

        # Битовая маска из r/w/x
        bits = 0
        for p in perm_chars:
            if p == "r":
                bits |= 4
            elif p == "w":
                bits |= 2
            elif p == "x":
                bits |= 1
            else:
                return None

        for shift in shifts:
            mask = 0b111 << shift
            if op == "+":
                result |= (bits << shift)
            elif op == "-":
                result &= ~(bits << shift)
            elif op == "=":
                result = (result & ~mask) | (bits << shift)

    return result & 0o777


def parse_chmod_mode(current: int, mode_str: str):
    """
    Разбирает режим chmod: числовой (755, 0644) или символьный (u+x).
    Возвращает новое число или None при ошибке.
    """
    # Восьмеричный режим: только цифры 0-7, длина 1-4
    if re.match(r"^[0-7]{1,4}$", mode_str):
        try:
            value = int(mode_str, 8)
        except ValueError:
            return None
        if value < 0 or value > 0o7777:
            return None
        return value & 0o777

    # Символьный режим
    if re.match(r"^[ugoa]*[+\-=][rwx]*(,[ugoa]*[+\-=][rwx]*)*$", mode_str):
        return parse_symbolic_mode(current, mode_str)

    return None


# ============================================================
#  VFS
# ============================================================

class VirtualFileSystem:
    """Виртуальная файловая система, загружаемая из директории на диске."""

    def __init__(self, root_path: str = None):
        self.root_path = root_path
        self.tree = {"type": "dir", "children": {}, "permissions": 0o755}
        self.current_path_components = []
        if root_path:
            self.load(root_path)

    def load(self, path: str) -> None:
        if not os.path.exists(path):
            raise FileNotFoundError(f"Путь не найден: {path}")
        if not os.path.isdir(path):
            raise NotADirectoryError(f"Не является директорией: {path}")
        self.tree = self._read_dir(path)
        self.root_path = path
        self.current_path_components = []

    def _read_dir(self, path: str) -> dict:
        node = {"type": "dir", "children": {}, "permissions": 0o755}
        try:
            st = os.stat(path)
            node["permissions"] = st.st_mode & 0o777
        except OSError:
            pass

        try:
            for entry in os.listdir(path):
                full = os.path.join(path, entry)
                if os.path.isdir(full):
                    node["children"][entry] = self._read_dir(full)
                else:
                    try:
                        with open(full, "r", encoding="utf-8") as f:
                            content = f.read()
                    except (UnicodeDecodeError, PermissionError, OSError):
                        content = ""
                    file_node = {"type": "file", "content": content,
                                 "permissions": 0o644}
                    try:
                        st = os.stat(full)
                        file_node["permissions"] = st.st_mode & 0o777
                    except OSError:
                        pass
                    node["children"][entry] = file_node
        except PermissionError:
            raise PermissionError(f"Нет доступа к директории: {path}")
        return node

    @property
    def current_path(self) -> str:
        if not self.current_path_components:
            return "/"
        return "/" + "/".join(self.current_path_components)

    def info(self) -> str:
        if self.root_path:
            return f"VFS загружена из: {self.root_path}"
        return "VFS по умолчанию (пустая)"

    def count_elements(self) -> int:
        def _count(node):
            if node["type"] == "dir":
                return 1 + sum(_count(c) for c in node["children"].values())
            return 1
        return _count(self.tree)

    def resolve(self, path: str) -> list:
        if path in ("", "~"):
            return []
        if path.startswith("/"):
            components = []
        else:
            components = list(self.current_path_components)

        for part in path.split("/"):
            if part in ("", "."):
                continue
            elif part == "..":
                if components:
                    components.pop()
            else:
                components.append(part)
        return components

    def get_node(self, components: list):
        node = self.tree
        for part in components:
            if node["type"] != "dir":
                return None
            if part not in node["children"]:
                return None
            node = node["children"][part]
        return node


# ============================================================
#  Состояние эмулятора
# ============================================================

class EmulatorState:
    def __init__(self):
        self.start_time = time.time()
        self.history = []

    def add_to_history(self, line: str) -> None:
        self.history.append(line)

    def uptime_seconds(self) -> int:
        return int(time.time() - self.start_time)


# ============================================================
#  Конфигурация
# ============================================================

class EmulatorConfig:
    def __init__(self, vfs_path: str = None, script_path: str = None):
        self.vfs_path = vfs_path
        self.script_path = script_path

    def debug_print(self) -> None:
        print("=" * 40)
        print("Конфигурация эмулятора:")
        print(f"  Путь к VFS:                {self.vfs_path or 'не указан'}")
        print(f"  Путь к стартовому скрипту: {self.script_path or 'не указан'}")
        print("=" * 40)
        print()


# ============================================================
#  Парсер
# ============================================================

def parse_command(line: str) -> list:
    try:
        return shlex.split(line) # разделение строки на элементы
    except ValueError as e:
        print(f"Ошибка разбора: {e}")
        return []


# ============================================================
#  Команды
# ============================================================

def cmd_ls(args, vfs, state):
    show_all = False
    long_format = False
    path = None

    for a in args:
        if a.startswith("--"):  # проверка префикса
            if a == "--all":
                show_all = True
            elif a == "--help":
                print("Использование: ls [-l] [-a] [путь]")
                return True
            else:
                print(f"ls: неизвестный параметр: {a}")
                return False
        elif a.startswith("-") and len(a) > 1:
            for flag in a[1:]:
                if flag == "a":
                    show_all = True
                elif flag == "l":
                    long_format = True
                else:
                    print(f"ls: неизвестный параметр: -{flag}")
                    return False
        else:
            if path is not None:
                print("ls: слишком много аргументов")
                return False
            path = a

    if path is None:
        components = list(vfs.current_path_components)
    else:
        components = vfs.resolve(path)

    node = vfs.get_node(components)
    if node is None:
        print(f"ls: невозможно получить доступ к '{path}': "
              f"Нет такого файла или каталога")
        return False

    if node["type"] == "file":
        if long_format:
            perms = mode_to_string(node.get("permissions", 0o644))
            size = len(node.get("content", "").encode("utf-8"))
            print(f"-{perms}  {size:>8}  {path if path else '.'}")
        else:
            print(path if path else ".")
        return True

    children = node["children"]
    names = sorted(children.keys())
    if not show_all:
        names = [n for n in names if not n.startswith(".")]

    if not names:
        return True

    if long_format:
        for name in names:
            child = children[name]
            perms = mode_to_string(child.get("permissions", 0o644))
            if child["type"] == "dir":
                print(f"d{perms}  {'<DIR>':>8}  {name}")
            else:
                size = len(child.get("content", "").encode("utf-8"))
                print(f"-{perms}  {size:>8}  {name}")
    else:
        print("  ".join(names))
    return True


def cmd_cd(args, vfs, state):
    if len(args) > 1:
        print("cd: слишком много аргументов")
        return False
    path = args[0] if args else "~"
    components = vfs.resolve(path)
    node = vfs.get_node(components)
    if node is None:
        print(f"cd: {path}: Нет такого файла или каталога")
        return False
    if node["type"] != "dir":
        print(f"cd: {path}: Не является каталогом")
        return False
    vfs.current_path_components = components
    return True


def cmd_chmod(args, vfs, state):
    """
    chmod [-R] РЕЖИМ ФАЙЛ...
    Поддерживает числовой (755) и символьный (u+x) режимы.
    Изменения только в памяти.
    """
    recursive = False
    positional = []
    for a in args:
        if a == "-R" or a == "--recursive":
            recursive = True
        elif a in ("-h", "--help"):
            print("Использование: chmod [-R] РЕЖИМ ФАЙЛ...")
            print("  РЕЖИМ может быть числовым (755) или символьным (u+x,go-w,a=r).")
            return True
        elif a.startswith("-") and len(a) > 1 and not a[1].isdigit():
            print(f"chmod: неизвестный параметр: {a}")
            return False
        else:
            positional.append(a)

    if len(positional) < 2:
        print("chmod: не указан режим или файл")
        print("Использование: chmod [-R] РЕЖИМ ФАЙЛ...")
        return False

    mode_str = positional[0]
    targets = positional[1:]

    if not re.match(r"^[0-7]{1,4}$", mode_str) and \
       not re.match(r"^[ugoa]*[+\-=][rwx]*(,[ugoa]*[+\-=][rwx]*)*$", mode_str):
        print(f"chmod: неверный режим: '{mode_str}'")
        return False

    overall_ok = True
    for target in targets:
        components = vfs.resolve(target)
        node = vfs.get_node(components)
        if node is None:
            print(f"chmod: невозможно получить доступ к '{target}': "
                  f"Нет такого файла или каталога")
            overall_ok = False
            continue

        # Если это директория без -R — предупреждаем, но применяем к ней самой
        if node["type"] == "dir" and not recursive:
            # Применим к самой директории (как делает GNU chmod без -R)
            pass

        def apply_mode(n):
            current = n.get("permissions", 0o644)
            new_mode = parse_chmod_mode(current, mode_str)
            if new_mode is None:
                return False
            n["permissions"] = new_mode
            return True

        def apply_recursive(n):
            ok = apply_mode(n)
            if n["type"] == "dir":
                for child in n["children"].values():
                    if not apply_recursive(child):
                        ok = False
            return ok

        if recursive:
            if not apply_recursive(node):
                print(f"chmod: неверный режим: '{mode_str}'")
                return False
        else:
            if not apply_mode(node):
                print(f"chmod: неверный режим: '{mode_str}'")
                return False

    return overall_ok


def cmd_uptime(args, vfs, state):
    if args:
        print("uptime: команда не принимает аргументов")
        return False
    now = datetime.datetime.now()
    uptime_sec = state.uptime_seconds()
    hours = uptime_sec // 3600
    minutes = (uptime_sec % 3600) // 60
    current_time = now.strftime("%H:%M:%S")
    print(f" {current_time} up {hours}:{minutes:02d}, 1 user")
    return True


def cmd_history(args, vfs, state):
    items = list(state.history)
    if items and items[-1].strip().startswith("history"):
        items = items[:-1]

    start_index = 0
    if args:
        if len(args) > 1:
            print("history: слишком много аргументов")
            return False
        try:
            n = int(args[0])
            if n < 0:
                print("history: число должно быть неотрицательным")
                return False
            start_index = max(0, len(items) - n)
        except ValueError:
            print(f"history: неверное число: '{args[0]}'")
            return False

    for i, cmd in enumerate(items[start_index:], start=start_index + 1):
        print(f"{i:5d}  {cmd}")
    return True

def cmd_echo(args: list, vfs: VirtualFileSystem, state) -> bool:
    """echo [аргументы] — печатает аргументы через пробел."""
    print(" ".join(args))
    return True


def cmd_head(args: list, vfs: VirtualFileSystem, state) -> bool:
    """head [-n N] файл — вывод первых N строк файла (по умолчанию 10)."""
    n = 10
    path = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "-n":
            if i + 1 >= len(args):
                print("head: параметр '-n' требует аргумент")
                return False
            try:
                n = int(args[i + 1])
            except ValueError:
                print(f"head: неверное число строк: '{args[i + 1]}'")
                return False
            i += 2
        elif a.startswith("-") and a[1:].isdigit():
            n = int(a[1:])
            i += 1
        elif a.startswith("-"):
            print(f"head: неизвестный параметр: {a}")
            return False
        else:
            if path is not None:
                print("head: слишком много аргументов")
                return False
            path = a
            i += 1

    if path is None:
        print("head: не указан файл")
        return False

    components = vfs.resolve(path)
    node = vfs.get_node(components)

    if node is None:
        print(f"head: невозможно открыть '{path}': Нет такого файла или каталога")
        return False
    if node["type"] != "file":
        print(f"head: ошибка чтения '{path}': Это каталог")
        return False

    content = node.get("content", "")
    lines = content.splitlines()
    for line in lines[:n]:
        print(line)
    return True


def cmd_vfs_info(args, vfs, state):
    print(vfs.info())
    print(f"Текущая директория: {vfs.current_path}")
    print(f"Всего элементов: {vfs.count_elements()}")
    return True


def cmd_help(args, vfs, state):
    print("Доступные команды:")
    print("  ls [-l] [-a] [путь]         — список содержимого директории")
    print("  cd [путь]                   — смена текущей директории")
    print("  chmod [-R] РЕЖИМ ФАЙЛ...    — изменение прав доступа (в памяти)")
    print("  uptime                      — время работы эмулятора")
    print("  history [N]                 — история команд")
    print("  vfs-info                    — информация о VFS")
    print("  help                        — эта справка")
    print("  head [-n N] файл            — вывод первых N строк файла")
    print("  echo [аргументы]            — вывод аргументов")
    print("  exit                        — выход из эмулятора")
    return True


# ============================================================
#  Диспетчер команд
# ============================================================

COMMANDS = {
    "ls": cmd_ls,
    "cd": cmd_cd,
    "chmod": cmd_chmod,
    "uptime": cmd_uptime,
    "history": cmd_history,
    "vfs-info": cmd_vfs_info,
    "help": cmd_help,
    "head": cmd_head,
    "echo": cmd_echo
}


def execute_command(command, args, vfs, state):
    if command == "exit":
        return True
    if command in COMMANDS:
        return COMMANDS[command](args, vfs, state)
    print(f"vfs: команда не найдена: {command}")
    return False


# ============================================================
#  Скрипт и REPL
# ============================================================

def get_prompt(vfs):
    return f"vfs:{vfs.current_path}> "


def run_script(script_path, vfs, state):
    if not os.path.isfile(script_path):
        print(f"Ошибка: стартовый скрипт не найден: {script_path}")
        sys.exit(1)

    print(f"Выполнение стартового скрипта: {script_path}\n")

    with open(script_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.rstrip("\n")
            if not line.strip() or line.strip().startswith("#"):
                continue
            print(f"{get_prompt(vfs)}{line}")
            state.add_to_history(line)
            parts = parse_command(line)
            if not parts:
                print(f"Ошибка в строке {line_num}: пустая команда")
            command = parts[0]
            args = parts[1:]
            if command == "exit":
                print("Выход из эмулятора.")
                sys.exit(0)
            if not execute_command(command, args, vfs, state):
                print(f"\nОшибка в строке {line_num}.")

    print("\nСтартовый скрипт успешно выполнен.")


def repl(vfs, state):
    print(f"Добро пожаловать в эмулятор оболочки. {vfs.info()}")
    print("Введите 'help' для списка команд, 'exit' для выхода.\n")

    while True:
        try:
            line = input(get_prompt(vfs))
        except (EOFError, KeyboardInterrupt):
            print("\nВыход.")
            break

        if not line.strip():
            continue

        state.add_to_history(line)

        parts = parse_command(line)
        if not parts:
            continue

        command = parts[0]
        args = parts[1:]

        if command == "exit":
            print("Выход из эмулятора.")
            break

        execute_command(command, args, vfs, state)


# ============================================================
#  Точка входа
# ============================================================

def main():
    parser = argparse.ArgumentParser(
        description="Эмулятор командной оболочки UNIX-подобной ОС (Вариант 18)"
    )
    parser.add_argument("--vfs", type=str, default="./vfs_samples",
                        help="Путь к директории с VFS")
    parser.add_argument("--script", type=str, default=None,
                        help="Путь к стартовому скрипту")
    args = parser.parse_args()

    config = EmulatorConfig(vfs_path=args.vfs, script_path=args.script)
    config.debug_print()

    vfs = VirtualFileSystem()
    if args.vfs:
        try:
            vfs.load(args.vfs)
            print(f"VFS успешно загружена: {args.vfs}")
        except Exception as e:
            print(f"Ошибка загрузки VFS: {e}")
            sys.exit(1)
    else:
        print("VFS не указана, используется пустая по умолчанию.")

    state = EmulatorState()

    if args.script:
        run_script(args.script, vfs, state)

    repl(vfs, state)


if __name__ == "__main__":
    main()