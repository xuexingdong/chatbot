import base64
import html
import json
import logging
import mimetypes
import os
import random
import re
import time
from abc import abstractmethod
from typing import Dict
from urllib.parse import urlencode
from xml.dom import minidom

import arrow
import qrcode
import requests
import urllib3
from requests_html import HTMLResponse, HTMLSession
from requests_toolbelt import MultipartEncoder
from urllib3.exceptions import InsecureRequestWarning

from webwx import constants
from webwx.enums import MsgType, QRCodeStatus, SubMsgType
from webwx.models import Friend, ChatRoom, MediaPlatform, Contact, SpecialUser, TextMsg, LocationMsg, ImageMsg, Msg, \
    EmotionMsg


class WebWxClient:
    logger = logging.getLogger(__name__)

    def __init__(self):
        self.session = HTMLSession()
        self.session.verify = False
        urllib3.disable_warnings(InsecureRequestWarning)
        self.session.headers = {
            'User-Agent': constants.USER_AGENT
        }

        # initial params
        self.device_id = self._gen_device_id()
        self.uuid = ''
        self.redirect_uri = ''
        self.base_uri = ''
        self.skey = ''
        self.sid = ''
        self.uin = ''
        self.pass_ticket = ''
        self.media_count = -1

        self.base_request = {}
        self.sync_key_dic = {}
        self.sync_host = ''

        self.user: Friend = None
        self.special_users: Dict[str, Contact] = {}
        self.usernames_of_builtin_special_users = constants.BUILTIN_SPECIAL_USERS
        # all contacts(including chatroom members)
        self.contacts: Dict[str, Contact] = {}
        # friends
        self.friends: Dict[str, Friend] = {}
        self.chatrooms: Dict[str, ChatRoom] = {}
        # members in chatroom
        self.chatroom_contacts: Dict[str, Friend] = {}
        self.media_platforms: Dict[str, MediaPlatform] = {}

    @property
    def sync_key(self):
        return '|'.join(
            [str(kv['Key']) + '_' + str(kv['Val']) for kv in self.sync_key_dic['List']])

    @property
    def sync_url(self):
        return self.base_uri + '/webwxsync?sid=%s&skey=%s&pass_ticket=%s' % (
            self.sid, self.skey, self.pass_ticket)

    def wait_for_login(self) -> bool:
        self.uuid = self._gen_uuid()
        self.logger.info(f"Generate uuid: {self.uuid}")
        self.logger.info("Scan the qrcode to login")
        self._print_login_qrcode(self.uuid)
        self._wait_until_scan_qrcode_success()
        self.logger.info("Login success")
        return self._init()

    def after_login(self):
        pass

    def relogin(self):
        r = self.session.get('https://login.weixin.qq.com/cgi-bin/mmwebwx-bin/webwxpushloginurl?uin=' + self.uin)
        res = r.json()
        if res['ret'] != 0:
            return False
        self.uuid = res['uuid']
        # replace the uuid in old redirect_uri
        self.redirect_uri = re.sub('(uuid=[^&]+)', 'uuid=' + self.uuid, self.redirect_uri)
        self._init()
        return True

    def logout(self):
        url = self.base_uri + '/webwxlogout'
        params = {
            'redirect': 1,
            'type':     1,
            'skey':     self.skey
        }
        data = {
            'sid': self.sid,
            'uin': self.uin
        }
        r = self.session.post(url, params=params, data=data, allow_redirects=False)
        return r.status_code == 301

    def _init(self):
        xml = self.session.get(self.redirect_uri).text
        doc = minidom.parseString(xml)
        root = doc.documentElement
        for node in root.childNodes:
            if node.nodeName == 'skey':
                self.skey = node.childNodes[0].data
            elif node.nodeName == 'wxsid':
                self.sid = node.childNodes[0].data
            elif node.nodeName == 'wxuin':
                self.uin = node.childNodes[0].data
            elif node.nodeName == 'pass_ticket':
                self.pass_ticket = node.childNodes[0].data

        self.base_request = {
            'Uin':      int(self.uin),
            'Sid':      self.sid,
            'Skey':     self.skey,
            'DeviceID': self.device_id
        }
        self.logger.info('Initing...')
        if not self._webwxinit():
            self.logger.error('Init failed')
            return False
        self.logger.info('Starting notifying...')
        if not self._webwxstatusnotify():
            self.logger.error('Start notifying failed')
            return False
        self.logger.info('Getting contacts...')
        if not self._webwxgetcontact():
            self.logger.error('获取联系人失败')
            return False
        self.logger.info('Checking sync interface')
        if not self.testsynccheck():
            self.logger.error('Checking failed')
            return False
        self.after_login()
        return True

    def _webwxinit(self):
        url = self.base_uri + '/webwxinit'
        params = {
            'pass_ticket': self.pass_ticket,
            'skey':        self.skey,
            'r':           int(time.time())
        }
        data = {
            'BaseRequest': self.base_request
        }
        r = self.session.post(url, params=params, json=data, timeout=60)
        r.encoding = 'utf-8'
        dic = r.json()
        if dic['BaseResponse']['Ret'] != 0:
            self.logger.error(f"webwxinit error: {dic['BaseResponse']['ErrMsg']}")
            return False
        self.sync_key_dic = dic['SyncKey']
        self.user = Friend(dic['User'])
        self._parse_contacts_json(dic['ContactList'])
        return True

    def _webwxstatusnotify(self):
        url = self.base_uri + '/webwxstatusnotify'
        params = {
            'lang':        'zh_CN',
            'pass_ticket': self.pass_ticket,
        }
        data = {
            'BaseRequest':  self.base_request,
            'Code':         3,
            'FromUserName': self.user.username,
            'ToUserName':   self.user.username,
            'ClientMsgId':  int(time.time())
        }
        dic = self.session.post(url, params=params, json=data).json()
        return dic['BaseResponse']['Ret'] == 0

    def _webwxgetcontact(self):
        url = self.base_uri + '/webwxgetcontact?pass_ticket=%s&skey=%s&r=%s' % (
            self.pass_ticket, self.skey, int(time.time()))
        r = self.session.post(url)
        r.encoding = 'utf-8'
        dic = r.json()
        if dic['BaseResponse']['Ret'] != 0:
            self.logger.error(f"webwxgetcontact error: {dic['BaseResponse']['ErrMsg']}")
            return False

        member_list = dic['MemberList'][:]
        self._parse_contacts_json(member_list)
        return True

    def _parse_contacts_json(self, contacts_json):
        for contact in contacts_json:
            self.contacts[contact['UserName']] = Contact(contact)
            # media platform
            if contact['VerifyFlag'] & 8 != 0:
                self.media_platforms[contact['UserName']] = MediaPlatform(contact)
            # special users
            elif contact['UserName'] in self.usernames_of_builtin_special_users:
                self.special_users[contact['UserName']] = SpecialUser(contact)
            # chatroom
            elif '@@' in contact['UserName']:
                self.chatrooms[contact['UserName']] = ChatRoom(contact)
                # if contact['MemberList']:
                #     self.webwxbatchgetcontact([group_member['UserName'] for group_member in contact['MemberList']])
            # self
            elif contact['UserName'] == self.user.username:
                self.contacts[self.user.username] = self.user
            # normal friends
            else:
                self.friends[contact['UserName']] = Friend(contact)

    def webwxbatchgetcontact(self, username_list):
        if not username_list:
            return True
        url = self.base_uri + '/webwxbatchgetcontact'
        params = {
            'type':        'ex',
            'pass_ticket': self.pass_ticket,
            'r':           int(time.time())
        }
        data = {
            'BaseRequest': self.base_request,
            'Count':       len(username_list),
            'List':        [{'UserName': u, 'EncryChatRoomId': ""} for u in username_list]
        }
        r = self.session.post(url, params=params, json=data)
        r.encoding = 'utf-8'
        dic = r.json()
        if dic['BaseResponse']['Ret'] != 0:
            self.logger.error(f"webwxbatchgetcontact error: {dic['BaseResponse']['ErrMsg']}")
            return False
        for member in dic['ContactList']:
            friend = Friend(member)
            self.contacts[friend.username] = friend
            self.chatroom_contacts[friend.username] = friend
        return True

    def testsynccheck(self):
        sync_hosts = ['wx2.qq.com',
                      'webpush.wx2.qq.com',
                      'wx8.qq.com',
                      'webpush.wx8.qq.com',
                      'qq.com',
                      'webpush.wx.qq.com',
                      'web2.wechat.com',
                      'webpush.web2.wechat.com',
                      'wechat.com',
                      'webpush.web.wechat.com',
                      'webpush.weixin.qq.com',
                      'webpush.wechat.com',
                      'webpush1.wechat.com',
                      'webpush2.wechat.com',
                      'webpush.wx.qq.com',
                      'webpush2.wx.qq.com']
        for host in sync_hosts:
            self.sync_host = host
            retcode, _ = self.synccheck()
            if retcode == '0':
                return True
        return False

    def synccheck(self):
        params = {
            'r':        int(time.time()),
            'sid':      self.sid,
            'uin':      self.uin,
            'skey':     self.skey,
            'deviceid': self.device_id,
            'synckey':  self.sync_key,
            '_':        int(time.time()),
        }
        url = 'https://' + self.sync_host + '/cgi-bin/mmwebwx-bin/synccheck?' + urlencode(params)
        try:
            r: HTMLResponse = self.session.get(url, timeout=60)
        except requests.exceptions.Timeout as _:
            self.logger.warning('Timeout')
            time.sleep(3)
            return [-1, -1]
        except requests.exceptions.ConnectionError as _:
            self.logger.warning('BadStatusLine')
            time.sleep(3)
            return [-1, -1]
        self.logger.debug(r.content)
        if r.text == '':
            return [-1, -1]

        retcode, selector = r.html.search('retcode:"{}",selector:"{}"')
        return retcode, selector

    def webwxsync(self):
        url = self.base_uri + '/webwxsync?sid=%s&skey=%s&pass_ticket=%s' % (
            self.sid, self.skey, self.pass_ticket)
        data = {
            'BaseRequest': self.base_request,
            'SyncKey':     self.sync_key_dic,
            'rr':          ~int(time.time())
        }
        try:
            r = self.session.post(url, json=data, timeout=60)
        except requests.exceptions.Timeout as _:
            self.logger.warning('Timeout')
            return
        except requests.exceptions.ConnectionError as _:
            self.logger.warning('Connection error')
            time.sleep(3)
            return
        r.encoding = 'utf-8'
        return r.json()

    def handle(self, res):
        if not res:
            return
        if res['BaseResponse']['Ret'] != 0:
            return
        self.sync_key_dic = res['SyncKey']
        if res['ModContactList']:
            # contact info updated
            self._parse_contacts_json(res['ModContactList'])
            self.handle_modify_contacts(list(map(lambda x: x['UserName'], res['ModContactList'])))
        for add_msg in res['AddMsgList']:
            msg_type = MsgType(int(add_msg['MsgType']))
            # can't find fromUsername in self.contacts, the message might be from the chatroom
            # call self.webwxbatchgetcontact to update the contracts list
            if add_msg['FromUserName'] not in self.contacts:
                self.webwxbatchgetcontact([add_msg['FromUserName']])
            if add_msg['ToUserName'] not in self.contacts:
                self.webwxbatchgetcontact([add_msg['ToUserName']])
            # unescape html
            content = html.unescape(add_msg['Content'])
            msg = Msg(add_msg['MsgId'], self.contacts[add_msg['FromUserName']],
                      self.contacts[add_msg['ToUserName']], content, add_msg['CreateTime'])

            if msg_type == MsgType.TEXT:
                # location info
                if SubMsgType(int(add_msg['SubMsgType'])):
                    content = self.webwxgetpubliclinkimg(msg.msg_id)
                    msg = LocationMsg(msg, base64.b64encode(content).decode())
                    self.handle_location(msg)
                else:
                    msg = TextMsg(msg, content)
                    self.handle_text(msg)
            # pic info
            elif msg_type == MsgType.IMAGE:
                content = self.webwxgetmsgimg(msg.msg_id)
                msg = ImageMsg(msg, base64.b64encode(content).decode())
                self.handle_image(msg)
            elif msg_type == MsgType.VOICE:
                self.handle_voice(msg)
            elif msg_type == MsgType.EMOTION:
                # HasProductId?
                msg = EmotionMsg(msg, content)
                self.handle_emotion(msg)
            elif msg_type == MsgType.LINK:
                self.handle_link(msg)
            elif msg_type == MsgType.GET_CONTACTS_INFO:
                self.handle_sync_contacts(msg)
            # revoke message
            elif msg_type == MsgType.BLOCKED:
                pass
            # elif msg_type == MsgType.CARD:
            #     info = msg['RecommendInfo']
            #     print('%s 发送了一张名片:' % name)
            #     print('=========================')
            #     print('= 昵称: %s' % info['NickName'])
            #     print('= 微信号: %s' % info['Alias'])
            #     print('= 地区: %s %s' % (info['Province'], info['City']))
            #     print('= 性别: %s' % ['未知', '男', '女'][info['Sex']])
            #     print('=========================')
            #     raw_msg = {'raw_msg': msg, 'message': '%s 发送了一张名片: %s' % (
            #         name.strip(), json.dumps(info))}
            #     self._showMsg(raw_msg)
            # elif msg_type == MsgType.EMOTION:
            #     url = self._searchContent('cdnurl', content)
            #     raw_msg = {'raw_msg': msg,
            #                'message': '%s 发了一个动画表情，点击下面链接查看: %s' % (name, url)}
            #     self._showMsg(raw_msg)
            #     self._safe_open(url)
            # elif msg_type == MsgType.LINK:
            #     appMsgType = defaultdict(lambda: "")
            #     appMsgType.update({5: '链接', 3: '音乐', 7: '微博'})
            #     print('%s 分享了一个%s:' % (name, appMsgType[msg['AppMsgType']]))
            #     print('=========================')
            #     print('= 标题: %s' % msg['FileName'])
            #     print('= 描述: %s' % self._searchContent('des', content, 'xml'))
            #     print('= 链接: %s' % msg['Url'])
            #     print('= 来自: %s' % self._searchContent('appname', content, 'xml'))
            #     print('=========================')
            #     card = {
            #         'title': msg['FileName'],
            #         'description': self._searchContent('des', content, 'xml'),
            #         'url': msg['Url'],
            #         'appname': self._searchContent('appname', content, 'xml')
            #     }
            #     raw_msg = {'raw_msg': msg, 'message': '%s 分享了一个%s: %s' % (
            #         name, appMsgType[msg['AppMsgType']], json.dumps(card))}
            #     self._showMsg(raw_msg)
            # elif msgType == 51:
            #     raw_msg = {'raw_msg': msg, 'message': '[*] 成功获取联系人信息'}
            #     self._showMsg(raw_msg)
            # elif msgType == 62:
            #     video = self.webwxgetvideo(msgid)
            #     raw_msg = {'raw_msg': msg,
            #                'message': '%s 发了一段小视频: %s' % (name, video)}
            #     self._showMsg(raw_msg)
            #     self._safe_open(video)
            # elif msgType == 10002:
            #     raw_msg = {'raw_msg': msg, 'message': '%s 撤回了一条消息' % name}
            #     self._showMsg(raw_msg)
            # else:
            #     self.loggerdebug('[*] 该消息类型为: %d，可能是表情，图片, 链接或红包: %s' %
            #                   (msg['MsgType'], json.dumps(msg)))
            #     raw_msg = {
            #         'raw_msg': msg, 'message': '[*] 该消息类型为: %d，可能是表情，图片, 链接或红包' % msg['MsgType']}
            #     self._showMsg(raw_msg)

    def start_receiving(self):
        self.logger.info('Start receiving...')
        while True:
            retcode, selector = self.synccheck()
            if retcode == '0':
                if selector == '0':
                    pass
                elif selector == '1':
                    msg = self.webwxsync()
                    self.logger.info(msg)
                elif selector == '2':
                    msg = self.webwxsync()
                    self.handle(msg)
                elif selector == '3':
                    msg = self.webwxsync()
                    self.handle(msg)
                elif selector == '4':
                    self.logger.info("Contact info updated")
                    self.webwxsync()
                elif selector == '5':
                    self.webwxsync()
                elif selector == '6':
                    self.logger.info('App message: red package, article, etc.')
                    msg = self.webwxsync()
                    self.handle(msg)
                elif selector == '7':
                    self.logger.info("Enter/leave chat window by phone")
                    self.webwxsync()
                    msg = self.webwxsync()
                    self.handle(msg)
                else:
                    self.logger.info(f"Unknown selector: {selector}")
            elif retcode == '1100':
                self.logger.info("Logout")
                self.wait_for_login()
            elif retcode == '1101':
                self.logger.info("Cookie expired")
                if not self.relogin():
                    self.wait_for_login()
            elif retcode == '1102':
                self.logger.info('1102')
                if not self.relogin():
                    self.wait_for_login()
            else:
                self.logger.warning(f"Unknown retcode: {retcode}")

    def webwxgetmsgimg(self, msgid):
        # add param type=slave to get the thumbnail instead of the whole image
        url = self.base_uri + '/webwxgetmsgimg?MsgID=%s&skey=%s' % (msgid, self.skey)
        return self.session.get(url).content

    # Not work now for weixin haven't support this API
    def webwxgetvideo(self, msgid):
        url = self.base_uri + '/webwxgetvideo?msgid=%s&skey=%s' % (msgid, self.skey)
        return self.session.get(url).content

    def webwxgetvoice(self, msgid):
        url = self.base_uri + '/webwxgetvoice?msgid=%s&skey=%s' % (msgid, self.skey)
        return self.session.get(url).content

    def webwxgetpubliclinkimg(self, msgid):
        url = self.base_uri + '/webwxgetpubliclinkimg?url=xxx&msgid=%s&pictype=location' % msgid
        return self.session.get(url).content

    def webwxoplog(self, to_username, remark_name):
        """
        set remark name to an user
        :param to_username:
        :param remark_name:
        :return:
        """
        url = self.base_uri + '/webwxoplog?pass_ticket=%s' % self.pass_ticket
        params = {
            'BaseRequest': self.base_request,
            'CmdId':       2,
            'RemarkName':  remark_name,
            'UserName':    to_username
        }
        headers = {'content-type': 'application/json;charset=UTF-8'}
        data = json.dumps(params, ensure_ascii=False).encode()
        dic = self.session.post(url, data=data, headers=headers).json()
        success = dic['BaseResponse']['Ret'] == 0
        return success

    def webwxrevokemsg(self, msgid, to_username):
        url = self.base_uri + '/webwxrevokemsg'
        params = {
            'BaseRequest': self.base_request,
            'Msg':         {
                'ToUserName':  to_username,
                'SvrMsgId':    msgid,
                'ClientMsgId': msgid
            }
        }
        headers = {'content-type': 'application/json;charset=UTF-8'}
        data = json.dumps(params, ensure_ascii=False).encode()
        dic = self.session.post(url, data=data, headers=headers).json()
        success = dic['BaseResponse']['Ret'] == 0
        return success

    def webwxsendmsg(self, to_username, content):
        url = self.base_uri + '/webwxsendmsg?pass_ticket=%s' % self.pass_ticket
        client_msg_id = self._gen_client_msg_id()
        params = {
            'BaseRequest': self.base_request,
            'Msg':         {
                'Type':         MsgType.TEXT.value,
                'Content':      content,
                'FromUserName': self.user.username,
                'ToUserName':   to_username,
                'LocalID':      client_msg_id,
                'ClientMsgId':  client_msg_id
            }
        }
        headers = {'content-type': 'application/json;charset=UTF-8'}
        data = json.dumps(params, ensure_ascii=False).encode()
        dic = self.session.post(url, data=data, headers=headers).json()
        success = dic['BaseResponse']['Ret'] == 0
        return success

    def webwxsendmsgimg(self, to_username, file_url):
        media_id, _ = self._webwxuploadmedia(file_url)
        if not media_id:
            return
        url = self.base_uri + '/webwxsendmsgimg?fun=async&f=json&pass_ticket=%s' % self.pass_ticket
        client_msg_id = self._gen_client_msg_id()
        params = {
            'BaseRequest': self.base_request,
            'Msg':         {
                'Type':         3,
                'MediaId':      media_id,
                'FromUserName': self.user.username,
                'ToUserName':   to_username,
                'LocalID':      client_msg_id,
                'ClientMsgId':  client_msg_id
            }
        }
        headers = {'content-type': 'application/json;charset=UTF-8'}
        data = json.dumps(params, ensure_ascii=False).encode()
        dic = self.session.post(url, data=data, headers=headers).json()
        success = dic['BaseResponse']['Ret'] == 0
        return success

    def webwxsendappmsg(self, to_username, file_url):
        media_id, file_size = self._webwxuploadmedia(file_url)
        if not media_id:
            return
        url = self.base_uri + '/webwxsendappmsg?fun=async&f=json&pass_ticket=' + self.pass_ticket
        client_msg_id = self._gen_client_msg_id()
        params = {
            'BaseRequest': self.base_request,
            'Msg':         {
                'Type':         6,
                'Content':      "<appmsg appid='wxeb7ec651dd0aefa9' sdkver=''><title>%s</title><des></des><action></action><type>6</type><content></content><url></url><lowurl></lowurl><appattach><totallen>%s</totallen><attachid>%s</attachid><fileext>%s</fileext></appattach><extinfo></extinfo></appmsg>" % (
                    os.path.basename(file_url), file_size,
                    media_id,
                    file_url.split('.')[-1]),
                'FromUserName': self.user.username,
                'ToUserName':   to_username,
                'LocalID':      client_msg_id,
                'ClientMsgId':  client_msg_id
            }
        }
        data = json.dumps(params, ensure_ascii=False).encode()
        dic = self.session.post(url, data=data).json()
        success = dic['BaseResponse']['Ret'] == 0
        return success

    def _webwxuploadmedia(self, file_url):
        url = 'https://file.wx2.qq.com/cgi-bin/mmwebwx-bin/webwxuploadmedia?f=json'

        file_name = os.path.basename(file_url)
        # MIME type
        # mime_type = application/pdf, image/jpeg, image/png, etc.
        mime_type = mimetypes.guess_type(file_url, strict=False)[0]
        # 微信识别的文档格式，微信服务器应该只支持两种类型的格式。pic和doc
        # pic格式，直接显示。doc格式则显示为文件。
        if mime_type and mime_type.split('/')[0] == 'image':
            media_type = 'pic'
        else:
            media_type = 'doc'
        now = arrow.now()
        last_modified_datetime = f'{now:ddd MMM DD YYYY HH:mm:ss} GMT{now:Z} (CST)'
        file_content = requests.get(file_url).content
        file_size = len(file_content)
        client_media_id = self._gen_client_msg_id()
        # get webwx_data_ticket from cookie
        webwx_data_ticket = self.session.cookies['webwx_data_ticket']

        uploadmediarequest = json.dumps({
            'BaseRequest':   self.base_request,
            'ClientMediaId': client_media_id,
            'TotalLen':      file_size,
            'StartPos':      0,
            'DataLen':       file_size,
            'MediaType':     4
        }, ensure_ascii=False).encode()

        # counter
        self.media_count += 1
        multipart_encoder = MultipartEncoder(
            fields={
                'id':                 'WU_FILE_' + str(self.media_count),
                'name':               file_name,
                'type':               'application/octet-stream',
                'lastModifieDate':    last_modified_datetime,
                'size':               str(file_size),
                'mediatype':          media_type,
                'uploadmediarequest': uploadmediarequest,
                'webwx_data_ticket':  webwx_data_ticket,
                'pass_ticket':        self.pass_ticket,
                'filename':           (file_name, file_content, 'application/octet-stream')
            },
            boundary='-----------------------------1575017231431605357584454111'
        )

        headers = {
            'Host':            'file2.wx.qq.com',
            'User-Agent':      'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.10; rv:42.0) Gecko/20100101 Firefox/42.0',
            'Accept':          'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'Accept-Encoding': 'gzip, deflate',
            'Referer':         'https://wx2.qq.com/',
            'Content-Type':    multipart_encoder.content_type,
            'Origin':          'https://wx2.qq.com',
            'Connection':      'keep-alive',
            'Pragma':          'no-cache',
            'Cache-Control':   'no-cache'
        }

        r = self.session.post(url, data=multipart_encoder, headers=headers)
        response_json = r.json()
        if response_json['BaseResponse']['Ret'] == 0:
            return response_json['MediaId'], file_size

    @abstractmethod
    def handle_text(self, msg):
        pass

    @abstractmethod
    def handle_image(self, msg):
        pass

    @abstractmethod
    def handle_file(self, msg):
        pass

    @abstractmethod
    def handle_voice(self, msg):
        pass

    @abstractmethod
    def handle_card(self, msg):
        pass

    @abstractmethod
    def handle_video(self, msg):
        pass

    @abstractmethod
    def handle_emotion(self, msg):
        pass

    @abstractmethod
    def handle_location(self, msg):
        pass

    @abstractmethod
    def handle_link(self, msg):
        pass

    @abstractmethod
    def handle_sync_contacts(self, msg):
        pass

    @abstractmethod
    def handle_modify_contacts(self, username_list):
        pass

    @abstractmethod
    def handle_call(self, msg):
        pass

    @abstractmethod
    def handle_system(self, msg):
        pass

    @abstractmethod
    def handle_blocked(self, msg):
        pass

    @staticmethod
    def _gen_client_msg_id():
        return str(int(time.time() * 1000)) + str(random.random())[:5].replace('.', '')

    def _gen_uuid(self):
        """
        生成uuid
        :return:
        """
        url = 'https://login.weixin.qq.com/jslogin'
        params = {
            'appid': 'wx782c26e4c19acffb',
            'fun':   'new',
            'lang':  'zh_CN',
            '_':     int(time.time()),
        }

        r: HTMLResponse = self.session.get(url, params=params)
        code, uuid = r.html.search('window.QRLogin.code = {}; window.QRLogin.uuid = "{}"')
        if code == '200':
            return uuid

    @staticmethod
    def _gen_device_id():
        return 'e' + repr(random.random())[2:17]

    @staticmethod
    def _print_login_qrcode(uuid):
        qr = qrcode.QRCode()
        qr.border = 1
        qr.add_data(f'https://login.weixin.qq.com/l/{uuid}')
        qr.make()
        qr.print_ascii(invert=True)

    def _get_qrcode_status(self, tip=1):
        url = 'https://login.weixin.qq.com/cgi-bin/mmwebwx-bin/login'
        params = {
            'loginicon': True,
            'tip':       tip,
            'uuid':      self.uuid,
            '_':         int(time.time()),
        }
        try:
            r: HTMLResponse = self.session.get(url, params=params, timeout=60)
        except requests.exceptions.Timeout as _:
            self.logger.warning('Querying qrcode status timeout')
            time.sleep(1)
            return QRCodeStatus.EXPIRED
        code = r.html.search('window.code={};')[0]
        if code == '201':
            return QRCodeStatus.SUCCESS
        elif code == '200':
            redirect_uri, = r.html.search('window.redirect_uri="{}";')
            self.redirect_uri = redirect_uri + '&fun=new'
            self.base_uri = redirect_uri[:redirect_uri.rfind('/')]
            return QRCodeStatus.CONFIRM
        elif code == '408':
            return QRCodeStatus.WAITING
        elif code == '400':
            return QRCodeStatus.EXPIRED

    def _wait_until_scan_qrcode_success(self):
        while True:
            status = QRCodeStatus.WAITING
            # if scanned
            while status == QRCodeStatus.WAITING:
                status = self._get_qrcode_status()
            # if click login
            while status == QRCodeStatus.SUCCESS:
                status = self._get_qrcode_status(0)
            if status == QRCodeStatus.EXPIRED:
                self.uuid = self._gen_uuid()
                self.logger.info(f"Qrcode is expired, regenerate with new uuid: {self.uuid}")
                self._print_login_qrcode(self.uuid)
            if status == QRCodeStatus.CONFIRM:
                break
