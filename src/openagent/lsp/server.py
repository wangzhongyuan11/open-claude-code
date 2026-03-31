from __future__ import annotations

from dataclasses import dataclass, field
import os
from pathlib import Path
import shutil
from typing import Callable


RootResolver = Callable[[Path], Path | None]


def _workspace_root(workspace: Path) -> Path:
    return workspace


@dataclass(frozen=True, slots=True)
class LspServerInfo:
    id: str
    command: list[str]
    extensions: tuple[str, ...]
    root: RootResolver = _workspace_root
    language_ids: dict[str, str] = field(default_factory=dict)

    def resolve_command(self) -> list[str] | None:
        if not self.command:
            return None
        binary = self.command[0]
        if Path(binary).is_absolute():
            return self.command if Path(binary).exists() else None
        resolved = shutil.which(binary)
        if resolved is None:
            nvm_bin = os.getenv("NVM_BIN")
            if nvm_bin:
                candidate = Path(nvm_bin) / binary
                if candidate.exists():
                    resolved = str(candidate)
        if resolved is None:
            home = Path.home() / ".nvm" / "versions" / "node"
            if home.exists():
                matches = sorted(home.glob(f"*/bin/{binary}"))
                if matches:
                    resolved = str(matches[-1])
        if resolved is None:
            return None
        return [resolved, *self.command[1:]]

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.extensions

    def language_id_for(self, path: Path) -> str:
        return self.language_ids.get(path.suffix.lower(), path.suffix.lower().lstrip(".") or "plaintext")


DEFAULT_SERVERS: tuple[LspServerInfo, ...] = (
    LspServerInfo(
        id="pyright",
        command=["pyright-langserver", "--stdio"],
        extensions=(".py",),
        language_ids={".py": "python"},
    ),
    LspServerInfo(
        id="typescript",
        command=["typescript-language-server", "--stdio"],
        extensions=(".ts", ".tsx", ".js", ".jsx", ".mts", ".cts", ".mjs", ".cjs"),
        language_ids={
            ".ts": "typescript",
            ".tsx": "typescriptreact",
            ".js": "javascript",
            ".jsx": "javascriptreact",
            ".mts": "typescript",
            ".cts": "typescript",
            ".mjs": "javascript",
            ".cjs": "javascript",
        },
    ),
)
