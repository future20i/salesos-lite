"""
Phase 2C — Intel Engine: four AI-driven intelligence cycles for the person portrait system.

B1 战前简报 (Pre-Battle Briefing): 30-second summary before opening a conversation.
B2 策略伴写 (Strategy Co-Write): what to say / avoid / hooks when drafting.
B3 自动复盘 (Auto Retrospective): extract new info and update profile after interaction.
B4 资源匹配 (Resource Matching): relationship-deepening opportunity recommendations.
"""

import json
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# B1 — 战前简报 (Pre-Battle Briefing)
# ═══════════════════════════════════════════════════════════════════════════════

async def generate_briefing(person_data: dict, recent_interactions: list[dict] | None = None) -> dict:
    """Generate a 30-second pre-battle briefing for a contact.

    Args:
        person_data: decrypted person profile dict (layers 1-4)
        recent_interactions: last 5 interaction summaries

    Returns:
        {who, cares_about, last_interaction, personal_touch_points, suggested_opener, risk_zones}
    """
    from src.llm_client import llm_complete

    # Build context
    context_parts = [f"联系人: {person_data.get('full_name', '未知')}"]
    if person_data.get('title'):
        context_parts.append(f"职位: {person_data['title']}")
    if person_data.get('hometown'):
        context_parts.append(f"家乡: {person_data['hometown']}")
    if person_data.get('education'):
        context_parts.append(f"教育: {person_data['education']}")
    if person_data.get('personality_tags'):
        context_parts.append(f"性格标签: {json.dumps(person_data['personality_tags'], ensure_ascii=False)}")

    # Interests
    interests = person_data.get('interests', [])
    if interests:
        interest_str = ", ".join(
            i.get('detail', i.get('category', '')) if isinstance(i, dict) else str(i)
            for i in interests
        )
        context_parts.append(f"兴趣爱好: {interest_str}")

    # Personal details
    if person_data.get('spouse_name'):
        context_parts.append(f"配偶: {person_data['spouse_name']}")
    children = person_data.get('children_info', [])
    if children:
        kids = ", ".join(
            f"{c.get('name','')}({c.get('age','')}岁,{c.get('school','')})"
            for c in children
        )
        context_parts.append(f"子女: {kids}")

    # Trust foundation (layer 3 — only for briefing requester)
    if person_data.get('trust_foundation'):
        context_parts.append(f"信任基础: {person_data['trust_foundation']}")
    if person_data.get('org_situation'):
        context_parts.append(f"组织处境: {person_data['org_situation']}")

    # Recent interactions
    if recent_interactions:
        interaction_lines = []
        for ix in recent_interactions[:5]:
            interaction_lines.append(
                f"- [{ix.get('interaction_type','')}] {ix.get('summary','')[:200]}"
            )
        context_parts.append("近期互动:\n" + "\n".join(interaction_lines))

    context = "\n".join(context_parts)

    prompt = f"""你是销售情报分析师。基于以下联系人信息，生成一份30秒战前简报。用中文回复，JSON格式。

{context}

返回JSON：
{{
  "who": "一句话概括这个人是谁（职位+性格+在公司里的角色）",
  "cares_about": ["最关心的3件事"],
  "last_interaction": "上次互动摘要（或'无记录'）",
  "personal_touch_points": ["2-3个可以聊的私人话题"],
  "suggested_opener": "建议的开场白（自然口语化）",
  "risk_zones": ["1-2个需要避开的雷区"],
  "relationship_score": 1-10 关系深度评估
}}

只返回JSON，不要其他文字。"""

    try:
        response = await llm_complete(prompt)
        # Extract JSON from response
        response = response.strip()
        if response.startswith("```"):
            response = response.split("\n", 1)[1]
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()
            if response.startswith("json"):
                response = response[4:].strip()
        return json.loads(response)
    except Exception as e:
        logger.exception("B1 briefing generation failed")
        return {
            "who": f"{person_data.get('full_name', '未知')}，{person_data.get('title', '未知职位')}",
            "cares_about": [],
            "last_interaction": "无记录",
            "personal_touch_points": [],
            "suggested_opener": f"{person_data.get('full_name','')}你好，最近怎么样？",
            "risk_zones": [],
            "relationship_score": 5,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# B2 — 策略伴写 (Strategy Co-Write)
# ═══════════════════════════════════════════════════════════════════════════════

async def generate_strategy_card(
    person_data: dict,
    opportunity_context: str = "",
    message_context: str = "",
) -> dict:
    """Generate a strategy card for composing a message.

    Returns:
        {say, avoid, hooks, tone, reference_points}
    """
    from src.llm_client import llm_complete

    parts = [f"联系人: {person_data.get('full_name', '未知')}"]
    if person_data.get('title'):
        parts.append(f"职位: {person_data['title']}")

    # Layer 3-4 intel
    if person_data.get('core_fear'):
        parts.append(f"核心恐惧: {person_data['core_fear']}")
    if person_data.get('core_ambition'):
        parts.append(f"核心野心: {person_data['core_ambition']}")
    if person_data.get('org_situation'):
        parts.append(f"组织处境: {person_data['org_situation']}")

    # Leverage points
    leverage = person_data.get('leverage_points', [])
    if leverage:
        lev_str = "\n".join(
            f"- {lp.get('type','')}: {lp.get('detail','')}"
            for lp in leverage
        )
        parts.append(f"可用的影响力杠杆:\n{lev_str}")

    # Relationship depth
    if person_data.get('relationship_depth'):
        parts.append(f"关系深度: {person_data['relationship_depth']}/10")

    if opportunity_context:
        parts.append(f"商机背景: {opportunity_context}")
    if message_context:
        parts.append(f"对话上下文: {message_context}")

    context = "\n\n".join(parts)

    prompt = f"""你是B2B销售策略顾问。基于以下情报，为业务员起草回复时提供策略建议。用中文，JSON格式。

{context}

返回JSON：
{{
  "say": ["应该强调的3个要点"],
  "avoid": ["2-3个绝对不要触碰的话题或措辞"],
  "hooks": ["2-3个可以引起对方兴趣的钩子（基于其兴趣/野心/恐惧）"],
  "tone": "建议的语气（如：专业直接/温暖关怀/数据驱动/谦逊请教）",
  "reference_points": ["可以引用的1-2个共同话题或过往互动"]
}}

只返回JSON。"""

    try:
        response = await llm_complete(prompt)
        response = response.strip()
        if response.startswith("```"):
            response = response.split("\n", 1)[1]
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()
            if response.startswith("json"):
                response = response[4:].strip()
        return json.loads(response)
    except Exception as e:
        logger.exception("B2 strategy card failed")
        return {
            "say": ["保持专业", "关注对方需求", "提供价值"],
            "avoid": ["不要催促", "不要贬低竞品"],
            "hooks": ["询问最近项目进展"],
            "tone": "专业友好",
            "reference_points": [],
        }


# ═══════════════════════════════════════════════════════════════════════════════
# B3 — 自动复盘 (Auto Retrospective)
# ═══════════════════════════════════════════════════════════════════════════════

async def auto_retrospect(
    message_content: str,
    person_data: dict,
    interaction_type: str = "message",
) -> dict:
    """Extract new personal information from a message and suggest profile updates.

    Returns:
        {extracted_facts: [{field, value, confidence}], suggested_tags: [...],
         new_interests: [...], relationship_delta: int, follow_up_date: str|None}
    """
    from src.llm_client import llm_complete

    # Build person summary without layer 3-4 (those are sensitive)
    person_summary_parts = []
    for field in ['full_name', 'title', 'birthday', 'hometown', 'education',
                   'spouse_name', 'spouse_occupation']:
        if person_data.get(field):
            person_summary_parts.append(f"{field}: {person_data[field]}")
    if person_data.get('interests'):
        person_summary_parts.append(f"已知兴趣: {json.dumps(person_data['interests'], ensure_ascii=False)}")
    if person_data.get('children_info'):
        person_summary_parts.append(f"子女: {json.dumps(person_data['children_info'], ensure_ascii=False)}")

    prompt = f"""你是销售情报分析师。从以下对话中提取关于联系人的新个人信息，判断哪些可以更新到画像中。

已有画像：
{chr(10).join(person_summary_parts)}

对话内容 ({interaction_type}):
{message_content[:2000]}

提取规则：
- 只提取新信息（画像中没有的）
- 置信度分高(>0.8)/中(0.5-0.8)/低(<0.5)
- 字段名用英文（如 birthday, children_info, interests, spouse_name 等）
- 只返回真正有价值的信息，不要硬凑

返回JSON：
{{
  "extracted_facts": [
    {{"field": "字段名", "value": "新值", "confidence": 0.9, "evidence": "原文证据"}}
  ],
  "suggested_tags": ["新标签"],
  "relationship_delta": -1到+3之间的整数（这次互动对关系的影响程度）,
  "follow_up_date": "建议下次联系的日期(YYYY-MM-DD)或null",
  "summary": "一句话总结这次互动"
}}

只返回JSON。"""

    try:
        response = await llm_complete(prompt)
        response = response.strip()
        if response.startswith("```"):
            response = response.split("\n", 1)[1]
            if response.endswith("```"):
                response = response[:-3]
            response = response.strip()
            if response.startswith("json"):
                response = response[4:].strip()
        return json.loads(response)
    except Exception as e:
        logger.exception("B3 auto retrospect failed")
        return {
            "extracted_facts": [],
            "suggested_tags": [],
            "relationship_delta": 0,
            "follow_up_date": None,
            "summary": "",
        }


async def apply_retrospect_updates(person_profile_id: uuid.UUID, tenant_id: uuid.UUID, retrospect: dict) -> int:
    """Apply extracted facts from auto retrospect to the person profile.

    Returns number of fields updated.
    """
    from src.database import AsyncSessionLocal
    from src.models.person_profile import PersonProfile
    from sqlalchemy import select

    facts = retrospect.get("extracted_facts", [])
    if not facts:
        return 0

    # Only apply high-confidence facts
    high_conf = [f for f in facts if f.get("confidence", 0) >= 0.8]
    if not high_conf:
        return 0

    updates = 0
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PersonProfile).where(
                    PersonProfile.id == person_profile_id,
                    PersonProfile.tenant_id == tenant_id,
                )
            )
            profile = result.scalar_one_or_none()
            if profile is None:
                return 0

            for fact in high_conf:
                field = fact["field"]
                value = fact["value"]
                if not hasattr(profile, field):
                    continue
                current = getattr(profile, field)
                # Don't overwrite existing data unless new data is richer
                if current is None or (isinstance(current, str) and len(str(value)) > len(current)):
                    setattr(profile, field, value)
                    updates += 1

            if updates:
                # Update relationship depth if delta is significant
                delta = retrospect.get("relationship_delta", 0)
                if delta != 0 and profile.relationship_depth is not None:
                    profile.relationship_depth = max(1, min(10, profile.relationship_depth + delta))
                    updates += 1

                profile.updated_at = datetime.now(timezone.utc)
                await db.commit()

    except Exception:
        logger.exception("apply_retrospect_updates failed")

    return updates


