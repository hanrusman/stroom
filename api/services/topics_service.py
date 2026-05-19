import asyncio
import json
from pathlib import Path
from fastapi import HTTPException


class TopicsService:
    def __init__(self, config_path: Path):
        self.config_path = config_path
        self.lock = asyncio.Lock()

    async def _read_config(self) -> dict:
        async with self.lock:
            if not self.config_path.exists():
                return {"topics": {}, "persons": {}}
            try:
                content = self.config_path.read_text()
                data = json.loads(content)
                return data
            except Exception:
                return {"topics": {}, "persons": {}}

    async def _write_config(self, data: dict) -> None:
        async with self.lock:
            tmp_path = self.config_path.with_suffix(".tmp")
            tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
            tmp_path.replace(self.config_path)

    def _normalize_name(self, name: str) -> str:
        return name.lower().replace(" ", "_")

    # Topics

    async def list_topics(self) -> dict[str, list[str]]:
        data = await self._read_config()
        return data.get("topics", {})

    async def create_topic(self, name: str, keywords: list[str]) -> dict:
        norm_name = self._normalize_name(name)
        data = await self._read_config()
        topics = data.setdefault("topics", {})
        if norm_name in topics:
            raise HTTPException(status_code=409, detail="Topic already exists")
        topics[norm_name] = keywords
        await self._write_config(data)
        return {"name": norm_name, "keywords": keywords}

    async def update_topic(self, name: str, keywords: list[str]) -> dict:
        norm_name = self._normalize_name(name)
        data = await self._read_config()
        topics = data.get("topics", {})
        if norm_name not in topics:
            raise HTTPException(status_code=404, detail="Topic not found")
        topics[norm_name] = keywords
        await self._write_config(data)
        return {"name": norm_name, "keywords": keywords}

    async def delete_topic(self, name: str) -> dict:
        norm_name = self._normalize_name(name)
        data = await self._read_config()
        topics = data.get("topics", {})
        if norm_name not in topics:
            raise HTTPException(status_code=404, detail="Topic not found")
        del topics[norm_name]
        await self._write_config(data)
        return {"name": norm_name, "keywords": []}

    # Persons

    async def list_persons(self) -> dict[str, list[str]]:
        data = await self._read_config()
        return data.get("persons", {})

    async def create_person(self, name: str, keywords: list[str]) -> dict:
        norm_name = self._normalize_name(name)
        data = await self._read_config()
        persons = data.setdefault("persons", {})
        if norm_name in persons:
            raise HTTPException(status_code=409, detail="Person already exists")
        persons[norm_name] = keywords
        await self._write_config(data)
        return {"name": norm_name, "keywords": keywords}

    async def update_person(self, name: str, keywords: list[str]) -> dict:
        norm_name = self._normalize_name(name)
        data = await self._read_config()
        persons = data.get("persons", {})
        if norm_name not in persons:
            raise HTTPException(status_code=404, detail="Person not found")
        persons[norm_name] = keywords
        await self._write_config(data)
        return {"name": norm_name, "keywords": keywords}

    async def delete_person(self, name: str) -> dict:
        norm_name = self._normalize_name(name)
        data = await self._read_config()
        persons = data.get("persons", {})
        if norm_name not in persons:
            raise HTTPException(status_code=404, detail="Person not found")
        del persons[norm_name]
        await self._write_config(data)
        return {"name": norm_name, "keywords": []}
