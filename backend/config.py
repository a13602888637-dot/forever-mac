from dataclasses import dataclass, field
import os
from pathlib import Path


@dataclass
class Settings:
    mode: str = "mock"
    data_dir: Path = field(default_factory=lambda: Path("data"))
    game_path: str | None = None
    model: str = "gpt-6-luna"
    api_key: str | None = field(default=None, repr=False)
    references_enabled: bool = True
    auto_sync: bool = True

    def __post_init__(self):
        if self.mode not in ("mock", "live"):
            raise ValueError("FAI_MODE 只能为 mock 或 live")
        self.data_dir = Path(self.data_dir).expanduser().resolve()
        if not self.model or len(self.model) > 100:
            raise ValueError("OPENAI_MODEL 无效")

    @classmethod
    def from_env(cls, mode=None):
        return cls(mode=mode or os.getenv("FAI_MODE", "mock"), data_dir=Path(os.getenv("FAI_DATA_DIR", "data")),
                   game_path=os.getenv("WOW_PATH") or None, model=os.getenv("OPENAI_MODEL", "gpt-6-luna"),
                   api_key=os.getenv("OPENAI_API_KEY") or None,
                   references_enabled=os.getenv("FAI_REFERENCE_ENABLED", "true").lower() == "true",
                   auto_sync=os.getenv("FAI_AUTO_SYNC", "true").lower() == "true")
