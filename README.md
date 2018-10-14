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

### @某人的分析
群聊中@某人时，分为本身在群组聊天界面内和不在群组聊天界面内两种情况
1. 如果用户本身处于当前群组聊天界面，则会在@用户名后有一个`\ufe0f`字符
2. 如果不在，则是在@用户名之后有`\ufe0f\u2005`两个字符

例如某群聊用户在里面的昵称为张三，则第一种情况收到消息为`你好@张三\ufe0f你好`，第二种情况为`你好@张三\ufe0f\u2005你好`

## Referer

https://github.com/Urinx/WeixinBot

