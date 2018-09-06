from typing import Dict

from webwx.enums import VerifyFlag, Sex


class Contact:

    def __init__(self, user_dict: dict):
        self.username = user_dict.get('UserName', '')
        self.nickname = user_dict.get('NickName', '')
        self.remark_name = user_dict.get('RemarkName', '')
        self.sex = Sex(user_dict.get('Sex', Sex.UNKNOWN.value))


class Person(Contact):
    verify_flag = VerifyFlag.PERSON


class ChatRoom(Contact):

    def __init__(self, user_dict: dict):
        super().__init__(user_dict)
        self.member_list: Dict[str, Person] = {}

    def add_member(self, person: Person):
        self.member_list[person.username] = person


class MediaPlatform(Contact):
    verify_flag = VerifyFlag.COMMON_MP
