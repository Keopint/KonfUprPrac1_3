import argparse
import datetime
import shlex
import sys
import os
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


# ============================================================
#  VFS
# ============================================================

class VirtualFileSystem:
    """Виртуальная файловая система, загружаемая из директории на диске."""

    def __init__(self, root_path: str = None):
        self.root_path = root_path
        self.tree = {"type": "dir", "children": {}}
        self.current_path_components = []  # список компонентов текущего пути
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
        node = {"type": "dir", "children": {}}
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
                    node["children"][entry] = {"type": "file", "content": content}
        except PermissionError:
            raise PermissionError(f"Нет доступа к директории: {path}")
        return node

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
        """Преобразует путь в список компонентов от корня."""
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
        """Возвращает узел VFS по списку компонентов или None."""
        node = self.tree
        for part in components:
            if node["type"] != "dir":
                return None
            if part not in node["children"]:
                return None
            node = node["children"][part]
        return node


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
#  Состояние эмулятора (время старта, история команд)
# ============================================================


class EmulatorState:
    """Хранит состояние сессии: время старта и историю команд."""

    def __init__(self):
        self.start_time = time.time()
        self.history = []

    def add_to_history(self, line: str) -> None:
        self.history.append(line)

    def uptime_seconds(self) -> int:
        return int(time.time() - self.start_time)


# ============================================================
#  Парсер
# ============================================================

def parse_command(line: str) -> list:
    try:
        return shlex.split(line)
    except ValueError as e:
        print(f"Ошибка разбора: {e}")
        return []


# ============================================================
#  Команды
# ============================================================

def cmd_ls(args: list, vfs: VirtualFileSystem, state: EmulatorState) -> bool:
    """ls [-l] [-a] [путь] — список содержимого директории."""
    show_all = False
    long_format = False
    path = None

    for a in args:
        if a.startswith("--"):
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
                print(f"ls: слишком много аргументов")
                return False
            path = a

    if path is None:
        components = list(vfs.current_path_components)
    else:
        components = vfs.resolve(path)

    node = vfs.get_node(components)
    if node is None:
        print(f"ls: невозможно получить доступ к '{path}': Нет такого файла или каталога")
        return False

    if node["type"] == "file":
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
            if child["type"] == "dir":
                print(f"drwxr-xr-x  {'<DIR>':>8}  {name}")
            else:
                size = len(child.get("content", "").encode("utf-8"))
                print(f"-rw-r--r--  {size:>8}  {name}")
    else:
        print("  ".join(names))
    return True


def cmd_cd(args: list, vfs: VirtualFileSystem, state: EmulatorState) -> bool:
    """cd [путь] — смена текущей директории."""
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


def cmd_echo(args: list, vfs: VirtualFileSystem, state: EmulatorState) -> bool:
    """echo [аргументы] — печатает аргументы через пробел."""
    print(" ".join(args))
    return True


def cmd_head(args: list, vfs: VirtualFileSystem, state: EmulatorState) -> bool:
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


def cmd_vfs_info(args: list, vfs: VirtualFileSystem, state: EmulatorState) -> bool:
    print(vfs.info())
    print(f"Текущая директория: {vfs.current_path}")
    print(f"Всего элементов: {vfs.count_elements()}")
    return True


def cmd_help(args: list, vfs: VirtualFileSystem, state: EmulatorState) -> bool:
    print("Доступные команды:")
    print("  ls [-l] [-a] [путь]  — список содержимого директории")
    print("  cd [путь]            — смена текущей директории")
    print("  uptime               — время работы эмулятора и load average")
    print("  history [N]          — история команд (последние N, если указано)")
    print("  vfs-info             — информация о VFS")
    print("  help                 — эта справка")
    print("  exit                 — выход из эмулятора")
    return True

def cmd_uptime(args: list, vfs: VirtualFileSystem, state: EmulatorState) -> bool:
    """uptime — показывает текущее время, время работы, число пользователей, load average."""
    if args:
        print("uptime: команда не принимает аргументов")
        return False

    now = datetime.datetime.now()
    uptime_sec = state.uptime_seconds()
    hours = uptime_sec // 3600
    minutes = (uptime_sec % 3600) // 60

    current_time = now.strftime("%H:%M:%S")
    print(f" {current_time} up {hours}:{minutes:02d}, 1 user, "
          f"load average: 0.00, 0.01, 0.05")
    return True


def cmd_history(args: list, vfs: VirtualFileSystem, state: EmulatorState) -> bool:
    """history [N] — выводит историю команд. С N — последние N команд."""
    # Исключаем саму команду history из вывода
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

# ============================================================
#  Диспетчер команд
# ============================================================

COMMANDS = {
    "ls": cmd_ls,
    "cd": cmd_cd,
    "echo": cmd_echo,
    "head": cmd_head,
    "vfs-info": cmd_vfs_info,
    "uptime": cmd_uptime,
    "history": cmd_history,
    "help": cmd_help
}


def execute_command(command: str, args: list,
                    vfs: VirtualFileSystem, state: EmulatorState) -> bool:
    if command == "exit":
        return True
    if command in COMMANDS:
        return COMMANDS[command](args, vfs, state)
    print(f"vfs: команда не найдена: {command}")
    return False


# ============================================================
#  Скрипт и REPL
# ============================================================

def get_prompt(vfs: VirtualFileSystem) -> str:
    return f"vfs:{vfs.current_path()}> "


def run_script(script_path: str, vfs: VirtualFileSystem,
               state: EmulatorState) -> None:
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
                print("Скрипт остановлен из-за ошибки.")
                sys.exit(1)
            command = parts[0]
            args = parts[1:]
            if command == "exit":
                print("Выход из эмулятора.")
                sys.exit(0)
            if not execute_command(command, args, vfs, state):
                print(f"\nСкрипт остановлен из-за ошибки в строке {line_num}.")
                sys.exit(1)

    print("\nСтартовый скрипт успешно выполнен.")


def repl(vfs: VirtualFileSystem, state: EmulatorState) -> None:
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

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Эмулятор командной оболочки UNIX-подобной ОС (Вариант 18)"
    )
    parser.add_argument("--vfs", type=str, default="./",
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