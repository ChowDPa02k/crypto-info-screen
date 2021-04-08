import websocket
from pprint import pprint
import json

check = [False, False]

def on_message(wsapp, message):
    global check
    result = json.loads(message)
    # pprint(json.loads(message))
    if not 's' in result:
        return 0

    if result['s'] == 'ETHUSDT':
        currency = 'ETH'
        check[0] = True
    
    if result['s'] == 'BTCUSDT':
        currency = 'BTC'
        check[1] = True
    
    print(currency, result['w'], result['P'], result['c'][:-6], result['h'][:-6], result['l'][:-6])
    if check == [True, True]:
        print()
        check = [False, False]

def on_open(wsapp):
    req = '{"method": "SUBSCRIBE","params": ["ethusdt@ticker", "btcusdt@ticker"],"id": 1}'
    print(req)
    wsapp.send(req)

def on_close(wsapp):
    req = '{"method": "UNSUBSCRIBE","params": ["ethusdt@ticker", "btcusdt@ticker"],"id": 1}'
    print(req)
    wsapp.send(req)

if __name__ == "__main__":
    websocket.enableTrace(True)
    wsapp = websocket.WebSocketApp("wss://stream.binance.com:9443/ws", on_message=on_message, on_open=on_open, on_close=on_close)
    wsapp.run_forever(ping_timeout=120)