# -*- coding: utf-8 -*-
"""Generate 80 merchants x 30 reviews each as a CSV for demo import.

Categories span many retail formats — restaurants, drinks, antiques, fashion,
jewelry, electronics, beauty, toys, home and education — so that intent routing
has enough variety to test knowledge_query / tool_use / general_chat.
"""
import csv
import math
import random
from datetime import datetime, timedelta

rng = random.Random(20260725)

# ---------------------------------------------------------------------------
# Location helpers — distribute merchants 100 m – 10 km from a reference point
# ---------------------------------------------------------------------------
REF_LON, REF_LAT = 104.08, 30.66  # Chunxi Road, Chengdu
M_PER_DEG_LAT = 111_000
M_PER_DEG_LON = 111_000 * math.cos(math.radians(REF_LAT))

DISTRICTS = ["锦江区", "青羊区", "武侯区", "金牛区", "成华区", "高新区"]
STREETS = [
    "滨江路", "窄巷子", "桐梓林北路", "西安北路", "文殊院街",
    "玉林西路", "人民南路", "建设路", "人民北路", "九眼桥路",
    "建设巷", "红星路", "光华村街", "抚琴西路", "科华北路",
    "茶店子路", "高升桥东路", "海椒市街", "建设北路", "玉林东路",
    "东大街", "宁夏街", "九里堤中路", "桐梓林南路", "镗钯街",
    "东城根街", "双楠路", "营门口路", "春熙路", "清江东路",
    "宏济新路", "高攀路", "双桥路", "琉璃路", "沙湾东一路",
    "晋阳路", "莲桂西路", "双林路", "武侯祠大街", "万象城",
    "奎星楼街", "盛隆街", "枣子巷", "大学路", "天府大道",
]


def random_location():
    """Return (lon, lat) 100 m – 10 km from the reference point."""
    distance = rng.uniform(100, 10_000)
    angle = rng.uniform(0, 2 * math.pi)
    dlat = (distance * math.cos(angle)) / M_PER_DEG_LAT
    dlon = (distance * math.sin(angle)) / M_PER_DEG_LON
    return round(REF_LON + dlon, 6), round(REF_LAT + dlat, 6)


def random_address():
    return f"{rng.choice(DISTRICTS)}{rng.choice(STREETS)}{rng.randint(1, 200)}号"


# ---------------------------------------------------------------------------
# Merchant data — (name, category, tags, price_lo, price_hi, rating, aspects, weaknesses)
# aspects   → keys into ASPECT_CN  (used in positive / neutral reviews)
# weaknesses → keys into REASON_TEXT_MAP (used in negative reviews)
# ---------------------------------------------------------------------------

# 15 restaurants
RESTAURANTS = [
    ("老码头鲜鱼火锅", "火锅", "鱼;火锅", 8800, 8800, 4.6, ["taste", "freshness"], ["slow_wait", "loud"]),
    ("巷子深川菜馆", "川菜", "川菜", 6200, 6200, 4.3, ["taste", "price"], ["no_seat", "dirty"]),
    ("樱花寿司屋", "日料", "日料", 13500, 13500, 4.8, ["freshness", "appearance"], ["overpriced"]),
    ("碳烤天下", "烧烤", "烧烤", 7200, 7200, 4.2, ["taste"], ["dirty", "loud"]),
    ("粤港茶餐厅", "粤菜", "粤菜", 5500, 5500, 4.2, ["taste", "variety"], ["slow_wait"]),
    ("兰州拉面馆", "面馆", "面食", 2200, 2200, 4.0, ["price", "taste"], ["dirty", "no_seat"]),
    ("鲜入围海鲜排档", "海鲜", "海鲜", 11500, 11500, 4.3, ["freshness", "variety"], ["overpriced", "slow_wait"]),
    ("韩式烤肉坊", "韩餐", "韩餐", 10200, 10200, 4.2, ["taste", "equipment"], ["overpriced", "slow_wait"]),
    ("老成都串串香", "串串", "串串", 6500, 6500, 4.4, ["taste", "variety"], ["dirty", "slow_wait"]),
    ("湘辣诱惑", "湘菜", "湘菜", 5800, 5800, 4.3, ["taste", "price"], ["loud", "slow_wait"]),
    ("云之南菌锅", "云南菜", "云南菜", 9200, 9200, 4.5, ["taste", "freshness"], ["slow_wait"]),
    ("包子传奇", "小吃", "包子", 1600, 1600, 4.4, ["taste", "price"], ["no_seat", "bad_pack"]),
    ("甜蜜时光烘焙", "甜品", "甜品", 3800, 3800, 4.7, ["appearance", "taste"], ["no_seat"]),
    ("蜀九香火锅", "火锅", "火锅", 8500, 8500, 4.5, ["taste", "decoration"], ["slow_wait"]),
    ("深夜食堂居酒屋", "日料", "日料", 9800, 9800, 4.4, ["taste", "attitude"], ["overpriced", "no_seat"]),
]

