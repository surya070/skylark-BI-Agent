"""monday.com GraphQL client.

Board data is always fetched live; nothing from the source spreadsheets is embedded.
Each fetch returns a snapshot carrying its own freshness and data-quality metadata so
callers can be honest with the user when monday.com is unreachable.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field, replace
from typing import Any

import httpx

from app.config import Settings
from app.schema import is_header_artifact

BOARD_ITEMS_QUERY = """
query ($boardId: [ID!]!, $cursor: String) {
  boards(ids: $boardId) {
    id
    name
    items_page(limit: 250, cursor: $cursor) {
      cursor
      items {
        id
        name
        column_values {
          id
          type
          text
          value
        }
      }
    }
  }
}
"""

BOARD_COLUMNS_QUERY = """
query ($boardId: [ID!]!) {
  boards(ids: $boardId) {
    id
    name
    columns {
      id
      title
      type
    }
  }
}
"""


class MondayUnavailable(RuntimeError):
    """monday.com could not be reached and no cached snapshot exists."""


@dataclass
class BoardSnapshot:
    board_id: str
    board_name: str
    records: list[dict[str, Any]]
    fetched_at: float
    dropped_header_rows: int = 0
    stale: bool = False
    error: str | None = None
    columns: list[dict[str, str]] = field(default_factory=list)

    def freshness(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "board": self.board_name,
            "records": len(self.records),
            "fetched_seconds_ago": round(time.time() - self.fetched_at, 1),
            "live": not self.stale,
        }
        if self.dropped_header_rows:
            info["excluded_header_rows"] = self.dropped_header_rows
        if self.stale:
            info["warning"] = (
                f"monday.com is unreachable ({self.error}). Serving the last successful "
                "snapshot — figures may be out of date."
            )
        return info


class MondayClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._snapshots: dict[str, BoardSnapshot] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, board_id: str) -> asyncio.Lock:
        if board_id not in self._locks:
            self._locks[board_id] = asyncio.Lock()
        return self._locks[board_id]

    async def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": self.settings.monday_api_token,
            "Content-Type": "application/json",
            "API-Version": self.settings.monday_api_version,
        }
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.post(
                self.settings.monday_api_url,
                headers=headers,
                json={"query": query, "variables": variables},
            )
        if resp.status_code == 429:
            raise RuntimeError("monday.com rate limit reached")
        resp.raise_for_status()
        payload = resp.json()
        if payload.get("errors"):
            messages = "; ".join(str(e.get("message", e)) for e in payload["errors"])
            raise RuntimeError(f"monday.com GraphQL error: {messages}")
        data = payload.get("data") or {}
        if not data.get("boards"):
            raise RuntimeError("Board not found or token lacks access")
        return data

    async def get_board(self, board_id: str, force: bool = False) -> BoardSnapshot:
        cached = self._snapshots.get(board_id)
        if not force and cached and not cached.stale:
            if time.time() - cached.fetched_at < self.settings.cache_ttl_seconds:
                return cached

        async with self._lock(board_id):
            cached = self._snapshots.get(board_id)
            if not force and cached and not cached.stale:
                if time.time() - cached.fetched_at < self.settings.cache_ttl_seconds:
                    return cached
            try:
                snapshot = await self._fetch(board_id)
            except Exception as exc:  # noqa: BLE001 — degrade instead of failing the request
                if cached:
                    return replace(cached, stale=True, error=str(exc))
                raise MondayUnavailable(str(exc)) from exc
            self._snapshots[board_id] = snapshot
            return snapshot

    async def _fetch(self, board_id: str) -> BoardSnapshot:
        meta = await self._graphql(BOARD_COLUMNS_QUERY, {"boardId": [board_id]})
        board_meta = meta["boards"][0]
        titles = {c["id"]: c["title"] for c in board_meta["columns"]}

        records: list[dict[str, Any]] = []
        dropped = 0
        cursor: str | None = None
        while True:
            data = await self._graphql(BOARD_ITEMS_QUERY, {"boardId": [board_id], "cursor": cursor})
            page = data["boards"][0]["items_page"]
            for raw in page["items"]:
                record: dict[str, Any] = {"id": raw["id"], "name": raw["name"]}
                for col in raw["column_values"]:
                    record[titles.get(col["id"], col["id"])] = self._normalize_cell(col)
                if is_header_artifact(record):
                    dropped += 1
                    continue
                records.append(record)
            cursor = page.get("cursor")
            if not cursor:
                break

        return BoardSnapshot(
            board_id=board_id,
            board_name=board_meta["name"],
            records=records,
            fetched_at=time.time(),
            dropped_header_rows=dropped,
            columns=[{"title": c["title"], "type": c["type"]} for c in board_meta["columns"]],
        )

    @staticmethod
    def _normalize_cell(col: dict[str, Any]) -> Any:
        text = (col.get("text") or "").strip()
        if text:
            return text
        raw = col.get("value")
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return raw
        if isinstance(parsed, dict):
            for key in ("label", "text", "name", "date"):
                value = parsed.get(key)
                if value not in (None, ""):
                    return value
            return None
        return parsed if parsed not in ("", {}, []) else None

    async def deals(self, force: bool = False) -> BoardSnapshot:
        return await self.get_board(self.settings.monday_deals_board_id, force=force)

    async def work_orders(self, force: bool = False) -> BoardSnapshot:
        return await self.get_board(self.settings.monday_work_orders_board_id, force=force)

    async def warm(self) -> None:
        """Prefetch both boards so the first user question isn't slow."""
        await asyncio.gather(self.deals(), self.work_orders(), return_exceptions=True)
