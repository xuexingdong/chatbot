from typing import Dict
from xml.dom import minidom

from webwx import utils
from webwx.enums import VerifyFlag, Sex, MsgType


class Contact:

    def __init__(self, user_dict: dict):
        self.username = user_dict['UserName']
        self.nickname = self._unescape_emoji(user_dict['NickName'])
        self.remark_name = self._unescape_emoji(user_dict['RemarkName'])
        self.sex = Sex(user_dict['Sex'])

    @staticmethod
    def _unescape_emoji(text):
        if 'emoji' not in text:
            return text
        return utils.replace_emoji(text)


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
        self.content = utils.replace_emoji(content)
        self.chatroom = None
        self.at = None

    def to_json(self):
        dic = super().to_json()
        dic.update({
            'content': self.content
        })
        return dic


class ImageMsg(Msg):
    def __init__(self, msg: Msg, base64_content: bytes):
        super().__init__(msg.msg_id, msg.from_user, msg.to_user, MsgType.IMAGE)
        self.base64_content = base64_content

    def to_json(self):
        dic = super().to_json()
        dic.update({
            'base64_content': self.base64_content
        })
        return dic


class EmotionMsg(Msg):
    def __init__(self, msg: Msg, content):
        super().__init__(msg.msg_id, msg.from_user, msg.to_user, MsgType.EMOTION)
        # wechat inside emotion has no content
        self.url = ''
        if content:
            index = content.find('<msg>')
            if index != -1:
                content = content[index:]
                self.url = self._parse_emotion_url(content)

    def to_json(self):
        dic = super().to_json()
        dic.update({
            'url': self.url
        })
        return dic

    @staticmethod
    def _parse_emotion_url(content):
        doc = minidom.parseString(content)
        root = doc.documentElement
        return root.getElementsByTagName('emoji')[0].getAttribute('cdnurl')
