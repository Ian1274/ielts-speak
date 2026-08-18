"""IELTS-style feedback: transcript stats + LLM scoring.

stats() is pure computation (word count, speech rate, sentence count).
score() asks a DashScope text model to grade the transcript against the
official IELTS Speaking Band Descriptors (British Council / IDP /
Cambridge, ielts.org). Pronunciation is excluded from the LLM score: a
plain transcript cannot assess phonemes, so the API labels the result
as text-based (see feedback_api.py).
"""
import json
import os
import urllib.error
import urllib.request

from ielts import tts

MODEL = os.environ.get("IELTS_SPEAK_FEEDBACK_MODEL", "qwen-flash")
# 发音评分模型:omni 系列真听音频(重音/语调/连读),非文本推断
PRON_MODEL = os.environ.get("IELTS_SPEAK_PRON_MODEL", "qwen-omni-turbo")

# 评分标准:IELTS 官方 Speaking Band Descriptors (public version)
# 来源:British Council / IDP / Cambridge 联合发布,https://ielts.org/cdn/ielts-guides/ielts-speaking-band-descriptors.pdf
# 官方注释:(i) 考生必须完全符合某 band 的全部正面特征才得该分;(ii) 按整场整体表现评分
DESCRIPTORS = """按雅思官方 Speaking Band Descriptors(public version, ielts.org)评估转写文本。官方四项中评三项:

【Fluency and Coherence 流利度与连贯性】
9 分:非常流利,仅极偶尔重复或自我修正;停顿只用于组织下一句内容;话题展开完全连贯且适当延伸
7 分:能毫不费力持续产出长段;有中途停顿、重复/自我修正(常表明在找词),但不影响连贯;灵活使用语篇标记词、连接词与衔接手段
6 分:愿意产出长段回答;停顿/重复/自我修正偶尔使连贯性受损;使用语篇标记词但不总是恰当
5 分:靠重复、自我修正和/或慢速才能继续说;某些语篇标记词过度使用;更复杂的表达通常导致不流利,但简单表达可流利说出
3-4 分:明显停顿、常重复、频繁自我修正;只能连接简单句,连贯性常断裂

【Lexical Resource 词汇资源】
9 分:所有语境下完全灵活、精准用词;持续使用准确地道语言
7 分:词汇能灵活讨论各类话题;能使用一些非常用词与地道表达,有语体与搭配意识(尽管有不当处);能有效转述(paraphrase)
6 分:词汇足以展开话题;用词有时不当但意思清楚;一般能成功转述
5 分:词汇能应对熟悉与不熟悉话题但灵活性有限;尝试转述但不总能成功
3-4 分:词汇限于简单词汇,不熟悉话题只能传达基本意思

【Grammatical Range and Accuracy 语法范围与准确性】
9 分:语法结构始终精准准确,除母语者式"口误"外无错误;使用全部范围结构
7 分:灵活使用多种结构;错误少的句子常见;简单句与复杂句都使用有效,虽有些错误;少量基础错误仍存在
6 分:短句与复杂句混合使用,结构多样但灵活性有限;复杂结构中错误频繁,但很少妨碍理解
5 分:基础句型准确性控制较好;复杂句范围有限、几乎总有错误,可能需要改述
3-4 分:能产出基础句型,少量短句无错;从句罕见,整体句子短、结构重复、错误频繁

【Pronunciation 发音】:官方标准包含发音,由另一模型直接听音频评估(重音、语调、连读),本模型不评此项。

打分 1-9(整数)。官方注:(i) 考生必须完全符合某 band 的全部正面特征才得该分;(ii) 按考生整体表现评分。评分严格:答非所问或内容过短不超过 5 分。"""

# 发音维度(官方四项之一):由 omni 模型直接听音频评估,不是文本推断
PRON_DESCRIPTORS = """你是雅思口语考官,直接听考生录音,按官方 Speaking Band Descriptors 的发音维度打分(雅思官方四项之一):

【Pronunciation 发音】
9 分:运用全部语音特征传达精确或微妙含义;连读等衔接特征全程灵活运用;听者毫不费力即可听懂;口音完全不影响可懂度
8 分:广泛运用语音特征;能保持恰当节奏;长句重音与语调灵活,虽有偶尔失误;全程容易听懂;口音对可懂度影响极小
7 分:具备 6 分的全部正面特征,且具备 8 分的一部分特征
6 分:使用一定范围语音特征但控制不稳定;意群切分总体恰当,但节奏可能因缺乏重音节奏或语速过快而受影响;能有效运用一些重音语调但不持续;个别词或音素发音不准,仅偶尔造成不清晰;听者基本无需费力即可听懂
5 分:具备 4 分的全部正面特征,且具备 6 分的一部分特征
4 分:能用一些可接受的语音特征但范围有限;意群切分尚可但整体节奏常有失误;尝试运用重音语调但控制有限;词或音素频繁发音不准造成不清晰;理解需要一定努力,可能有听不懂的片段
3 分:可用的语音特征很少;整体发音问题损害连贯表达;常常无法理解
2 分:几乎无法传达意思;个别词和音素多为错误发音;常常无法理解
1 分:仅偶尔能听出个别词或音素,无整体意义;无法理解

只输出 JSON,不要任何其他文字,结构:
{"score": 1-9 整数, "reason": "一句中文理由,指出最典型的问题或亮点"}"""


