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


## rabbitmq数据结构说明
```json
{
    "to_username": "@xxx",
    "event_type": 1,
    "msg_type": 1,
    "content": "hello world"
}

```
- `to_username`: 操作对象
- `event_type`: 事件类型，对应枚举`EventType`
- `msg_type`: 如果`event_type`为`SEND_MESSAGE`, 则表示消息类型
- `content`: 消息内容，随格式变化而变化。

各个事件的参数格式如下:

### 发送消息事件
```json
{
    "msg_type": 1,
    "content": "hello world"
}
```

### 修改好友备注名事件
```json
{
    "remark_name": "hello world"
}
```

### 修改群名称事件
```json
{
    "name": "hello world"
}
```

### 文本消息

### 图片消息

## @某人的分析
群聊中@某人时，分为本身在群组聊天界面内和不在群组聊天界面内两种情况
1. 如果用户本身处于当前群组聊天界面，则会在@用户名后有一个`\ufe0f`字符
2. 如果不在，则是在@用户名之后有`\ufe0f\u2005`两个字符

例如某群聊用户在里面的昵称为张三，则第一种情况收到消息为`你好@张三\ufe0f你好`，第二种情况为`你好@张三\ufe0f\u2005你好`

ps：电脑版微信，在@完人和正文之间有个空格，如`你好@张三\ufe0f 你好`或`你好@张三\ufe0f\u2005 你好`

## Referer

https://github.com/Urinx/WeixinBot