# 10 drink shops
DRINK_SHOPS = [
    ("拾光咖啡", "咖啡", "咖啡;手冲", 2500, 4500, 4.5, ["taste", "quiet", "decoration"], ["slow_wait"]),
    ("鹿见奶茶铺", "奶茶", "奶茶;鲜奶", 1200, 3000, 4.3, ["taste", "appearance"], ["too_sweet", "slow_wait"]),
    ("竹叶青茶馆", "茶馆", "茶馆;绿茶", 3000, 8000, 4.4, ["environment", "quiet", "taste"], ["overpriced"]),
    ("鲜榨果汁工坊", "果汁", "果汁;鲜榨", 1500, 3500, 4.2, ["freshness", "taste"], ["small_portion"]),
    ("微醺小酒馆", "酒馆", "酒馆;鸡尾酒", 5000, 12000, 4.3, ["environment", "variety", "decoration"], ["overpriced", "slow_wait"]),
    ("手冲实验室", "咖啡", "咖啡;手冲;精品", 3000, 5500, 4.6, ["taste", "professionalism", "quiet"], ["overpriced", "slow_wait"]),
    ("精酿啤酒坊", "精酿啤酒", "精酿;啤酒", 4000, 10000, 4.2, ["variety", "taste", "environment"], ["overpriced"]),
    ("柠檬茶事", "柠檬茶", "柠檬茶;手打", 1500, 3000, 4.2, ["taste", "freshness"], ["too_sweet", "small_portion"]),
    ("抹茶研究所", "抹茶", "抹茶;日式", 2500, 5000, 4.4, ["taste", "appearance", "decoration"], ["too_sweet"]),
    ("清吧小酌", "清吧", "清吧;微醺", 4000, 9000, 4.2, ["environment", "quiet", "variety"], ["overpriced", "slow_wait"]),
]

# 8 antique / curio shops
ANTIQUE_SHOPS = [
    ("古韵文玩阁", "文玩", "文玩;古玩", 3000, 25000, 4.5, ["quality", "variety", "professionalism"], ["overpriced", "rude_staff"]),
    ("翡翠缘玉器行", "玉器", "玉器;翡翠", 8000, 50000, 4.7, ["quality", "material", "authenticity"], ["overpriced"]),
    ("墨香斋字画", "字画", "字画;书法", 2000, 30000, 4.3, ["craftsmanship", "variety", "environment"], ["no_variety"]),
    ("紫砂天地", "紫砂壶", "紫砂;茶具", 5000, 30000, 4.6, ["craftsmanship", "material", "professionalism"], ["overpriced"]),
    ("老物件古玩店", "古玩", "古玩;收藏", 3000, 40000, 4.4, ["variety", "authenticity", "professionalism"], ["rude_staff"]),
    ("茗茶雅集", "茶叶", "茶叶;茶", 2000, 15000, 4.5, ["quality", "variety", "environment"], ["overpriced"]),
    ("青花瓷器阁", "瓷器", "瓷器;青花", 3000, 25000, 4.3, ["quality", "appearance", "variety"], ["damaged"]),
    ("蜜蜡世家", "琥珀蜜蜡", "蜜蜡;琥珀", 3000, 28000, 4.4, ["quality", "material", "variety"], ["fake", "overpriced"]),
]

