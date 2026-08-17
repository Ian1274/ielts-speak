# 全真模拟 · 固定题库全文(考官台词 + P1 固定首问)

修订日期:2026-08-15 · 与 [mock-exam-flow-design.md](./mock-exam-flow-design.md) 附录一致,后续实现时转录为 `mock_fixed.py`
说明:[N] 为占位符,实现时替换为该用户全真模拟场次 + 1;英文为考官 TTS 语音原文,中文注释不入语音

```text
【考官自我介绍】
Good morning / Good afternoon. My name is Alex. This is your [N]th mock speaking test.

【出示准考证】
Can I see your identification, please?

【P1 第一主题 A · 工作/学习】
首问:Do you work or are you a student?
备选(抽 2):Why did you choose that job / course?
            Do you enjoy it? Why?
            Is there anything you would like to change about it?

【P1 第一主题 B · 家乡/住处】
首问:Let's talk about your hometown. Where is it?
备选(抽 2):What do you like most about it?
            Has it changed much in recent years?
            Would you like to live there in the future?

【P2 过渡】(过渡语开始的同时题卡上屏)
Now I'm going to give you a topic, and I'd like you to talk about it for one to two minutes.
Before you talk, you'll have one minute to think about what you're going to say.
You can make some notes if you wish. Do you understand?
Here's some paper and a pencil for making notes, and here's your topic.

【P2 准备结束】
All right? Remember you have one to two minutes for this, so don't worry if I stop you.
I'll tell you when the time is up. Can you start speaking now, please?

【P3 过渡】
We've been talking about [P2 话题]. I'd like to discuss with you one or two more general
questions relating to this topic.

【结束语】
This is the end of the speaking test. Thank you.
```
