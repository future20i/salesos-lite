# SalesOS Lite — 人脉兵法：人脉画像规格

> 人是商业的根本驱动力。人脉画像系统是 SalesOS 的核心差异化层——不是 CRM 的客户档案，而是关系情报系统。
> 
> 日期：2026-06-20

---

## 指导思想

1. **人先于事。** 理解一个人之前不谈方案。
2. **隐私即信任。** 记下的越多，保护必须越严密。
3. **关系即资产。** 今天不成交的客户，三年后可能是最大的项目。
4. **知己知彼，知人知局。** 竞争性销售的本质是比谁更理解决策地图。
5. **AI 是幕僚，不是代言人。** 人做判断，AI 做情报。
6. **长线经营。** 你今天记下的"女儿考上清华"，十年后最值钱。

---

## 四层理解深度

| 层 | 名称 | 内容 | 可见性 |
|----|------|------|--------|
| 1 | 商业需求 | 产品规格、价格、交期 | 团队共享 |
| 2 | 个人画像 | 麦凯66（个人/家庭/兴趣/背景） | 🔒 创建者+上级 |
| 3 | 决策驱动力 | 恐惧、野心、组织处境 | 🔒 仅创建者 |
| 4 | 影响力杠杆 | 情感/事业/社交/信息杠杆 + 关系活动 | 🔒 仅创建者 |

---

## 数据模型

### PersonProfile（人脉画像）

```python
class PersonProfile(Base):
    __tablename__ = "person_profiles"
    
    id, tenant_id, lead_id (可空), opportunity_id (可空)
    
    # 第二层：个人画像（麦凯66核心）
    birthday, hometown, education, personality_tags
    spouse_name, spouse_occupation
    children_info (JSON)  # [{name, age, school, milestone}]
    interests (JSON)       # [{category, detail, note}]
    
    # 第三层：决策驱动力（加密字段）
    core_fear                # 真正怕什么
    core_ambition            # 真正要什么  
    org_situation            # 组织处境
    trust_foundation         # 信任基础
    
    # 第四层：影响力杠杆
    leverage_points (JSON)   # [{type: emotional/career/social/info, detail, status}]
    relationship_activities (JSON) # [{type, date, detail, outcome}]
    
    # 关系健康度
    relationship_depth (1-10)
    last_personal_touch_at
    
    # 权限（第三/四层加密字段）
    encrypted_fields         # 标记哪些字段是加密的
    access_list (JSON)       # [{user_id, access_level}]
    created_by, created_at, updated_at
```

### PowerMap（权力地图）

```python
class PowerMap(Base):
    __tablename__ = "power_maps"
    
    id, opportunity_id, tenant_id
    
    # 决策链上的每个人
    stakeholders (JSON)
    # [{person_profile_id, role (decision_maker/influencer/gatekeeper/user),
    #   stance (champion/neutral/opponent/unknown),
    #   concerns, influence_level (1-10), notes}]
    
    # 关系网络
    connections (JSON)
    # [{from_id, to_id, relationship_type, strength}]
    
    created_at, updated_at
```

### InteractionLog（互动记录）

```python
class InteractionLog(Base):
    __tablename__ = "interaction_logs"
    
    id, person_profile_id, tenant_id
    interaction_type  # message/call/visit/event/other
    channel, summary
    personal_topics (JSON)  # 涉及的私人话题
    key_takeaways (Text)    # 关键收获
    tags (JSON)             # 分类标签
    
    created_at, created_by
```

---

## 三个关键时刻

| 时刻 | 触发 | 系统行为 |
|------|------|---------|
| 📨 战前简报 | 打开对话/点击联系人 | 30秒简报：谁/关心什么/上次聊了什么/该做什么 |
| ✏️ 策略伴写 | 正在起草回复 | 策略卡：该说/忌说/可用的钩子 |
| ✅ 自动复盘 | 消息发出后 | 提取新信息、更新画像、建议下次触达时机 |

---

## 关系深化活动框架

| 类型 | 示例 | 频率 |
|------|------|------|
| 个人里程碑 | 生日、入职周年、子女升学 | 按日历触发 |
| 兴趣连接 | 高尔夫/音响/读书/运动 | 不定期 |
| 行业背书 | 联合演讲、白皮书署名、奖项推荐 | 按机会触发 |
| 资源引荐 | 人脉介绍、子女职业帮助 | 按需求触发 |
| 价值输出 | 行业报告、竞品动态、技术前沿 | 持续 |

---

## 隐私设计

- 第二层（个人画像）：创建者 + 直属上级可见
- 第三/四层（决策驱动力 + 影响力杠杆）：**仅创建者可见**。字段加密存储。
- 权力地图（不含隐私信息）：商机团队成员可见
- 任何人对第三/四层信息的访问需要创建者显式授权
- 数据导出时自动剥离第三/四层信息
