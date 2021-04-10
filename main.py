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
from scipy.interpolate import interp1d
import datetime
import numpy as np

coins = ['ETHUSDT', 'BTCUSDT']
price_change= {}

SERIAL_BLOCKED = False
COLOR_UP_GREEN = '7596'
COLOR_DOWN_RED = '64106'
# init object parameters in HMI
# use array is not a good way, but who cares?
controls = {
    # coin name, change mark, price change percent, 24h highest, 24h lowest, price integer, price dot
    'ETH': ['page0.cn0', 'page0.m0', 'page0.pc0', 'page0.h0', 'page0.l0', 'page0.p0', 'page0.p0d'],
    'BTC': ['page0.cn1', 'page0.m1', 'page0.pc1', 'page0.h1', 'page0.l1', 'page0.p1', 'page0.p1d']
}
pool_controls = {
        'pool_name' : 'page1.pn',
        'balance' : 'page1.vb',
        'daily_income': 'page1.vd',
        'monthly_income': 'page1.vm',
        'realtime_hashrate': 'page1.rh',
        'average_hashrate': 'page1.ah',
        'local_hashrate': 'page1.lh',
        'average_local_hashrate': 'page1.la',
        'online': 'page1.onc',
        'offline': 'page1.ofc',
        'balance_cny': 'page1.vbc',
        'daily_cny': 'page1.vdc',
        'monthly_cny': 'page1.vmc',
        'scale': 'page1.scale'
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

def serial_pool_command_generator(content):
    global pool_controls
    commands = []
    commands.append(pool_controls['pool_name'] + '.txt="%s"' % content['pool_name'])
    for key in ['balance', 'daily_income', 'monthly_income']:
        commands.append(pool_controls[key] + '.txt="%.6f"' % float(content[key]))
    for key in ['balance_cny', 'daily_cny', 'monthly_cny']:
        commands.append(pool_controls[key] + '.txt="%.2f CNY"' % float(content[key]))
    for key in ['realtime_hashrate', 'average_hashrate', 'local_hashrate', 'average_local_hashrate']:
        commands.append(pool_controls[key] + '.txt="%.2fM"' % float(float(content[key])/1000000.0))
    for key in ['online', 'offline']:
        commands.append(pool_controls[key] + '.txt="%.0f"' % content[key])
    scale = content['online'] / (content['online'] + content['offline'])
    commands.append(pool_controls['scale'] + '.val=%i' % int(scale*100))
    return commands

def serial_chart_command_generator(content):
    commands = ['page 2', 'cle 3,0', 'cle 3,1']
    for item in content['hashrate']:
        commands.append('add 3,0,%i' % item)
    for item in content['price']:
        commands.append('add 3,1,%i' % item)
    for item in range(4,8):
        commands.append('ref %i' % item)
    commands.append('page 0')
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
    # print('💹 Price change updated')

def get_pool_status(miner):
    worker = 'https://www.sparkpool.com/v1/miner/stats'
    bill = 'https://www.sparkpool.com/v1/bill/stats'
    exchange = 'https://api.coinbase.com/v2/exchange-rates?currency=ETH'

    r_worker = requests.get(worker, params={
        'currency': 'ETH',
        'miner': miner
    })
    r_bill = requests.get(bill, params={
        'currency': 'ETH',
        'miner': miner
    })
    r_exchange = requests.get(exchange)

    worker_status = r_worker.json()
    bill_status = r_bill.json()
    exchange_value = r_exchange.json()
    exchange_value = float(exchange_value['data']['rates']['CNY'])

    balance_exchanged = exchange_value * float(bill_status['data']['balance'])
    daily_exchanged = exchange_value * float(bill_status['data']['pay1day'])
    monthly_exchanged = exchange_value * float(bill_status['data']['paid30days'])

    return {
        'pool_name' : miner,
        'balance' : bill_status['data']['balance'],
        'daily_income': bill_status['data']['pay1day'],
        'monthly_income': bill_status['data']['paid30days'],
        'realtime_hashrate': worker_status['data']['hashrate'],
        'average_hashrate': worker_status['data']['meanHashrate24h'],
        'local_hashrate': worker_status['data']['localHashrate'],
        'average_local_hashrate': worker_status['data']['meanLocalHashrate24h'],
        'online': float(worker_status['data']['onlineWorkerCount']),
        'offline': float(worker_status['data']['offlineWorkerCount']),
        'balance_cny': balance_exchanged,
        'daily_cny': daily_exchanged,
        'monthly_cny': monthly_exchanged
    }

def update_pool_status():
    global pool, SERIAL_BLOCKED
    pool_status = get_pool_status(pool)
    if verbose:
        print(pool_status)
    commands = serial_pool_command_generator(pool_status)
    if serial_debug:
        print(commands)
    if not print_only:
        while True:
            if not SERIAL_BLOCKED:
                SERIAL_BLOCKED = True
                sleep(0.2)
                send_serial(device, commands)
                SERIAL_BLOCKED = False
                break
            print('Sparkpool status: Waiting for serial port released')
            sleep(1)
    print('🔥 Sparkpool status', pool, 'updated')

def update_network_status():
    global SERIAL_BLOCKED

    def norm(array):
        return (224 * (array - np.min(array)) / np.ptp(array)).astype(int)

    url = 'https://www.sparkpool.com/v1/currency/statsHistory'
    r = requests.get(url, params={
        'currency': 'ETH',
        'zoom': 'm'
    })
    data = r.json()['data']

    hashrate = []
    usd = []

    for item in data:
    # time.append(dateutil.parser.isoparse(item['time']))
        hashrate.append(float(item['hashrate'])/1000000000000)
        usd.append(item['usd'])
    x = np.linspace(0,120,120)
    x_scaled = np.linspace(0, 120, 448)

    interpreted_hashrate = interp1d(x, hashrate, kind='cubic')
    interpreted_price = interp1d(x, usd, kind='cubic')
    commands = serial_chart_command_generator({
        'hashrate': norm(interpreted_hashrate(x_scaled)),
        'price': norm(interpreted_price(x_scaled))
    })
    if verbose:
        print(data)
    if serial_debug:
        print(commands)
    if not print_only:
        while True:
            if not SERIAL_BLOCKED:
                SERIAL_BLOCKED = True
                sleep(0.2)
                send_serial(device, commands)
                SERIAL_BLOCKED = False
                break
            print('Global ETH mining status: Waiting for serial port released')
            sleep(1)
    print('🌐 Global ETH mining status updated')

def on_message(wsapp, message):
    result = gzip.decompress(message)
    result = json.loads(result)

    if 'ping' in result:
        print('❤ Got ping')
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
            if not SERIAL_BLOCKED:
                send_serial(device, command)
            else:
                print('⏭ Skipped update price information due to blocked serial port')

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
    parser.add_argument("-p", "--pool", dest="pool", help="update miner account information in sparkpool if given")
    parser.add_argument("-l", "--list-only", dest="po", help="only print information rather than sending to serial port", action="store_true")
    parser.add_argument("-v", "--verbose", dest="verbose", help="print data from network", action="store_true")
    parser.add_argument("--serial-debug", dest="sd", help="show commands that sent to serial port", action="store_true")
    args = parser.parse_args()
    
    print_only = True if args.po else False
    serial_debug = True if args.sd else False
    verbose = True if args.verbose else False
    pool = args.pool if not (args.pool == None) else False
    serial_port = args.serial if not (args.serial == None) else '/dev/ttyAMA0'
    if (print_only and (serial_debug or not(args.serial == None))):
        raise ValueError('list_only conflicts with serial port arguments')

    # open serial port
    if not print_only:
        device = serial.Serial(serial_port, 115200, timeout=1)
        print('🔌Successfully open serial port', device.name)

    # init increses variable
    # get_price_change()
    # print('Initialized cryptocurrency price changes:')
    # for item in price_change:
    #     print(item, price_change[item])

    # create a schedular to get price change percent
    print('💹 Creating price change update schedular')
    schedular = background.BackgroundScheduler()
    schedular.add_job(get_price_change, 'interval', seconds=2, id='refresh_price_change')

    print('🌐 Creating global ETH mining status update schedular')
    schedular.add_job(update_network_status, 'interval', hours=24, id='refresh_eth')

    # create another schedular to update mining pool status
    if pool:
        print('⭐ Creating sparkpool update schedular')
        schedular.add_job(update_pool_status, 'interval', minutes=1, id='refresh_sparkpool')
    schedular.start()

    for job in schedular.get_jobs():
        print('Trigerring job', job.id, 'init run')
        job.modify(next_run_time=datetime.datetime.now())

    # establish websocket connection
    print('⛓ Establishing websocket connection\n')
    websocket.enableTrace(False)
    wsapp = websocket.WebSocketApp("wss://api.huobi.pro/ws", on_message=on_message, on_open=on_open)
    signal.signal(signal.SIGINT, sigint_handler)
    wsapp.run_forever(ping_timeout=5)
