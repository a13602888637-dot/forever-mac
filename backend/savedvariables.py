"""Data-only SavedVariables parser. This module never evaluates Lua/Python code."""
from __future__ import annotations

import json
import re
from pathlib import Path

from .models import Snapshot

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_DEPTH = 32
MAX_TOKENS = 100000


class ImportError(ValueError):
    pass


class LiteralParser:
    def __init__(self, text: str):
        self.text = text.lstrip("\ufeff")
        self.pos = 0
        self.tokens = 0

    def skip(self):
        while self.pos < len(self.text):
            if self.text[self.pos].isspace():
                self.pos += 1
            elif self.text.startswith("--[[", self.pos):
                end = self.text.find("]]", self.pos + 4)
                if end < 0:
                    raise ImportError("未闭合注释")
                self.pos = end + 2
            elif self.text.startswith("--", self.pos):
                end = self.text.find("\n", self.pos)
                self.pos = len(self.text) if end < 0 else end + 1
            else:
                break

    def take(self, token: str):
        self.skip()
        if not self.text.startswith(token, self.pos):
            raise ImportError(f"预期 {token}，位置 {self.pos}")
        self.pos += len(token)

    def string(self):
        quote = self.text[self.pos]
        self.pos += 1
        result = []
        escapes = {"a": "\a", "b": "\b", "f": "\f", "n": "\n", "r": "\r", "t": "\t", "v": "\v",
                   "\\": "\\", '"': '"', "'": "'"}
        while self.pos < len(self.text):
            char = self.text[self.pos]
            self.pos += 1
            if char == quote:
                return "".join(result)
            if char in "\r\n":
                raise ImportError("字符串包含未转义换行")
            if char != "\\":
                result.append(char)
                continue
            if self.pos >= len(self.text):
                break
            char = self.text[self.pos]
            self.pos += 1
            if char in escapes:
                result.append(escapes[char])
            elif char.isascii() and char.isdigit():
                digits = char
                while self.pos < len(self.text) and len(digits) < 3 and self.text[self.pos].isascii() and self.text[self.pos].isdigit():
                    digits += self.text[self.pos]
                    self.pos += 1
                if int(digits) > 255:
                    raise ImportError("非法 Lua 字符转义")
                result.append(chr(int(digits)))
            elif char == "\n":
                result.append("\n")
            elif char == "\r":
                if self.pos < len(self.text) and self.text[self.pos] == "\n":
                    self.pos += 1
                result.append("\n")
            else:
                raise ImportError("不支持的字符串转义")
        raise ImportError("未闭合字符串")

    def value(self, depth=0):
        self.skip()
        self.tokens += 1
        if depth > MAX_DEPTH or self.tokens > MAX_TOKENS:
            raise ImportError("存档结构超出限制")
        if self.pos >= len(self.text):
            raise ImportError("文件不完整，请等待 /reload 完成")
        char = self.text[self.pos]
        if char in "\"'":
            return self.string()
        if char == "{":
            self.pos += 1
            result = {}
            index = 1
            while True:
                self.skip()
                if self.pos < len(self.text) and self.text[self.pos] == "}":
                    self.pos += 1
                    return result
                if self.pos < len(self.text) and self.text[self.pos] == "[":
                    self.pos += 1
                    key = self.value(depth + 1)
                    if type(key) not in (str, int):
                        raise ImportError("表键只能为字符串或整数")
                    self.take("]")
                    self.take("=")
                else:
                    match = re.match(r"([A-Za-z_][A-Za-z_0-9]*)\s*=", self.text[self.pos:])
                    if match:
                        key = match.group(1)
                        self.pos += match.end()
                    else:
                        key = index
                        index += 1
                if key in result:
                    raise ImportError("存档包含重复表键")
                result[key] = self.value(depth + 1)
                self.skip()
                if self.pos < len(self.text) and self.text[self.pos] in ",;":
                    self.pos += 1
                elif self.pos >= len(self.text) or self.text[self.pos] != "}":
                    raise ImportError("缺少表分隔符或文件被截断")
        for token, value in (("true", True), ("false", False), ("nil", None)):
            if self.text.startswith(token, self.pos) and not re.match(r"[A-Za-z_0-9]", self.text[self.pos + len(token):self.pos + len(token) + 1]):
                self.pos += len(token)
                return value
        match = re.match(r"-?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?", self.text[self.pos:])
        if match:
            self.pos += match.end()
            raw = match.group()
            return float(raw) if any(c in raw for c in ".eE") else int(raw)
        raise ImportError(f"存档包含非字面量或不支持的语法，位置 {self.pos}")

    def parse(self):
        self.take("ForeverAICharDB")
        self.take("=")
        result = self.value()
        self.skip()
        if self.pos != len(self.text) or not isinstance(result, dict):
            raise ImportError("只允许 ForeverAICharDB 的单次表赋值")
        return result


def parse_savedvariables(text: str) -> Snapshot:
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        raise ImportError("存档超过 2 MiB")
    try:
        data = LiteralParser(text).parse()
        if type(data.get("schema_version")) is not int or data["schema_version"] != 1:
            raise ImportError("不支持的存档 schema_version")
        raw = data.get("snapshot_json")
        if not isinstance(raw, str):
            raise ImportError("没有快照，请在游戏中 /fai export 后 /reload")
        def no_duplicates(pairs):
            result = {}
            for key, value in pairs:
                if key in result:
                    raise ImportError("快照 JSON 含重复键")
                result[key] = value
            return result
        snapshot = Snapshot.model_validate(json.loads(raw, object_pairs_hook=no_duplicates))
        if snapshot.data_mode != "live":
            raise ImportError("游戏存档不接受 Mock 快照")
        return snapshot
    except (RecursionError, UnicodeError, json.JSONDecodeError) as exc:
        raise ImportError("快照编码错误或结构过深") from exc


def read_snapshot(path: Path, expected_name: str, expected_realm: str) -> Snapshot:
    if path.is_symlink() or not path.is_file() or path.name != "ForeverAI.lua":
        raise ImportError("仅接受角色目录中的 ForeverAI.lua 普通文件")
    before = path.stat()
    if before.st_size > MAX_FILE_BYTES:
        raise ImportError("存档超过 2 MiB")
    with path.open("rb") as handle:
        raw = handle.read(MAX_FILE_BYTES + 1)
    after = path.stat()
    if len(raw) > MAX_FILE_BYTES or (before.st_mtime_ns, before.st_size, before.st_ino) != (after.st_mtime_ns, after.st_size, after.st_ino):
        raise ImportError("游戏正在写入文件，请稍后重试")
    try:
        snapshot = parse_savedvariables(raw.decode("utf-8-sig"))
    except UnicodeError as exc:
        raise ImportError("存档必须为 UTF-8") from exc
    def normalize(s):
        return "".join(s.casefold().split())
    if normalize(snapshot.character.name) != normalize(expected_name) or normalize(snapshot.character.realm) != normalize(expected_realm):
        raise ImportError("快照角色身份与存档目录不一致")
    return snapshot
