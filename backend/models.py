import ipaddress
import re
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, model_validator


def valid_host(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return bool(len(value) <= 253 and re.fullmatch(
            r"(?=.{1,253}\Z)(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)*"
            r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.?", value))


class Target(BaseModel):
    id: int | None = None
    name: str = Field(min_length=1, max_length=80)
    kind: Literal["ping", "dns", "http"]
    address: str = Field(min_length=1, max_length=2048)
    enabled: bool = True

    @model_validator(mode="after")
    def validate_address(self):
        self.name = self.name.strip()
        self.address = self.address.strip()
        if not self.name:
            raise ValueError("Nome vazio")
        if self.kind == "http":
            try:
                url = urlsplit(self.address)
                if url.scheme not in ("http", "https") or not url.hostname or url.username or url.password:
                    raise ValueError()
                if not valid_host(url.hostname):
                    raise ValueError()
                _ = url.port
            except ValueError:
                raise ValueError("Use uma URL HTTP/HTTPS válida sem credenciais")
        elif not valid_host(self.address):
            raise ValueError("Use um endereço IP ou hostname válido")
        return self


class Settings(BaseModel):
    interval_seconds: int = Field(default=30, ge=5, le=3600)
    timeout_seconds: float = Field(default=2, ge=0.2, le=10)
    ping_count: int = Field(default=3, ge=1, le=10)
    retention_days: int = Field(default=30, ge=1, le=365)


class Configuration(BaseModel):
    settings: Settings
    targets: list[Target] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def unique_targets(self):
        ids = [t.id for t in self.targets if t.id is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("IDs duplicados")
        pairs = [(t.kind, t.address.lower()) for t in self.targets]
        if len(pairs) != len(set(pairs)):
            raise ValueError("Destinos duplicados")
        return self