class FeedbackError(Exception):
    """Raised on scoring failure; message is safe to show the user."""


def stats(transcript: str, duration_sec: float) -> dict:
    """Pure text stats: words, duration, speech rate, sentence count."""
    words = len([w for w in transcript.split() if w.strip()])
    sentences = max(
        1, sum(transcript.count(p) for p in (".", "!", "?")) or (1 if words else 0)
    )
    wpm = round(words / max(duration_sec, 1) * 60, 1) if duration_sec > 0 else 0.0
    return {
        "words": words,
        "duration_sec": round(duration_sec, 1),
        "wpm": wpm,
        "sentences": sentences,
    }


_SCORE_PROMPT = """{descriptors}

题目:{question}
作答时长:{duration} 秒
考生转写文本:
```
{transcript}
```

只输出 JSON,不要任何其他文字。JSON 结构(字段名必须一致):
{{
  "scores": {{"fluency": 1-9 整数, "lexical": 1-9 整数, "grammar": 1-9 整数}},
  "summary": "50 字内中文总评,说明主要扣分点",
  "issues": ["中文问题 1", "中文问题 2", "中文问题 3"],  (最多 3 条,具体到原文词句)
  "advice": ["中文改进建议 1", "中文改进建议 2"],  (最多 2 条,可操作)
  "model_answer": "一段 90 字内的英文示范回答,水平明显高于考生,符合题目"
}}"""


def _parse_content(content: str) -> dict:
    """Parse the LLM's JSON reply; fail fast on malformed output."""
    text = content.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # 模型偶尔在 JSON 外包 ```json 代码块
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            data = json.loads(text)
        else:
            raise FeedbackError("评分解析失败,请重试。") from None
    scores = data.get("scores")
    if not isinstance(scores, dict) or any(
        not isinstance(v, int) or not 1 <= v <= 9 for v in scores.values()
    ):
        raise FeedbackError("评分结果格式异常,请重试。")
    for key in ("summary", "issues", "advice", "model_answer"):
        if key not in data:
            raise FeedbackError("评分结果缺少字段,请重试。")
    return data


def score(
    transcript: str, question_text: str, part: str, duration_sec: float
) -> dict:
    """Grade the transcript against IELTS descriptors via a text model."""
    prompt = _SCORE_PROMPT.format(
        descriptors=DESCRIPTORS,
        question=question_text,
        duration=round(duration_sec, 1),
        transcript=transcript,
    )
    body = json.dumps(
        {
            "model": MODEL,
            "input": {
                "messages": [
                    {"role": "system", "content": "你是一位资深雅思口语考官,评分严格、反馈具体。"},
                    {"role": "user", "content": prompt},
                ]
            },
            "parameters": {"result_format": "message", "max_tokens": 800},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        tts.BASE_URL + "/api/v1/services/aigc/text-generation/generation",
        data=body,
        headers={
            "Authorization": f"Bearer {tts._load_api_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise FeedbackError(f"评分服务失败 (HTTP {exc.code})") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise FeedbackError("评分网络请求失败。") from exc

    content = (
        payload.get("output", {})
        .get("choices", [{}])[0]
        .get("message", {})
        .get("content")
    )
    if not isinstance(content, str):
        raise FeedbackError("评分服务未返回结果。")
    return _parse_content(content)


def pronunciation_score(audio_b64: str, mime: str) -> dict:
    """Grade pronunciation by listening to the actual audio (qwen-omni).

    Returns {"score": int, "reason": str}. The omni model hears phonemes,
    stress, intonation and connected speech — unlike the text-based score.
    """
    body = json.dumps(
        {
            "model": PRON_MODEL,
            "input": {
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"audio": f"data:{mime};base64,{audio_b64}"},
                            {"text": PRON_DESCRIPTORS},
                        ],
                    }
                ]
            },
            "parameters": {"result_format": "message", "max_tokens": 300},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        tts.BASE_URL + tts.GEN_PATH,
        data=body,
        headers={
            "Authorization": f"Bearer {tts._load_api_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        raise FeedbackError(f"发音评分服务失败 (HTTP {exc.code})") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise FeedbackError("发音评分网络请求失败。") from exc

    content = (
        payload.get("output", {})
        .get("choices", [{}])[0]
        .get("message", {})
        .get("content")
    )
    # omni 模型 content 是 [{"text": ...}] 列表,文本模型是 str
    if isinstance(content, list) and content:
        text = content[0].get("text")
    elif isinstance(content, str):
        text = content
    else:
        raise FeedbackError("发音评分服务未返回结果。")
    return _parse_pron_content(text)


def _parse_pron_content(content: str) -> dict:
    """Parse the omni model's JSON reply; fail fast on malformed output."""
    text = content.strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            data = json.loads(text)
        else:
            raise FeedbackError("发音评分解析失败,请重试。") from None
    score = data.get("score")
    reason = data.get("reason")
    if not isinstance(score, int) or not 1 <= score <= 9 or not isinstance(reason, str):
        raise FeedbackError("发音评分结果格式异常,请重试。")
    return {"score": score, "reason": reason}
