# 人际关系系统维护指南

## 目标
- 保证跨群/私聊关系一致性稳定运行。
- 提供新手友好的日常运维与故障处理步骤。

## 部署前检查
- 配置：确认 `affinity_flow.scene_relationship_weight` 与 `base_relationship_score` 已配置或使用默认值。
- 数据库：如未运行程序自动迁移，手工确保表 `relationship_scene_facets` 存在（参考 overview 中的 DDL）。
- 依赖：确保数据库权限允许 DDL（自动创建表需要）。

## 启动时自动检查
- 程序会在启动阶段执行：
  - 检测/创建 `relationship_scene_facets` 表。
  - 日志出现 “✅ relationship_scene_facets 已确保存在 (db=...)” 视为成功。
- 如失败：
  - 检查数据库账号是否有建表权限。
  - 对 PostgreSQL 手动执行 DDL 并重启。

## 日常操作
- 查看关系快照：调用 `relationship_profile_service.get_snapshot(user_id, scene_id?, scene_type?, platform?)`。
- 记录交互：在业务逻辑里调用 `record_relationship_interaction`（写入全局+场景）。
- 清理缓存：
  - 全清：`relationship_profile_service.clear_cache()`
  - 单用户：`relationship_profile_service.clear_cache(user_id="xxx", scene_id? , scene_type?)`

## 故障排查
- 认人失败/错认：
  - 检查是否传入正确的 user_id/scene_id/scene_type。
  - 验证 facet 表是否有数据；若为空，确认写路径是否调用 `record_relationship_interaction`。
- 关系分不更新：
  - 确认 score_delta/sentiment_delta 是否传入。
  - 检查数据库写权限或事务报错。
- 性能问题：
  - 关注关系查询 P95；如缓存命中低，检查场景参数是否变化过多。
  - 必要时将写入改为批调度（AdaptiveBatchScheduler）。

## 数据治理
- 重置单用户：删除 user_relationships 对应记录，并删除 facet 表中该 user_id 的行。
- 批量衰减：可通过 unified_scheduler 定期任务对 affinity_score/sentiment_score 做时间衰减。
- 审计：在调用快照时添加日志标记跨场景引用，便于排查误用。

## 升级/回滚建议
- 先建表再发版，避免缺表异常。
- 回滚代码时保留新表，不影响旧逻辑；未使用的新表可留存。
- 如需停用场景分，配置 `scene_relationship_weight=0` 即可退化为全局分。
