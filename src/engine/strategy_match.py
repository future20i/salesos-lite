"""
StrategyMatchEngine v3.1
— 输入阶段判定 + blockage_source → 输出策略建议（四合一）
— 每条输出：方向 + why + 话术示例 + 警惕 + 禁用清单
"""

from src.engine.strategy_phrasings import (
    STAGE_A_STRATEGIES,
    STAGE_B_STRATEGIES,
    STAGE_C_STRATEGIES,
    STAGE_B_FORBIDDEN,
    BLOCKAGE_ACTION_CATALOG,
    UNIVERSAL_GUIDANCE,
)

# ── 策略分组索引 ──
STRATEGY_GROUPS = {
    "stage_a_problem_unawareness": {
        "strategies": STAGE_A_STRATEGIES,
        "forbidden": [],  # 阶段A无禁用项
        "guidance": "讲清楚不解决的真实代价，建立紧迫感",
    },
    "stage_b_fear_of_failure": {
        "strategies": STAGE_B_STRATEGIES,
        "forbidden": STAGE_B_FORBIDDEN,
        "guidance": "降低决策风险感，提供退路与责任分担，绝不催单",
    },
    "stage_c_status_quo_bias": {
        "strategies": STAGE_C_STRATEGIES,
        "forbidden": [],
        "guidance": "邀请客户共同重新核实现状，不直接否定",
    },
    "unclear": {
        "strategies": {},
        "forbidden": [{
            "action": "any_strategic_push",
            "label": "任何策略性推进",
            "why_forbidden": "阶段不清时使用任何策略都可能方向错误",
        }],
        "guidance": "先多问一轮以确认阶段，本轮不推荐任何策略性动作",
    },
}


class StrategyMatchEngine:
    """
    策略匹配引擎 v3.1。

    输入：阶段判定结果 + blockage_source（可选）
    输出：策略建议列表（四合一格式）+ 禁用清单
    """

    def recommend(
        self,
        stage: str,
        blockage_source: str | None = None,
        uncertainty_flag: bool = False,
    ) -> dict:
        group = STRATEGY_GROUPS.get(stage, STRATEGY_GROUPS["unclear"])

        # ── 构建策略建议列表 ──
        recommendations = []
        for key, strat in group["strategies"].items():
            rec = {
                "id": key,
                "direction": strat["direction"],
                "why_this_matters": strat["why_this_matters"],
                "sample_phrasing": strat["sample_phrasing"],
                "watch_out": strat["watch_out"],
            }
            recommendations.append(rec)

        # ── blockage 专项动作 ──
        blockage_actions = []
        if blockage_source and blockage_source in BLOCKAGE_ACTION_CATALOG:
            blockage_actions = BLOCKAGE_ACTION_CATALOG[blockage_source]

        # ── 复用通用原则 ──
        universal = []
        for key, item in UNIVERSAL_GUIDANCE.items():
            if key == "decision_fatigue":
                universal.append({
                    "id": key,
                    "direction": item["direction"],
                    "why": item["why"],
                    "rule": item["rule"],
                })

        return {
            "stage": stage,
            "guidance": group["guidance"],
            "uncertainty_flag": uncertainty_flag,
            "recommendations": recommendations,
            "blockage_actions": blockage_actions,
            "forbidden": group["forbidden"],
            "universal": universal,
            "self_check": UNIVERSAL_GUIDANCE["compliance_self_check"]["question"],
        }

    def stage_summary(self, stage: str, blockage_source: str | None = None) -> dict:
        """快速摘要——用于微信一句话推送场景"""
        group = STRATEGY_GROUPS.get(stage, STRATEGY_GROUPS["unclear"])

        summary_map = {
            "stage_a_problem_unawareness": (
                "先让他看到不动的代价。别说教。"
            ),
            "stage_b_fear_of_failure": (
                "别催。给退路+给案例+帮他推动内部。"
            ),
            "stage_c_status_quo_bias": (
                "不挑战现状。用外部变化邀请他重新审视。"
            ),
            "unclear": "信号不够。先试探，别急着推。",
        }

        caution_map = {
            "stage_b_fear_of_failure": "⛔ 不催单 不施压 不讲代价",
            "unclear": "⛔ 先不推任何策略",
        }

        return {
            "stage": stage,
            "one_liner": summary_map.get(stage, summary_map["unclear"]),
            "caution": caution_map.get(stage, ""),
            "blockage_hint": (
                BLOCKAGE_ACTION_CATALOG.get(blockage_source, [{}])[0].get(
                    "action", ""
                )
                if blockage_source
                else ""
            ),
        }
