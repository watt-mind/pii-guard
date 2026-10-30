"""Where a placeholder sits in a shell command inside JSON tool-call ``arguments`` (LAB-1483).

A restored value is byte-exact by default. In one case the gateway knows the quoting around a
placeholder for sure: the string value of a top-level ``command``/``cmd`` key of the arguments
(or the script after ``-c``/``-lc`` in a ``command`` array), read by a small shell lexer.
There, a value restored

- inside a single-quoted string gets ``'`` written as ``'\\''``;
- inside the single-quoted script of a ``sed`` command, in an ``s`` replacement, also gets
  ``\\``, ``&``, the delimiter and a newline backslashed (and in an ``s`` pattern, a delimiter
  that :func:`~pii_guard.gateway.restore.regex_literal` leaves as is);
- inside a double-quoted string gets ``$``, backtick, ``"`` and ``\\`` backslashed, so command
  and parameter substitution cannot run and the value arrives literal (a newline is already
  literal inside double quotes, so it stays as is) (LAB-1564);
- unquoted gets every shell metacharacter and whitespace backslash-escaped, so it stays one
  literal word (a newline goes in as a single-quoted segment, since backslash-newline is a
  line continuation) (LAB-1564).

Anything the lexer does not model (``$'...'``, heredocs, comments, command substitution in
double quotes, a sed bracket expression or another sed command) makes the rest of that string
unknown, so values there stay byte-exact.

:class:`ArgumentsContext` reads the raw JSON text in order, in as many pieces as it arrives, so
a streamed restore escapes exactly as the whole one does. :class:`ShellText` is the same lexer
over a raw (already decoded) command string, for freeform tool input.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["BYTE_EXACT", "ArgumentsContext", "ShellContext", "ShellText", "shell_escape"]

#: Top-level argument keys whose string value is a shell command.
COMMAND_KEYS = frozenset({"command", "cmd"})
#: In a ``command`` array, the element after one of these is a script (``bash -lc "..."``).
_SCRIPT_FLAG_RE = re.compile(r"-[a-z]*c")
_SED_NAMES = frozenset({"sed", "gsed"})
#: sed commands without an argument (so ``1d;s/a/b/`` reads on).
_SED_BARE = frozenset("dpgGhHxnNDP=")
_SED_FLAGS = frozenset("gpiImMe0123456789")
#: Delimiters ``regex_literal`` already makes literal (backslashed or bracketed).
_REGEX_SAFE = frozenset("\\.*[]^$/+?(){}|@")


@dataclass(frozen=True)
class ShellContext:
    """Quoting at a placeholder. ``sed_replacement``/``sed_pattern``: the ``s`` delimiter."""

    single_quoted: bool = False
    sed_replacement: str | None = None
    sed_pattern: str | None = None
    double_quoted: bool = False
    unquoted: bool = False


BYTE_EXACT = ShellContext()

#: Characters a shell reads as themselves in an unquoted word (as in ``shlex.quote``).
_UNQUOTED_SAFE = frozenset(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_@%+=:,./-"
)
#: Characters a shell still acts on inside double quotes.
_DOUBLE_ACTIVE = frozenset('$`"\\')


def shell_escape(value: str, context: ShellContext, *, regex: bool = False) -> str:
    """``value`` as it must be written at ``context`` to mean itself.

    ``regex``: ``value`` is already a regex literal (an escaped placeholder in a pattern).
    Security (LAB-1564): in double-quoted and unquoted command contexts the escaping below is
    what keeps a restored value inert — a value holding ``$(...)``, backticks, ``;`` or a space
    must arrive as literal argument text, never as shell syntax.
    """
    if context.double_quoted:
        # A newline needs no escape: inside double quotes it is literal, and backslash-newline
        # would be a line continuation that drops it.
        return "".join("\\" + char if char in _DOUBLE_ACTIVE else char for char in value)
    if context.unquoted:
        return "".join(
            "'\n'" if char == "\n" else char if char in _UNQUOTED_SAFE else "\\" + char
            for char in value
        )
    if not context.single_quoted:
        return value
    if context.sed_replacement is not None and not regex:
        delimiter = context.sed_replacement
        value = "".join(
            "\\" + char if char in ("\\", "&", "\n", delimiter) else char for char in value
        )
    elif context.sed_pattern is not None and regex and context.sed_pattern not in _REGEX_SAFE:
        value = value.replace(context.sed_pattern, "\\" + context.sed_pattern)
    return value.replace("'", "'\\''")


class _Sed:
    """The script of one single-quoted ``sed`` word, read character by character."""

    def __init__(self) -> None:
        self.state = "start"
        self.delimiter = ""
        self.escape = False

    def context(self) -> ShellContext:
        if self.state == "replacement" and not self.escape:
            return ShellContext(True, sed_replacement=self.delimiter)
        if self.state == "pattern" and not self.escape:
            return ShellContext(True, sed_pattern=self.delimiter)
        return ShellContext(True)

    def feed(self, char: str) -> None:
        state = self.state
        if state == "unknown":
            return
        if state in ("pattern", "replacement", "address"):
            if self.escape:
                self.escape = False
            elif char == "\\":
                self.escape = True
            elif char == self.delimiter:
                self.state = {"pattern": "replacement", "replacement": "flags"}.get(state, "start")
            elif char == "\n" or (char == "[" and state != "replacement"):
                self.state = "unknown"
            return
        if state == "delimiter":
            if char.isalnum() or char.isspace() or char in "\\[":
                self.state = "unknown"
            else:
                self.delimiter, self.state = char, "pattern"
            return
        if state == "flags":
            if char in _SED_FLAGS:
                return
            state = self.state = "start"
        if state == "start":
            if char.isspace() or char in ";{}" or char.isdigit() or char in "$,!":
                return
            if char == "/":
                self.delimiter, self.state = "/", "address"
            elif char == "s":
                self.state = "delimiter"
            elif char in _SED_BARE:
                return
            else:
                self.state = "unknown"


class _Shell:
    """Quoting state of one shell command string, read character by character."""

    def __init__(self) -> None:
        self.mode = "normal"  # normal | single | double | unknown
        self.escape = False
        self.previous = ""
        self.word = ""  # the current word's text outside quotes
        self.in_word = False
        self.word_quoted = False  # it had a quoted part
        self.word_content = False  # it had any character but the quotes
        self.command: str | None = None  # first word of the simple command
        self.sed_next_script = False  # after -e
        self.sed_script_seen = False
        self.sed: _Sed | None = None

    def context(self) -> ShellContext:
        if self.mode == "single":
            return self.sed.context() if self.sed is not None else ShellContext(True)
        if self.mode == "double":
            return ShellContext(double_quoted=True)
        if self.mode == "normal":
            return ShellContext(unquoted=True)
        return BYTE_EXACT

    def feed(self, char: str) -> None:
        mode = self.mode
        if mode == "unknown":
            return
        if mode == "single":
            if char == "'":
                self.mode, self.sed = "normal", None
            else:
                self.word_content = True
                if self.sed is not None:
                    self.sed.feed(char)
        elif mode == "double":
            self._double(char)
        else:
            self._normal(char)
        self.previous = char

    def _double(self, char: str) -> None:
        if char != '"' or self.escape:
            self.word_content = True
        if self.escape:
            self.escape = False
        elif char == "\\":
            self.escape = True
        elif char == '"':
            self.mode = "normal"
        elif char == "`" or (char == "(" and self.previous == "$"):
            self.mode = "unknown"

    def _normal(self, char: str) -> None:
        if self.escape:
            self.escape, self.word_content = False, True
            self.word += char
            return
        if char == "\\":
            self.escape, self.in_word = True, True
        elif char == "'":
            if self.previous == "$":
                self.mode = "unknown"
                return
            if self._sed_script_starts():
                self.sed = _Sed()
            self.mode, self.in_word, self.word_quoted = "single", True, True
        elif char == '"':
            self.mode, self.in_word, self.word_quoted = "double", True, True
        elif char == "#" and not self.in_word:
            self.mode = "unknown"
        elif char == "<" and self.previous == "<":
            self.mode = "unknown"  # heredoc (or a here-string): not modeled
        elif char.isspace() and char != "\n":
            self._end_word()
        elif char in "\n;|&()`<>":
            self._end_word()
            if char not in "<>":
                self.command, self.sed_next_script, self.sed_script_seen = None, False, False
        else:
            self.word += char
            self.in_word = self.word_content = True

    def _sed_script_starts(self) -> bool:
        return (
            not self.in_word
            and self.command in _SED_NAMES
            and (self.sed_next_script or not self.sed_script_seen)
        )

    def _end_word(self) -> None:
        if not self.in_word:
            return
        word, quoted, content = self.word, self.word_quoted, self.word_content
        self.word, self.in_word, self.word_quoted, self.word_content = "", False, False, False
        if self.command is None:
            if "=" not in word or quoted:  # VAR=value before the command is skipped
                self.command = word.rsplit("/", 1)[-1]
            return
        if self.command not in _SED_NAMES:
            return
        if self.sed_next_script:
            self.sed_next_script, self.sed_script_seen = False, True
        elif word in ("-e", "--expression"):
            self.sed_next_script = True
        elif word in ("-f", "--file") or word.startswith("--file="):
            self.sed_script_seen = True
        elif word.startswith("-") or not content:
            return  # an option, or an empty '' (BSD ``sed -i ''``)
        else:
            self.sed_script_seen = True


class ShellText:
    """The shell lexer over one raw command string (freeform tool input, already decoded)."""

    def __init__(self) -> None:
        self._shell = _Shell()

    def context(self) -> ShellContext:
        return self._shell.context()

    def feed(self, text: str) -> None:
        for char in text:
            self._shell.feed(char)


class ArgumentsContext:
    """Reads raw JSON ``arguments`` text in order and tells the shell context at its end."""

    def __init__(self) -> None:
        self._broken = False
        self._stack: list[str] = []  # "o" (object) or "a" (array)
        self._expect_key = False
        self._key: str | None = None  # the top-level key whose value is being read
        self._in_string = False
        self._string_is_key = False
        self._fresh = False  # in a string, nothing of it read yet
        self._escape = False
        self._unicode = ""
        self._buffer = ""  # decoded text of a short string (a key or an array element)
        self._previous_element = ""
        self._shell: _Shell | None = None

    def context(self) -> ShellContext:
        if self._broken or self._shell is None or not self._in_string:
            return BYTE_EXACT
        return self._shell.context()

    @property
    def at_value_start(self) -> bool:
        """The last character read opened a string that is a value, not an object key."""
        return not self._broken and self._in_string and self._fresh and not self._string_is_key

    def feed(self, text: str) -> None:
        for char in text:
            if self._broken:
                return
            if self._in_string:
                self._string_char(char)
            else:
                self._structure(char)

    def _string_char(self, char: str) -> None:
        self._fresh = False
        if self._unicode:
            self._unicode += char
            if len(self._unicode) == 5:
                try:
                    code = int(self._unicode[1:], 16)
                except ValueError:
                    self._broken = True
                    return
                self._unicode = ""
                self._decoded(chr(code) if not 0xD800 <= code <= 0xDFFF else "x")
            return
        if self._escape:
            self._escape = False
            if char == "u":
                self._unicode = "u"
                return
            decoded = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}.get(char, char)
            self._decoded(decoded)
            return
        if char == "\\":
            self._escape = True
        elif char == '"':
            self._end_string()
        else:
            self._decoded(char)

    def _decoded(self, char: str) -> None:
        if self._shell is not None:
            self._shell.feed(char)
        elif len(self._buffer) < 64:
            self._buffer += char

    def _start_string(self) -> None:
        self._in_string, self._buffer, self._fresh = True, "", True
        self._string_is_key = bool(self._stack) and self._stack[-1] == "o" and self._expect_key
        if self._string_is_key:
            return
        depth = len(self._stack)
        if self._key in COMMAND_KEYS and (
            (depth == 1 and self._stack == ["o"])
            or (
                depth == 2
                and self._stack == ["o", "a"]
                and _SCRIPT_FLAG_RE.fullmatch(self._previous_element)
            )
        ):
            self._shell = _Shell()

    def _end_string(self) -> None:
        self._in_string, self._shell = False, None
        if self._string_is_key:
            if len(self._stack) == 1:
                self._key = self._buffer
            self._expect_key = False
        elif self._stack and self._stack[-1] == "a":
            self._previous_element = self._buffer

    def _structure(self, char: str) -> None:
        if char == '"':
            self._start_string()
        elif char in "{[":
            self._stack.append("o" if char == "{" else "a")
            self._expect_key = char == "{"
            self._previous_element = ""
        elif char in "}]":
            if not self._stack:
                self._broken = True
                return
            self._stack.pop()
            self._expect_key = False
        elif char == "," and self._stack and self._stack[-1] == "o":
            self._expect_key = True
            if len(self._stack) == 1:
                self._key = None
