# -*- coding: utf-8 -*-
"""Generate 50 merchants x 20 reviews each as a CSV for demo import."""
import csv
import random
from datetime import datetime, timedelta

rng = random.Random(20260717)

MERCHANTS = [
    ("老码头鲜鱼火锅", "火锅", "锦江区滨江路12号", 104.081, 30.652, 8800, 4.6, "OPEN", "鱼;火锅", ["taste", "freshness"], ["waiting_time", "loud"]),
    ("巷子深川菜馆", "川菜", "青羊区窄巷子8号", 104.056, 30.669, 6200, 4.3, "OPEN", "川菜", ["taste", "price"], ["space", "hygiene"]),
    ("樱花寿司屋", "日料", "武侯区桐梓林北路32号", 104.064, 30.538, 13500, 4.8, "OPEN", "日料", ["freshness", "appearance"], ["price"]),
    ("碳烤天下", "烧烤", "金牛区西安北路66号", 104.043, 30.682, 7200, 4.2, "OPEN", "烧烤", ["taste"], ["hygiene", "loud"]),
    ("素心斋", "素食", "青羊区文殊院街15号", 104.061, 30.676, 5200, 4.6, "OPEN", "素食", ["hygiene", "quiet"], ["variety"]),
    ("意面工坊", "西餐", "锦江区IFS国际金融中心B1", 104.082, 30.655, 8600, 4.5, "OPEN", "西餐", ["taste", "decoration"], ["price"]),
    ("甜蜜时光烘焙坊", "甜品", "武侯区玉林西路25号", 104.058, 30.551, 3800, 4.7, "OPEN", "甜品", ["appearance", "taste"], ["seating"]),
    ("粤港茶餐厅", "粤菜", "武侯区人民南路四段88号", 104.059, 30.546, 5500, 4.2, "OPEN", "粤菜", ["taste", "variety"], ["efficiency"]),
    ("鲜果切水果工坊", "甜品", "成华区建设路55号", 104.109, 30.652, 2500, 4.5, "OPEN", "水果", ["freshness", "price"], ["portion"]),
    ("兰州拉面馆", "面馆", "金牛区人民北路一段3号", 104.070, 30.691, 2200, 4.0, "OPEN", "面食", ["price", "taste"], ["hygiene", "space"]),
    ("鲜入围海鲜大排档", "海鲜", "锦江区九眼桥路58号", 104.087, 30.643, 11500, 4.3, "OPEN", "海鲜", ["freshness", "variety"], ["price", "waiting_time"]),
    ("茶语时光", "奶茶", "成华区建设巷45号", 104.101, 30.660, 1800, 4.4, "OPEN", "奶茶", ["taste", "appearance"], ["packing"]),
    ("韩式烤肉坊", "韩餐", "锦江区红星路三段99号", 104.080, 30.651, 10200, 4.2, "OPEN", "韩餐", ["taste", "equipment"], ["price", "efficiency"]),
    ("云南米线坊", "米粉", "青羊区光华村街38号", 104.034, 30.662, 2800, 4.3, "OPEN", "米线", ["taste", "price"], ["attitude"]),
    ("老成都串串香", "串串", "金牛区抚琴西路55号", 104.046, 30.672, 6500, 4.4, "OPEN", "串串", ["taste", "variety"], ["hygiene", "waiting_time"]),
    ("湘辣诱惑", "湘菜", "武侯区科华北路72号", 104.067, 30.560, 5800, 4.3, "OPEN", "湘菜", ["taste", "price"], ["loud", "waiting_time"]),
    ("西北风味居", "西北菜", "金牛区茶店子路28号", 104.038, 30.701, 4800, 4.1, "OPEN", "西北菜", ["portion", "price"], ["decoration", "hygiene"]),
    ("云之南菌锅", "云南菜", "武侯区高升桥东路16号", 104.055, 30.575, 9200, 4.5, "OPEN", "云南菜", ["taste", "freshness"], ["waiting_time"]),
    ("黔味酸汤鱼", "贵州菜", "锦江区海椒市街9号", 104.090, 30.638, 6800, 4.3, "OPEN", "贵州菜", ["taste", "variety"], ["attitude", "space"]),
    ("包子传奇", "小吃", "成华区建设北路二段18号", 104.096, 30.669, 1600, 4.4, "OPEN", "包子", ["taste", "price"], ["space", "packing"]),
    ("渝味晓宇火锅", "火锅", "武侯区玉林东路6号", 104.062, 30.548, 7800, 4.4, "OPEN", "火锅", ["taste", "variety"], ["waiting_time", "loud"]),
    ("鳗鱼亭", "日料", "锦江区东大街97号", 104.078, 30.647, 14800, 4.7, "OPEN", "日料", ["taste", "freshness"], ["price"]),
    ("饺饺者", "小吃", "青羊区宁夏街22号", 104.050, 30.678, 1800, 4.2, "OPEN", "饺子", ["taste", "price"], ["space", "efficiency"]),
    ("山城烤鱼王", "烧烤", "金牛区九里堤中路40号", 104.057, 30.696, 6800, 4.1, "OPEN", "烤鱼", ["taste"], ["waiting_time", "hygiene"]),
    ("花胶鸡小馆", "粤菜", "武侯区桐梓林南路11号", 104.066, 30.533, 12800, 4.6, "OPEN", "粤菜", ["taste", "freshness"], ["price", "seating"]),
    ("好望角咖啡", "咖啡", "锦江区镗钯街38号", 104.075, 30.645, 3200, 4.5, "OPEN", "咖啡", ["quiet", "decoration"], ["efficiency"]),
    ("留香面馆", "面馆", "青羊区东城根街15号", 104.059, 30.671, 1500, 4.1, "OPEN", "面食", ["taste", "price"], ["space", "hygiene"]),
    ("蜀九香火锅", "火锅", "武侯区双楠路7号", 104.050, 30.565, 8500, 4.5, "OPEN", "火锅", ["taste", "decoration"], ["waiting_time"]),
    ("深夜食堂居酒屋", "日料", "锦江区镗钯街55号", 104.076, 30.644, 9800, 4.4, "OPEN", "日料", ["taste", "attitude"], ["price", "space"]),
    ("糯小米甜品店", "甜品", "成华区万象城L2-12", 104.108, 30.653, 3200, 4.6, "OPEN", "甜品", ["appearance", "taste"], ["seating", "waiting_time"]),
    ("重庆老灶火锅", "火锅", "金牛区营门口路33号", 104.047, 30.688, 7500, 4.3, "OPEN", "火锅", ["taste", "variety"], ["loud", "waiting_time"]),
    ("春阳茶事", "奶茶", "锦江区春熙路伊藤旁", 104.079, 30.649, 1500, 4.3, "OPEN", "奶茶", ["taste", "price"], ["packing", "waiting_time"]),
    ("川西坝子", "川菜", "青羊区清江东路8号", 104.052, 30.674, 5800, 4.4, "OPEN", "川菜", ["taste", "portion"], ["waiting_time", "loud"]),
    ("锅锅香焖锅", "小吃", "成华区建设路第五大道", 104.099, 30.658, 4500, 4.2, "OPEN", "焖锅", ["taste", "price"], ["efficiency", "hygiene"]),
    ("壹零伍咖啡", "咖啡", "武侯区科华北路4号", 104.068, 30.563, 2800, 4.4, "OPEN", "咖啡", ["quiet", "equipment"], ["price"]),
    ("南洋肉骨茶", "粤菜", "锦江区宏济新路33号", 104.085, 30.635, 6200, 4.2, "OPEN", "粤菜", ["taste", "variety"], ["attitude", "space"]),
    ("辣妹子湘菜馆", "湘菜", "武侯区高攀路12号", 104.071, 30.569, 5200, 4.1, "OPEN", "湘菜", ["taste", "price"], ["loud", "hygiene"]),
    ("兰州牛肉面大王", "面馆", "成华区双桥路178号", 104.095, 30.666, 1800, 4.0, "OPEN", "面食", ["price", "taste"], ["hygiene", "attitude"]),
    ("一叶一世界素餐", "素食", "锦江区琉璃路566号", 104.092, 30.621, 4600, 4.5, "OPEN", "素食", ["quiet", "hygiene"], ["variety", "price"]),
    ("老王记烧烤", "烧烤", "金牛区沙湾东一路9号", 104.040, 30.695, 5500, 4.0, "OPEN", "烧烤", ["taste", "price"], ["hygiene", "loud"]),
    ("丝路味道大盘鸡", "西北菜", "武侯区晋阳路128号", 104.044, 30.580, 4200, 4.2, "OPEN", "西北菜", ["portion", "taste"], ["attitude", "efficiency"]),
    ("海云台韩餐", "韩餐", "锦江区东大街紫东楼段", 104.077, 30.646, 7800, 4.3, "OPEN", "韩餐", ["taste", "variety"], ["price", "waiting_time"]),
    ("花溪牛肉粉", "米粉", "青羊区西安南路29号", 104.053, 30.677, 1500, 4.2, "OPEN", "米粉", ["taste", "price"], ["space", "attitude"]),
    ("蚝英雄生蚝专门店", "海鲜", "锦江区莲桂西路58号", 104.088, 30.634, 10800, 4.3, "OPEN", "海鲜", ["freshness", "taste"], ["price", "waiting_time"]),
    ("香遇干锅", "川菜", "成华区双林路388号", 104.093, 30.663, 4800, 4.2, "OPEN", "川菜", ["taste", "variety"], ["loud", "waiting_time"]),
    ("黔灵酸汤牛肉", "贵州菜", "武侯区武侯祠大街57号", 104.063, 30.572, 7200, 4.4, "OPEN", "贵州菜", ["taste", "freshness"], ["waiting_time", "space"]),
    ("玲珑糕点铺", "甜品", "成华区SM广场L1-08", 104.105, 30.656, 2200, 4.5, "OPEN", "甜品", ["appearance", "taste"], ["packing", "price"]),
    ("三顾冒菜", "小吃", "青羊区奎星楼街18号", 104.057, 30.675, 2800, 4.1, "OPEN", "冒菜", ["taste", "price"], ["space", "hygiene"]),
    ("西贡印象越南粉", "米粉", "武侯区盛隆街12号", 104.069, 30.555, 3800, 4.3, "OPEN", "米粉", ["taste", "freshness"], ["attitude", "portion"]),
    ("卤味江湖", "小吃", "金牛区枣子巷25号", 104.048, 30.684, 3500, 4.1, "OPEN", "卤味", ["taste", "price"], ["hygiene", "efficiency"]),
    ("云朵咖啡", "咖啡", "武侯区大学路12号", 104.072, 30.558, 2600, 4.5, "OPEN", "咖啡", ["quiet", "decoration"], ["seating", "efficiency"]),
]

