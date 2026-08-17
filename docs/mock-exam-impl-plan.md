# 全真模拟 + 导航 + 主题重设计 · 实现计划

计划日期:2026-08-17 · 依据:[mock-exam-flow-design.md](./mock-exam-flow-design.md)(用户审定版)、[mock-fixed-bank.md](./mock-fixed-bank.md)
范围:练习模式功能不动,新增全真模拟,首页加模式导航,整体主题改乐观活泼
版本:完成后升 v0.4.0

## 一、总览

```
index.html(练习模式,原样保留 + 新导航)
  ├─ 练习模式 → 现有配置/会话流程(不动)
  └─ 全真模拟 → mock.html(配置 → 考试 → 时间汇总)
后端:
  mock_api.py   POST /api/mock/session(抽题包 + 建场次)
                POST /api/mock/finish(记录作答历史 + 结算场次)
  mock_fixed.py 考官台词固定数据(转录自 mock-fixed-bank.md)
  db.py         history 加 mode/mock_session_id 列 + mock_sessions 表 + 迁移
主题:style.css 整体换亮色(乐观活泼),login.css/admin.css 对齐
```

## 二、数据库改动(db.py)

- `history` 表加两列:`mode TEXT NOT NULL DEFAULT 'practice'`、`mock_session_id INTEGER NULL`
- 新表 `mock_sessions(id, user_id, section, voice, status, started_at, completed_at, durations_json)`,status = created | completed | abandoned
- **迁移**:`init_db()` 建表后查 `PRAGMA table_info(history)`,缺列则 `ALTER TABLE ADD COLUMN`(幂等,老库直接升级)
- 第 N 次考试 = 该用户 `mock_sessions` 中 status='completed' 场次数 + 1

## 三、后端(mock_api.py + mock_fixed.py)

### mock_fixed.py
转录 `docs/mock-fixed-bank.md`:开场白、出示准考证、P1 首主题 A/B(首问+3 备选)、P2 过渡、P2 准备结束、P3 过渡、结束语。`[N]` 运行时替换,`[P2 话题]` 用 P2 主题中文名(TTS 混合朗读)。

### POST /api/mock/session
入参 `{section, voice}`,校验 section ∈ 题库、voice ∈ VOICES。抽题(全部走 7 天避重,复用 `sampling.py` 的 `_weights`/`_sample_no_replacement` + recent Counter,历史含 practice + mock 全部行 = 共用历史):

1. P1 首主题:A/B 随机抽一 → 固定首问 + 3 备选抽 2
2. P1 二、三主题:从题库 P1 随机抽 2 主题(不重复),每主题随机 2–3 问
3. P2:调用现有 `sample_session(payload, section, "P2", 1, recent, rng)` 抽 1 张题卡(避重)
4. P3:从 P2 同主题的 P3 题库抽 3 问(不足 3 全出,主题一致)

响应:固定台词脚本 + 上述题包 + `session_id`。同时插入 `mock_sessions`(status=created)行。**历史行不在此刻写入**(弃考不记录,见设计 §八)。

### POST /api/mock/finish
入参 `{session_id, answered_keys, durations}`:
- 校验 session 属于当前用户且 status=created
- 按 answered_keys 写 history(mode='mock', mock_session_id=…);跳过/放弃的题不写
- 更新 mock_sessions → status=completed + durations_json
- 幂等:重复调用只结算一次

## 四、前端

### 导航(index.html)
masthead 下加模式切换:`练习模式 | 全真模拟` 两个 tab。练习模式 = 现有 UI 原样;全真模拟 → 跳 `/mock.html`。`app.js` 只加导航绑定,练习逻辑零改动。

### mock.html + mock.js + mock.css(新文件)
单页四态:配置 → 考试 → 时间汇总 → 返回。

