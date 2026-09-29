"""运行配置：全部来自环境变量（ZANH_ 前缀），便于本地/演示/评测环境切换。

LLM 适配器面向 OpenAI 兼容协议；provider 预置只填 base_url/model 差异，
密钥一律走环境变量，不写入代码或配置文件。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_REPO_ROOT = Path(__file__).resolve().parents[3]  # .../zhongan-competition
_DEFAULT_WORK = str(_REPO_ROOT.parent / "work")  # 医疗数据与运行产物一律放仓库外

_PROVIDER_PRESETS = {
    "deepseek": {"base_url": "https://api.deepseek.com", "model": "deepseek-flash"},
    "zhipu": {"base_url": "https://open.bigmodel.cn/api/paas/v4", "model": "glm-4.5-flash",
              "thinking": "disabled"},
    "ollama": {"base_url": "http://127.0.0.1:11434/v1", "model": "qwen3:8b"},
    "mock": {"base_url": "", "model": "mock"},
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ZANH_", env_file=".env", extra="ignore")

    # 数据与工件目录（医疗数据一律在仓库外）
    dataset_dir: str = ""
    ocr_dir: str = ""
    work_dir: str = _DEFAULT_WORK

    # LLM
    llm_provider: str = "mock"  # deepseek | zhipu | ollama | mock
    llm_base_url: str = ""  # 显式覆盖 provider 预置
    llm_model: str = ""
    llm_api_key: str = ""
    llm_timeout_s: float = 120.0
    llm_max_retries: int = 2
    llm_temperature: float = 0.2
    # 国内 API 直连；本机系统代理（如 127.0.0.1:7897）会挂起请求，需要代理时显式配置
    llm_proxy: str = ""

    # 数据库（原型默认 SQLite；PG 仅需改 url）
    database_url: str = "sqlite:///./zanh.db"

    @property
    def llm_preset(self) -> dict:
        return _PROVIDER_PRESETS.get(self.llm_provider, {})

    def resolved_llm(self) -> tuple[str, str, str]:
        base = self.llm_base_url or self.llm_preset.get("base_url", "")
        model = self.llm_model or self.llm_preset.get("model", "")
        return base, model, self.llm_api_key

    @property
    def llm_thinking(self) -> str:
        return self.llm_preset.get("thinking", "")


@lru_cache
def get_settings() -> Settings:
    return Settings()
