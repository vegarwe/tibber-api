import aiohttp
import asyncio
import aio_mqtt
import logging
import typing as ty
import ssl
import sys
import websockets

from python_graphql_client import GraphqlClient

API_ENDPOINT    = "https://api.tibber.com/v1-beta/gql"
SUB_ENDPOINT    = "wss://api.tibber.com/v1-beta/gql/subscriptions"
AUTH_TOKEN      = "tant-og-fjase-og-slett-ikke-gyldig-kode-her"
AUTH_HEADER     = {'Authorization': f"Bearer {AUTH_TOKEN}"}

MQTT_HOST       = 'localhost'
MQTT_PORT       = 1883
MQTT_USER       = 'anonymous'
MQTT_PASS       = 'userpassword...'
MQTTCACRT       = None # '/home/vegarwe/devel/amqp_testing/mosquitto_keys/ca.crt'

async def get_homes() -> dict:
    view = "{ viewer { homes { id } }}"
    async with aiohttp.ClientSession(headers=AUTH_HEADER) as session:
        resp = await session.post(API_ENDPOINT, json={"query": view})
        #print('resp', resp)
        if resp.status != 200:
            return None
        return await resp.json()

class TibberMqtt:
    def __init__(self, home_id: str, reconnection_interval: int = 10, loop: ty.Optional[asyncio.AbstractEventLoop] = None) -> None:
        self._home_id = home_id
        self._reconnection_interval = reconnection_interval
        self._loop = loop or asyncio.get_event_loop()
        self._client = aio_mqtt.Client(loop=self._loop)
        self._tasks = [
            self._loop.create_task(self._connect_forever())
        ]

        self._i = 0

    async def close(self) -> None:
        for task in self._tasks:
            if task.done():
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        if self._client.is_connected():
            await self._client.disconnect()

    def print_handle(self, data: dict) -> None:
        #logging.info(data)
        mqtt_payload = {'power': data["data"]["liveMeasurement"]["power"]}

        self._i += 1
        if (self._i % 100) == 1:
            logging.info('pub: %s' % (mqtt_payload))

        if not self._client.is_connected():
            logging.info('not connected')

        self._loop.create_task(self._client.publish(
            aio_mqtt.PublishableMessage(
                topic_name='tibber/power',
                payload=str(mqtt_payload),
                qos=aio_mqtt.QOSLevel.QOS_0)
        ))

    async def run_livestream(self) -> None:
        await self._client.wait_for_connect()

        client = GraphqlClient(endpoint=SUB_ENDPOINT)
        query = """
        subscription{
          liveMeasurement(homeId:"%s"){
            timestamp
            power
          }
        }
        """ % (self._home_id)
        while True:
            try:
                await client.subscribe(query=query, headers={'Authorization': AUTH_TOKEN}, handle=self.print_handle)
            except websockets.exceptions.ConnectionClosedError:
                logging.error('except ConnectionClosedError')
            except websockets.exceptions.InvalidStatusCode:
                logging.error('except InvalidStatusCode')
            except asyncio.exceptions.CancelledError:
                logging.error('except CancelledError')
            except asyncio.exceptions.TimeoutError:
                logging.error('except TimeoutError')

            await asyncio.sleep(10)


    async def _connect_forever(self) -> None:
        while True:
            logging.info("_connect_forever loop")
            try:
                ssl_context = None
                if MQTTCACRT:
                    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS)
                    #ssl_context.verify_mode = ssl.CERT_NONE
                    ssl_context.verify_mode = ssl.CERT_OPTIONAL
                    ssl_context.check_hostname = False
                    #ssl_context.load_cert_chain(MQTTCACRT)
                    ssl_context.load_verify_locations(cafile=MQTTCACRT)
                connect_result = await self._client.connect(
                        MQTT_HOST, port=MQTT_PORT, ssl=ssl_context, username=MQTT_USER, password=MQTT_PASS)
                logging.info("Connected")

                #await self._client.subscribe(('in', aio_mqtt.QOSLevel.QOS_1))

                logging.info("Wait for network interruptions...")
                await connect_result.disconnect_reason
                logging.info('mqtt disconnected')
            except asyncio.CancelledError:
                raise

            except aio_mqtt.AccessRefusedError as e:
                logging.error("Access refused", exc_info=e)

            except aio_mqtt.ConnectionLostError as e:
                logging.error("Connection lost. Will retry in %d seconds", self._reconnection_interval, exc_info=e)
                await asyncio.sleep(self._reconnection_interval, loop=self._loop)

            except aio_mqtt.ConnectionCloseForcedError as e:
                logging.error("Connection close forced", exc_info=e)
                return

            except Exception as e:
                logging.error("Unhandled exception during connecting", exc_info=e)
                return

            else:
                logging.info("Disconnected")
                return

if __name__ == '__main__':
    logging.basicConfig(level='INFO')

    loop = asyncio.get_event_loop()
    home = loop.run_until_complete(get_homes())
    if not home or 'errors' in home:
        print("Error fetching homes for current API key.", home, file=sys.stderr)
        sys.exit(-1)

    try:
        # '{'data': {'viewer': {'homes': [{'id': '87ad7ad0-34b0-404c-b3f2-e44f9057d506'}]}}}
        home_id = home['data']['viewer']['homes'][0]['id']
    except KeyError:
        print("Error fetching home id for current API key.", home, file=sys.stderr)
        sys.exit(-1)

    print('home', repr(home))

    client = TibberMqtt(home_id, reconnection_interval=10, loop=loop)
    asyncio.ensure_future(client.run_livestream())
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(client.close())
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.close()

