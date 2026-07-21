# 同集评测报告

**任务 ID**: lora-001
**测试集**: backend/training/data/test.jsonl
**评测时间**: 2026-07-21T09:19:34.425001+00:00

## 指标对比

| 指标 | 基线 | LoRA | 变化 |
| --- | --- | --- | --- |
| Macro-F1 | 0.122 | 0.9851 | +0.8631 |
| Accuracy | 0.2239 | 0.9851 | +0.7612 |
| NEGATIVE Recall | 0.0 | 0.9773 | +0.9773 |

### NEGATIVE
- 基线: P=0.0 R=0.0 F1=0.0
- LoRA: P=1.0 R=0.9773 F1=0.9885

### NEUTRAL
- 基线: P=0.2239 R=1.0 F1=0.3659
- LoRA: P=0.9677 R=1.0 F1=0.9836

### POSITIVE
- 基线: P=0.0 R=0.0 F1=0.0
- LoRA: P=0.9833 R=0.9833 F1=0.9833

## 门禁结果

**通过**: ✅

| 检查项 | 基线值 | LoRA值 | 变化 | 通过 |
| --- | --- | --- | --- | --- |
| negative_recall_not_decreased | 0.0 | 0.9773 | +0.9773 | ✅ |
| macro_f1_not_below_baseline | 0.122 | 0.9851 | +0.8631 | ✅ |
| macro_f1_improvement_ge_0.03 | 0.122 | 0.9851 | +0.8631 | ✅ |

## 误差分析

   总测试样本: 134
   基线错分数: 104
   LoRA 错分数: 2
   改善样本（基线错→LoRA对）: 102
   退化样本（基线对→LoRA错）: 0
   预测不一致（两模型预测不同）: 1
   净改善: 102

   错分方向统计:
     基线:
       POSITIVE→NEUTRAL: 60
       NEGATIVE→NEUTRAL: 44
     LoRA:
       NEGATIVE→POSITIVE: 1
       POSITIVE→NEUTRAL: 1

   高置信度错分（≥0.8）:
     基线: 0 条
     LoRA: 2 条

   改善样本详情（102 条）:
     [POSITIVE 基线→NEUTRAL LoRA→正确] 讲真，不用排队，到店就有座，蔬菜脆嫩，吃得出很新鲜...
     [POSITIVE 基线→NEUTRAL LoRA→正确] 讲真，店员很亲切，有需求都及时响应，菜品种类很多，选择空间大，个人感受哈...
     [POSITIVE 基线→NEUTRAL LoRA→正确] 体验下来，蔬菜脆嫩，吃得出很新鲜，菜品种类很多，选择空间大，办事效率很高，加菜撤盘都很快，下次再试试别的...
     [POSITIVE 基线→NEUTRAL LoRA→正确] 整体来说，价格很实惠，人均不高，打包盒质量很好，不会软塌塌的...
     [NEGATIVE 基线→NEUTRAL LoRA→正确] 体验下来，服务员态度很差，爱答不理的，仅供参考...
     [NEGATIVE 基线→NEUTRAL LoRA→正确] 肉质发柴，一看就不新鲜，店里太脏了，桌面都是油，个人感受哈...
     [POSITIVE 基线→NEUTRAL LoRA→正确] 整体来说，出餐效率很高，赶时间也没问题，定价合理，不会虚高，可以参考一下...
     [POSITIVE 基线→NEUTRAL LoRA→正确] 讲真，氛围安静，用餐体验很好...
     [POSITIVE 基线→NEUTRAL LoRA→正确] 个人感觉，分量实打实，不会偷工减料，位置很好找，地铁出来就到，店员很亲切，有需求都及时响应，可以参考一下...
     [POSITIVE 基线→NEUTRAL LoRA→正确] 说实话，店内设备很新，空调很足，办事效率很高，加菜撤盘都很快...
