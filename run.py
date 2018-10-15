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
        self.r = StrictRedis(REDIS_HOST, REDIS_PORT, REDIS_DB, decode_responses=True)
        keys = self.r.keys('chatbot:*')
        if keys:
            self.r.delete(*keys)
        self.conn = pika.BlockingConnection(pika.ConnectionParameters(RABBIT_HOST, RABBIT_PORT))
        self.receive_channel = self.conn.channel()
        self.receive_channel.queue_declare(queue=RECEIVE_QUEUE)

        # rabbitmq heartbeat keeping thread
        scheduler = BackgroundScheduler()
        scheduler.add_job(lambda conn: conn.process_data_events(), 'interval',
                          seconds=10, args=[self.conn])
        scheduler.start()

    def after_login(self):
        # persist cookie
        self.r.hmset("chatbot:session", self.session.cookies.get_dict())
        # chatid is webwx's username
        self.r.set('chatbot:self_chatid', self.user.username)
        username_dict = {}
        remark_name_dict = {}
        for username, contact in self.friends.items():
            # set a default remark name when contact has no remark name
            if not contact.remark_name:
                remark_name = self._gen_remark_name(contact.nickname)
                # do not to modify redis data immediately
                # modify it when receiving webwx message and the function handle_modify_contacts called
                self.webwxoplog(contact.username, remark_name)
            else:
                username_dict[username] = contact.remark_name
                remark_name_dict[contact.remark_name] = username
        if username_dict:
            self.r.hmset('chatbot:username_remark_name_mapping', username_dict)
        if remark_name_dict:
            self.r.hmset('chatbot:remark_name_username_mapping', remark_name_dict)

    def handle_text(self, msg):
        self._publish(msg)

    def handle_image(self, msg):
        self._publish(msg)

    def handle_emotion(self, msg):
        self._publish(msg)

    def handle_location(self, msg):
        self._publish(msg)

    def handle_modify_contacts(self, username_list):
        for username in username_list:
            # only manage the remark name of friends, exclude chatrooms or else contacts
            if username in self.friends:
                self.r.hset('chatbot:remark_name_username_mapping', self.friends[username].remark_name, username)
                old_remark_name = self.r.hget('chatbot:username_remark_name_mapping', username)
                # remove the old remark name
                self.r.hdel('chatbot:remark_name_username_mapping', old_remark_name)
                self.r.hset('chatbot:username_remark_name_mapping', username, self.friends[username].remark_name)

    def _publish(self, msg):
        self.logger.info(msg.json)
        self.receive_channel.basic_publish(exchange='', routing_key=RECEIVE_QUEUE,
                                           body=json.dumps(msg.json))

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
    if client.wait_for_login():
        threading.Thread(target=consume, args=[client]).start()
        client.start_receiving()