# 10 fashion / apparel shops
FASHION_SHOPS = [
    ("潮领男装", "男装", "男装;潮牌", 8000, 30000, 4.3, ["style", "quality", "variety"], ["overpriced", "no_variety"]),
    ("霓裳女装", "女装", "女装;时尚", 5000, 25000, 4.4, ["style", "appearance", "variety"], ["overpriced", "rude_staff"]),
    ("童趣童装店", "童装", "童装;儿童", 3000, 15000, 4.2, ["quality", "appearance", "price"], ["no_variety"]),
    ("飞跃运动服饰", "运动服饰", "运动;健身", 5000, 20000, 4.3, ["quality", "style", "variety"], ["overpriced"]),
    ("锦瑟汉服馆", "汉服", "汉服;国风", 3000, 18000, 4.5, ["style", "appearance", "variety"], ["slow_wait"]),
    ("暖冬羽绒服", "羽绒服", "羽绒服;冬装", 8000, 35000, 4.1, ["quality", "price"], ["no_variety", "overpriced"]),
    ("牛仔很忙", "牛仔", "牛仔;休闲", 3000, 12000, 4.0, ["style", "price"], ["poor_quality", "no_variety"]),
    ("贴身秘密内衣", "内衣", "内衣;贴身", 2000, 8000, 4.2, ["quality", "material", "fitting"], ["no_variety"]),
    ("步云鞋坊", "鞋店", "鞋;皮鞋", 3000, 15000, 4.1, ["quality", "style", "fitting"], ["overpriced", "rude_staff"]),
    ("饰界配饰", "配饰", "配饰;饰品", 1000, 8000, 4.0, ["appearance", "variety", "price"], ["poor_quality"]),
]

# 8 jewelry shops
JEWELRY_SHOPS = [
    ("金鼎黄金", "黄金", "黄金;珠宝", 10000, 100000, 4.5, ["quality", "authenticity", "professionalism"], ["overpriced"]),
    ("银月银饰", "银饰", "银饰;925", 2000, 15000, 4.2, ["style", "price", "variety"], ["poor_quality"]),
    ("璀璨钻石", "钻石", "钻石;婚戒", 30000, 200000, 4.6, ["quality", "appearance", "authenticity"], ["overpriced", "rude_staff"]),
    ("珍珠姑娘", "珍珠", "珍珠;海水", 5000, 50000, 4.3, ["quality", "appearance"], ["fake", "overpriced"]),
    ("水晶之恋", "水晶", "水晶;天然", 3000, 30000, 4.1, ["appearance", "variety"], ["fake", "poor_quality"]),
    ("翠玉坊", "翡翠饰品", "翡翠;饰品", 5000, 80000, 4.4, ["quality", "material", "appearance"], ["overpriced", "fake"]),
    ("琥珀之光", "琥珀", "琥珀;蜜蜡", 3000, 25000, 4.0, ["quality", "appearance"], ["fake", "damaged"]),
    ("钛钢潮饰", "钛钢", "钛钢;潮流", 1000, 8000, 3.9, ["style", "price"], ["poor_quality", "no_variety"]),
]

# 8 electronics / digital shops
ELECTRONICS_SHOPS = [
    ("极客手机", "手机", "手机;数码", 200000, 1000000, 4.3, ["quality", "variety", "after_sale"], ["overpriced", "fake"]),
    ("笔记本世界", "电脑", "电脑;笔记本", 300000, 2000000, 4.2, ["variety", "professionalism", "after_sale"], ["overpriced", "slow_wait"]),
    ("声学耳机馆", "耳机", "耳机;音响", 5000, 50000, 4.4, ["quality", "variety", "appearance"], ["overpriced"]),
    ("智能穿戴坊", "智能手表", "智能手表;穿戴", 10000, 50000, 4.1, ["variety", "appearance"], ["poor_quality", "fake"]),
    ("配件大全", "配件", "配件;手机壳", 500, 5000, 4.0, ["variety", "price"], ["poor_quality"]),
    ("极速维修站", "维修", "维修;手机", 1000, 8000, 3.8, ["price", "after_sale"], ["slow_wait", "rude_staff"]),
    ("光影相机", "相机", "相机;摄影", 50000, 300000, 4.5, ["quality", "professionalism", "variety"], ["overpriced"]),
    ("游戏机乐园", "游戏机", "游戏机;Switch", 20000, 80000, 4.2, ["variety", "price"], ["fake", "overpriced"]),
]

