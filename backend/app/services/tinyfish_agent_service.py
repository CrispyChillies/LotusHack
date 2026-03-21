from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timezone
from typing import Any

import requests
from fastapi import HTTPException, status

from app.services.memory_graph_service import memory_graph_service


class TinyfishWebAgentClient:
    def __init__(self) -> None:
        self.endpoint = os.getenv("TINYFISH_SSE_ENDPOINT", "https://agent.tinyfish.ai/v1/automation/run-sse")

    @staticmethod
    def _get_api_key() -> str:
        api_key = os.getenv("TINYFISH_API_KEY")
        if not api_key:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Missing TINYFISH_API_KEY in environment.",
            )
        return api_key

    def run_sse(self, *, url: str, goal: str, timeout_seconds: int | None = None) -> list[dict[str, Any]]:
        if timeout_seconds is None:
            timeout_seconds = int(os.getenv("TINYFISH_TIMEOUT_SECONDS", "180"))

        headers = {
            "X-API-Key": self._get_api_key(),
            "Content-Type": "application/json",
        }
        payload = {"url": url, "goal": goal}

        events: list[dict[str, Any]] = []

        try:
            with requests.post(
                self.endpoint,
                headers=headers,
                json=payload,
                stream=True,
                timeout=timeout_seconds,
            ) as response:
                if response.status_code >= 400:
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=f"TinyFish request failed with status {response.status_code}: {response.text}",
                    )

                for raw_line in response.iter_lines(decode_unicode=True):
                    if not raw_line:
                        continue
                    if not raw_line.startswith("data: "):
                        continue

                    body = raw_line[6:].strip()
                    if body == "[DONE]":
                        break

                    try:
                        event = json.loads(body)
                    except json.JSONDecodeError:
                        continue

                    if isinstance(event, dict):
                        events.append(event)
        except HTTPException:
            raise
        except requests.Timeout as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail=f"TinyFish SSE timeout: {exc}",
            )
        except requests.RequestException as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"TinyFish request error: {exc}",
            )

        return events


