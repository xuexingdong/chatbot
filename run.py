import functools
import json
import random
import threading
from logging.config import dictConfig

import pika
import yaml
from apscheduler.schedulers.background import BackgroundScheduler
from redis import StrictRedis

from config import RABBIT_HOST, RABBIT_PORT, RECEIVE_QUEUE, SEND_QUEUE, REDIS_HOST, REDIS_PORT, REDIS_DB
from webwx.client import WebWxClient
from webwx.enums import MsgType


class CustomClient(WebWxClient):

    def __init__(self):
        super().__init__()
        self.r = StrictRedis(REDIS_HOST, REDIS_PORT, REDIS_DB)
        keys = self.r.keys('chatbot:*')
        if keys:
            self.r.delete(*keys)
        self.conn = pika.BlockingConnection(pika.ConnectionParameters(RABBIT_HOST, RABBIT_PORT))
        self.receive_channel = self.conn.channel()
        self.receive_channel.queue_declare(queue=RECEIVE_QUEUE)

        # 定时维护rabbitmq心跳
        scheduler = BackgroundScheduler()
        scheduler.add_job(lambda conn: conn.process_data_events(), 'interval',
                          seconds=30, args=[self.conn])
        scheduler.start()

    def after_login(self):
        # 好友id列表
        chatids = self.friends.keys()
        # 昵称映射到chatid
        # chatid代表微信网页版聊天时为用户分配的id
        self.r.set('chatbot:self_chatid', self.user.username)
        username_dict = {}
        remark_name_dict = {}
        for username, contact in self.friends.items():
            # 没有备注，进行备注填充
            if not contact.remark_name:
                # 如果没有备注，则自动设置备注
                remark_name = self._gen_remark_name(contact.nickname)
                # 这里不去修改redis，等消息同步时，发现用户信息更新，再去修改
                self.webwxoplog(contact.username, remark_name)
            else:
                username_dict[username] = contact.remark_name
                remark_name_dict[contact.remark_name] = username
        if username_dict:
            self.r.hmset('chatbot:username_remark_name_mapping', username_dict)
        if remark_name_dict:
            self.r.hmset('chatbot:remark_name_username_mapping', remark_name_dict)

    def handle_text(self, msg):
        self.logger.info(msg.to_json())
        self._publish(msg)

    def handle_modify_contacts(self, username_list):
        for username in username_list:
            # 好友才进行备注处理，排除掉群组和其他奇怪的账号
            if username in self.friends:
                self.r.hset('chatbot:remark_name_username_mapping', self.friends[username].remark_name, username)
                old_remark_name = self.r.hget('chatbot:username_remark_name_mapping', username)
                # 旧备注删掉
                self.r.hdel('chatbot:remark_name_username_mapping', old_remark_name)
                self.r.hset('chatbot:username_remark_name_mapping', username, self.friends[username].remark_name)

    def _publish(self, msg):
        self.receive_channel.basic_publish(exchange='', routing_key=RECEIVE_QUEUE,
                                           body=json.dumps(msg.to_json()))

    @staticmethod
    def _gen_remark_name(nickname):
        return nickname + str(random.randint(100, 999))


def send(ch, method, properties, msg, webwx_client: WebWxClient):
    msg = json.loads(msg.decode())
    webwx_client.logger.info(msg)
    msg_type = MsgType(msg['msg_type'])
    try:
        if msg_type == MsgType.TEXT:
            webwx_client.webwxsendmsg(msg['to_username'], msg['content'])
        elif msg_type == MsgType.IMAGE:
            webwx_client.webwxsendmsgimg(msg['to_username'], msg['content'])
        elif msg_type == MsgType.FILE:
            webwx_client.webwxsendappmsg(msg['to_username'], msg['content'])
    except Exception as e:
        webwx_client.logger.info(e)


def consume(webwx_client):
    cb = functools.partial(send, webwx_client=webwx_client)
    conn = pika.BlockingConnection(pika.ConnectionParameters(RABBIT_HOST, RABBIT_PORT))
    channel = conn.channel()
    channel.queue_declare(queue=SEND_QUEUE)
    channel.basic_consume(cb, queue=SEND_QUEUE, no_ack=True)
    channel.start_consuming()


if __name__ == '__main__':
    with open('logging.yaml', 'rt') as f:
        config = yaml.safe_load(f.read())
    dictConfig(config)
    client = CustomClient()
    if client.wait_for_login():
        threading.Thread(target=consume, args=[client]).start()
        client.start_receiving()