# Diversified review templates - 25 each
POSITIVE = [
    # taste
    "味道真的绝了，{aspect}特别棒，下次还要来！",
    "口感非常好，{aspect}让人欲罢不能。",
    "这家店的{aspect}太正宗了，完全超出预期。",
    # price
    "没想到这个价位能吃到这么好的{aspect}，太划算了。",
    "性价比炸裂，{aspect}比同价位高出一大截。",
    "很实惠，{aspect}对得起价格还有余。",
    # environment
    "环境超赞，适合约会，{aspect}也加分。",
    "店里氛围很好，{aspect}配合着特别惬意。",
    "装修很用心，{aspect}在这样的环境里更美味了。",
    # service
    "服务员特别热情，推荐的{aspect}果然好吃。",
    "老板人很好，还送了小菜，{aspect}品质稳定。",
    "带外地朋友来的，朋友对{aspect}赞不绝口。",
    # variety
    "种类很丰富，{aspect}随便点都不踩雷。",
    "菜单上的{aspect}基本都试过了，每样都很稳。",
    "看了推荐点的，{aspect}果然名不虚传。",
    # location
    "位置好找，就在路边，{aspect}值得专门跑一趟。",
    "周边好停车，{aspect}也没让人失望。",
    # daily
    "中午来吃个工作餐，{aspect}出餐快又好吃。",
    "下班后跟同事来吃的，{aspect}大家都说好。",
    "带爸妈来的，老人特别喜欢{aspect}这家。",
    "路过看到人很多就知道没来错，{aspect}确实好。",
    "朋友聚会选对了地方，{aspect}大家都满意。",
    "经常来吃，{aspect}每次都很稳定。",
    "外卖点了好几次了，{aspect}包装好味道也在线。",
    "周末特地过来的，{aspect}没有让我失望。",
]

