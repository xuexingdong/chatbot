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
from webwx.enums import MsgType, EventType


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
        self.r.hmset("chatbot:client:cookie", self.session.cookies.get_dict())
        # chatid is webwx's username
        self.r.set('chatbot:client:self_chatid', self.user.username)
        username_dict = {}
        nickname_dict = {}
        remark_name_dict = {}
        for contact in self.contacts.values():
            username = contact.username
            nickname_dict[username] = contact.nickname
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
            self.r.hmset('chatbot:client:username_remark_name_mapping', username_dict)
        if nickname_dict:
            self.r.hmset('chatbot:client:username_nickname_mapping', nickname_dict)
        if remark_name_dict:
            self.r.hmset('chatbot:client:remark_name_username_mapping', remark_name_dict)

        self._persist_contact_data()

    def handle_text(self, msg):
        self._publish(msg)

    def handle_image(self, msg):
        self._publish(msg)

    def handle_emotion(self, msg):
        self._publish(msg)

    def handle_location(self, msg):
        self._publish(msg)

    def handle_update_contacts(self, username_list):
        for username in username_list:
            if username in self.chatrooms:
                self._update_chatroom_member_data(self.chatrooms[username])
            # update username remark_name mapping
            self.r.hset('chatbot:client:remark_name_username_mapping', self.contacts[username].remark_name, username)
            old_remark_name = self.r.hget('chatbot:client:username_remark_name_mapping', username)
            # remove the old remark name
            self.r.hdel('chatbot:client:remark_name_username_mapping', old_remark_name)
            self.r.hset('chatbot:client:username_remark_name_mapping', username,
                        self.contacts[username].remark_name)
            self.r.hset('chatbot:client:username_nickname_mapping', username, self.contacts[username].nickname)

    def _persist_contact_data(self):
        for special_user in self.special_users.values():
            self.r.hmset('chatbot:client:special_user:' + special_user.username, special_user.json)
        for chatroom in self.chatrooms.values():
            self.r.hmset('chatbot:client:media_platform:' + chatroom.username, chatroom.json)
        for media_platform in self.media_platforms.values():
            self.r.hmset('chatbot:client:media_platform:' + media_platform.username, media_platform.json)
        for friend in self.friends.values():
            self.r.hmset('chatbot:client:friend:' + friend.username, friend.json)

    def _update_chatroom_member_data(self, chatroom):
        chatroom_username_nickname_dict = {}
        chatroom_username_display_name_dict = {}
        member_list = chatroom.member_list
        for member in member_list.values():
            # set user nickname who is not your friend but in the chatroom
            chatroom_username_nickname_dict[member.username] = member.nickname
            chatroom_username_display_name_dict[member.username] = member.display_name
        self.r.hmset('chatbot:client:username_nickname_mapping', chatroom_username_nickname_dict)
        self.r.hmset('chatbot:client:chatroom:' + chatroom.username + ':username_display_name_mapping',
                     chatroom_username_display_name_dict)

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
    to = msg['to_username']
    event_type = EventType[msg['event_type']]
    content = msg['content']
    try:
        if event_type == EventType.SEND_MESSAGE:
            msg_type = MsgType(msg['msg_type'])
            if msg_type == MsgType.TEXT:
                webwx_client.webwxsendmsg(to, content)
            elif msg_type == MsgType.IMAGE:
                webwx_client.webwxsendmsgimg(to, content)
            elif msg_type == MsgType.FILE:
                webwx_client.webwxsendappmsg(to, content)
        elif event_type == EventType.MODIFY_FRIEND_REMARK_NAME:
            client.webwxoplog(to, content)
        elif event_type == EventType.MODIFY_FRIEND_REMARK_NAME:
            client.webwxupdatechatroom(to, content)
    except Exception as e:
        webwx_client.logger.error(e)
    ch.basic_ack(delivery_tag=method.delivery_tag)


def consume(webwx_client):
    cb = functools.partial(send, webwx_client=webwx_client)
    conn = pika.BlockingConnection(pika.ConnectionParameters(RABBIT_HOST, RABBIT_PORT))
    channel = conn.channel()
    channel.queue_declare(queue=SEND_QUEUE)
    channel.basic_consume(cb, queue=SEND_QUEUE)
    channel.start_consuming()


if __name__ == '__main__':
    with open('logging.yaml', 'rt') as f:
        config = yaml.safe_load(f.read())
    dictConfig(config)
    client = CustomClient()
    client.wait_for_login()
    threading.Thread(target=consume, args=[client]).start()
    client.start_receiving()