- **配置**:题库单选(大陆新题/大陆老题/非大陆新题)+ 声音 男(Ethan)/女(Jennifer),点「开始考试」直接进(无候考)
- **考试界面**:布局按设计 §六 —— 考官占位中央(深色圆窗 + 名字标签 Alex)+ 考生画面占位右上角(后续接摄像头)+ 底部操作条「出示身份证/继续/跳过/重复」+ 状态条(Part · 第几问 · 第 N 次考试)
- **流程状态机**(设计 §四,全部用 mock_fixed 台词 TTS,沿用 `/api/tts`):
  1. 入场:自我介绍(第 N 次)语音 → 出示准考证语音 → 点「出示身份证」进 P1
  2. P1:首问固定 → 每问后 继续/跳过/重复
  3. P2 过渡:过渡语音同时题卡上屏 → 1:00 硬倒计时大字 → 倒计时到 0 放准备结束语 → 点「继续」进陈述
  4. P2 陈述:2:00 倒计时,题卡常驻;到点停止计时,不自动进;点「继续」进 P3
  5. P3:过渡语音 → 停顿 3 秒 → 逐题提问(继续/跳过/重复)
  6. 结束:结束语 → 时间汇总页(入场/P1/P2 准备/P2 陈述/P3/总时长)→ 调 finish → 返回首页按钮
- **中途退出**:confirm「退出 = 放弃本场」→ 回首页,不调 finish
- TTS 失败:字幕常显 + 重复键可重听(沿用 speech.js 降级 speechSynthesis)
- 每环节时长用 performance.now 记录,汇总页展示

### 主题重设计(乐观活泼)
现状为暗色「黄昏考场」。方案:整体换亮色暖系。

- 主色:**阳光橙 #FF8C42**(主按钮/高亮)+ **天空蓝 #4A9BFF**(辅助)+ 奶白背景 `#FFF9F0`、深灰文字 `#2D2A26`
- 卡片:大圆角(16px)+ 柔和投影 + 浅橙/浅蓝描边
- 背景:暖白 → 淡橙渐变,点缀小圆点/波浪(纯 CSS)
- 文字:加大标题字重,按钮圆角胶囊化;考试界面(mock)同一色系,考官区保持深色圆窗保证辨识
- 涉及:style.css 整体改(≈500 行,重点色变量化),login.css/admin.css 同步,index.html/mock.html 结构微调

备选配色(若橙蓝不合口味):
- 柠檬绿 × 天蓝:`#7CB342` + `#42A5F5`,清新感,更「考卷」
- 樱花粉 × 浅紫:`#FF8FA3` + `#B39DDB`,柔和女性向
- 保持橙蓝,但整体降低饱和度做「奶油感」

## 五、测试(tests/)

- mock session:首主题 A/B 覆盖、二/三主题 2 主题且不重复、P3 与 P2 主题一致、P3 不足 3 问全出、section/voice 非法 422、P2 避重(近期抽过的卡出现概率降低)
- mock_sessions:第 N 次计数(completed 才计入)、finish 只记录 answered_keys、重复 finish 幂等、弃考(不调 finish)不写历史
- 迁移:老 schema 库启动后列补齐,数据不丢
- 现有 50 用例全绿不回归

## 六、浏览器验证(Playwright)

1. 登录 → 首页导航两模式可切换
2. 练习模式回归:抽一轮 P1 正常
3. 全真模拟完整跑一遍:入场 → P1(继续/跳过/重复各用一次)→ P2 准备倒计时 → 陈述到点不自动进 → P3 → 汇总页时间合理
4. 中途退出 → 确认弹窗 → 回首页,历史无新增
5. 主题:三个页面(首页/登录/管理)亮色正常,无对比度问题
6. 移动端宽度操作条不溢出

## 七、发布顺序(铁律不变)

1. Mac:pytest 全绿 + Playwright 验证
2. commit 分步:① docs 三件套(设计/题库/计划)② 后端(迁移+fixed+api+tests)③ 前端导航+mock 页面 ④ 主题 ⑤ README/TODO + v0.4.0
3. git push → VPS `git pull && uv sync && systemctl restart ielts-speak`
4. curl + 浏览器验证外网(http://218.11.5.114:10607/、http://111.62.241.72:10169/)
5. 老库迁移在部署重启时自动完成(init_db 幂等)

## 八、待用户拍板

1. 配色:默认橙蓝奶油系?还是备选柠檬绿/樱花粉?(可先按默认做,不满意再换色变量)
2. 第 N 次考试只计「完成」的场次(弃考不计) —— 同意?
3. 中途退出 → 场次记 abandoned(不计入第 N 次)—— 同意?
