"""关系画像融合服务

提供全局 + 场景视图的关系快照，减少群/私聊割裂。
"""

from __future__ import annotations

import time
from typing import Any

from src.common.database.api.crud import CRUDBase
from src.common.database.api.query import QueryBuilder
from src.common.database.core.models import RelationshipSceneFacet, UserRelationships
from src.common.logger import get_logger
from src.config.config import global_config

logger = get_logger("relationship_profile_service")


class RelationshipProfileService:
    """聚合关系画像，提供跨场景一致的视图"""

    CACHE_TTL = 120  # seconds
    SCENE_WEIGHT = 0.65  # 场景分权重，剩余给全局分

    def __init__(self):
        self._user_crud = CRUDBase(UserRelationships)
        self._facet_crud = CRUDBase(RelationshipSceneFacet)
        self._cache: dict[str, tuple[float, dict[str, Any]]] = {}

    async def get_snapshot(
        self,
        user_id: str,
        *,
        scene_id: str | None = None,
        scene_type: str | None = None,
        platform: str | None = None,
    ) -> dict[str, Any]:
        """获取聚合关系快照，场景信息可选"""
        scene_type = scene_type or "group"
        cache_key = self._cache_key(user_id, scene_id, scene_type)
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        base = await self._get_or_create_global(user_id)

        facet: RelationshipSceneFacet | None = None
        if scene_id:
            facet = await self._facet_crud.get_by(
                user_id=user_id,
                scene_id=scene_id,
                scene_type=scene_type,
                use_cache=True,
            )

        if facet is None:
            facet = await self._get_recent_facet(user_id)

        snapshot = self._compose_snapshot(
            base=base,
            facet=facet,
            scene_id=scene_id,
            scene_type=scene_type,
            platform=platform,
        )

        self._cache[cache_key] = (time.time(), snapshot)
        return snapshot

    async def record_interaction(
        self,
        user_id: str,
        *,
        scene_id: str | None = None,
        scene_type: str | None = None,
        platform: str | None = None,
        score_delta: float = 0.0,
        sentiment_delta: float = 0.0,
        topics: list[str] | None = None,
        keywords: list[str] | None = None,
    ) -> None:
        """记录一次交互，更新全局与场景分数"""
        scene_type = scene_type or "group"
        base = await self._get_or_create_global(user_id)

        # 更新全局关系分
        if score_delta != 0.0:
            new_global = self._clamp_score((base.relationship_score or 0.0) + score_delta)
            await self._user_crud.update(
                base.id,
                {
                    "relationship_score": new_global,
                    "last_updated": time.time(),
                },
            )
            base.relationship_score = new_global  # keep local cache in sync

        # 更新场景关系分
        if scene_id:
            facet, _created = await self._facet_crud.get_or_create(
                defaults={
                    "user_id": user_id,
                    "platform": platform,
                    "scene_id": scene_id,
                    "scene_type": scene_type,
                    "affinity_score": base.relationship_score,
                    "last_interaction_time": time.time(),
                },
                user_id=user_id,
                scene_id=scene_id,
                scene_type=scene_type,
            )

            facet_updates: dict[str, Any] = {
                "interaction_count": (facet.interaction_count or 0) + 1,
                "last_interaction_time": time.time(),
                "last_updated": time.time(),
            }

            if score_delta != 0.0:
                facet_updates["affinity_score"] = self._clamp_score(
                    (facet.affinity_score or base.relationship_score) + score_delta
                )

            if sentiment_delta != 0.0:
                facet_updates["sentiment_score"] = (facet.sentiment_score or 0.0) + sentiment_delta

            if topics:
                facet_updates["recent_topics"] = ",".join(dict.fromkeys([t.strip() for t in topics if t.strip()])) or None

            if keywords:
                facet_updates["recent_keywords"] = ",".join(
                    dict.fromkeys([kw.strip() for kw in keywords if kw.strip()])
                ) or None

            await self._facet_crud.update(facet.id, facet_updates)

        # 交互后清理缓存
        self.clear_cache(user_id=user_id, scene_id=scene_id, scene_type=scene_type)

    def clear_cache(self, *, user_id: str | None = None, scene_id: str | None = None, scene_type: str | None = None):
        """清理缓存（按用户或全清）"""
        if not user_id:
            self._cache.clear()
            return

        scene_type = scene_type or "group"
        keys_to_delete = []
        for key in list(self._cache.keys()):
            if key.startswith(f"{user_id}|"):
                if scene_id is None or key == self._cache_key(user_id, scene_id, scene_type):
                    keys_to_delete.append(key)
        for key in keys_to_delete:
            self._cache.pop(key, None)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------
    def _cache_key(self, user_id: str, scene_id: str | None, scene_type: str | None) -> str:
        return f"{user_id}|{scene_id or 'any'}|{scene_type or 'any'}"

    def _get_cached(self, cache_key: str) -> dict[str, Any] | None:
        cached = self._cache.get(cache_key)
        if not cached:
            return None
        ts, payload = cached
        if time.time() - ts > self.CACHE_TTL:
            self._cache.pop(cache_key, None)
            return None
        return payload

    async def _get_or_create_global(self, user_id: str) -> UserRelationships:
        base_score = global_config.affinity_flow.base_relationship_score
        record, _created = await self._user_crud.get_or_create(
            defaults={
                "user_name": "",
                "relationship_text": "新用户",
                "relationship_score": base_score,
                "first_met_time": time.time(),
                "last_updated": time.time(),
            },
            user_id=user_id,
        )
        return record

    async def _get_recent_facet(self, user_id: str) -> RelationshipSceneFacet | None:
        query = QueryBuilder(RelationshipSceneFacet)
        return await query.filter(user_id=user_id).order_by("-last_interaction_time").first()

    def _compose_snapshot(
        self,
        *,
        base: UserRelationships,
        facet: RelationshipSceneFacet | None,
        scene_id: str | None,
        scene_type: str | None,
        platform: str | None,
    ) -> dict[str, Any]:
        global_score = base.relationship_score or global_config.affinity_flow.base_relationship_score
        scene_score = facet.affinity_score if facet else None

        if scene_score is None:
            merged_score = global_score
            scene_used = False
        else:
            merged_score = self._blend_score(global_score, scene_score)
            scene_used = True

        return {
            "user_id": base.user_id,
            "platform": platform or getattr(facet, "platform", None),
            "relationship_score": merged_score,
            "global_relationship_score": global_score,
            "scene_relationship_score": scene_score,
            "relationship_stage": base.relationship_stage,
            "relationship_text": base.relationship_text,
            "impression_text": base.impression_text or base.relationship_text,
            "preference_keywords": base.preference_keywords,
            "key_facts": base.key_facts,
            "scene_id": getattr(facet, "scene_id", scene_id),
            "scene_type": getattr(facet, "scene_type", scene_type),
            "recent_topics": getattr(facet, "recent_topics", None),
            "recent_keywords": getattr(facet, "recent_keywords", None),
            "sentiment_score": getattr(facet, "sentiment_score", 0.0),
            "interaction_count": getattr(facet, "interaction_count", 0),
            "last_interaction_time": getattr(facet, "last_interaction_time", None),
            "used_scene_facet": scene_used,
        }

    def _blend_score(self, global_score: float, scene_score: float) -> float:
        weight = getattr(global_config.affinity_flow, "scene_relationship_weight", self.SCENE_WEIGHT)
        weight = min(max(weight, 0.0), 1.0)
        return self._clamp_score(weight * scene_score + (1 - weight) * global_score)

    def _clamp_score(self, score: float) -> float:
        return max(0.0, min(1.0, score))


relationship_profile_service = RelationshipProfileService()