# 8 beauty / cosmetics shops
BEAUTY_SHOPS = [
    ("美妆天地", "化妆品", "化妆品;彩妆", 3000, 30000, 4.3, ["variety", "appearance", "quality"], ["overpriced", "fake"]),
    ("肌肤之钥", "护肤", "护肤;美容", 2000, 20000, 4.4, ["quality", "effectiveness", "professionalism"], ["overpriced"]),
    ("香水日记", "香水", "香水;香氛", 3000, 15000, 4.2, ["appearance", "variety"], ["overpriced", "fake"]),
    ("指尖艺术美甲", "美甲", "美甲;美甲", 500, 5000, 4.1, ["appearance", "price", "creativity"], ["slow_wait", "poor_quality"]),
    ("花容美容院", "美容院", "美容;护肤", 5000, 30000, 4.3, ["professionalism", "environment", "effectiveness"], ["overpriced", "rude_staff"]),
    ("顶上功夫理发", "理发店", "理发;美发", 3000, 12000, 4.0, ["professionalism", "price"], ["slow_wait", "rude_staff"]),
    ("刺青堂纹身", "纹身", "纹身;刺青", 5000, 30000, 4.2, ["creativity", "professionalism", "quality"], ["overpriced", "rude_staff"]),
    ("禅意SPA", "SPA", "SPA;按摩", 8000, 30000, 4.5, ["environment", "professionalism", "quiet"], ["overpriced", "slow_wait"]),
]

# 6 toy / stationery shops
TOY_SHOPS = [
    ("欢乐玩具店", "玩具", "玩具;儿童", 1000, 8000, 4.1, ["variety", "appearance", "price"], ["poor_quality", "no_variety"]),
    ("惊喜盲盒屋", "盲盒", "盲盒;潮玩", 1000, 5000, 4.3, ["appearance", "variety", "creativity"], ["overpriced", "no_variety"]),
    ("文采文具店", "文具", "文具;办公", 500, 5000, 4.0, ["variety", "price"], ["no_variety"]),
    ("手办之家", "手办", "手办;模型", 2000, 20000, 4.4, ["appearance", "variety", "quality"], ["overpriced", "damaged"]),
    ("创意乐高坊", "乐高", "乐高;积木", 3000, 15000, 4.5, ["creativity", "quality", "variety"], ["overpriced"]),
    ("桌游部落", "桌游", "桌游;聚会", 1000, 8000, 4.2, ["variety", "price", "environment"], ["no_variety"]),
]

# 4 home / living shops
HOME_SHOPS = [
    ("宜居家具", "家具", "家具;家居", 5000, 80000, 4.2, ["quality", "variety", "appearance"], ["overpriced", "slow_wait"]),
    ("暖巢家纺", "家纺", "家纺;床品", 2000, 20000, 4.1, ["quality", "material", "price"], ["no_variety"]),
    ("厨艺厨具", "厨具", "厨具;厨房", 1000, 15000, 4.0, ["variety", "quality", "price"], ["poor_quality"]),
    ("花香满径花店", "花卉", "花卉;花艺", 500, 5000, 4.4, ["freshness", "appearance", "creativity"], ["overpriced", "stale"]),
]

# 3 bookstore / education shops
EDUCATION_SHOPS = [
    ("知味书屋", "书店", "书店;图书", 1000, 8000, 4.3, ["variety", "environment", "quiet"], ["no_variety", "overpriced"]),
    ("学霸培训机构", "培训机构", "培训;教育", 10000, 50000, 4.0, ["professionalism", "quality"], ["overpriced", "rude_staff"]),
    ("弦音乐器行", "乐器", "乐器;音乐", 3000, 50000, 4.2, ["quality", "variety", "professionalism"], ["overpriced"]),
]

