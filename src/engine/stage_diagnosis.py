"""
StageDiagnosisEngine v3.1
— 规则引擎 + embedding 语义匹配（MVP：关键词匹配）
— 低信号场景不再停摆
— 冷却期机制
"""

import re
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# 信号规则库
# ═══════════════════════════════════════════════════════════

SIGNAL_RULES = [
    # ── Override 优先级（accoutability_fear）：一旦命中直接跳变 ──
    {
        "signal_type": "accountability_fear",
        "patterns": [
            r"谁负责", r"万一不行", r"出问题怎么办", r"风险谁担",
            r"领导还要再看", r"上面还没定", r"党组.*讨论", r"评审.*意见",
            r"审计", r"追责", r"这个责任", r"怕.*出.*问题",
        ],
        "implies_stage": "stage_b_fear_of_failure",
        "priority": "override",
        "theory": "JOLT Effect (Dixon & McKenna, 2022)",
    },
    {
        "signal_type": "peer_validation_request",
        "patterns": [
            r"别人也这样", r"同行怎么做", r"有没有先例",
            r"哪个.*用过", r"案例.*看看", r"类似.*项目",
        ],
        "implies_stage": "stage_b_fear_of_failure",
        "priority": "high",
        "theory": "JOLT Effect + Cialdini Social Proof",
    },
    {
        "signal_type": "specific_implementation_inquiry",
        "patterns": [
            r"怎么实施", r"分几个阶段", r"落地.*方案",
            r"实施.*周期", r"部署.*时间", r"人员.*培训",
            r"试点", r"怎么.*推",
        ],
        "implies_stage": "stage_b_fear_of_failure",
        "priority": "normal",
        "theory": "JOLT Effect — 实施细节关注=阶段B信号",
    },

    # ── 阶段A信号 ──
    {
        "signal_type": "necessity_doubt",
        "patterns": [
            r"有必要吗", r"真的需要", r"现在做的意义",
            r"有没有.*必要", r"值得.*做",
        ],
        "implies_stage": "stage_a_problem_unawareness",
        "priority": "normal",
        "theory": "JOLT Effect (Dixon & McKenna, 2022)",
    },
    {
        "signal_type": "cost_questioning",
        "patterns": [
            r"性价比", r"值不值", r"成本.*高", r"预算.*不够",
            r"太贵", r"降.*价", r"优惠",
        ],
        "implies_stage": "stage_a_problem_unawareness",
        "priority": "normal",
        "theory": "SPIN/Gap Selling — 价格敏感=未认可价值",
    },

    # ── 阶段C信号 ──
    {
        "signal_type": "status_quo_defense",
        "patterns": [
            r"现在挺好", r"也没出过问题", r"先这样用着",
            r"暂时.*不需要", r"够用", r"现有.*可以",
            r"不着急", r"以后再说",
        ],
        "implies_stage": "stage_c_status_quo_bias",
        "priority": "normal",
        "theory": "JOLT Effect (Dixon & McKenna, 2022)",
    },
]

# ── 信号强度阈值 ──
MIN_CHARS_FOR_ANALYSIS = 8       # 少于8字进入稀疏模式
MIN_SIGNALS_FOR_CONFIDENCE = 2   # 少于2个匹配信号 → 低置信度
SIGNAL_DECAY_DAYS = 30           # 超过30天未更新的信号降权到0.3
OVERRIDE_COOLDOWN_HOURS = 24     # override 触发后的冷却期


