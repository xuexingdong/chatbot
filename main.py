import json
from concurrent.futures import ThreadPoolExecutor
from logging.config import dictConfig

import functools
import pika
import yaml

from config import RABBIT_HOST, RABBIT_PORT, RECEIVE_QUEUE, SEND_QUEUE
from webwx.client import WebWxClient
from webwx.enums import MsgType


class CustomClient(WebWxClient):

    def __init__(self):
        super().__init__()
        self.conn = pika.BlockingConnection(pika.ConnectionParameters(RABBIT_HOST, RABBIT_PORT))
        self.receive_channel = self.conn.channel()
        self.receive_channel.queue_declare(queue=RECEIVE_QUEUE)

    def handle_text(self, msg):
        self.logger.info(msg)
        # 备注处理
        if msg['from_username'].startswith('@') and msg['content'].startswith('#备注 '):
            if self.webwxoplog(msg['from_username'], msg['content'][4:]):
                self._publish(msg)
        else:
            self._publish(msg)

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
    except Exception as e:
        webwx_client.logger.error(e)


def consume(webwx_client):
    cb = functools.partial(send, webwx_client=webwx_client)
    channel = webwx_client.conn.channel()
    channel.queue_declare(queue=SEND_QUEUE)
    channel.basic_consume(cb, queue=SEND_QUEUE, no_ack=True)
    channel.start_consuming()


if __name__ == '__main__':
    with open('logging.yaml', 'rt') as f:
        config = yaml.safe_load(f.read())
    dictConfig(config)
    executor = ThreadPoolExecutor(1)
    client = CustomClient()
    executor.submit(consume, client)
    client.run()
