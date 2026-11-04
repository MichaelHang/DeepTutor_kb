<div align="center">

# DeepTutor — MichaelHang Fork

**基于 [HKUDS/DeepTutor](https://github.com/HKUDS/DeepTutor) 的个人分支，针对「高中地理」知识库场景做了定制。**

上游项目介绍、完整文档与安装指南请见根目录 [README.md](../README.md)。

</div>

---

## 本 Fork 的改动

本仓库在上游 v1.7.1 基础上做了以下改动，全部围绕**知识库的可用性管理**展开：

### 1. 解除关联时连带删除已导入文档

上游的「解除关联」只断开文件夹与知识库的映射，已经导入的文档仍留在索引里、依然能被检索到。

本 Fork 改为：**解除关联时一并清除该文件夹已导入的文档，并自动触发一次后台强制重建索引**。

- 归属判定采用「相对路径优先 + 内容哈希唯一匹配回退」；哈希存在歧义时不做删除，避免误删
- 清除后立即重建，保证向量与 BM25 侧写索引中不再残留这些文档

相关实现：`deeptutor/api/routers/knowledge.py`（`_purge_unlinked_documents`）、`deeptutor/knowledge/add_documents.py`（`_prune_empty_dirs` / `rekey_moved_documents`）、`deeptutor/services/rag/visual_assets.py`（`remove_source`）。

### 2. 索引版本治理：查看并删除历史版本

上游每次全量重建都会写入一个新的 `version-N` 目录，旧版本一直堆积占空间（单库可达数 GB）。

本 Fork 在「索引版本」区域新增：

- **标注当前激活版本**（正在为检索服务的那个版本），并显示其就绪状态
- **删除指定版本**按钮，回收磁盘空间
- 保护机制：当前服役的版本禁止删除（返回 409）；版本名格式与路径归属均做校验
- 修正了 `.building.json` 的判定逻辑——它是常驻发布守卫而非「仍在构建」标记，此前会导致所有已发布版本都无法删除

相关实现：`deeptutor/services/rag/index_versioning.py`（`is_version_published`）、`deeptutor/api/routers/knowledge.py`（`DELETE /knowledge-bases/{kb_name}/index-versions/{version}`）、`web/components/knowledge/KbIndexVersionsSection.tsx`。

### 3. 文件树默认收起，支持展开 / 合拢

知识库文档树默认收起，避免文档多时整屏铺开。工具栏提供「展开全部 / 收起全部」以及单个「展开 / 收起」按钮。

相关实现：`web/components/knowledge/KbDocumentList.tsx`。

### 4. 修复模型 API 返回 400

模型在写工具调用时触达输出上限，参数 JSON 会被截断成非法片段。该片段对工具分发器仍可用，但助手消息里存的是原始文本，而各 provider 都会把 `function.arguments` 按 JSON 校验——重放该轮次时整个请求直接 400，且这一轮会污染之后每一次重放。

本 Fork 在重放前归一化工具调用参数：能正常解析的原样返回（避免重写请求前缀、命中 provider 的 prompt cache），截断的按分发器同样的规则修复。

相关实现：`deeptutor/utils/json_parser.py`（`normalize_tool_call_arguments`）、`deeptutor/runtime/agentic/messages.py`、`deeptutor/services/session/model_history.py`。

---

## 与上游的同步方式

本仓库通过 `merge` 保持与上游的同步（不使用 rebase，保留双方 commit 历史）：

```bash
git fetch upstream
git merge upstream/main
```

上游 README 改动频繁（近一年 380+ 次），为避免每次同步都产生冲突：

- **根目录 `README.md` 保持上游原样**，不做本地修改 —— 同步时零冲突
- **本文件位于 `.github/README.md`**，上游从不涉及该路径，因此同样零冲突
- GitHub 展示 README 的优先级为 `.github/` → 仓库根目录 → `docs/`，所以本文件即为仓库首页展示的内容

---

## 上游信息

DeepTutor 是一个**智能学习伙伴**（Lifelong Personalized Tutoring），采用 agent-native 架构组织：单次调用的 **Tools** 与多阶段接管整个回合的 **Capabilities** 两层插件模型，通过 CLI、WebSocket API 与 Python SDK 三个入口暴露，全部汇入持久化的 turn 应用服务。

项目主页：<https://github.com/HKUDS/DeepTutor> · 官方文档：<https://deeptutor.info>

<details>
<summary><b>展开上游 README（项目特性、截图、CLI、生态与社区）</b></summary>

完整的项目介绍、功能截图、CLI 用法、DeepTutor Hub 生态与社区信息，请见根目录的 [README.md](../README.md)（内容与上游保持一致）。

</details>

---

## License

遵循上游的 [Apache 2.0](../LICENSE) 许可协议。