class StageDiagnosisEngine:
    """
    阶段判定规则引擎 v3.1。

    修正：
    - 低信号场景不再输出"unclear, 自行判断"
    - 改为"按上次已知阶段保守推进 + 给出具体探测问题"
    - override 跳变需要冷却期确认
    """

    def diagnose(
        self,
        interaction_text: str,
        person_id: str,
        last_known_stage: str | None = None,
        recent_signals: list[dict] | None = None,
    ) -> dict:
        """
        输入：
        - interaction_text: 客户说的原话（或摘要）
        - person_id: 联系人 ID
        - last_known_stage: 上次判定的阶段
        - recent_signals: 近期信号列表 [{signal_type, created_at, confidence}, ...]

        输出：DiagnosisResult dict
        """
        text = (interaction_text or "").strip()
        signal_strength = self._assess_signal_strength(
            text, recent_signals or []
        )

        # ── 分支1：信号稀疏 → 保守推进，生成探测问题 ──
        if signal_strength == "sparse":
            return self._sparse_diagnosis(last_known_stage, person_id)

        # ── 分支2：信号充足 → 正常判定 ──
        return self._normal_diagnosis(text, last_known_stage)

    # ── 信号强度评估 ──

    def _assess_signal_strength(
        self, text: str, recent_signals: list[dict]
    ) -> str:
        """评估当前可用信号的密度"""
        if len(text) < MIN_CHARS_FOR_ANALYSIS:
            # 文字太短 + 近期无有效信号
            active_signals = [
                s for s in recent_signals
                if self._signal_is_fresh(s)
            ]
            if len(active_signals) < MIN_SIGNALS_FOR_CONFIDENCE:
                return "sparse"
        return "normal"

    def _signal_is_fresh(self, signal: dict) -> bool:
        """信号是否在衰减期之前"""
        created = signal.get("created_at")
        if not created:
            return True
        if isinstance(created, str):
            created = datetime.fromisoformat(created.replace("Z", "+00:00"))
        age_days = (datetime.now(timezone.utc) - created).days
        return age_days < SIGNAL_DECAY_DAYS

    # ── 稀疏信号分支 ──

    def _sparse_diagnosis(
        self, last_known_stage: str | None, person_id: str
    ) -> dict:
        """
        信号不足时的默认策略：
        - 按上次已知阶段保守推进
        - 标注不确定性
        - 给出具体的探测问题（以给换得）
        """
        assumed_stage = last_known_stage or "stage_a_problem_unawareness"
        probe = self._generate_probe_question(assumed_stage)

        return {
            "stage": "unclear",
            "confidence": "low",
            "signal_strength": "sparse",
            "fallback_assumed_stage": assumed_stage,
            "uncertainty_flag": True,
            "suggested_probe": probe,
            "caution": (
                "当前信号不足，以下建议基于上次已知阶段，"
                "实际阶段可能有偏差。建议用探测问题获取更多信号。"
            ),
        }

    def _generate_probe_question(self, assumed_stage: str) -> dict:
        """
        生成"以给换得"探测问题。

        原则：不问"你卡在哪了"——给客户一个有价值的东西，
        用客户的反应来判断阶段。
        """
        probes = {
            "stage_a_problem_unawareness": {
                "action": "发送同行业客户的前后对比数据",
                "sample_phrasing": (
                    "我们梳理了XX行业几家公司在[类似场景]下的数据——"
                    "处理这个问题的团队，平均每年能省下 XX 万成本。"
                    "发你看看，也许可以作为内部推动的参考。"
                ),
                "what_to_watch": (
                    "他的反应告诉你他是否真的关心这个问题："
                    "追问具体数字 → 警觉了 / 只回'好的' → 还在阶段A或C"
                ),
            },
            "stage_b_fear_of_failure": {
                "action": "发送分步实施方案（含退出机制）",
                "sample_phrasing": (
                    "我整理了一个三段式的实施计划，每一步都有明确的"
                    "完成标准。如果哪一步达不到预期，随时可以停——"
                    "不用一次性承诺全量。你看看这个思路对不对。"
                ),
                "what_to_watch": (
                    "他的反应告诉你卡在哪里："
                    "讨论哪一步有问题 → 已跨过怕担责 / "
                    "不回或说'再看看' → 仍卡在阶段B"
                ),
            },
            "stage_c_status_quo_bias": {
                "action": "发送现状风险推演（外部变化视角）",
                "sample_phrasing": (
                    "最近行业有几个变化——[具体变化]。"
                    "我推演了一下，如果维持现在这套方案，"
                    "在未来12-18个月可能会面临几个风险点。"
                    "发你看看，不是说你现在的方案不好——"
                    "是外部环境在变，大家一起看看。"
                ),
                "what_to_watch": (
                    "是否愿意讨论风险点："
                    "追问具体风险 → 开始重新审视现状 / "
                    "说'没事我们不担心' → 仍在阶段C"
                ),
            },
        }
        return probes.get(assumed_stage, probes["stage_a_problem_unawareness"])

    # ── 正常判定分支 ──

    def _normal_diagnosis(
        self, text: str, last_known_stage: str | None
    ) -> dict:
        """信号充足时执行完整规则匹配"""
        matched_rules = self._match_rules(text)

        # ── Override 优先级处理 ──
        override_rules = [
            r for r in matched_rules
            if r.get("priority") == "override"
        ]
        if override_rules:
            new_stage = override_rules[0]["implies_stage"]
            stage_changed = (
                last_known_stage is not None
                and last_known_stage != new_stage
            )

            # 冷却期逻辑：第一次 override → 标记待确认
            if stage_changed:
                return {
                    "stage": last_known_stage,
                    "confidence": "medium",
                    "signal_strength": "normal",
                    "override_triggered": True,
                    "override_pending_stage": new_stage,
                    "override_reason": self._build_reasoning(override_rules),
                    "alert": (
                        f"⚠️ 检测到阶段跳变信号（{new_stage}），"
                        "建议本轮多问一轮确认后再切换。"
                    ),
                    "suggested_confirm_question": (
                        "你刚才提到[引用原话中的关键词]，"
                        "是不是你们内部对这个项目的审批流程有什么变化？"
                    ),
                }

            # 已确认的 override → 直接切换
            return {
                "stage": new_stage,
                "confidence": "high",
                "signal_strength": "normal",
                "override_triggered": False,
                "override_confirmed": True,
                "reasoning": self._build_reasoning(override_rules),
            }

        # ── 无 override → 聚合判定 ──
        if not matched_rules:
            return {
                "stage": "unclear",
                "confidence": "medium",
                "signal_strength": "normal",
                "reasoning": [],
                "note": "文本长度足够但未匹配到任何信号模式——"
                        "建议人工复核或等下一轮互动再判定",
            }

        return self._aggregate_rules(matched_rules)

    # ── 规则匹配 ──

    def _match_rules(self, text: str) -> list[dict]:
        """关键词模式匹配"""
        matched = []
        for rule in SIGNAL_RULES:
            for pattern in rule["patterns"]:
                if re.search(pattern, text):
                    matched.append({
                        "signal_type": rule["signal_type"],
                        "implies_stage": rule["implies_stage"],
                        "priority": rule["priority"],
                        "theory": rule["theory"],
                        "matched_pattern": pattern,
                    })
                    break  # 一条规则只匹配一次
        return matched

    # ── 聚合 ──

    def _aggregate_rules(self, matched_rules: list[dict]) -> dict:
        """多信号聚合：按优先级和频率综合判定"""
        # 统计每个阶段的命中数
        from collections import Counter
        stage_counts = Counter(
            r["implies_stage"] for r in matched_rules
        )

        # 如果有高优先级信号，用它的阶段
        high_priority = [
            r for r in matched_rules if r.get("priority") == "high"
        ]
        if high_priority:
            dominant_stage = high_priority[0]["implies_stage"]
        else:
            dominant_stage = stage_counts.most_common(1)[0][0]

        confidence = "high" if len(matched_rules) >= 3 else "medium"

        return {
            "stage": dominant_stage,
            "confidence": confidence,
            "signal_strength": "normal",
            "matched_signals": stage_counts,
            "reasoning": self._build_reasoning(matched_rules),
        }

    # ── 可解释性 ──

    def _build_reasoning(self, rules: list[dict]) -> list[dict]:
        return [
            {
                "matched_signal": r["signal_type"],
                "matched_pattern": r.get("matched_pattern", ""),
                "theory_basis": r["theory"],
                "engine_version": "v3.1",
            }
            for r in rules
        ]
