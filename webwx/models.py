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

    def to_json(self):
        return {
            'msg_id':           self.msg_id,
            'msg_type':         self.msg_type,
            'from_username':    self.from_user.username,
            'to_username':      self.to_user.username,
            'from_nickname':    self.from_user.nickname,
            'to_nickname':      self.to_user.nickname,
            'from_remark_name': self.from_user.remark_name,
            'to_remark_name':   self.to_user.remark_name,
        }


class LocationMsg(Msg):
    def __init__(self, msg: Msg, url, content):
        super().__init__(msg.msg_id, msg.from_user, msg.to_user, MsgType.LOCATION)
        self.url = url
        self.content = content

    def to_json(self):
        dic = super().to_json()
        dic.update({
            'url':     self.url,
            'content': self.content
        })
        return dic


class TextMsg(Msg):
    def __init__(self, msg: Msg, content):
        super().__init__(msg.msg_id, msg.from_user, msg.to_user, MsgType.TEXT)
        self.content = content

    def to_json(self):
        dic = super().to_json()
        dic.update({
            'content': self.content
        })
        return dic


class ImageMsg(Msg):
    def __init__(self, msg: Msg, content):
        super().__init__(msg.msg_id, msg.from_user, msg.to_user, MsgType.IMAGE)
        self.content = content

    def to_json(self):
        dic = super().to_json()
        dic.update({
            'content': self.content
        })
        return dic