class AgenticMemoryCompanionService:
    def __init__(self) -> None:
        self.tinyfish = TinyfishWebAgentClient()

    @staticmethod
    def _dedupe_keep_order(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = value.strip()
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(normalized)
        return result

    @staticmethod
    def _extract_json_list(value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]

        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except Exception:
                pass

            lines = [line.strip(" -•\t") for line in raw.splitlines() if line.strip()]
            return lines

        if isinstance(value, dict):
            for candidate_key in ("queries", "items", "resultJson", "hints", "results"):
                if candidate_key in value:
                    return AgenticMemoryCompanionService._extract_json_list(value[candidate_key])

        return []

    def _tinyfish_subqueries(self, *, context_url: str, journey_goal: str, subquery_count: int) -> tuple[list[str], int]:
        goal = (
            "Extract concise memory-retrieval hints from this webpage for dementia-support journey generation. "
            f"Return a JSON array with {subquery_count} short queries related to: {journey_goal}."
        )
        events = self.tinyfish.run_sse(url=context_url, goal=goal)

        queries: list[str] = []
        for event in reversed(events):
            if not isinstance(event, dict):
                continue
            for key in ("resultJson", "result_json", "result", "data", "output", "text"):
                if key in event:
                    queries = self._extract_json_list(event[key])
                    if queries:
                        return queries[:subquery_count], len(events)

        return [], len(events)

    @staticmethod
    def _fallback_subqueries(journey_goal: str, subquery_count: int) -> list[str]:
        base = [
            journey_goal,
            f"{journey_goal} with family members",
            f"{journey_goal} in familiar places",
            f"{journey_goal} positive moments",
            f"{journey_goal} with grandparents or parents",
            f"{journey_goal} emotionally meaningful moments",
            f"{journey_goal} events and celebrations",
        ]
        return base[:subquery_count]

    @staticmethod
    def _infer_media_kind(url: str | None) -> str | None:
        if not url:
            return None
        lowered = url.lower()
        if any(lowered.endswith(ext) for ext in (".mp4", ".mov", ".webm", ".m4v")):
            return "video"
        if any(lowered.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp")):
            return "image"
        return "media"

    @staticmethod
    def _make_slide(result: dict[str, Any], index: int) -> dict[str, Any]:
        content = (result.get("content") or "").strip()
        metadata = result.get("metadata") or {}
        title = metadata.get("title") or f"Memory {index + 1}"
        media_url = metadata.get("media_url") or metadata.get("s3_url")
        narration = f"Let us revisit this memory together. {content[:240]}" if content else "Let us revisit this memory together."

        return {
            "slide_index": index + 1,
            "source_type": str(result.get("source_type") or "memory"),
            "source_id": str(result.get("source_id") or ""),
            "title": str(title),
            "memory_text": content,
            "narration_text": narration,
            "media_url": media_url,
            "media_kind": AgenticMemoryCompanionService._infer_media_kind(media_url),
            "score": float(result.get("final_score") or 0.0),
        }

    async def build_journey(
        self,
        *,
        family_id: str,
        journey_goal: str,
        top_k_slides: int,
        subquery_count: int,
        context_url: str | None,
    ) -> dict[str, Any]:
        tinyfish_queries: list[str] = []
        tinyfish_event_count = 0

        if context_url:
            try:
                tinyfish_queries, tinyfish_event_count = await asyncio.to_thread(
                    self._tinyfish_subqueries,
                    context_url=context_url,
                    journey_goal=journey_goal,
                    subquery_count=subquery_count,
                )
            except HTTPException:
                tinyfish_queries = []
                tinyfish_event_count = 0

        fallback_queries = self._fallback_subqueries(journey_goal, subquery_count)
        queries = self._dedupe_keep_order(tinyfish_queries + fallback_queries)[:subquery_count]

        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for query in queries:
            result = await memory_graph_service.advanced_memory_query(
                family_id=family_id,
                query=query,
                required_entities=[],
                required_relations=[],
                max_hops=2,
                top_k=max(5, top_k_slides),
            )
            for item in result.get("results", []):
                key = (str(item.get("source_type") or "memory"), str(item.get("source_id") or ""))
                existing = merged.get(key)
                if existing is None or float(item.get("final_score") or 0.0) > float(existing.get("final_score") or 0.0):
                    merged[key] = item

        ranked = sorted(merged.values(), key=lambda x: float(x.get("final_score") or 0.0), reverse=True)
        selected = ranked[:top_k_slides]
        slides = [self._make_slide(item, index) for index, item in enumerate(selected)]

        return {
            "family_id": family_id,
            "journey_goal": journey_goal,
            "generated_subqueries": queries,
            "slides": slides,
            "tinyfish_used": bool(context_url),
            "tinyfish_event_count": tinyfish_event_count,
            "generated_at": datetime.now(timezone.utc),
        }

    @staticmethod
    def _meaning_bonus(content: str) -> float:
        lowered = content.lower()
        keywords = [
            "birthday",
            "anniversary",
            "wedding",
            "mom",
            "dad",
            "mother",
            "father",
            "grandpa",
            "grandma",
            "family",
            "love",
            "together",
            "celebrate",
            "home",
            "visit",
        ]
        hits = sum(1 for token in keywords if token in lowered)
        return min(0.25, 0.03 * hits)

    @staticmethod
    def _notification_candidate(item: dict[str, Any], score: float) -> dict[str, Any]:
        content = (item.get("content") or "").strip()
        metadata = item.get("metadata") or {}
        title = metadata.get("title") or "Meaningful family memory"
        return {
            "source_type": str(item.get("source_type") or "memory"),
            "source_id": str(item.get("source_id") or ""),
            "title": str(title),
            "message": f"A meaningful memory is ready to revisit: {content[:120]}",
            "score": score,
            "suggested_action": "Share this memory with family by call/video and replay the story.",
            "memory_preview": content[:300],
            "media_url": metadata.get("media_url") or metadata.get("s3_url"),
        }

    def _tinyfish_notification_queries(self, *, context_url: str) -> tuple[list[str], int]:
        goal = (
            "Extract important family events, anniversaries, birthdays, and caregiving moments from this page. "
            "Return a JSON array of short search queries for a memory database."
        )
        events = self.tinyfish.run_sse(url=context_url, goal=goal)
        queries: list[str] = []
        for event in reversed(events):
            if not isinstance(event, dict):
                continue
            for key in ("resultJson", "result_json", "result", "data", "output", "text"):
                if key in event:
                    queries = self._extract_json_list(event[key])
                    if queries:
                        return queries[:6], len(events)
        return [], len(events)

    async def meaningful_notifications(
        self,
        *,
        family_id: str,
        min_score: float,
        max_notifications: int,
        context_url: str | None,
    ) -> dict[str, Any]:
        tinyfish_queries: list[str] = []
        tinyfish_event_count = 0

        if context_url:
            try:
                tinyfish_queries, tinyfish_event_count = await asyncio.to_thread(
                    self._tinyfish_notification_queries,
                    context_url=context_url,
                )
            except HTTPException:
                tinyfish_queries = []
                tinyfish_event_count = 0

        base_queries = [
            "family birthday memory",
            "wedding anniversary memory",
            "grandpa grandma together memory",
            "happy family celebration",
            "care and support memory",
            "home visit family memory",
        ]
        queries = self._dedupe_keep_order(tinyfish_queries + base_queries)

        merged: dict[tuple[str, str], dict[str, Any]] = {}
        for query in queries:
            result = await memory_graph_service.advanced_memory_query(
                family_id=family_id,
                query=query,
                required_entities=[],
                required_relations=[],
                max_hops=2,
                top_k=max(5, max_notifications * 3),
            )
            for item in result.get("results", []):
                key = (str(item.get("source_type") or "memory"), str(item.get("source_id") or ""))
                existing = merged.get(key)
                if existing is None or float(item.get("final_score") or 0.0) > float(existing.get("final_score") or 0.0):
                    merged[key] = item

        scored: list[tuple[dict[str, Any], float]] = []
        for item in merged.values():
            base_score = float(item.get("final_score") or 0.0)
            bonus = self._meaning_bonus(str(item.get("content") or ""))
            score = base_score + bonus
            if score >= min_score:
                scored.append((item, score))

        scored.sort(key=lambda pair: pair[1], reverse=True)
        selected = scored[:max_notifications]
        candidates = [self._notification_candidate(item, score) for item, score in selected]

        return {
            "family_id": family_id,
            "should_notify": len(candidates) > 0,
            "generated_queries": queries,
            "candidates": candidates,
            "tinyfish_used": bool(context_url),
            "tinyfish_event_count": tinyfish_event_count,
            "generated_at": datetime.now(timezone.utc),
        }


agentic_memory_companion_service = AgenticMemoryCompanionService()