MERCHANTS = (
    RESTAURANTS + DRINK_SHOPS + ANTIQUE_SHOPS + FASHION_SHOPS
    + JEWELRY_SHOPS + ELECTRONICS_SHOPS + BEAUTY_SHOPS
    + TOY_SHOPS + HOME_SHOPS + EDUCATION_SHOPS
)

# ---------------------------------------------------------------------------
# Category → shop type  (determines which review templates are used)
# ---------------------------------------------------------------------------
RESTAURANT_CATS = {
    "火锅", "川菜", "日料", "烧烤", "粤菜", "面馆", "海鲜", "韩餐",
    "串串", "湘菜", "云南菜", "小吃", "甜品",
}
DRINK_CATS = {
    "咖啡", "奶茶", "茶馆", "果汁", "酒馆", "精酿啤酒",
    "柠檬茶", "抹茶", "清吧",
}
ANTIQUE_CATS = {
    "文玩", "玉器", "字画", "紫砂壶", "古玩", "茶叶", "瓷器", "琥珀蜜蜡",
}


def shop_type(category: str) -> str:
    if category in RESTAURANT_CATS:
        return "restaurant"
    if category in DRINK_CATS:
        return "drink"
    if category in ANTIQUE_CATS:
        return "antique"
    return "retail"


# ---------------------------------------------------------------------------
# Aspect and weakness vocabulary
# ---------------------------------------------------------------------------
ASPECT_CN = {
    # restaurant / drink
    "taste": "味道", "portion": "分量", "price": "性价比",
    "freshness": "新鲜度", "appearance": "卖相", "variety": "品种",
    "space": "空间", "quiet": "安静程度", "decoration": "装修",
    "hygiene": "卫生", "seating": "座位", "waiting_time": "出餐速度",
    "attitude": "服务态度", "efficiency": "效率", "packing": "打包",
    "equipment": "设施", "environment": "环境", "sweetness": "甜度",
    # antique
    "quality": "品质", "craftsmanship": "做工", "material": "材质",
    "condition": "品相", "professionalism": "专业性", "authenticity": "真品保证",
    # retail (fashion / jewelry / electronics / beauty / toy / home / education)
    "style": "款式", "after_sale": "售后", "fitting": "试穿体验",
    "creativity": "创意", "effectiveness": "效果",
}

REASON_TEXT_MAP = {
    # restaurant
    "taste_bad": "味道太差了", "cold_food": "菜上来都是凉的",
    "stale": "食材不新鲜", "overpriced": "价格虚高",
    "dirty": "卫生条件太差了", "loud": "环境太吵了",
    "no_seat": "去了根本没有座位", "slow_wait": "等了一个小时",
    "rude_staff": "服务员态度恶劣", "wrong_order": "上错菜还不承认",
    # drink
    "too_sweet": "甜得发腻", "small_portion": "份量少得可怜",
    "bad_pack": "打包洒了一半",
    # antique / retail
    "fake": "疑似假货", "poor_quality": "做工粗糙",
    "no_variety": "品种太少", "damaged": "有瑕疵没提前说",
    # retail specific
    "wrong_size": "尺码不准", "expired": "产品过期了",
}

# ---------------------------------------------------------------------------
# Review templates
# ---------------------------------------------------------------------------
POSITIVE_COMMON = [
    "真的不错，{aspect}特别棒，下次还要来！",
    "性价比很高，{aspect}超出预期。",
    "环境很好，{aspect}也加分。",
    "店员特别热情，推荐的{aspect}果然好。",
    "种类丰富，{aspect}随便选都不踩雷。",
    "位置好找，{aspect}值得专门跑一趟。",
    "经常来，{aspect}每次都很稳定。",
    "装修很用心，{aspect}在这样的环境里更出众了。",
    "看了推荐来的，{aspect}果然名不虚传。",
    "朋友带来，{aspect}让我很惊喜。",
    "周边好停车，{aspect}也没让人失望。",
    "周末特地过来的，{aspect}没有让我失望。",
]