NEUTRAL = [
    "一般般吧，{aspect}没有什么特别惊艳的地方。",
    "路过随便吃吃的，{aspect}中规中矩不出错。",
    "没有想象中那么好，{aspect}也就及格水平。",
    "价格不算贵，{aspect}还算对得起价格。",
    "朋友非要来这家，{aspect}我觉得还行吧。",
    "不算难吃，但{aspect}也没什么亮点。",
    "环境还行，{aspect}不功不过。",
    "凑合能吃，{aspect}填饱肚子没问题。",
    "人多等了会儿，{aspect}上来的时候已经凉了些。",
    "看评价挺高来的，实际{aspect}没有描述得好。",
    "普通的味道普通的价位，{aspect}没什么记忆点。",
    "在附近办事顺便来的，{aspect}无功无过。",
    "开在商场里，{aspect}跟同层其他店差不多水平。",
    "不能说差，但{aspect}也没有再来一次的冲动。",
    "团购来的，{aspect}对得起团购价吧。",
    "调味偏淡了，{aspect}中规中矩，不难吃也不惊艳。",
    "份量适中，{aspect}吃完刚刚好，不多不少。",
    "等了二十分钟才上菜，{aspect}勉强及格。",
    "第一次来，{aspect}体验一般，可能不会专门再来。",
    "有进步空间，{aspect}目前来说还算过得去。",
]

