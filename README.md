# 网页版微信聊天机器人

## 实现功能
1. 消息接收时，发送到指定队列
2. 监听指定的消息队列数据，并调用网页版接口发送

## 数据结构

### 消息类型

- TEXT
- IMAGE
- FILE
- VOICE
- CARD
- VIDEO
- EMOTION
- LOCATION
- LINK
- CALL
- GET_CONTACTS_INFO
# SHARE_LOCATION = 51
VIDEO2
SYSTEM
# 撤回
BLOCKED

```json
{
  "type": "",
  "content": ""
}
```

### 文本消息

### 图片消息

```python
TEXT = 1
IMAGE = 3
FILE = 6
VOICE = 34
CARD = 42
VIDEO = 43
EMOTION = 47
LOCATION = 48
LINK = 49
CALL = 50
GET_CONTACTS_INFO = 51
SHARE_LOCATION = 51
VIDEO2 = 62
SYSTEM = 10000
# 撤回
BLOCKED = 10002

UNHANDLED = -999
```

## Referer

https://github.com/Urinx/WeixinBot