# ═══════════════════════════════════════════════════════════════════════════════
# B4 — 资源匹配引擎 (Resource Matching)
# ═══════════════════════════════════════════════════════════════════════════════

async def recommend_relationship_actions(tenant_id: uuid.UUID) -> list[dict]:
    """Scan all person profiles and recommend relationship-deepening actions.

    Returns list of {person_id, person_name, action_type, action_detail, reason, urgency: 1-5}
    """
    from src.database import AsyncSessionLocal
    from src.models.person_profile import PersonProfile
    from sqlalchemy import select

    recommendations = []
    try:
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(PersonProfile).where(
                    PersonProfile.tenant_id == tenant_id,
                ).order_by(PersonProfile.updated_at.desc()).limit(50)
            )
            profiles = result.scalars().all()

        for profile in profiles:
            actions = _check_person_triggers(profile)
            recommendations.extend(actions)

        # Sort by urgency descending
        recommendations.sort(key=lambda x: x.get("urgency", 0), reverse=True)
    except Exception:
        logger.exception("B4 resource matching failed")

    return recommendations[:20]


def _check_person_triggers(profile) -> list[dict]:
    """Check a single person profile for relationship triggers."""
    triggers = []
    now = datetime.now(timezone.utc)
    person_name = profile.full_name or "未知"

    # Trigger 1: Birthday within 7 days
    if profile.birthday:
        try:
            bday_parts = profile.birthday.split("-")
            if len(bday_parts) >= 2:
                bday_this_year = datetime(now.year, int(bday_parts[0]), int(bday_parts[1]), tzinfo=timezone.utc)
                days_until_bday = (bday_this_year - now).days
                if 0 <= days_until_bday <= 7:
                    triggers.append({
                        "person_id": str(profile.id),
                        "person_name": person_name,
                        "action_type": "personal_milestone",
                        "action_detail": f"生日（{profile.birthday}），还有{days_until_bday}天",
                        "reason": f"生日祝福是低成本高回报的关系维护",
                        "urgency": 4 if days_until_bday <= 2 else 3,
                    })
        except (ValueError, IndexError):
            pass

    # Trigger 2: No personal touch in 30+ days
    if profile.last_personal_touch_at:
        days_since = (now - profile.last_personal_touch_at).days
        if days_since > 30:
            triggers.append({
                "person_id": str(profile.id),
                "person_name": person_name,
                "action_type": "value_output",
                "action_detail": f"上次私人接触在{days_since}天前",
                "reason": "超过30天没有私人接触，需要发送行业报告或相关资讯重新建立连接",
                "urgency": 3 if days_since > 60 else 2,
            })

    # Trigger 3: Interests match — suggest activity
    interests = profile.interests or []
    if interests:
        interest_categories = [i.get("category", "") for i in interests if isinstance(i, dict)]
        for cat in interest_categories:
            action = _match_interest_action(cat)
            if action:
                triggers.append({
                    "person_id": str(profile.id),
                    "person_name": person_name,
                    "action_type": "interest_connection",
                    "action_detail": action,
                    "reason": f"基于兴趣'{cat}'推荐深化活动",
                    "urgency": 1,
                })

    # Trigger 4: Children milestone
    children = profile.children_info or []
    for child in children:
        milestone = child.get("milestone", "")
        if milestone and "毕业" in str(milestone) or "高考" in str(milestone) or "升学" in str(milestone):
            triggers.append({
                "person_id": str(profile.id),
                "person_name": person_name,
                "action_type": "personal_milestone",
                "action_detail": f"子女里程碑: {child.get('name','子女')} - {milestone}",
                "reason": f"子女重要人生节点，适合表达关心",
                "urgency": 4,
            })

    return triggers


def _match_interest_action(category: str) -> str | None:
    """Map interest categories to recommended actions."""
    mapping = {
        "golf": "邀请参加高尔夫活动或分享高尔夫资讯",
        "高尔夫": "邀请参加高尔夫活动或分享高尔夫资讯",
        "wine": "推荐新酒或邀请品酒",
        "红酒": "推荐新酒或邀请品酒",
        "tea": "寄送特色茶叶或邀请茶会",
        "茶": "寄送特色茶叶或邀请茶会",
        "reading": "分享好书或邀请参加读书会",
        "读书": "分享好书或邀请参加读书会",
        "sports": "分享运动赛事资讯或邀请观赛",
        "运动": "分享运动赛事资讯或邀请观赛",
        "travel": "分享旅行攻略或目的地推荐",
        "旅行": "分享旅行攻略或目的地推荐",
        "tech": "分享行业技术前沿报告",
        "技术": "分享行业技术前沿报告",
        "music": "分享音乐会信息或歌单",
        "音乐": "分享音乐会信息或歌单",
        "art": "分享展览信息或艺术资讯",
        "艺术": "分享展览信息或艺术资讯",
    }
    return mapping.get(category.lower())
