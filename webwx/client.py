import html
import json
import logging
import mimetypes
import os
import random
import time
from abc import abstractmethod
from urllib.parse import urlencode
from xml.dom import minidom

import arrow
import qrcode
import requests
from requests_html import HTMLSession, HTMLResponse
from requests_toolbelt import MultipartEncoder

from webwx.enums import MsgType, QRCodeStatus


class WebWxClient:
    logger = logging.getLogger(__name__)

    def __init__(self):
        self.session = HTMLSession()
        # 初始化参数
        self.device_id = 'e' + repr(random.random())[2:17]
        self.redirect_uri = ''
        self.base_uri = ''
        self.skey = ''
        self.sid = ''
        self.uin = ''
        self.pass_ticket = ''
        # 上传的多媒体文件数
        self.media_count = -1

        self.base_request = None
        self.sync_key_dic = None

        self.sync_key = ''

        self.user = None
        # 特殊账号
        self.special_users = {}
        self.builtin_special_users = ['newsapp', 'fmessage', 'filehelper', 'weibo', 'qqmail', 'fmessage', 'tmessage',
                                      'qmessage',
                                      'qqsync', 'floatbottle', 'lbsapp', 'shakeapp', 'medianote', 'qqfriend',
                                      'readerapp',
                                      'blogapp', 'facebookapp', 'masssendapp', 'meishiapp', 'feedsapp',
                                      'voip', 'blogappweixin', 'weixin', 'brandsessionholder', 'weixinreminder',
                                      'wxid_novlwrv3lqwv11', 'gh_22b87fa7cb3c', 'officialaccounts',
                                      'notification_messages',
                                      'wxid_novlwrv3lqwv11', 'gh_22b87fa7cb3c', 'wxitil', 'userexperience_alarm',
                                      'notification_messages']

        # 好友
        self.contacts = {}
        # 群组
        self.groups = {}
        # 群友
        self.group_contacts = {}
        # 公众账号
        self.media_platforms = {}
        # 同步地址域名
        self.sync_host = ''

        # 登录
        status = None
        while status != QRCodeStatus.CONFIRM:
            # 生成uuid
            self.uuid = self._gen_uuid()
            status = QRCodeStatus.WAITING
            self.logger.info('请扫描下方二维码')
            # 控制台打印二维码
            self._print_qrcode()
            # 判断用户是否扫码
            while status != QRCodeStatus.EXPIRED and status != QRCodeStatus.SUCCESS:
                status = self._get_qrcode_status()
            # 判断用户是否点击登录
            while status != QRCodeStatus.EXPIRED and status != QRCodeStatus.CONFIRM:
                status = self._get_qrcode_status(0)
        self.logger.info('登录')
        if not self._login():
            self.logger.error('登录失败')
            return
        self.logger.info('初始化')
        if not self._webwxinit():
            self.logger.error('初始化失败')
            return
        self.logger.info('开启状态通知')
        if not self._webwxstatusnotify():
            self.logger.error('开启状态通知失败')
            return
        self.logger.info('获取联系人')
        if not self._webwxgetcontact():
            self.logger.error('获取联系人失败')
            return
        self.logger.info('检查同步接口')
        if not self.testsynccheck():
            self.logger.error('检查同步接口失败')
            return

    def _gen_uuid(self):
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

    def _print_qrcode(self):
        qr = qrcode.QRCode()
        qr.border = 1
        qr.add_data('https://login.weixin.qq.com/l/' + self.uuid)
        qr.make()
        qr.print_ascii(invert=True)

    def _get_qrcode_status(self, tip=1):
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

    def _login(self):
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

        if '' in (self.skey, self.sid, self.uin, self.pass_ticket):
            return False

        self.base_request = {
            'Uin':      int(self.uin),
            'Sid':      self.sid,
            'Skey':     self.skey,
            'DeviceID': self.device_id
        }
        return True

    def _logout(self):
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
        dic = self.session.post(url, json=data).json()
        if dic['BaseResponse']['Ret'] != 0:
            self.logger.error("webwxinit error: %s", dic['BaseResponse']['ErrMsg'])
            return False
        self.sync_key_dic = dic['SyncKey']
        self.sync_key = '|'.join(
            [str(kv['Key']) + '_' + str(kv['Val']) for kv in self.sync_key_dic['List']])
        self.user = dic['User']
        return True

    def _webwxstatusnotify(self):
        url = self.base_uri + '/webwxstatusnotify?lang=zh_CN&pass_ticket=%s' % self.pass_ticket
        data = {
            'BaseRequest':  self.base_request,
            "Code":         3,
            "FromUserName": self.user['UserName'],
            "ToUserName":   self.user['UserName'],
            "ClientMsgId":  int(time.time())
        }
        dic = self.session.post(url, json=data).json()
        return dic['BaseResponse']['Ret'] == 0

    def _webwxgetcontact(self):
        url = self.base_uri + '/webwxgetcontact?pass_ticket=%s&skey=%s&r=%s' % (
            self.pass_ticket, self.skey, int(time.time()))
        r = self.session.post(url)
        r.encoding = 'utf-8'
        dic = r.json()
        if dic == '':
            return False

        member_list = dic['MemberList'][:]
        for member in member_list:
            # 公众号/服务号
            if member['VerifyFlag'] & 8 != 0:
                member_list.remove(member)
                self.media_platforms[member['UserName']] = member
            # 特殊账号
            elif member['UserName'] in self.builtin_special_users:
                member_list.remove(member)
                self.special_users[member['UserName']] = member
            # 群聊
            elif '@@' in member['UserName']:
                member_list.remove(member)
                self.groups[member['UserName']] = member
            # 自己
            elif member['UserName'] == self.user['UserName']:
                member_list.remove(member)
            else:
                self.contacts[member['UserName']] = member
        return True

    # 批量获取群内联系人
    def webwxbatchgetcontact(self):
        url = self.base_uri + '/webwxbatchgetcontact?type=ex&r=%s&pass_ticket=%s' % (
            int(time.time()), self.pass_ticket)
        data = {
            'BaseRequest': self.base_request,
            "Count":       len(self.group_contacts),
            "List":        [{"UserName": u, "EncryChatRoomId": ""} for u in self.group_contacts]
        }
        dic = self.session.post(url, json=data).json()
        if dic == '':
            return False
        for member in dic['ContactList']:
            for group_member in member['MemberList']:
                self.group_contacts[group_member['UserName']] = group_member
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
        r: HTMLResponse = self.session.get(url)
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
        r = self.session.post(url, json=data)
        r.encoding = 'utf-8'
        msg = r.json()
        self.handle(msg)

    def get_sync_url(self):
        return self.base_uri + '/webwxsync?sid=%s&skey=%s&pass_ticket=%s' % (
            self.sid, self.skey, self.pass_ticket)

    def get_remark_name(self, openid):
        # 自己
        if openid in self.contacts:
            return self.contacts[openid]['RemarkName']
        # 群组的名字不算备注名，算昵称
        if openid[:2] == '@@':
            return ''
        if openid in self.special_users:
            return self.special_users[openid]['RemarkName']
        if openid in self.media_platforms:
            return self.media_platforms[openid]['RemarkName']
        if openid in self.group_contacts:
            member = self.group_contacts[openid]
            name = member['DisplayName'] if member['DisplayName'] else member['NickName']
        return ''

    def get_nick_name(self, openid):
        # 自己
        if openid == self.user['UserName']:
            return self.user['NickName']
        # 群组
        if openid[:2] == '@@':
            name = self.get_group_name(openid)
        if openid in self.contacts:
            return self.contacts[openid]['NickName']
        if openid in self.special_users:
            return self.special_users[openid]['NickName']
        if openid in self.media_platforms:
            return self.media_platforms[openid]['NickName']
        if openid in self.group_contacts:
            member = self.group_contacts[openid]
            name = member['DisplayName'] if member['DisplayName'] else member['NickName']
        return ''

    def get_group_name(self, openid):
        if openid in self.groups:
            return self.groups[openid]['NickName']
        # 现有群里面查不到
        groups = self.get_name_by_request(openid)
        for group in groups:
            # 追加到群组列表
            self.groups[group['UserName']] = group
            if group['UserName'] == openid:
                name = group['NickName']
                # 获取群名称的同时，缓存群组联系人列表
                for member in group['MemberList']:
                    self.group_contacts[member['UserName']] = member
        return self.groups[openid]['NickName']

    def get_name_by_request(self, username):
        url = self.base_uri + '/webwxbatchgetcontact?type=ex&r=%s&pass_ticket=%s' % (
            int(time.time()), self.pass_ticket)
        data = {
            'BaseRequest': self.base_request,
            "Count":       1,
            "List":        [{"UserName": username, "EncryChatRoomId": ""}]
        }
        return self.session.post(url, json=data).json()['ContactList']

    def handle(self, message):
        if message['BaseResponse']['Ret'] != 0:
            return
        self.sync_key_dic = message['SyncKey']
        self.sync_key = '|'.join(
            [str(kv['Key']) + '_' + str(kv['Val']) for kv in self.sync_key_dic['List']])

        # 遍历追加的消息
        for add_msg in message['AddMsgList']:
            try:
                msg_type = MsgType(int(add_msg['MsgType']))
            except ValueError:
                return
            msg = {
                'msg_id':           add_msg['MsgId'],
                'msg_type':         msg_type,
                'from_username':    add_msg['FromUserName'],
                'to_username':      add_msg['ToUserName'],
                'from_nickname':    self.get_nick_name(add_msg['FromUserName']),
                'to_nickname':      self.get_nick_name(add_msg['ToUserName']),
                'from_remark_name': self.get_remark_name(add_msg['FromUserName']),
                'to_remark_name':   self.get_remark_name(add_msg['ToUserName']),
                'create_time':      arrow.get(add_msg['CreateTime']).to('local').format('YYYY-MM-DD HH:mm:ss')
            }
            # 反转义
            content = html.unescape(add_msg['Content'])
            # 位置消息
            if content.find('&pictype=location') != -1:
                msg['url'] = add_msg['Url']
                msg['content'] = content
                self.handle_location(msg)
            # 文字消息
            elif msg_type == MsgType.TEXT:
                msg['content'] = content
                self.handle_text(msg)
            # 图片消息
            elif msg_type == MsgType.IMAGE:
                self.handle_image(msg)
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
                pass
            # 撤回消息
            elif msg_type == MsgType.BLOCKED:
                pass
            # 名片消息
            # 表情消息
            # 分享链接
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
            pass

    def run(self):
        self.logger.info('开始监听消息')
        # try:
        while True:
            retcode, _ = self.synccheck()
            # cookie失效
            if retcode == '1101':
                self._logout()
                self.logger.error('cookie过期')
                break
            self.webwxsync()
            time.sleep(3)
        # except Exception as e:
        #     self.logger.error(e)
        #     self._logout()

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
        """设置备注名"""
        url = self.base_uri + '/webwxoplog'
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
                "ToUserName":  to_username,
                "SvrMsgId":    msgid,
                "ClientMsgId": msgid
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
                "Type":         MsgType.TEXT.value,
                "Content":      content,
                "FromUserName": self.user['UserName'],
                "ToUserName":   to_username,
                "LocalID":      client_msg_id,
                "ClientMsgId":  client_msg_id
            },
            'Scene':       0
        }
        headers = {'content-type': 'application/json;charset=UTF-8'}
        data = json.dumps(params, ensure_ascii=False).encode()
        dic = self.session.post(url, data=data, headers=headers).json()
        success = dic['BaseResponse']['Ret'] == 0
        return success

    def webwxsendmsgimg(self, to_username, file_name):
        url = self.base_uri + '/webwxsendmsgimg?fun=async&f=json&pass_ticket=%s' % self.pass_ticket
        client_msg_id = self._gen_client_msg_id()
        media_id = self._webwxuploadmedia(file_name)
        params = {
            "BaseRequest": self.base_request,
            "Msg":         {
                "Type":         3,
                "MediaId":      media_id,
                "FromUserName": self.user['UserName'],
                "ToUserName":   to_username,
                "LocalID":      client_msg_id,
                "ClientMsgId":  client_msg_id
            }
        }
        headers = {'content-type': 'application/json;charset=UTF-8'}
        data = json.dumps(params, ensure_ascii=False).encode()
        dic = self.session.post(url, data=data, headers=headers).json()
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
        last_modified_date = '{0:ddd MMM DD YYYY HH:mm:ss} GMT{0:Z} (CST)'.format(arrow.now())
        file_content = requests.get(file_url).content
        # 文件大小
        file_size = len(file_content)
        # clientMediaId
        client_media_id = self._gen_client_msg_id()
        # webwx_data_ticket
        webwx_data_ticket = self.session.cookies['webwx_data_ticket']

        uploadmediarequest = json.dumps({
            "BaseRequest":   self.base_request,
            "ClientMediaId": client_media_id,
            "TotalLen":      file_size,
            "StartPos":      0,
            "DataLen":       file_size,
            "MediaType":     4
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
