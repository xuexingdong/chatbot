import functools
import json
import threading
from logging.config import dictConfig

import apscheduler
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
        self.r.delete(*self.r.keys('chatbot:*'))
        # chatid代表微信网页版聊天时为用户分配的id
        self.r.set('chatbot:self_chatid', self.user['UserName'])
        self.conn = pika.BlockingConnection(pika.ConnectionParameters(RABBIT_HOST, RABBIT_PORT))
        self.receive_channel = self.conn.channel()
        self.receive_channel.queue_declare(queue=RECEIVE_QUEUE)
        # 好友id列表
        chatids = self.contacts.keys()
        self.r.sadd('chatbot:chatids', chatids)
        # 定时维护rabbitmq心跳
        scheduler = BackgroundScheduler()
        scheduler.add_job(lambda conn: conn.process_data_events(), 'interval',
                          seconds=30, args=[self.conn])
        scheduler.start()

    def handle_text(self, msg):
        self.logger.info(msg)
        self._publish(msg)
        # # 备注处理
        # if msg['from_username'].startswith('@') and msg['content'] == '#备注':
        #     content = msg['from_remark_name'] if msg['from_remark_name'] else '无备注'
        #     if self.webwxsendmsg(msg['from_username'], content):
        #         self._publish(msg)
        # elif msg['from_username'].startswith('@') and msg['content'].startswith('#备注 '):
        #     if self.webwxoplog(msg['from_username'], msg['content'][4:]):
        #         self._publish(msg)
        # else:
        #     self._publish(msg)

    def _publish(self, msg):
        self.receive_channel.basic_publish(exchange='', routing_key=RECEIVE_QUEUE,
                                           body=json.dumps(msg, ensure_ascii=False))


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
        webwx_client.logger.error(e)


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
    threading.Thread(target=consume, args=[client]).start()
    client.start_receiving()
