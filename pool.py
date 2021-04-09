import requests
from apscheduler.schedulers import background
import serial
from main import send_serial
from pprint import pprint

serial_port = 'COM3'
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

def serial_pool_command_generator(content):
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

if __name__ == "__main__":
    device = serial.Serial(serial_port, 115200, timeout=1)
    pool_status = get_pool_status('sp_chowdpa02k')
    # pprint(pool_status)
    commands = serial_pool_command_generator(pool_status)
    # pprint(commands)
    send_serial(device, commands)