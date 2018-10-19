from enum import unique, Enum, IntEnum


@unique
class QRCodeStatus(Enum):
    WAITING = '等待扫码'
    SUCCESS = '扫码成功'
    EXPIRED = '二维码过期'
    CONFIRM = '确认登录'


@unique
class MsgType(IntEnum):
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
    # SHARE_LOCATION = 51
    VIDEO2 = 62
    SYSTEM = 10000
    # 撤回
    BLOCKED = 10002

    UNHANDLED = -999


@unique
class EventType(IntEnum):
    # message
    SEND_MESSAGE = 101

    # friend management
    AGREE_FRIEND_REQUEST = 201
    REJECT_FRIEND_REQUEST = 202
    MODIFY_FRIEND_REMARK_NAME = 203

    # chatroom management
    MODIFY_CHATROOM_NAME = 301


@unique
class SubMsgType(IntEnum):
    TEXT = 0
    LOCATION = 48


@unique
class VerifyFlag(IntEnum):
    PERSON = 0
    COMMON_MP = 8
    ENTERPRISE_MP = 24
    WECHAT = 56


@unique
class Sex(IntEnum):
    UNKNOWN = 0
    MALE = 1
    FEMALE = 2
