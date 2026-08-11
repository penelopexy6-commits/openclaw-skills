#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
category_config.py — 画像管线品类配置（跨品类复用的关键）
=====================================================================
每个品类定义：LLM 打标枚举（pain_point/usage_scene/purchase_reason）
+ Persona 规则模板。新增品类只需在此加一个配置。

当前品类: 泳衣（默认）/ 宠物玩具 / 眼镜
用法:
    from category_config import CATEGORY_CONFIG
    cfg = CATEGORY_CONFIG[category]  # 无则用 "泳衣" 兜底
    cfg["prompt_enums"]   → LLM 提示词枚举段
    cfg["build_personas"](agg) → Persona 列表
=====================================================================
"""

# =====================================================================
# 泳衣（默认，V1 定版）
# =====================================================================
SWIM_PROMPT_ENUMS = """- pain_point: size=尺码问题, chest_support=胸部支撑, missing_parts=缺件漏发, wrong_item=发错货/二手, quality=质量差, pilling=勾丝起球, fading=褪色, workmanship=做工瑕疵, fit_shape=版型/上身效果, fabric=面料, none=无明显痛点, other=其他
- emotion: positive=满意, neutral=一般, negative=失望, angry=愤怒
- body_feature: slim=苗条, normal=普通, plus_size=丰满/大码, big_bust=大胸, unknown=无法判断
- usage_scene: pool=泳池, vacation=度假/海滩, sport=运动游泳, sauna=桑拿, gift=送礼, daily=日常, unknown=无法判断
- purchase_reason: slimming=显瘦塑形, comfort=舒适, design=设计好看, quality=质量好, price=价格, support=支撑好, brand=品牌, unknown=无"""


def _swim_personas(agg):
    pain_map = {k: pct for k, c, pct in agg["pain"]}
    scene_map = {k: pct for k, c, pct in agg["scenes"]}
    total = agg["total_reviews"] or 1
    plus_pct = round(100.0 * agg["plus_signals"] / total, 1)
    gift_pct = round(100.0 * agg["gift_signals"] / total, 1)
    chest = pain_map.get("chest_support", 0)
    pool = scene_map.get("pool", 0)
    vacation = scene_map.get("vacation", 0)
    size = pain_map.get("size", 0)

    personas = []
    if plus_pct > 5 or size > 15:
        personas.append({
            "id": "P1", "name": "成熟丰满度假女性（Plus Size Vacationer）",
            "percentage": round(45 + (plus_pct - 10) * 0.5, 0) if plus_pct > 10 else 40,
            "age": "35-55", "gender": "女", "body": f"丰满/大码（大码提及 {plus_pct}%）",
            "scene": f"度假/海滩（{vacation}%）+ 出行前急购",
            "pain": [("尺码偏小/不符", size), ("胸部支撑不足", chest)],
            "keywords": ["купальник женский больших размеров", "утягивающий", "высокой посадкой"],
            "visual": "丰满真人模特 + 遮腹设计展示 + 身高体重尺码表",
            "ad": ["大码也能美（模特同身材）", "显瘦遮肚前后对比", "尺码诚实承诺"],
        })
    if pool > 10:
        personas.append({
            "id": "P2", "name": "泳池常客女性（Pool Regular）",
            "percentage": round(pool, 0),
            "age": "45-65", "gender": "女", "body": "普通/微胖，多为连体款",
            "scene": f"泳池/水上乐园（{pool}%）每周2-3次",
            "pain": [("褪色掉色", pain_map.get("fading", 0)), ("质量差", pain_map.get("quality", 0))],
            "keywords": ["купальник слитный женский", "для бассейна"],
            "visual": "素色/黑色连体 + 面料耐氯承诺 + 机洗不变形",
            "ad": ["每周游泳不褪色", "耐氯面料实测", "运动游泳专业款"],
        })
    if chest > 5:
        personas.append({
            "id": "P3", "name": "大胸支撑刚需人群（Big Bust）",
            "percentage": round(chest, 0),
            "age": "30-45", "gender": "女", "body": "大胸（D+杯）",
            "scene": "泳池+度假双场景",
            "pain": [("胸部支撑不足", chest), ("版型", pain_map.get("fit_shape", 0))],
            "keywords": ["лиф купальный женский", "с поддержкой"],
            "visual": "带钢圈/宽肩带设计特写 + 罩杯对照表",
            "ad": ["大胸也能稳稳托住", "杯型不塌不空", "游泳不掉肩带"],
        })
    if gift_pct > 2:
        personas.append({
            "id": "P4", "name": "代买/送礼人群（Gift Buyer）",
            "percentage": round(gift_pct * 3, 0) if gift_pct * 3 < 15 else 15,
            "age": "30-55", "gender": "男/子女（代买）", "body": "无（给妻子/母亲/女儿买）",
            "scene": "送礼、紧急补买",
            "pain": [("发错货/二手", pain_map.get("wrong_item", 0)), ("缺件漏发", pain_map.get("missing_parts", 0))],
            "keywords": ["купальник женский", "подарок"],
            "visual": "完整套装展示（含泳裤）+ 礼品包装 + 尺码速查",
            "ad": ["给她的完美礼物", "套装齐全不踩雷", "快速尺码指南"],
        })
    if not personas:
        personas.append(_fallback_persona(pain_map))
    return personas


# =====================================================================
# 宠物玩具（{店铺}1，规则01达标竞品）
# =====================================================================
PET_PROMPT_ENUMS = """- pain_point: durability=不耐咬/易坏, material=材质差/气味大, squeaker=发声器坏, choking=太小易吞/窒息风险, size=尺寸不符, quality=整体质量差, missing_parts=缺件漏发, wrong_item=发错货/二手, workmanship=做工瑕疵, none=无明显痛点, other=其他
- emotion: positive=满意, neutral=一般, negative=失望, angry=愤怒
- body_feature: small_dog=小型犬, medium_dog=中型犬, large_dog=大型犬/咬合力强, puppy=幼犬, unknown=无法判断（未提犬种体型）
- usage_scene: chew=啃咬/磨牙, fetch=叼咬/互动, indoor=室内玩, outdoor=户外玩, training=训练奖励, gift=送礼, unknown=无法判断
- purchase_reason: durability=耐咬持久, material=材质安全, fun=趣味互动, quality=质量好, price=价格合适, design=设计好看, brand=品牌, unknown=无"""


def _pet_personas(agg):
    pain_map = {k: pct for k, c, pct in agg["pain"]}
    scene_map = {k: pct for k, c, pct in agg["scenes"]}
    total = agg["total_reviews"] or 1
    durability = pain_map.get("durability", 0)
    material = pain_map.get("material", 0)
    squeaker = pain_map.get("squeaker", 0)
    choking = pain_map.get("choking", 0)

    personas = []
    if durability > 10:
        personas.append({
            "id": "P1", "name": "耐咬刚需主人（Durability Hunter）",
            "percentage": round(durability, 0),
            "age": "25-45", "gender": "男女（犬主）", "body": "中大型犬/咬合力强/幼犬换牙期",
            "scene": f"啃咬/磨牙（{scene_map.get('chew', 0)}%）",
            "pain": [("不耐咬/易坏", durability), ("材质差/气味大", material)],
            "keywords": ["игрушка для собак прочная", "каучук", "для жевания"],
            "visual": "抗咬实测对比（同款犬种 30 分钟/数天）+ 材质断面特写",
            "ad": ["咬不烂承诺", "耐咬材质实测", "幼犬换牙期专用"],
        })
    if choking > 5 or squeaker > 5:
        personas.append({
            "id": "P2", "name": "安全敏感型主人（Safety First）",
            "percentage": round(choking + squeaker, 0),
            "age": "30-50", "gender": "男女（犬主）", "body": "小型犬/幼犬主人",
            "scene": "室内玩（关注吞咽风险）",
            "pain": [("太小易吞/窒息", choking), ("发声器坏", squeaker)],
            "keywords": ["игрушка для щенка", "безопасная", "без мелких деталей"],
            "visual": "尺寸对比手部特写 + 发声器固定结构展示 + 材质安全认证",
            "ad": ["吞不下的大小", "发声器不脱落", "安全材质"],
        })
    if material > 5:
        personas.append({
            "id": "P3", "name": "材质挑剔型主人（Material Snob）",
            "percentage": round(material, 0),
            "age": "25-40", "gender": "男女（犬主）", "body": "重视材质/气味",
            "scene": "室内玩",
            "pain": [("材质差/气味大", material)],
            "keywords": ["игрушка для собак натуральная", "без запаха", "латекс"],
            "visual": "天然橡胶/无异味卖点 + 材质成分标注",
            "ad": ["无味不刺激", "天然材质", "耐咬且安全"],
        })
    if not personas:
        personas.append(_fallback_persona(pain_map))
    return personas


# =====================================================================
# 眼镜（老花镜/防蓝光，{店铺}1）
# =====================================================================
GLASS_PROMPT_ENUMS = """- pain_point: lens_quality=镜片质量差/模糊/花, degree_wrong=度数错发/不符, broken=破损/断裂, material=材质差（塑料冒充玻璃）, fit=佩戴不适/夹头, desc_mismatch=描述不符/色差, missing_parts=缺件漏发, wrong_item=发错货/二手, none=无明显痛点, other=其他
- emotion: positive=满意, neutral=一般, negative=失望, angry=愤怒
- body_feature: old_age=中老年（老花）, young=青壮年（防蓝光）, unknown=无法判断
- usage_scene: reading=阅读/看近, computer=电脑/办公, outdoor=户外/遮阳, driving=开车, gift=送礼, daily=日常, unknown=无法判断
- purchase_reason: clarity=清晰度高, comfort=佩戴舒适, price=价格合适, design=设计好看, quality=质量好, brand=品牌, unknown=无"""


def _glass_personas(agg):
    pain_map = {k: pct for k, c, pct in agg["pain"]}
    scene_map = {k: pct for k, c, pct in agg["scenes"]}
    total = agg["total_reviews"] or 1
    lens = pain_map.get("lens_quality", 0)
    degree = pain_map.get("degree_wrong", 0)
    broken = pain_map.get("broken", 0)
    fit = pain_map.get("fit", 0)
    reading = scene_map.get("reading", 0)
    computer = scene_map.get("computer", 0)

    personas = []
    if degree > 8:
        personas.append({
            "id": "P1", "name": "老花刚需用户（Reading Needs）",
            "percentage": round(degree + reading * 0.5, 0),
            "age": "45-65+", "gender": "男女", "body": "老花，度数档位敏感",
            "scene": f"阅读/看近（{reading}%）",
            "pain": [("度数错发/不符", degree), ("镜片质量差", lens)],
            "keywords": ["очки для чтения", "для пожилых", "+2,5"],
            "visual": "度数档位对照表 + 镜片清晰度实测（文字对比）",
            "ad": ["度数精准不虚标", "清晰防晕", "老花专用"],
        })
    if computer > 10 or lens > 15:
        personas.append({
            "id": "P2", "name": "办公/电脑人群（Screen User）",
            "percentage": round(computer + lens * 0.3, 0),
            "age": "25-45", "gender": "男女", "body": "防蓝光需求",
            "scene": f"电脑/办公（{computer}%）",
            "pain": [("镜片质量差", lens), ("佩戴不适", fit)],
            "keywords": ["очки антиблик", "для компьютера", "защита глаз"],
            "visual": "防蓝光实测（滤蓝光对比图）+ 轻量佩戴展示",
            "ad": ["护眼防蓝光", "久戴不累", "轻量无压"],
        })
    if broken > 8:
        personas.append({
            "id": "P3", "name": "务实平价买家（Budget Buyer）",
            "percentage": round(broken + pain_map.get("desc_mismatch", 0) * 0.3, 0),
            "age": "30-60", "gender": "男女", "body": "价格敏感，一次性用品心态",
            "scene": "日常备用/应急",
            "pain": [("破损/断裂", broken), ("描述不符", pain_map.get("desc_mismatch", 0))],
            "keywords": ["очки недорого", "дешево"],
            "visual": "坚固测试（摔落/弯折）+ 实物实拍与描述一致",
            "ad": ["结实耐用", "实物与图一致", "平价不将就"],
        })
    if not personas:
        personas.append(_fallback_persona(pain_map))
    return personas


# =====================================================================
# 兜底
# =====================================================================
def _fallback_persona(pain_map):
    if hasattr(pain_map, "most_common"):  # Counter
        top = pain_map.most_common(1)[0] if pain_map else ("other", 0)
    elif pain_map:  # dict
        k = max(pain_map, key=pain_map.get)
        top = (k, pain_map[k])
    else:
        top = ("other", 0)
    return {
        "id": "P1", "name": "核心购买人群", "percentage": 100, "age": "未知", "gender": "未知",
        "body": "未知", "scene": "未知", "pain": [(top[0], top[1])],
        "keywords": [], "visual": "产品实拍 + 规格表", "ad": ["通用卖点"],
    }


# =====================================================================
# 落地要点（数据驱动 + 品类专属；每个品类独立实现）
# =====================================================================
def _swim_landing(agg):
    pain_map = {k: pct for k, c, pct in agg["pain"]}
    top = agg["pain"][0] if agg["pain"] else None
    top_name = "尺码" if top and top[0] == "size" else (top[1] if top else "—")
    points = []
    if pain_map.get("size", 0) >= 10:
        points.append(f"尺码诚实 + 身高体重对照表（第一痛点 尺码 {pain_map['size']}%）")
    elif top:
        points.append(f"主攻第一痛点：{top[1]}（{top[2]}%）→ 主图/描述直击")
    points.append("卖点按 Persona 打（见各卡主图/广告方向）")
    if pain_map.get("wrong_item", 0) >= 5 or pain_map.get("missing_parts", 0) >= 5:
        points.append(f"品控红线：套装完整（错发 {pain_map.get('wrong_item',0)}%/缺件 {pain_map.get('missing_parts',0)}%）+ 标签齐全 + 质检")
    else:
        points.append("品控红线：标签齐全 + 质检")
    return points


def _pet_landing(agg):
    pain_map = {k: pct for k, c, pct in agg["pain"]}
    points = []
    if pain_map.get("durability", 0) >= 10:
        points.append(f"耐咬实测承诺（第一痛点 不耐咬 {pain_map['durability']}%）→ 主图犬种实测/时长对比")
    if pain_map.get("squeaker", 0) >= 5 or pain_map.get("choking", 0) >= 5:
        points.append(f"安全设计：发声器加固（{pain_map.get('squeaker',0)}%）+ 尺寸防吞（{pain_map.get('choking',0)}%）")
    if pain_map.get("material", 0) >= 5:
        points.append(f"材质信任：无异味/天然橡胶卖点（材质差 {pain_map.get('material',0)}%）")
    points.append("详情页标注适用犬种/体型/年龄段（降低误购）")
    points.append("品控红线：发声器牢固 + 无小零件脱落 + 材质安全")
    return points


def _glass_landing(agg):
    pain_map = {k: pct for k, c, pct in agg["pain"]}
    points = []
    if pain_map.get("degree_wrong", 0) >= 8:
        points.append(f"度数精准承诺（第一痛点 度数错发 {pain_map['degree_wrong']}%）→ 发货前验度数 + 标注清晰")
    if pain_map.get("lens_quality", 0) >= 10:
        points.append(f"镜片清晰度实测（镜片质量差 {pain_map['lens_quality']}%）→ 实拍文字对比/防晕")
    if pain_map.get("broken", 0) >= 8:
        points.append(f"破损防护包装（破损 {pain_map['broken']}%）→ 加固包装 + 破损包赔")
    if pain_map.get("fit", 0) >= 5:
        points.append(f"佩戴舒适优化（夹头 {pain_map['fit']}%）→ 尺寸/可调节设计")
    points.append("材质如实标注（塑料/玻璃/TR90，防描述不符差评）")
    return points


# =====================================================================
# 智能手表（荣超坤店，规则03达标竞品）
# =====================================================================
WATCH_PROMPT_ENUMS = """- pain_point: screen=屏幕问题（花屏/白条/黑屏/触控失灵）, battery=续航差/掉电快, sensor=测量不准（血压/心率/血氧/计步）, connect=连接问题（蓝牙断连/收不到通知）, sound=声音问题（无铃声/无声/通知不响）, strap=表带问题（扣子坏/易断/过敏）, quality=做工质量差, wrong_item=发错货/二手/缺件, no_manual=无俄语说明书/功能不符描述, none=无明显痛点, other=其他
- emotion: positive=满意, neutral=一般, negative=失望, angry=愤怒
- body_feature: female=女性用户, male=男性用户, kid=儿童, elderly=老人/送父母, unknown=无法判断
- usage_scene: fitness=运动/健身, health=健康监测（血压/心率）, daily=日常佩戴, work=办公/看消息, gift=送礼, unknown=无法判断
- purchase_reason: price=价格合适, design=外观好看, health=健康监测功能, battery=续航好, screen=屏幕好, gift=送礼, quality=质量好, brand=品牌, unknown=无"""


def _watch_personas(agg):
    pain_map = {k: pct for k, c, pct in agg["pain"]}
    scene_map = {k: pct for k, c, pct in agg["scenes"]}
    total = agg["total_reviews"] or 1
    screen = pain_map.get("screen", 0)
    battery = pain_map.get("battery", 0)
    sensor = pain_map.get("sensor", 0)
    connect = pain_map.get("connect", 0)
    health = scene_map.get("health", 0)
    fitness = scene_map.get("fitness", 0)
    gift = scene_map.get("gift", 0)

    personas = []
    if screen > 10:
        personas.append({
            "id": "P1", "name": "屏幕质量敏感用户（Screen Quality First）",
            "percentage": round(screen, 0),
            "age": "25-45", "gender": "男女", "body": "对显示/触控要求高",
            "scene": f"日常佩戴+看消息（{scene_map.get('daily', 0)}%）",
            "pain": [("屏幕问题", screen), ("做工质量差", pain_map.get("quality", 0))],
            "keywords": ["смарт часы amoled", "умные часы с хорошим экраном"],
            "visual": "屏幕实拍（亮屏/息屏）+ 触控演示 + 分辨率标注",
            "ad": ["高清不花屏", "AMOLED 屏实测", "触控流畅"],
        })
    if battery > 8 or sensor > 8:
        personas.append({
            "id": "P2", "name": "健康监测刚需用户（Health Tracker）",
            "percentage": round(battery + sensor, 0),
            "age": "30-55", "gender": "男女", "body": "关注血压/心率/睡眠，可能送父母",
            "scene": f"健康监测（{health}%）",
            "pain": [("测量不准", sensor), ("续航差", battery)],
            "keywords": ["смарт часы с давлением", "часы с пульсометром"],
            "visual": "血压/心率实测对比图 + 传感器位置说明",
            "ad": ["测量准确承诺", "续航 7 天", "老人健康监护"],
        })
    if connect > 8:
        personas.append({
            "id": "P3", "name": "连接体验挑剔用户（Connectivity First）",
            "percentage": round(connect, 0),
            "age": "25-40", "gender": "男女", "body": "依赖通知/通话功能",
            "scene": "办公/看消息",
            "pain": [("连接问题", connect), ("声音问题", pain_map.get("sound", 0))],
            "keywords": ["смарт часы с звонками", "часы уведомления"],
            "visual": "来电/通知推送截图演示 + 蓝牙连接稳定性说明",
            "ad": ["连接稳定不掉线", "通知即时推送", "通话清晰"],
        })
    if gift > 5:
        personas.append({
            "id": "P4", "name": "送礼人群（Gift Buyer）",
            "percentage": round(gift, 0),
            "age": "30-55", "gender": "男女（送父母/伴侣/子女）", "body": "给长辈/伴侣买",
            "scene": "送礼",
            "pain": [("发错货/二手", pain_map.get("wrong_item", 0)), ("无俄语说明书", pain_map.get("no_manual", 0))],
            "keywords": ["смарт часы подарок", "часы для родителей"],
            "visual": "礼盒包装展示 + 俄语说明书承诺 + 长辈使用场景",
            "ad": ["送礼体面", "附俄语说明书", "长辈易上手"],
        })
    if not personas:
        personas.append(_fallback_persona(pain_map))
    return personas


def _watch_landing(agg):
    pain_map = {k: pct for k, c, pct in agg["pain"]}
    points = []
    if pain_map.get("screen", 0) >= 8:
        points.append(f"屏幕质控（第一痛点 屏幕问题 {pain_map['screen']}%）→ 出货前点亮测试 + 主图实拍")
    if pain_map.get("sensor", 0) >= 5:
        points.append(f"测量功能校准（测量不准 {pain_map['sensor']}%）→ 出厂校准 + 说明误差范围")
    if pain_map.get("battery", 0) >= 5:
        points.append(f"续航实测宣传（续航差 {pain_map['battery']}%）→ 实标续航天数")
    if pain_map.get("connect", 0) >= 5:
        points.append(f"连接稳定性（断连 {pain_map['connect']}%）→ 固件更新 + 兼容性说明")
    if pain_map.get("wrong_item", 0) >= 5 or pain_map.get("no_manual", 0) >= 5:
        points.append(f"品控红线：发货验货（错发/二手 {pain_map.get('wrong_item',0)}%）+ 附俄语说明书（{pain_map.get('no_manual',0)}%）")
    points.append("详情页如实标注功能（血压/血氧等测量仅参考，防功能不符差评）")
    return points


# =====================================================================
# 注册表
# =====================================================================
CATEGORY_CONFIG = {
    "泳衣": {
        "product_cn": "泳衣",
        "prompt_enums": SWIM_PROMPT_ENUMS,
        "build_personas": _swim_personas,
        "landing_points": _swim_landing,
        "PAIN_CN": {"size": "尺码偏小/不符", "quality": "质量差", "wrong_item": "发错货/二手", "fading": "褪色掉色",
                    "chest_support": "胸部支撑不足", "workmanship": "做工瑕疵", "missing_parts": "缺件漏发",
                    "fit_shape": "版型/上身效果", "fabric": "面料问题", "pilling": "勾丝起球",
                    "none": "无明显痛点", "other": "其他"},
        "SCENE_CN": {"vacation": "度假/海滩", "pool": "泳池", "daily": "日常", "sport": "运动游泳",
                     "sauna": "桑拿", "gift": "送礼", "unknown": "未知"},
        "REASON_CN": {"quality": "质量好", "design": "设计好看", "comfort": "舒适", "slimming": "显瘦塑形",
                      "support": "支撑好", "fit_shape": "版型合身", "price": "价格合适", "brand": "品牌", "unknown": "未明确"},
    },
    "宠物玩具": {
        "product_cn": "宠物玩具",
        "prompt_enums": PET_PROMPT_ENUMS,
        "build_personas": _pet_personas,
        "landing_points": _pet_landing,
        "PAIN_CN": {"durability": "不耐咬/易坏", "material": "材质差/气味大", "squeaker": "发声器坏",
                    "choking": "太小易吞/窒息", "size": "尺寸不符", "quality": "整体质量差",
                    "missing_parts": "缺件漏发", "wrong_item": "发错货/二手", "workmanship": "做工瑕疵",
                    "none": "无明显痛点", "other": "其他"},
        "SCENE_CN": {"chew": "啃咬/磨牙", "fetch": "叼咬/互动", "indoor": "室内玩", "outdoor": "户外玩",
                     "training": "训练奖励", "gift": "送礼", "unknown": "未知"},
        "REASON_CN": {"durability": "耐咬持久", "material": "材质安全", "fun": "趣味互动",
                      "quality": "质量好", "price": "价格合适", "design": "设计好看", "brand": "品牌", "unknown": "未明确"},
    },
    "眼镜": {
        "product_cn": "眼镜",
        "prompt_enums": GLASS_PROMPT_ENUMS,
        "build_personas": _glass_personas,
        "landing_points": _glass_landing,
        "PAIN_CN": {"lens_quality": "镜片质量差", "degree_wrong": "度数错发/不符", "broken": "破损/断裂",
                    "material": "材质差", "fit": "佩戴不适/夹头", "desc_mismatch": "描述不符/色差",
                    "missing_parts": "缺件漏发", "wrong_item": "发错货/二手", "none": "无明显痛点", "other": "其他"},
        "SCENE_CN": {"reading": "阅读/看近", "computer": "电脑/办公", "outdoor": "户外/遮阳",
                     "driving": "开车", "gift": "送礼", "daily": "日常", "unknown": "未知"},
        "REASON_CN": {"clarity": "清晰度高", "comfort": "佩戴舒适", "price": "价格合适",
                      "design": "设计好看", "quality": "质量好", "brand": "品牌", "unknown": "未明确"},
    },
    "智能手表": {
        "product_cn": "智能手表",
        "prompt_enums": WATCH_PROMPT_ENUMS,
        "build_personas": _watch_personas,
        "landing_points": _watch_landing,
        "PAIN_CN": {"screen": "屏幕问题", "battery": "续航差", "sensor": "测量不准",
                    "connect": "连接问题", "sound": "声音问题", "strap": "表带问题",
                    "quality": "做工质量差", "wrong_item": "发错货/二手/缺件",
                    "no_manual": "无俄语说明书/功能不符", "none": "无明显痛点", "other": "其他"},
        "SCENE_CN": {"fitness": "运动/健身", "health": "健康监测", "daily": "日常佩戴",
                     "work": "办公/看消息", "gift": "送礼", "unknown": "未知"},
        "REASON_CN": {"price": "价格合适", "design": "外观好看", "health": "健康监测功能",
                      "battery": "续航好", "screen": "屏幕好", "gift": "送礼",
                      "quality": "质量好", "brand": "品牌", "unknown": "未明确"},
    },
}


def get_config(category: str) -> dict:
    """按品类取配置，未注册品类回退泳衣模板"""
    return CATEGORY_CONFIG.get(category, CATEGORY_CONFIG["泳衣"])