POSITIVE_RESTAURANT = [
    "味道真的绝了，{aspect}特别棒，下次还要来！",
    "中午来吃个工作餐，{aspect}出餐快又好吃。",
    "朋友聚会选对了地方，{aspect}大家都满意。",
    "外卖点了好几次了，{aspect}包装好味道也在线。",
    "带爸妈来的，老人特别喜欢{aspect}。",
]

POSITIVE_DRINK = [
    "口感很好，{aspect}让人回味。",
    "颜值超高，{aspect}也很在线，拍照必来。",
    "下午来喝杯，{aspect}配着甜点太惬意了。",
    "每天必点，{aspect}一直很稳定。",
    "朋友推荐的，{aspect}果然没让我失望。",
]

POSITIVE_ANTIQUE = [
    "品质没得说，{aspect}让人爱不释手。",
    "老板很专业，讲解{aspect}头头是道。",
    "淘到了宝贝，{aspect}超值。",
    "逛了一下午，{aspect}值得慢慢挑。",
    "老顾客了，{aspect}一直保持水准。",
]

POSITIVE_RETAIL = [
    "品质不错，{aspect}让人满意，值得推荐。",
    "款式很新，{aspect}在同城算得上拔尖。",
    "逛了一圈，{aspect}是这家最好。",
    "导购很专业，帮忙挑的{aspect}正合心意。",
    "试用了一下，{aspect}确实好，果断入手。",
    "品牌齐全，{aspect}随便挑都不踩雷。",
]

NEUTRAL_COMMON = [
    "一般般，{aspect}没有特别惊艳的地方。",
    "中规中矩，{aspect}不出错。",
    "价格还行，{aspect}对得起价格。",
    "没有想象中好，{aspect}也就及格水平。",
    "朋友非要来，{aspect}我觉得还行吧。",
    "看评价来的，实际{aspect}没有描述得好。",
    "第一次来，{aspect}体验一般，可能不会专门再来。",
    "在附近办事顺便来的，{aspect}无功无过。",
    "普通水准，{aspect}没什么记忆点。",
    "凑合，{aspect}填个需求没问题。",
]

NEGATIVE_COMMON = [
    "太差了，{reason}，不会再来了。",
    "踩雷了，{reason}，浪费钱。",
    "服务态度差，{reason}，气得不行。",
    "价格高得离谱，{reason}，不值这个价。",
    "环境太吵了，{reason}，说话都听不见。",
    "等了快一个小时，{reason}，体验极差。",
    "实物跟图片差太远，{reason}，太失望了。",
    "不会再去了，{reason}，反正周边选择很多。",
    "朋友来选了这里被吐槽，{reason}，很尴尬。",
    "网上好评都是刷的吧，{reason}，完全不推荐。",
]

NEGATIVE_RESTAURANT = [
    "太难吃了，{reason}，绝对不会再来了。",
    "卫生堪忧，{reason}，看到就不想吃了。",
    "食材不新鲜，{reason}，吃完还拉肚子了。",
    "上错了菜还不承认，{reason}，服务太差了。",
    "带着孩子去的，{reason}，一点都不亲子友好。",
]

NEGATIVE_DRINK = [
    "太甜了，{reason}，完全喝不下去。",
    "份量少得可怜，{reason}，不值这个价。",
    "水果不新鲜，{reason}，口感很差。",
    "打包洒了一半，{reason}，体验极差。",
    "等了二十分钟才做好，{reason}，效率太低了。",
]

NEGATIVE_ANTIQUE = [
    "疑似假货，{reason}，再也不敢来了。",
    "做工粗糙，{reason}，完全不值这个价。",
    "老板态度傲慢，{reason}，不推荐。",
    "有瑕疵没提前说，{reason}，太不诚信了。",
    "品种太少，{reason}，没什么可挑的。",
]

NEGATIVE_RETAIL = [
    "质量太差了，{reason}，用了一次就坏了。",
    "退换货特别麻烦，{reason}，售后太差了。",
    "导购一直推销，{reason}，体验很差。",
    "疑似假货，{reason}，再也不敢来了。",
    "款式老旧，{reason}，完全不值这个价。",
]