NEGATIVE = [
    "太难吃了，{reason}，绝对不会再来了。",
    "踩雷了，{reason}，浪费钱。",
    "服务态度太差，{reason}，气得不行。",
    "等了快一个小时，{reason}，体验极差。",
    "卫生堪忧，{reason}，看到就不想吃了。",
    "实物跟图片差太远，{reason}，太失望了。",
    "价格高得离谱，{reason}，不值这个价。",
    "食材不新鲜，{reason}，吃完还拉肚子了。",
    "环境太吵了，{reason}，说话都听不见。",
    "上错了菜还不承认，{reason}，服务太差了。",
    "去的时候根本没座位，{reason}，白跑一趟。",
    "网上好评都是刷的吧，{reason}，完全不推荐。",
    "打包带回家发现份量好少，{reason}，不值。",
    "带着孩子去的，{reason}，一点都不亲子友好。",
    "过节涨价就算了，{reason}，品质还降了。",
    "说是现做的但明显是预制菜，{reason}，太假了。",
    "朋友聚餐选了这家被大家吐槽了，{reason}，很尴尬。",
    "半夜肚子疼，{reason}，怀疑食材有问题。",
    "叫了外卖超时一个多小时，{reason}，到了都凉了。",
    "不会再去了，{reason}，反正周边选择很多。",
]

