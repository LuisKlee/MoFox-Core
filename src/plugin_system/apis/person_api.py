"""个人信息API模块

提供个人信息查询功能，用于插件获取用户相关信息
使用方式：
    from src.plugin_system.apis import person_api
    person_id = person_api.get_person_id("qq", 123456)
    info = await person_api.get_person_info(person_id)
"""

import asyncio
from typing import Any

from src.common.logger import get_logger
from src.person_info.person_info import PersonInfoManager, get_person_info_manager
from src.plugin_system.services.relationship_profile_service import relationship_profile_service
from src.plugin_system.services.relationship_service import relationship_service

logger = get_logger("person_api")


# =============================================================================
# 辅助函数
# =============================================================================


def get_person_id(platform: str, user_id: int | str) -> str:
    """根据平台和用户ID获取person_id (同步)

    这是一个核心的辅助函数，用于生成统一的用户标识。
    """
    try:
        return PersonInfoManager.get_person_id(platform, user_id)
    except Exception as e:
        logger.error(f"[PersonAPI] 获取person_id失败: platform={platform}, user_id={user_id}, error={e}")
        return ""


async def get_person_id_by_name(person_name: str) -> str:
    """根据用户名获取person_id"""
    try:
        person_info_manager = get_person_info_manager()
        return await person_info_manager.get_person_id_by_person_name(person_name)
    except Exception as e:
        logger.error(f"[PersonAPI] 根据用户名获取person_id失败: person_name={person_name}, error={e}")
        return ""


# =============================================================================
# 核心信息查询API
# =============================================================================


async def is_person_known(platform: str, user_id: int) -> bool:
    """判断是否认识某个用户"""
    try:
        person_info_manager = get_person_info_manager()
        return await person_info_manager.is_person_known(platform, user_id)
    except Exception as e:
        logger.error(f"[PersonAPI] 检查用户是否已知失败: platform={platform}, user_id={user_id}, error={e}")
        return False


async def get_person_info(person_id: str) -> dict[str, Any]:
    """获取用户的核心基础信息

    返回一个包含用户基础信息的字典，例如 person_name, nickname, know_times, attitude 等。
    """
    if not person_id:
        return {}
    try:
        person_info_manager = get_person_info_manager()
        fields = ["person_name", "nickname", "know_times", "know_since", "last_know", "attitude"]
        values = await person_info_manager.get_values(person_id, fields)
        return values
    except Exception as e:
        logger.error(f"[PersonAPI] 获取用户信息失败: person_id={person_id}, error={e}")
        return {}


async def get_person_impression(person_id: str, short: bool = False) -> str:
    """获取对用户的印象

    Args:
        person_id: 用户的唯一标识ID
        short: 是否获取简短版印象，默认为False

    Returns:
        一段描述性的文本。
    """
    if not person_id:
        return "用户ID为空，无法获取印象。"
    try:
        person_info_manager = get_person_info_manager()
        field = "short_impression" if short else "impression"
        impression = await person_info_manager.get_value(person_id, field)
        return impression or "还没有形成对该用户的印象。"
    except Exception as e:
        logger.error(f"[PersonAPI] 获取用户印象失败: person_id={person_id}, error={e}")
        return "获取用户印象时发生错误。"


async def get_person_points(person_id: str, limit: int = 5) -> list[tuple]:
    """获取关于用户的'记忆点'

    Args:
        person_id: 用户的唯一标识ID
        limit: 返回的记忆点数量上限，默认为5

    Returns:
        一个列表，每个元素是一个包含记忆点内容、权重和时间的元组。
    """
    if not person_id:
        return []
    try:
        person_info_manager = get_person_info_manager()
        points = await person_info_manager.get_value(person_id, "points")
        if not points:
            return []

        # 验证 points 是列表类型
        if not isinstance(points, list):
            logger.warning(f"[PersonAPI] 用户记忆点数据类型错误: person_id={person_id}, type={type(points)}, value={points}")
            return []

        # 过滤掉格式不正确的记忆点 (应该是包含至少3个元素的元组或列表)
        valid_points = []
        for point in points:
            if isinstance(point, list | tuple) and len(point) >= 3:
                valid_points.append(point)
            else:
                logger.warning(f"[PersonAPI] 跳过格式错误的记忆点: person_id={person_id}, point={point}")

        if not valid_points:
            return []

        # 按权重和时间排序，返回最重要的几个点
        sorted_points = sorted(valid_points, key=lambda x: (x[1], x[2]), reverse=True)
        return sorted_points[:limit]
    except Exception as e:
        logger.error(f"[PersonAPI] 获取用户记忆点失败: person_id={person_id}, error={e}")
        return []


# =============================================================================
# 关系查询API
# =============================================================================