TEMPLATES = {
    "restaurant": (POSITIVE_COMMON + POSITIVE_RESTAURANT,
                   NEUTRAL_COMMON,
                   NEGATIVE_COMMON + NEGATIVE_RESTAURANT),
    "drink": (POSITIVE_COMMON + POSITIVE_DRINK,
              NEUTRAL_COMMON,
              NEGATIVE_COMMON + NEGATIVE_DRINK),
    "antique": (POSITIVE_COMMON + POSITIVE_ANTIQUE,
                NEUTRAL_COMMON,
                NEGATIVE_COMMON + NEGATIVE_ANTIQUE),
    "retail": (POSITIVE_COMMON + POSITIVE_RETAIL,
               NEUTRAL_COMMON,
               NEGATIVE_COMMON + NEGATIVE_RETAIL),
}

# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------
now = datetime(2026, 7, 25, 12, 0, 0)


def gen_reviews(m, m_idx):
    """Generate 30 reviews for one merchant."""
    stype = shop_type(m[1])
    pos_pool, neu_pool, neg_pool = TEMPLATES[stype]
    aspects = m[6]
    weaknesses = m[7]

    # 30 reviews: ~16 positive, ~8 neutral, ~6 negative
    sentiments = (
        ["POSITIVE"] * 16 + ["NEUTRAL"] * 8 + ["NEGATIVE"] * 6
    )
    rng.shuffle(sentiments)

    price = rng.randint(m[3], m[4]) if m[3] != m[4] else m[3]
    lon, lat = random_location()
    address = random_address()

    reviews = []
    for i, sent in enumerate(sentiments):
        review_key = f"demo80-m{m_idx:02d}-r{i:02d}"
        days_ago = rng.randint(1, 120)
        reviewed_at = now - timedelta(days=days_ago, hours=rng.randint(8, 22))

        if sent == "POSITIVE":
            aspect = rng.choice(aspects)
            aspect_cn = ASPECT_CN.get(aspect, aspect)
            text = rng.choice(pos_pool).format(aspect=aspect_cn)
            rating = round(rng.uniform(4.0, 5.0), 1)
        elif sent == "NEUTRAL":
            aspect = rng.choice(aspects)
            aspect_cn = ASPECT_CN.get(aspect, aspect)
            text = rng.choice(neu_pool).format(aspect=aspect_cn)
            rating = round(rng.uniform(2.5, 3.8), 1)
        else:
            reason_key = rng.choice(weaknesses)
            reason_text = REASON_TEXT_MAP.get(reason_key, "体验太差了")
            text = rng.choice(neg_pool).format(reason=reason_text)
            rating = round(rng.uniform(1.0, 2.5), 1)

        author = f"食客_{m_idx + 1:03d}_{i + 1:02d}"
        reviews.append({
            "merchant_key": f"demo80-m{m_idx:02d}",
            "merchant_name": m[0],
            "category": m[1],
            "address": address,
            "longitude": lon,
            "latitude": lat,
            "avg_price_cent": price,
            "merchant_rating": m[5],
            "business_status": "OPEN",
            "review_key": review_key,
            "review_content": text,
            "review_rating": rating,
            "reviewed_at": reviewed_at.isoformat(),
            "author_ref": author,
            "tags": m[2],
            "owner_username": "demo-merchant",
        })
    return reviews


all_rows = []
for idx, m in enumerate(MERCHANTS):
    all_rows.extend(gen_reviews(m, idx))

fields = [
    "merchant_key", "merchant_name", "category", "address",
    "longitude", "latitude", "avg_price_cent", "merchant_rating",
    "business_status", "review_key", "review_content", "review_rating",
    "reviewed_at", "author_ref", "tags", "owner_username",
]

output_path = "D:/CodingProjects/LocalLife Copilot/backend/demo_data/merchant_80.csv"
with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(all_rows)

# Summary
from collections import Counter
cat_counts = Counter(m[1] for m in MERCHANTS)
type_counts = Counter(shop_type(m[1]) for m in MERCHANTS)
print(f"Generated {len(MERCHANTS)} merchants with {len(all_rows)} reviews")
print(f"Saved to: {output_path}")
print(f"Shop types: {dict(type_counts)}")
print(f"Categories ({len(cat_counts)}): {dict(cat_counts)}")
