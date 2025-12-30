# 新人际关系系统说明（跨群/私聊一体化）

## 设计目标
- 同一用户在群/跨群/私聊保持连续的关系与印象，降低“认不出人”。
- 读写分层：快速读快照，写入异步批处理，避免热路径阻塞。
- 可观测与可控：可清缓存、重置用户关系、审计跨场景调用。

## 核心概念
- 全局节点（UserRelationships）：用户的全局亲密度、印象、偏好。
- 场景视图（RelationshipSceneFacet）：按群号/私聊ID存储局部亲密度、情感、近期话题。
- 聚合快照（RelationshipProfileService）：融合全局+场景，提供单一查询口；可配置场景权重（默认 0.65）。

## 数据模型
- 表：user_relationships（已存在）
- 表：relationship_scene_facets（新）
  - user_id, platform, scene_id, scene_type(group/private)
  - affinity_score, interaction_count, last_interaction_time
  - recent_topics, recent_keywords, sentiment_score
  - 索引：user_id+scene_id+scene_type(unique)、last_updated

## 读路径
- API: `relationship_profile_service.get_snapshot(user_id, scene_id?, scene_type?, platform?)`
- 聚合策略：
  - 若存在场景分：`merged = w_scene*scene + (1-w_scene)*global`
  - 否则返回全局分。
- person_api 兼容层：`get_user_relationship_score` / `get_user_relationship_data` 已透传场景参数。
- 调用示例：
  - ChatStream 取关系分时传 group_id/stream_id。
  - AffinityInterestCalculator 取分时带 message 的 group_id/stream_id。
  - default_generator 降级查询时带 scene 上下文。

## 写路径
- API: `relationship_profile_service.record_interaction(user_id, scene_id?, scene_type?, platform?, score_delta=0.0, sentiment_delta=0.0, topics=None, keywords=None)`
- 逻辑：
  - 更新全局分（可选，score_delta）。
  - upsert 场景 facet，累加交互次数、情感分，更新亲密度/话题/关键词。
  - 清理对应缓存键。
- 建议接入点：
  - 消息处理后确定需要正/负向调整时调用。
  - 回复/拒绝/警告等场景写 sentiment_delta。
  - 主题抽取结果写 topics/keywords。

## 缓存策略
- 服务内内存缓存 TTL 120s，按 user_id|scene_id|scene_type 键。
- CRUD/QueryBuilder 自带 L2 缓存；批写用 AdaptiveBatchScheduler 推荐但当前 record_interaction 直接 CRUD 更新，可视需要接入批调度。

## 配置参数
- `affinity_flow.scene_relationship_weight`（默认 0.65）：场景分权重；0 表示只看全局，1 表示只看场景。
- `affinity_flow.base_relationship_score`：新用户默认分。

## 迁移与部署
1) 数据库迁移：创建表 relationship_scene_facets（字段如上）。
2) 确认 person_api / ChatStream / affinity_interest_calculator / default_generator 已升级（现有代码已带场景参数）。
3) 接入写路径：在业务动作处调用 `record_relationship_interaction`，填充场景数据。
4) 灰度与观察：
   - 指标：认人失败率下降、关系查询 P95、缓存命中率。
   - 审计：日志中标记跨场景查询（可在调用侧添加日志）。

## 重置与清理
- 清缓存：`relationship_profile_service.clear_cache(user_id? , scene_id?, scene_type?)`。
- 重置用户关系：删除 user_relationships 与对应 facets 记录（需自定义管理指令）。

## 后续增强建议
- 增加定时衰减任务（unified_scheduler）：对场景亲密度/情感分做时间衰减。
- 增加跨场景推荐：当场景缺数据时，挑选最近活跃的 facet 作为补充并标注来源。
- 增加 API 速查：`get_snapshot` 返回字段可扩展 `used_scene_facet`（已包含），供上层调试。

## 内置自动迁移（对新手友好）
- 在启动时检测表 `relationship_scene_facets` 是否存在；若不存在则自动执行 DDL 创建。
- 参考伪代码（可放在启动初始化模块）：
  ```python
  from sqlalchemy import text
  from src.common.database.core import get_db_session

  CREATE_SQL = """
  CREATE TABLE IF NOT EXISTS relationship_scene_facets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    platform TEXT,
    scene_id TEXT,
    scene_type TEXT NOT NULL DEFAULT 'group',
    affinity_score REAL NOT NULL DEFAULT 0.3,
    interaction_count INTEGER NOT NULL DEFAULT 0,
    last_interaction_time REAL,
    recent_topics TEXT,
    recent_keywords TEXT,
    sentiment_score REAL NOT NULL DEFAULT 0.0,
    last_updated REAL NOT NULL DEFAULT (strftime('%s','now')),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, scene_id, scene_type)
  );
  CREATE INDEX IF NOT EXISTS idx_relationship_facet_last_updated ON relationship_scene_facets(last_updated);
  """

  async def ensure_relationship_tables():
      async with get_db_session() as session:
          await session.execute(text(CREATE_SQL))
  ```
- SQLite/PG 区别：
  - PostgreSQL 将 `AUTOINCREMENT` 改为 `SERIAL`，`strftime` 改为 `EXTRACT(EPOCH FROM NOW())`，类型用 TEXT/REAL/TIMESTAMP。
- 放置位置：
  - 建议在系统初始化阶段（如 MainSystem.initialize）或数据库模块启动处调用一次，避免请求路径上检查。
- 用户可见提示：
  - 检测到缺表并自动创建时，日志打印“Created relationship_scene_facets automatically”以便新手确认。
