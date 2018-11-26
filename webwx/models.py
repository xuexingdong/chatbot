from typing import Dict
from xml.dom import minidom

from webwx import utils
from webwx.enums import VerifyFlag, Sex, MsgType


def _unescape_emoji(text):
    if 'emoji' not in text:
        return text
    return utils.replace_emoji(text)


class Contact:

    def __init__(self, user_dict: dict):
        self.username = user_dict['UserName']
        self.head_img_url = user_dict['HeadImgUrl']
        self.nickname = _unescape_emoji(user_dict['NickName'])
        self.remark_name = _unescape_emoji(user_dict['RemarkName'])
        self.sex = Sex(user_dict['Sex'])

    @property
    def json(self):
        return {
            'username':     self.username,
            'head_img_url': self.head_img_url,
            'nickname':     self.nickname,
            'remark_name':  self.remark_name,
            'sex':          self.sex
        }


class SpecialUser(Contact):
    verify_flag = VerifyFlag.PERSON


class Friend(Contact):
    verify_flag = VerifyFlag.PERSON

    def __init__(self, user_dict: dict):
        super().__init__(user_dict)


class ChatroomMember:
    def __init__(self, user_dict: dict):
        self.username = user_dict['UserName']
        # remark name if contact is remarked, else is nickname
        self.nickname = _unescape_emoji(user_dict['NickName'])
        # nickname in the chatroom
        self.display_name = _unescape_emoji(user_dict['DisplayName'])


class ChatRoom(Contact):

    def __init__(self, user_dict: dict):
        super().__init__(user_dict)
        # chatroom member profile is different from user profile
        self.member_list: Dict[str, ChatroomMember] = {}

    def add_member(self, member: ChatroomMember):
        self.member_list[member.username] = member

    def clear_members(self):
        self.member_list.clear()


class MediaPlatform(Contact):
    verify_flag = VerifyFlag.COMMON_MP

    def __init__(self, user_dict: dict):
        super().__init__(user_dict)


class Msg:
    def __init__(self, msg_id, from_user, to_user, content, create_time, msg_type=MsgType.UNHANDLED):
        self.msg_id = msg_id
        self.from_user = from_user
        self.to_user = to_user
        self.msg_type = msg_type
        self.create_time = create_time
        self.content = content

    @property
    def json(self):
        return {
            'msg_id':           self.msg_id,
            'msg_type':         self.msg_type,
            'from_username':    self.from_user.username,
            'to_username':      self.to_user.username,
            'from_nickname':    self.from_user.nickname,
            'to_nickname':      self.to_user.nickname,
            'from_remark_name': self.from_user.remark_name,
            'to_remark_name':   self.to_user.remark_name,
            'content':          self.content,
            'create_time':      self.create_time
        }


class TextMsg(Msg):
    def __init__(self, msg: Msg, content):
        super().__init__(msg.msg_id, msg.from_user, msg.to_user, msg.content, msg.create_time, MsgType.TEXT)
        self.content = utils.replace_emoji(content)


class ImageMsg(Msg):
    def __init__(self, msg: Msg, base64_content):
        super().__init__(msg.msg_id, msg.from_user, msg.to_user, msg.content, msg.create_time, MsgType.IMAGE)
        self.base64_content = base64_content

    @property
    def json(self):
        dic = super().json
        dic.update({
            'base64_content': self.base64_content
        })
        return dic


class EmotionMsg(Msg):
    def __init__(self, msg: Msg, content):
        super().__init__(msg.msg_id, msg.from_user, msg.to_user, msg.content, msg.create_time, MsgType.EMOTION)
        # wechat inside emotion has no content
        self.url = ''
        if content:
            index = content.find('<msg>')
            if index != -1:
                content = content[index:]
                self.url = self._parse_emotion_url(content)

    @property
    def json(self):
        dic = super().json
        dic.update({
            'url': self.url
        })
        return dic

    @staticmethod
    def _parse_emotion_url(content):
        doc = minidom.parseString(content)
        root = doc.documentElement
        return root.getElementsByTagName('emoji')[0].getAttribute('cdnurl')


class LocationMsg(ImageMsg):
    def __init__(self, msg: Msg, base64_content):
        super().__init__(msg, base64_content)
        self.msg_type = MsgType.LOCATION