async def get_user_relationship_score(
    user_id: str,
    *,
    scene_id: str | None = None,
    scene_type: str | None = None,
    platform: str | None = None,
) -> float:
    """
    获取用户关系分，支持按场景融合

    Args:
        user_id: 用户ID
        scene_id: 场景ID（群号/私聊ID，可选）
        scene_type: 场景类型（group/private，可选）
        platform: 平台（可选）

    Returns:
        关系分 (0.0 - 1.0)
    """
    try:
        snapshot = await relationship_profile_service.get_snapshot(
            user_id,
            scene_id=scene_id,
            scene_type=scene_type,
            platform=platform,
        )
        return float(snapshot.get("relationship_score", 0.0))
    except Exception as e:
        logger.error(f"[PersonAPI] 获取聚合关系分失败，回退基础服务: user_id={user_id}, error={e}")
        return await relationship_service.get_user_relationship_score(user_id)


async def get_user_relationship_data(
    user_id: str,
    *,
    scene_id: str | None = None,
    scene_type: str | None = None,
    platform: str | None = None,
) -> dict:
    """
    获取用户完整关系数据（聚合全局 + 场景）

    Args:
        user_id: 用户ID
        scene_id: 场景ID（群号/私聊ID，可选）
        scene_type: 场景类型（group/private，可选）
        platform: 平台（可选）

    Returns:
        包含关系分、关系文本、场景信息等的字典
    """
    try:
        return await relationship_profile_service.get_snapshot(
            user_id,
            scene_id=scene_id,
            scene_type=scene_type,
            platform=platform,
        )
    except Exception as e:
        logger.error(f"[PersonAPI] 获取聚合关系数据失败，回退基础服务: user_id={user_id}, error={e}")
        return await relationship_service.get_user_relationship_data(user_id)


async def update_user_relationship(
    user_id: str,
    relationship_score: float,
    relationship_text: str | None = None,
    user_name: str | None = None,
):
    """
    更新用户关系数据（全局记录，兼容旧逻辑）

    Args:
        user_id: 用户ID
        relationship_score: 关系分 (0.0 - 1.0)
        relationship_text: 关系描述文本
        user_name: 用户名称
    """
    await relationship_service.update_user_relationship(user_id, relationship_score, relationship_text, user_name)


async def record_relationship_interaction(
    user_id: str,
    *,
    scene_id: str | None = None,
    scene_type: str | None = None,
    platform: str | None = None,
    score_delta: float = 0.0,
    sentiment_delta: float = 0.0,
    topics: list[str] | None = None,
    keywords: list[str] | None = None,
):
    """记录一次交互，更新全局 + 场景关系"""
    await relationship_profile_service.record_interaction(
        user_id,
        scene_id=scene_id,
        scene_type=scene_type,
        platform=platform,
        score_delta=score_delta,
        sentiment_delta=sentiment_delta,
        topics=topics,
        keywords=keywords,
    )


# =============================================================================
# 系统状态与缓存API
# =============================================================================


def get_system_stats() -> dict[str, Any]:
    """
    获取系统统计信息

    Returns:
        包含各子系统统计的字典
    """
    return {
        "relationship_service": relationship_service.get_cache_stats(),
    }


def clear_caches(user_id: str | None = None):
    """
    清理缓存

    Args:
        user_id: 特定用户ID，如果为None则清理所有缓存
    """
    relationship_service.clear_cache(user_id)
    logger.info(f"清理缓存: {user_id if user_id else '全部'}")


# =============================================================================
# 报告API
# =============================================================================


async def get_full_relationship_report(person_id: str) -> str:
    """生成一份关于你和用户的完整'关系报告'

    综合基础信息、印象、记忆点和关系分，提供一个全方位的关系概览。
    """
    if not person_id:
        return "无法生成报告，因为用户ID为空。"

    try:
        person_info_manager = get_person_info_manager()
        user_id = await person_info_manager.get_value(person_id, "user_id")

        if not user_id:
            return "无法生成报告，因为找不到对应的用户信息。"

        # 异步获取所有需要的信息
        info, impression, points, rel_data = await asyncio.gather(
            get_person_info(person_id),
            get_person_impression(person_id),
            get_person_points(person_id, limit=3),
            relationship_service.get_user_relationship_data(str(user_id)),
        )

        # 构建报告
        report = f"--- 与 {info.get('person_name', '未知用户')} 的关系报告 ---\n"
        report += f"昵称: {info.get('nickname', '未知')}\n"
        report += f"关系分数: {rel_data.get('relationship_score', 0.0):.2f}/1.0\n"
        report += f"关系描述: {rel_data.get('relationship_text', '暂无')}\n"
        report += f"我对ta的印象: {impression}\n"

        if points:
            report += "最近的重要记忆点:\n"
            for point in points:
                report += f"  - {point[0]} (重要性: {point[1]})\n"

        report += "----------------------------------------\n"
        return report

    except Exception as e:
        logger.error(f"[PersonAPI] 生成关系报告失败: person_id={person_id}, error={e}")
        return "生成关系报告时发生错误。"