REASON_TEXT_MAP = {
    "taste_bad": "味道太差了",
    "cold_food": "菜上来都是凉的",
    "stale": "食材不新鲜",
    "overpriced": "价格虚高",
    "dirty": "卫生条件太差了",
    "loud": "环境太吵了",
    "no_seat": "去了根本没有座位",
    "slow_wait": "上菜等了一个小时",
    "rude_staff": "服务员态度恶劣",
    "wrong_order": "上错菜还不承认",
}

ASPECT_CN = {
    "taste": "味道", "portion": "分量", "price": "性价比",
    "freshness": "新鲜度", "appearance": "卖相", "variety": "品种",
    "space": "空间", "quiet": "安静程度", "decoration": "装修",
    "hygiene": "卫生", "seating": "座位", "waiting_time": "出餐速度",
    "attitude": "服务态度", "efficiency": "效率", "packing": "打包",
    "equipment": "设施",
}

WEAKNESS_REASON_MAP = {
    "taste": "taste_bad", "freshness": "stale", "price": "overpriced",
    "hygiene": "dirty", "loud": "loud", "seating": "no_seat",
    "waiting_time": "slow_wait", "attitude": "rude_staff",
    "efficiency": "wrong_order", "packing": "bad_pack", "space": "no_seat",
}

now = datetime(2026, 7, 10, 12, 0, 0)

def gen_reviews(m, m_idx):
    # 20 reviews per merchant: ~11 positive, ~5 neutral, ~4 negative
    sent_weights = [0.55, 0.25, 0.20]
    sentiments = rng.choices(["POSITIVE", "NEUTRAL", "NEGATIVE"], weights=sent_weights, k=20)

    reviews = []
    for i, sent in enumerate(sentiments):
        review_key = f"demo50-m{m_idx:02d}-r{i:02d}"
        days_ago = rng.randint(1, 120)
        reviewed_at = now - timedelta(days=days_ago, hours=rng.randint(8, 22))

        if sent == "POSITIVE":
            aspect_list = m[10] if rng.random() < 0.65 else (m[10] + m[11])
            aspect = rng.choice(aspect_list)
            aspect_cn = ASPECT_CN.get(aspect, aspect)
            template = rng.choice(POSITIVE)
            text = template.format(aspect=aspect_cn)
            rating = round(rng.uniform(4.0, 5.0), 1)
        elif sent == "NEUTRAL":
            aspect_list = m[10] + m[11]
            aspect = rng.choice(aspect_list)
            aspect_cn = ASPECT_CN.get(aspect, aspect)
            template = rng.choice(NEUTRAL)
            text = template.format(aspect=aspect_cn)
            rating = round(rng.uniform(2.5, 3.8), 1)
        else:
            weakness = rng.choice(m[11])
            reason = WEAKNESS_REASON_MAP.get(weakness, "slow_wait")
            reason_text = REASON_TEXT_MAP.get(reason, "体验太差了")
            template = rng.choice(NEGATIVE)
            text = template.format(reason=reason_text)
            rating = round(rng.uniform(1.0, 2.5), 1)

        author = f"食客_{m_idx + 1:03d}_{i + 1:02d}"
        reviews.append({
            "merchant_key": f"demo50-m{m_idx:02d}",
            "merchant_name": m[0],
            "category": m[1],
            "address": m[2],
            "longitude": m[3],
            "latitude": m[4],
            "avg_price_cent": m[5],
            "merchant_rating": m[6],
            "business_status": m[7],
            "review_key": review_key,
            "review_content": text,
            "review_rating": rating,
            "reviewed_at": reviewed_at.isoformat(),
            "author_ref": author,
            "tags": m[8],
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

output_path = "D:/CodingProjects/LocalLife Copilot/backend/demo_data/merchant_50.csv"
with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.DictWriter(f, fieldnames=fields)
    w.writeheader()
    w.writerows(all_rows)

print(f"Generated {len(MERCHANTS)} merchants with {len(all_rows)} reviews")
print(f"Saved to: {output_path}")
