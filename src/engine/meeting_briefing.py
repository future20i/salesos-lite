"""
MeetingBriefingGenerator v3.1
— 多人会议场景 → 一条整合策略（而非 N 条独立简报）
— 主攻对象选择 + 阶段冲突约束 + 会前行动 + 会中叙事弧
"""

import logging

logger = logging.getLogger(__name__)


class MeetingBriefingGenerator:
    """
    多人会议策略生成器。

    输入：opportunity_id + 多个 person 的阶段判定
    输出：一条整合会议策略
    """

    def generate(
        self,
        opportunity_summary: dict,
        attendees: list[dict],
    ) -> dict:
        """
        attendees: [
          {
            person_id, name, role_type, influence_level,
            stage, blockage_source, recommended_strategy
          },
          ...
        ]
        opportunity_summary: { name, industry, value, current_stage, ... }
        """
        if not attendees:
            return {"error": "no_attendees"}

        # 1. 主攻对象选择
        primary = self._select_primary_target(attendees)
        secondary = [a for a in attendees if a["person_id"] != primary["person_id"]]

        # 2. 阶段冲突分析
        constraints = self._analyze_stage_constraints(primary, secondary)

        # 3. 会前行动
        pre_meeting = self._generate_pre_meeting_actions(primary, secondary, constraints)

        # 4. 会中叙事弧
        in_meeting = self._generate_in_meeting_arcs(primary, secondary, constraints, opportunity_summary)

        # 5. 会后跟进
        post_meeting = self._generate_post_meeting(primary)

        return {
            "meeting_objective": self._one_line_objective(primary, opportunity_summary),
            "primary_target": {
                "name": primary["name"],
                "role": primary.get("role_type", ""),
                "stage": primary["stage"],
                "why_primary": self._explain_why_primary(primary, opportunity_summary),
                "strategy_direction": primary.get(
                    "recommended_strategy", {}
                ).get("direction", ""),
            },
            "secondary_attendees": [
                {
                    "name": a["name"],
                    "role": a.get("role_type", ""),
                    "stage": a["stage"],
                    "constraint": constraints.get(a["person_id"], ""),
                }
                for a in secondary
            ],
            "pre_meeting_actions": pre_meeting,
            "in_meeting_arcs": in_meeting,
            "post_meeting": post_meeting,
            "red_lines": self._collect_red_lines(primary, secondary),
        }

    # ── 主攻对象选择 ──

    def _select_primary_target(self, attendees: list[dict]) -> dict:
        """
        优先级：
        1. 高影响力 + 阶段A → 最高
        2. 高影响力 + 阶段B → 次高
        3. 任何人 + 阶段A/B → 有推进空间
        4. 第一个人 → fallback
        """
        high_influence = [
            a for a in attendees
            if a.get("influence_level") == "high"
        ]
        if high_influence:
            stage_a_dm = [
                d for d in high_influence
                if d["stage"] == "stage_a_problem_unawareness"
            ]
            if stage_a_dm:
                return stage_a_dm[0]
            stage_b_dm = [
                d for d in high_influence
                if d["stage"] == "stage_b_fear_of_failure"
            ]
            if stage_b_dm:
                return stage_b_dm[0]
            return high_influence[0]

        actionable = [
            a for a in attendees
            if a["stage"] in (
                "stage_a_problem_unawareness",
                "stage_b_fear_of_failure",
            )
        ]
        if actionable:
            return actionable[0]
        return attendees[0]

    def _explain_why_primary(
        self, primary: dict, opp: dict
    ) -> str:
        stage_reasons = {
            "stage_a_problem_unawareness": (
                f"{primary['name']}还没有意识到这个问题的代价有多大。"
                "这次会议的核心目标是让他看到'不动的代价'——"
                "在他心中种下'这个问题值得立项'的种子。"
            ),
            "stage_b_fear_of_failure": (
                f"{primary['name']}已认可需求但卡在担责恐惧上。"
                "这次的核心目标不是说服他方案好——"
                "是让他看到'选我们这件事没有他担心的那么危险'。"
            ),
            "stage_c_status_quo_bias": (
                f"{primary['name']}倾向于维持现状。"
                "这次不试图'说服'——试图'邀请'他重新审视现状。"
                "用外部变化作为理由，不挑战他过去的判断。"
            ),
            "unclear": (
                f"{primary['name']}的阶段尚未判定。"
                "这次会议的首要任务是试探——"
                "通过信息交换观察他的反应来判断他卡在哪。"
            ),
        }
        return stage_reasons.get(
            primary["stage"],
            stage_reasons["unclear"],
        )

    def _one_line_objective(
        self, primary: dict, opp: dict
    ) -> str:
        opp_name = opp.get("name", "该项目")
        person_name = primary["name"]
        obj_map = {
            "stage_a_problem_unawareness": (
                f"让 {person_name} 意识到 {opp_name} 的现状代价——建立紧迫感"
            ),
            "stage_b_fear_of_failure": (
                f"帮 {person_name} 降低决策风险感——给他退路和同行先例"
            ),
            "stage_c_status_quo_bias": (
                f"用外部变化数据邀请 {person_name} 重新审视现状——不挑战、只邀请"
            ),
            "unclear": (
                f"通过信息交换试探 {person_name} 的关注点——先判断阶段再决定策略"
            ),
        }
        return obj_map.get(primary["stage"], obj_map["unclear"])

    # ── 冲突分析 ──

    def _analyze_stage_constraints(
        self, primary: dict, secondary: list[dict]
    ) -> dict:
        constraints = {}

        for person in secondary:
            pid = person["person_id"]
            ps = person["stage"]

            if primary["stage"] == "stage_a_problem_unawareness" and ps == "stage_c_status_quo_bias":
                constraints[pid] = (
                    f"⚠️ {person['name']} 倾向维持现状。"
                    "避免在他面前直接讲'不改变的代价'——"
                    "他会觉得你在否定他此前的判断。"
                    "会前单独沟通，不要在会场上挑战他。"
                )
            elif primary["stage"] == "stage_a_problem_unawareness" and ps == "stage_b_fear_of_failure":
                constraints[pid] = (
                    f"{person['name']} 已认可需求但怕担责。"
                    "主攻阶段A策略会自然覆盖到他的关切。"
                    "不需要专门对他讲代价——他已经过了那个阶段。"
                )
            elif primary["stage"] == "stage_b_fear_of_failure" and ps == "stage_a_problem_unawareness":
                constraints[pid] = (
                    f"{person['name']} 还没意识到问题严重性。"
                    "会议开头先讲代价（覆盖他的阶段A需求），"
                    "再自然过渡到降险策略——两种需求都要覆盖。"
                )
            elif primary["stage"] == "stage_b_fear_of_failure" and ps == "stage_c_status_quo_bias":
                constraints[pid] = (
                    f"⚠️ {person['name']} 倾向维持现状。"
                    "降险策略对他可能不够——他需要的是重新审视现状的理由。"
                    "建议会前单独沟通，不要在会议上让两种策略冲突。"
                )

        return constraints

    # ── 会前行动 ──

    def _generate_pre_meeting_actions(
        self, primary: dict, secondary: list[dict], constraints: dict
    ) -> list[dict]:
        actions = []

        # 阶段C者 → 会前对齐
        stage_c_attendees = [
            a for a in secondary
            if a["stage"] == "stage_c_status_quo_bias"
        ]
        for person in stage_c_attendees:
            actions.append({
                "type": "pre_align",
                "target": person["name"],
                "action": (
                    f"会前单独和 {person['name']} 通个电话或喝个茶。"
                    "不是'搞定他'——是提前让他知道会议要讨论什么，"
                    "给他心理准备。"
                ),
                "sample_phrasing": (
                    f"'{person['name']}，下周的会上我会分享一些行业变化数据，"
                    "主要是帮大家对齐信息——您先看看有没有您觉得需要补充的。'"
                ),
            })

        # 阶段B者 → 提前给材料
        stage_b_attendees = [
            a for a in secondary
            if a["stage"] == "stage_b_fear_of_failure"
        ]
        if stage_b_attendees:
            names = "、".join(a["name"] for a in stage_b_attendees)
            actions.append({
                "type": "pre_material",
                "targets": [a["name"] for a in stage_b_attendees],
                "action": (
                    f"会前给 {names} 发一份会议背景材料。"
                    "让他们在会前就有安全感——知道讨论范围、不会被迫表态。"
                ),
                "material_checklist": [
                    "讨论范围说明（不含决策，仅信息交流）",
                    "同类项目参考数据（行业级别，不给具体公司名）",
                    "拟讨论的技术要点（让他们提前准备）",
                ],
            })

        return actions

    # ── 会中叙事弧 ──

    def _generate_in_meeting_arcs(
        self,
        primary: dict,
        secondary: list[dict],
        constraints: dict,
        opp: dict,
    ) -> list[dict]:
        arcs = []

        # 开场 — 建立安全感
        arcs.append({
            "phase": "开场（前5分钟）",
            "purpose": "建立安全感和会议边界",
            "sample_phrasing": (
                "感谢各位的时间。今天主要想跟大家同步一下我们观察到的一些行业变化，"
                "以及几家公司他们在类似情况下的做法。"
                "不做决策讨论，纯粹是信息交流。"
            ),
            "note": (
                "先说'不做决策'降低阶段B者的压力。"
                "说'行业变化'打开阶段C者的信息缺口。"
            ),
        })

        # 主体1：如果有阶段A的与会者（包括主攻对象）
        stage_a_folks = [
            a for a in [primary] + secondary
            if a["stage"] == "stage_a_problem_unawareness"
        ]
        if stage_a_folks:
            arcs.append({
                "phase": "问题呈现（5-10分钟）",
                "targets": [a["name"] for a in stage_a_folks],
                "purpose": (
                    "让阶段A的人意识到'这个问题的代价比想象中大'"
                ),
                "sample_phrasing": (
                    "我们梳理了这个行业过去三年的数据——"
                    "在[具体问题]这个环节上，"
                    "平均每年因为非计划停机造成的直接损失在 XX 万量级。"
                    "而且这个数字在过去两年在持续上升。"
                ),
                "caution": (
                    "有阶段C的与会者在场时——"
                    "用'行业整体数据'而非'你们的现状'。避免直接挑战。"
                ) if any(
                    a["stage"] == "stage_c_status_quo_bias"
                    for a in secondary
                ) else "",
            })

        # 主体2：如果有阶段B的与会者
        stage_b_folks = [
            a for a in [primary] + secondary
            if a["stage"] == "stage_b_fear_of_failure"
        ]
        if stage_b_folks:
            arcs.append({
                "phase": "方案呈现（10-15分钟）",
                "targets": [a["name"] for a in stage_b_folks],
                "purpose": (
                    "不是'说服他方案好'——是让他看到"
                    "'选这件事没有他担心的那么危险'"
                ),
                "sample_phrasing": (
                    "关于各位最关心的实施风险，我重点讲两个部分。"
                    "第一，我们的分阶段实施机制——每一步都有明确的完成标准和退出条件。"
                    "第二，几家公司在类似体量项目上的做法和风险控制经验。"
                ),
                "caution": "不说'我们的方案最安全'——让他自己判断。你只给数据和案例。",
            })

        # 收尾
        arcs.append({
            "phase": "收尾（5分钟）",
            "purpose": "不给压力地推动下一步",
            "sample_phrasing": (
                "今天聊的行业数据、变化趋势、还有几家的做法——"
                "我回头整理一份发给各位。"
                "各位如果有需要我单独再聊的细节，随时跟我说。"
            ),
            "note": (
                "不说'下次再约'——把主动权给他。"
                "你留的是'材料'和'随时'——他不觉得被逼。"
                "如果他主动提下一步，那就是真信号。"
            ),
        })

        return arcs

    # ── 会后 ──

    def _generate_post_meeting(self, primary: dict) -> dict:
        return {
            "immediate": (
                "24小时内发送会议纪要 + 承诺的数据/案例。"
                "不是群发——给每个人单独发，内容根据他的阶段微调。"
            ),
            "followup_signal": (
                "看他的回复速度和质量——"
                "如果他三天内追问了你提到的某个数据 → 强信号 → 阶段可能在推进。"
                "如果一周没消息 → 可能需要一次不相关的互动重新建立联系。"
            ),
        }

    # ── 雷区 ──

    def _collect_red_lines(
        self, primary: dict, secondary: list[dict]
    ) -> list[str]:
        red_lines = []

        all_people = [primary] + secondary

        # 如果有阶段B者 → 禁用紧迫感
        has_stage_b = any(
            a["stage"] == "stage_b_fear_of_failure" for a in all_people
        )
        if has_stage_b:
            red_lines.append(
                "不要使用'限时优惠''再不决定就XX'等紧迫感话术——"
                "场内有阶段B的决策者，这会让他的压力暴增。"
            )

        # 如果有阶段C者 → 不否定现状
        has_stage_c = any(
            a["stage"] == "stage_c_status_quo_bias" for a in all_people
        )
        if has_stage_c:
            red_lines.append(
                "不要直接说'你们现在这套方案不行'——"
                "有阶段C的与会者在场——否定现状等于否定他过去的判断。"
            )

        # 通用雷区
        red_lines.append(
            "不要在会议上请任何人当场表态——"
            "B2B决策从来不是在会上做的。会上表决 = 逼人拒绝。"
        )

        # 如果主攻阶段A且有阶段B在场
        if (
            primary["stage"] == "stage_a_problem_unawareness"
            and has_stage_b
        ):
            red_lines.append(
                "主攻阶段A（讲代价）但场内有阶段B者——"
                "讲完代价后必须立刻衔接'但我们有办法控制这些风险'——"
                "不能把代价悬在那里不收。"
            )

        return red_lines
