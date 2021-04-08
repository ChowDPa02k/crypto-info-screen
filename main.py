import websocket
import json
import gzip
from apscheduler.schedulers import background
import requests
from time import sleep
import signal,os,logging
import binascii
import serial
import argparse

coins = ['ETHUSDT', 'BTCUSDT']
price_change= {}

COLOR_UP_GREEN = '7596'
COLOR_DOWN_RED = '64106'
# init object parameters in HMI
# use array is not a good way, but who cares?
controls = {
    # coin name, change mark, price change percent, 24h highest, 24h lowest, price integer, price dot
    'ETH': ['cn0', 'm0', 'pc0', 'h0', 'l0', 'p0', 'p0d'],
    'BTC': ['cn1', 'm1', 'pc1', 'h1', 'l1', 'p1', 'p1d']
}

def serial_command_generator(content):
    global COLOR_DOWN_RED, COLOR_UP_GREEN, controls
    # print('got it')
    parameter = controls[content['currency']]
    # freeze screen while updating partial data might make it looks more... stable?
    commands = ['ref_stop', ]

    # change color if price goes up
    if content['rise'] == 1:
        # change mark
        commands.append(parameter[1] + '.pic=2')
        # change percent color
        commands.append(parameter[2] + '.pco=' + COLOR_UP_GREEN)
        # change price color
        commands.append(parameter[5] + '.bco=' + COLOR_UP_GREEN)
        commands.append(parameter[6] + '.bco=' + COLOR_UP_GREEN)
    # and if price goes down...
    if content['rise'] == 0:
        commands.append(parameter[1] + '.pic=1')
        commands.append(parameter[2] + '.pco=' + COLOR_DOWN_RED)
        commands.append(parameter[5] + '.bco=' + COLOR_DOWN_RED)
        commands.append(parameter[6] + '.bco=' + COLOR_DOWN_RED)
    
    # change value
    commands.append(parameter[0] + '.txt="' + content['currency'] + '"')
    
    if float(content['change']) >= 0:
        change_str = '+' + content['change'] + '%'
    else:
        change_str = content['change'] + '%'
    commands.append(parameter[2] + '.txt="' + change_str + '"')
    
    commands.append(parameter[3] + '.txt="' + str(content['high']) + '"')
    commands.append(parameter[4] + '.txt="' + str(content['low']) + '"')
    # seperate price dot to make ui looks comfortable
    price = str(content['price']).split('.')
    commands.append(parameter[5] + '.txt="' + str(price[0]) + '"')
    # some part of this 2 price controls overlayed each other, 
    # we want price after dot rendered at the top, 
    # so unfreeze before p*d got rendered, then render it,
    # this make sure that p*d will always be the last control that got updated
    commands.append('ref_star')
    commands.append(parameter[6] + '.txt=".' + str(price[1]) +' "')
    if serial_debug:
        print(commands)
    return commands

def send_serial(device, commands):
    for item in commands:
        cmd = binascii.hexlify(item.encode('utf-8')).decode('utf-8')
        cmd = bytes.fromhex(cmd+'ff ff ff')
        device.write(cmd)

def get_price_change():
    global coins, price_change
    for item in coins:
        r = requests.get('https://api.binance.com/api/v3/ticker/24hr?symbol=' + item)
        result = r.json()
        price_change[item] = result['priceChangePercent']
        # if item == 'ETHUSDT':
        #     eth_price_change = result['priceChangePercent']
        # if item == 'BTCUSDT':
        #     btc_price_change = result['priceChangePercent']
        sleep(0.5)

def on_message(wsapp, message):
    result = gzip.decompress(message)
    result = json.loads(result)

    if 'ping' in result:
        print('Got ping')
        wsapp.send(
            json.dumps({"pong": result['ping']})
        )
    if 'ch' in result:
        if result['ch'] == 'market.ethusdt.detail':
            currency = 'ETH'
            change = price_change['ETHUSDT']
        if result['ch'] == 'market.btcusdt.detail':
            currency = 'BTC'
            change = price_change['BTCUSDT']
        if verbose or print_only:
            print(currency, result['tick']['close'], float(change), result['tick']['high'], result['tick']['low'])
        if not print_only:
            command = serial_command_generator({
                'currency': currency,
                'price': result['tick']['close'],
                'rise': 0 if float(change)<0 else 1,
                'change': change,
                'high': result['tick']['high'],
                'low': result['tick']['low']
            })
            send_serial(device, command)

def on_open(wsapp):
    req_eth = '{"sub": "market.ethusdt.detail", "id": "1110"}'
    req_btc = '{"sub": "market.btcusdt.detail", "id": "1111"}'
    # print(req)
    wsapp.send(req_btc)
    wsapp.send(req_eth)

def sigint_handler():
    global schedular, wsapp
    print('Stopping Schedular...')
    schedular.shutdown()
    print('Stopping Websocket...')
    wsapp.close()

if __name__ == "__main__":
    # argument parser
    parser = argparse.ArgumentParser()
    parser.add_argument("-s", "--serial", dest="serial", help="serial port location, default is /dev/ttyAMA0")
    parser.add_argument("-l", "--list-only", dest="po", help="only print information rather than sending to serial port", action="store_true")
    parser.add_argument("-v", "--verbose", dest="verbose", help="print data from websocket", action="store_true")
    parser.add_argument("--serial-debug", dest="sd", help="show commands that sent to serial port", action="store_true")
    args = parser.parse_args()
    
    print_only = True if args.po else False
    serial_debug = True if args.sd else False
    verbose = True if args.verbose else False
    serial_port = args.serial if not (args.serial == None) else '/dev/ttyAMA0'
    if (print_only and (serial_debug or not(args.serial == None))):
        raise ValueError('list_only conflicts with serial port arguments')

    # open serial port
    if not print_only:
        device = serial.Serial(serial_port, 115200, timeout=1)
        print('Successfully open serial port', device.name)

    # init increses variable
    get_price_change()
    print('Initialized cryptocurrency price changes:')
    for item in price_change:
        print(item, price_change[item])

    # create a schedular to get price change percent
    print('Creating price change update schedular')
    schedular = background.BackgroundScheduler()
    schedular.add_job(get_price_change, 'interval', seconds=1, id='refresh')
    schedular.start()

    # establish websocket connection
    print('Establishing websocket connection\n')
    websocket.enableTrace(False)
    wsapp = websocket.WebSocketApp("wss://api.huobi.pro/ws", on_message=on_message, on_open=on_open)
    signal.signal(signal.SIGINT, sigint_handler)
    wsapp.run_forever(ping_timeout=5)
