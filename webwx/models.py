from typing import Dict

from webwx.enums import VerifyFlag, Sex, MsgType


class Contact:

    def __init__(self, user_dict: dict):
        self.username = user_dict['UserName']
        self.nickname = user_dict['NickName']
        self.remark_name = user_dict['RemarkName']
        self.sex = Sex(user_dict['Sex'])


class SpecialUser(Contact):
    verify_flag = VerifyFlag.PERSON


class Friend(Contact):
    verify_flag = VerifyFlag.PERSON

    def __init__(self, user_dict: dict):
        super().__init__(user_dict)
        self.display_name = user_dict.get('DisplayName', '')


class ChatRoom(Contact):

    def __init__(self, user_dict: dict):
        super().__init__(user_dict)
        self.member_list: Dict[str, Friend] = {}

    def add_member(self, person: Friend):
        self.member_list[person.username] = person


class MediaPlatform(Contact):
    def __init__(self, user_dict: dict):
        super().__init__(user_dict)

    verify_flag = VerifyFlag.COMMON_MP


class Msg:
    def __init__(self, msg_id, from_user, to_user, msg_type=MsgType.UNHANDLED):
        self.msg_id = msg_id
        self.from_user = from_user
        self.to_user = to_user
        self.msg_type = msg_type


class LocationMsg(Msg):
    def __init__(self, msg: Msg, url, content):
        super().__init__(msg.msg_id, msg.from_user, msg.to_user, MsgType.LOCATION)
        self.url = url
        self.content = content


class TextMsg(Msg):
    def __init__(self, msg: Msg, content):
        super().__init__(msg.msg_id, msg.from_user, msg.to_user, MsgType.LOCATION)
        self.content = content


class ImageMsg(Msg):
    def __init__(self, msg: Msg, content):
        super().__init__(msg.msg_id, msg.from_user, msg.to_user, MsgType.IMAGE)
        self.content = content
