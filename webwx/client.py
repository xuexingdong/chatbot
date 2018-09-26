import html
import json
import logging
import mimetypes
import os
import random
import time
from abc import abstractmethod
from http.client import BadStatusLine
from typing import Dict
from urllib.parse import urlencode
from xml.dom import minidom

import arrow
import qrcode
import requests
from requests_html import HTMLResponse, HTMLSession
from requests_toolbelt import MultipartEncoder

from webwx import constants
from webwx.enums import MsgType, QRCodeStatus
from webwx.models import Friend, ChatRoom, MediaPlatform, Contact, SpecialUser, TextMsg, LocationMsg, ImageMsg, Msg


class WebWxClient:
    logger = logging.getLogger(__name__)

    __login_status = False

    def __init__(self):
        self.session = HTMLSession()
        self.session.headers = {
            'User-Agent': constants.USER_AGENT
        }

        # 初始化参数
        self.device_id = self.__gen_device_id()
        self.uuid = ''
        self.redirect_uri = ''
        self.base_uri = ''
        self.skey = ''
        self.sid = ''
        self.uin = ''
        self.pass_ticket = ''
        self.media_count = -1

        # 请求所需的参数
        self.base_request = {}
        self.sync_key_dic = {}
        self.sync_host = ''

        self.user: Friend = None
        # 特殊账号
        self.special_users: Dict[str, Contact] = {}
        self.usernames_of_builtin_special_users = constants.BUILTIN_SPECIAL_USERS
        # 所有列表（也包括群聊里的人，所以此列表没有什么实际意义）
        self.contacts: Dict[str, Contact] = {}
        # 好友
        self.friends: Dict[str, Friend] = {}
        # 群组
        self.chatrooms: Dict[str, ChatRoom] = {}
        # 群友
        self.chatroom_contacts: Dict[str, Friend] = {}
        # 公众账号
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
        """
        等待扫码登录
        :return:
        """
        self.logger.info('生成uuid')
        self.uuid = self.__gen_uuid()
        self.logger.info('请扫描下方二维码')
        # 控制台打印二维码
        self.__print_login_qrcode(self.uuid)
        # 等待扫码成功
        self.__wait_until_scan_qrcode_success()
        self.logger.info('扫码成功，登录中')
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
        self.logger.info('登录成功，进行初始化')
        if not self._webwxinit():
            self.logger.error('初始化失败')
            return False
        self.logger.info('开启状态通知')
        if not self._webwxstatusnotify():
            self.logger.error('开启状态通知失败')
            return False
        self.logger.info('获取联系人')
        if not self._webwxgetcontact():
            self.logger.error('获取联系人失败')
            return False
        self.logger.info('检查同步接口')
        if not self.testsynccheck():
            self.logger.error('检查同步接口失败')
            return False
        self.after_login()
        return True

    def after_login(self):
        pass

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

    def _webwxinit(self):
        url = self.base_uri + '/webwxinit?pass_ticket=%s&skey=%s&r=%s' % (
            self.pass_ticket, self.skey, int(time.time()))
        data = {
            'BaseRequest': self.base_request
        }
        r = self.session.post(url, json=data)
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
        url = self.base_uri + '/webwxstatusnotify?lang=zh_CN&pass_ticket=%s' % self.pass_ticket
        data = {
            'BaseRequest':  self.base_request,
            'Code':         3,
            'FromUserName': self.user.username,
            'ToUserName':   self.user.username,
            'ClientMsgId':  int(time.time())
        }
        dic = self.session.post(url, json=data).json()
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
        """
        解析联系人json
        :param contacts_json:
        :return:
        """
        for contact in contacts_json:
            # 丢入联系人
            self.contacts[contact['UserName']] = Contact(contact)
            # 公众号/服务号
            if contact['VerifyFlag'] & 8 != 0:
                self.media_platforms[contact['UserName']] = MediaPlatform(contact)
            # 特殊账号
            elif contact['UserName'] in self.usernames_of_builtin_special_users:
                self.special_users[contact['UserName']] = SpecialUser(contact)
            # 群聊
            elif '@@' in contact['UserName']:
                self.chatrooms[contact['UserName']] = ChatRoom(contact)
                # 不为空才传进去（为空可能也是因为太久没访问了）
                if contact['MemberList']:
                    self.webwxbatchgetcontact([group_member['UserName'] for group_member in contact['MemberList']])
            # 自己忽略
            elif contact['UserName'] == self.user.username:
                self.contacts[self.user.username] = self.user
            # 其他情况为朋友
            else:
                self.friends[contact['UserName']] = Friend(contact)

    def webwxbatchgetcontact(self, username_list):
        """
        批量获取联系人信息，列表为空会报错
        :param username_list:
        :return:
        """
        if not username_list:
            return True
        url = self.base_uri + '/webwxbatchgetcontact?type=ex&r=%s&pass_ticket=%s' % (
            int(time.time()), self.pass_ticket)
        data = {
            'BaseRequest': self.base_request,
            'Count':       len(username_list),
            'List':        [{'UserName': u, 'EncryChatRoomId': ""} for u in username_list]
        }
        r = self.session.post(url, json=data)
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
            r: HTMLResponse = self.session.get(url)
        except BadStatusLine as _:
            # 对方正在输入，会有这个问题
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
            r = self.session.post(url, json=data)
        except BadStatusLine as _:
            # 同步消息错误
            time.sleep(3)
            return
        r.encoding = 'utf-8'
        self.logger.info('收到消息:' + json.dumps(r.json()))
        return r.json()

    def handle(self, res):
        if not res:
            return
        if res['BaseResponse']['Ret'] != 0:
            return
        self.sync_key_dic = res['SyncKey']
        if res['ModContactList']:
            # 好友信息更新
            self._parse_contacts_json(res['ModContactList'])
            self.handle_modify_contacts(list(map(lambda x: x['UserName'], res['ModContactList'])))

        # 遍历追加的消息
        for add_msg in res['AddMsgList']:
            try:
                msg_type = MsgType(int(add_msg['MsgType']))
            except ValueError:
                self.logger.error('invalid msg type:{}', add_msg['MsgType'])
                continue

            # 消息来源找不到，则属于很久没聊天的群组，需要临时获取
            if add_msg['FromUserName'] not in self.contacts:
                self.webwxbatchgetcontact([add_msg['FromUserName']])
            msg = Msg(add_msg['MsgId'], self.contacts[add_msg['FromUserName']],
                      self.contacts[add_msg['ToUserName']])
            # 反转义
            content = html.unescape(add_msg['Content'])
            # 位置消息
            if content.find('&pictype=location') != -1:
                msg = LocationMsg(msg, add_msg['Url'], content)
                self.handle_location(msg)
            elif msg_type == MsgType.TEXT:
                msg = TextMsg(msg, content)
                self.handle_text(msg)
            # 图片消息
            elif msg_type == MsgType.IMAGE:
                msg = ImageMsg(msg, content)
                self.handle_text(msg)
            # 语音消息
            elif msg_type == MsgType.VOICE:
                self.handle_voice(msg)
            # 表情
            elif msg_type == MsgType.EMOTION:
                self.handle_emotion(msg)
            # 链接
            elif msg_type == MsgType.LINK:
                self.handle_link(msg)
            # 获取联系人信息
            elif msg_type == MsgType.GET_CONTACTS_INFO:
                self.handle_sync_contacts(msg)
            # 撤回消息
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
        self.logger.info('开始监听消息')
        while True:
            retcode, selector = self.synccheck()
            if retcode == '0':
                if selector == '0':
                    self.logger.debug('无新消息')
                elif selector == '1':
                    self.logger.info('未知1')
                    msg = self.webwxsync()
                    self.logger.info(msg)
                elif selector == '2':
                    self.logger.info('新消息')
                    msg = self.webwxsync()
                    self.handle(msg)
                elif selector == '3':
                    self.logger.info('未知3')
                    msg = self.webwxsync()
                    self.handle(msg)
                elif selector == '4':
                    self.logger.info('通讯录更新')
                    self.webwxsync()
                elif selector == '5':
                    self.logger.info('未知5')
                    self.webwxsync()
                elif selector == '6':
                    self.logger.info('疑似红包')
                    msg = self.webwxsync()
                    self.handle(msg)
                elif selector == '7':
                    self.logger.info('手机操作微信聊天')
                    self.webwxsync()
                    msg = self.webwxsync()
                    self.handle(msg)
                else:
                    self.logger.info(f'未知selector: {selector}')
            elif retcode == '1100':
                self.logger.info('手动登出')
                self.logout()
            elif retcode == '1101':
                self.logger.info('cookie过期')
                self.logout()
            elif retcode == '1102':
                self.logger.info('1102')
                break
            else:
                self.logger.warning(f'未知retcode: {retcode}')

    def webwxgetmsgimg(self, msgid):
        url = self.base_uri + '/webwxgetmsgimg?MsgID=%s&skey=%s&type=slave' % (msgid, self.skey)
        return self.session.get(url).content

    # Not work now for weixin haven't support this API
    def webwxgetvideo(self, msgid):
        url = self.base_uri + '/webwxgetvideo?msgid=%s&skey=%s' % (msgid, self.skey)
        return self.session.get(url).content

    def webwxgetvoice(self, msgid):
        url = self.base_uri + '/webwxgetvoice?msgid=%s&skey=%s' % (msgid, self.skey)
        return self.session.get(url).content

    def webwxoplog(self, to_username, remark_name):
        """
        设置备注名
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

    def webwxsendmsgimg(self, to_username, file_name):
        media_id = self._webwxuploadmedia(file_name)
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

    def webwxsendappmsg(self, to_username, file_name):
        media_id = self._webwxuploadmedia(file_name)
        if not media_id:
            return
        url = self.base_uri + '/webwxsendappmsg?fun=async&f=json&pass_ticket=' + self.pass_ticket
        client_msg_id = self._gen_client_msg_id()
        params = {
            'BaseRequest': self.base_request,
            'Msg':         {
                'Type':         6,
                'Content':      (
                                        "<appmsg appid='wxeb7ec651dd0aefa9' sdkver=''><title>%s</title><des></des><action></action><type>6</type><content></content><url></url><lowurl></lowurl><appattach><totallen>%s</totallen><attachid>%s</attachid><fileext>%s</fileext></appattach><extinfo></extinfo></appmsg>" % (
                                    os.path.basename(file_name).encode(), str(os.path.getsize(file_name)),
                                    media_id,
                                    file_name.split('.')[-1])).encode(),
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
        # MIME格式
        # mime_type = application/pdf, image/jpeg, image/png, etc.
        mime_type = mimetypes.guess_type(file_url, strict=False)[0]
        # 微信识别的文档格式，微信服务器应该只支持两种类型的格式。pic和doc
        # pic格式，直接显示。doc格式则显示为文件。
        media_type = 'pic' if mime_type.split('/')[0] == 'image' else 'doc'
        # 上一次修改日期
        now = arrow.now()
        last_modified_date = f'{now:ddd MMM DD YYYY HH:mm:ss} GMT{now:Z} (CST)'
        file_content = requests.get(file_url).content
        # 文件大小
        file_size = len(file_content)
        # clientMediaId
        client_media_id = self._gen_client_msg_id()
        # webwx_data_ticket
        webwx_data_ticket = self.session.cookies['webwx_data_ticket']

        uploadmediarequest = json.dumps({
            'BaseRequest':   self.base_request,
            'ClientMediaId': client_media_id,
            'TotalLen':      file_size,
            'StartPos':      0,
            'DataLen':       file_size,
            'MediaType':     4
        }, ensure_ascii=False).encode()

        # 计数器
        self.media_count += 1
        multipart_encoder = MultipartEncoder(
            fields={
                'id':                 'WU_FILE_' + str(self.media_count),
                'name':               file_name,
                'type':               mime_type,
                'lastModifieDate':    last_modified_date,
                'size':               str(file_size),
                'mediatype':          media_type,
                'uploadmediarequest': uploadmediarequest,
                'webwx_data_ticket':  webwx_data_ticket,
                'pass_ticket':        self.pass_ticket,
                'filename':           (file_name, file_content, mime_type.split('/')[1])
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
            return response_json['MediaId']

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

    def __gen_uuid(self):
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
    def __gen_device_id():
        return 'e' + repr(random.random())[2:17]

    @staticmethod
    def __print_login_qrcode(uuid):
        """
        控制台打印二维码
        :return:
        """
        qr = qrcode.QRCode()
        qr.border = 1
        qr.add_data(f'https://login.weixin.qq.com/l/{uuid}')
        qr.make()
        qr.print_ascii(invert=True)

    def __get_qrcode_status(self, tip=1):
        url = 'https://login.weixin.qq.com/cgi-bin/mmwebwx-bin/login?loginicon=true&tip=%s&uuid=%s&_=%s' % (
            tip, self.uuid, int(time.time()))
        r: HTMLResponse = self.session.get(url)
        code = r.html.search('window.code={};')[0]
        if code == '201':
            return QRCodeStatus.SUCCESS
        elif code == '200':
            redirect_uri = r.html.search('window.redirect_uri="{}";')[0]
            self.redirect_uri = redirect_uri + '&fun=new'
            self.base_uri = redirect_uri[:redirect_uri.rfind('/')]
            return QRCodeStatus.CONFIRM
        elif code == '408':
            return QRCodeStatus.WAITING
        elif code == '400':
            return QRCodeStatus.EXPIRED

    def __wait_until_scan_qrcode_success(self):
        status = QRCodeStatus.WAITING
        while status != QRCodeStatus.CONFIRM:
            # 判断用户是否扫码
            while status != QRCodeStatus.EXPIRED and status != QRCodeStatus.SUCCESS:
                status = self.__get_qrcode_status()
            # 判断用户是否点击登录
            while status != QRCodeStatus.EXPIRED and status != QRCodeStatus.CONFIRM:
                status = self.__get_qrcode_status(0)
