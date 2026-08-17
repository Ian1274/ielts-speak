"""Fixed examiner scripts for the mock speaking test.

Transcribed from docs/mock-fixed-bank.md (user-approved). The English strings
are spoken verbatim by TTS; Chinese comments are annotations only.

Placeholders resolved at packet build time (mock_api.py):
  {greeting}  → "Good morning" / "Good afternoon" by server hour
  {n}         → user's completed mock count + 1
  {topic}     → P2 topic name (Chinese; qwen3-tts reads mixed text fine)
"""
import datetime

EXAMINER_NAME = "Alex"

GREETING_MORNING = "Good morning"
GREETING_AFTERNOON = "Good afternoon"

OPENING = "{greeting}. My name is {examiner}. This is your {n}th mock speaking test."

ID_CHECK = "Can I see your identification, please?"

# P1 第一主题 A · 工作/学习:固定首问 + 备选 3 抽 2
P1_TOPIC_A = {
    "topic": "工作/学习",
    "lead": "Do you work or are you a student?",
    "backup": (
        "Why did you choose that job or course?",
        "Do you enjoy it? Why?",
        "Is there anything you would like to change about it?",
    ),
}

# P1 第一主题 B · 家乡/住处:固定首问 + 备选 3 抽 2
P1_TOPIC_B = {
    "topic": "家乡/住处",
    "lead": "Let's talk about your hometown. Where is it?",
    "backup": (
        "What do you like most about it?",
        "Has it changed much in recent years?",
        "Would you like to live there in the future?",
    ),
}

# P2 过渡:过渡语开始的同时题卡上屏
P2_TRANSITION = (
    "Now I'm going to give you a topic, and I'd like you to talk about it "
    "for one to two minutes. Before you talk, you'll have one minute to "
    "think about what you're going to say. You can make some notes if you "
    "wish. Do you understand? Here's some paper and a pencil for making "
    "notes, and here's your topic."
)

# P2 准备结束:1 分钟倒计时到 0 后播放
P2_PREP_END = (
    "All right? Remember you have one to two minutes for this, so don't "
    "worry if I stop you. I'll tell you when the time is up. Can you start "
    "speaking now, please?"
)

# P3 过渡:{topic} = P2 主题名
P3_TRANSITION = (
    "We've been talking about {topic}. I'd like to discuss with you one or "
    "two more general questions relating to this topic."
)

CLOSING = "This is the end of the speaking test. Thank you."


def greeting(now: datetime.datetime | None = None) -> str:
    """Morning before 12:00, afternoon otherwise."""
    now = now or datetime.datetime.now()
    return GREETING_MORNING if now.hour < 12 else GREETING_AFTERNOON
