
from flask import Flask, render_template, request, jsonify, Response
from SRT.passenger import Adult
from SRT import SRT, SeatType
import requests
from datetime import datetime
import time
import threading
import queue
import os
import logging
import logging.handlers
import configparser
import io
import random
from typing import Dict

__version__ = "1.4.6"

app = Flask(__name__)


# Log 폴더 생성 (도커 실행 시 로그폴더 매핑)
def make_folder(folder_name):
    if not os.path.isdir(folder_name):
        os.mkdir(folder_name)
root_dir = str(os.path.dirname(os.path.realpath(__file__)))
log_dir = root_dir + '/log/'
make_folder(log_dir)
logfile = 'srtapp.log'
log_path = str(log_dir + '/' + logfile)




def get_config(key, default=None):
    config = configparser.ConfigParser()
    config_file = '/share/srt/app.conf'
    if os.path.exists(config_file):
        config.read(config_file)
        try:
            return config.get('DEFAULT', key)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return default
    else:
        logger.error(f"설정 파일을 찾을 수 없습니다: {config_file}")
        return default

global messages, output_queue
messages = []
output_queue = queue.Queue()
stop_event = threading.Event()
current_srt = None
current_srt_lock = threading.Lock()

# 설정 값 가져오기
SRT_ID = get_config('srt_id', '')
SRT_PASSWORD = get_config('srt_password', '')
TELEGRAM_BOT_TOKEN = get_config('telegram_bot_token', '')
TELEGRAM_CHAT_ID = get_config('telegram_chat_id', '')
PHONE_NUMBER = get_config('phone_number', '')
DELAY = int(get_config('time_delay', '1'))
TELEGRAM_ERROR_COOLDOWN = int(get_config('telegram_error_cooldown', '600'))
ERROR_BACKOFF_BASE = int(get_config('error_backoff_base', '5'))
ERROR_BACKOFF_MAX = int(get_config('error_backoff_max', '120'))

NETFUNNEL_ALERT_EVERY = int(get_config('netfunnel_alert_every', '10'))
netfunnel_alert_counter = 0
last_telegram_error_sent: Dict[str, float] = {}

def is_transient_service_error(message):
    return "서비스가 접속이 원활하지 않습니다" in message

def is_netfunnel_error(message):
    return "NetFunnel" in message or "Wrong Server ID" in message

def is_connection_error(message):
    return "Connection aborted" in message or "RemoteDisconnected" in message or "ConnectionError" in message

def categorize_error(message):
    if is_netfunnel_error(message):
        return "netfunnel"
    if is_transient_service_error(message):
        return "service_unavailable"
    if is_connection_error(message):
        return "connection"
    if "Expecting value" in message:
        return "expecting_value"
    return "generic"

def should_send_error_telegram(message):
    category = categorize_error(message)
    if category == "netfunnel":
        global netfunnel_alert_counter
        netfunnel_alert_counter += 1
        if netfunnel_alert_counter % max(1, NETFUNNEL_ALERT_EVERY) != 0:
            return False
    now = time.time()
    last_sent = last_telegram_error_sent.get(category, 0)
    if now - last_sent < TELEGRAM_ERROR_COOLDOWN:
        return False
    last_telegram_error_sent[category] = now
    return True

def calculate_backoff(failure_count):
    base = min(ERROR_BACKOFF_MAX, ERROR_BACKOFF_BASE * max(1, failure_count))
    jitter = random.randint(0, 3)
    return min(ERROR_BACKOFF_MAX, base + jitter)

def send_telegram_message(bot_token, chat_id, message):
    if bot_token and chat_id:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": 'SRTrain Rev \n' + message + ' \n@' + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            logger.info("메시지가 성공적으로 전송되었습니다.")
        else:
            logger.error(f"메시지 전송에 실패했습니다. 상태 코드: {response.status_code}")

class StopReservation(Exception):
    pass

def wait_or_stop(seconds):
    if stop_event.wait(seconds):
        raise StopReservation

def stop_if_requested():
    if stop_event.is_set():
        raise StopReservation

def set_current_srt(instance):
    global current_srt
    with current_srt_lock:
        current_srt = instance

def clear_current_srt():
    global current_srt
    with current_srt_lock:
        current_srt = None

def attempt_reservation(sid, spw, dep_station, arr_station, date, time_start, time_end, phone_number, enable_telegram, bot_token, chat_id, num_adults, seat_type):
    er_cnt = 0
    netfunnel_failures = 0
    service_failures = 0
    global messages
    try: #매크로 종료 알림림
        while True:
            stop_if_requested()
            try:
                srt = SRT(sid, spw, verbose=False)
                set_current_srt(srt)
                wait_or_stop(0.5)
                while True:
                    stop_if_requested()
                    try:
                        message = '예약시도.....' + ' @' + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        trains = srt.search_train(dep_station, arr_station, date, time_start, time_end, available_only=False)
                        netfunnel_failures = 0
                        service_failures = 0
                        logger.info(message)
                        output_queue.put(message)
                        wait_or_stop(DELAY)
        
                        if 'Expecting value' in str(trains):
                            message = 'Expecting value 오류'
                            logger.error(message)
                            output_queue.put(message)
                            messages.append(message)
                            continue
        
                        for train in trains:
                            logger.info(str(train))
                            output_queue.put(str(train))
        
                        retry_search = False
                        for train in trains:                            
                            stop_if_requested()
                            try:
                                passengers = [Adult() for _ in range(num_adults)] 

                                if "예약가능" in str(train):
                                    srt.reserve(train, passengers=passengers, special_seat=seat_type)
                                    success_message = f"SRT 예약 완료, !!결재 필요!! {train}"
                                # if "예약대기 가능" in str(train): #동탄~수서(16:20~16:37) 특실 예약가능, 일반실 예약가능, 예약대기 불가능:
                                srt.reserve_standby_option_settings(phone_number, True, True)
                                srt.reserve_standby(train)                        
                                success_message = f"SRT 예약 대기 완료 {train}"
                                # else:
                                #     continue
    
                                messages.append(success_message)
                                output_queue.put(success_message)
                                
                                if enable_telegram:
                                    send_telegram_message(bot_token, chat_id, success_message)
                                logger.info("예약 성공했지만 계속 진행합니다.")
                                netfunnel_failures = 0
                                service_failures = 0
                                er_cnt = 0 #에러 카운트 리셋
                                continue #열차 여러개인데 첫번쨰 열차가 성공해도 두번쨰 세번째도 진행하도록
                            except StopReservation:
                                raise
                            except Exception as e:
                                error_message = f"열차 {train}에 대한 오류 발생: {e}"
                                logger.error(error_message)
                                output_queue.put(error_message)
                                messages.append(error_message)

                                if is_netfunnel_error(str(e)) or is_transient_service_error(str(e)):
                                    if is_netfunnel_error(str(e)):
                                        netfunnel_failures += 1
                                    if is_transient_service_error(str(e)):
                                        service_failures += 1
                                    backoff = calculate_backoff(max(netfunnel_failures, service_failures))
                                    logger.warning(f"일시적 오류 감지: {e} - {backoff}초 대기 후 재시도합니다.")
                                    if 'srt' in locals() and srt is not None:
                                        srt.logout()
                                        del srt
                                    wait_or_stop(backoff)
                                    srt = SRT(sid, spw, verbose=False)
                                    set_current_srt(srt)
                                    wait_or_stop(0.5)
                                    retry_search = True
                                    break

                                if 'Expecting value' in str(e):
                                    message = 'Expecting value 오류'
                                    logger.error(message)
                                    output_queue.put(message)
                                    messages.append(message)
                                    wait_or_stop(5) #5초 대기하고
                                    if 'srt' in locals() and srt is not None: #로그아웃하고 로그인하게 하기
                                        srt.logout()
                                        logger.error("SRT LOGOUT")
                                        del srt
                                    clear_current_srt()
                                    srt = None
                                    wait_or_stop(3) # 로그인 하면 ip 밴이라 그 전에 3초 대기기
                                    logger.error("SRT객체생성시도")
                                    srt = SRT(sid, spw, verbose=False) #로그인까지 새롭게
                                    set_current_srt(srt)
                                    wait_or_stop(0.5)
                                    trains = srt.search_train(dep_station, arr_station, date, time_start, time_end, available_only=False)#expecting에서 trains 바로 하면 또 expecting
                                if "서비스가 접속이 원활하지 않습니다" in str(e):
                                    wait_or_stop(30) #잠시 대기

                            wait_or_stop(0.5) #for문 train 사이사이 딜레이 두기
                        if retry_search:
                            continue
                                
    
        
                    except StopReservation:
                        raise
                    except Exception as e:
                        error_message = f"메인 루프에서 오류 발생: {e}"
                        logger.error(error_message)
                        output_queue.put(error_message)
                        messages.append(error_message)
                        if is_connection_error(str(e)):
                            backoff = calculate_backoff(max(1, er_cnt))
                            logger.warning(f"연결 오류 감지: {e} - {backoff}초 대기 후 재시도합니다.")
                            if 'srt' in locals() and srt is not None:
                                srt.logout()
                                del srt
                            clear_current_srt()
                            wait_or_stop(backoff)
                            srt = SRT(sid, spw, verbose=False)
                            set_current_srt(srt)
                            continue
                        if is_netfunnel_error(str(e)):
                            netfunnel_failures += 1
                            backoff = calculate_backoff(netfunnel_failures)
                            logger.warning(f"NetFunnel 오류 감지: {e} - {backoff}초 대기 후 재시도합니다.")
                            if 'srt' in locals() and srt is not None:
                                srt.logout()
                                del srt
                            clear_current_srt()
                            wait_or_stop(backoff)
                            srt = SRT(sid, spw, verbose=False)
                            set_current_srt(srt)
                            continue
                        if is_transient_service_error(str(e)):
                            service_failures += 1
                            backoff = calculate_backoff(service_failures)
                            logger.warning(f"접속 불안정 오류 감지: {e} - {backoff}초 대기 후 재시도합니다.")
                            if 'srt' in locals() and srt is not None:
                                srt.logout()
                                del srt
                            clear_current_srt()
                            wait_or_stop(backoff)
                            srt = SRT(sid, spw, verbose=False)
                            set_current_srt(srt)
                            continue
                        if '사용자가 많아 접속이 원활하지 않습니다.' in str(e):
                            wait_or_stop(5)
                            srt = SRT(sid, spw, verbose=False)
                            set_current_srt(srt)
                            continue
                        if 'Expecting value' in str(e):
                            message = 'Expecting value 오류'
                            logger.error(message)
                            wait_or_stop(10) #10초 대기하고
                            if 'srt' in locals() and srt is not None: #로그아웃하고 로그인하게 하기
                                srt.logout()
                                logger.error("SRT LOGOUT")
                                del srt
                            clear_current_srt()
                            srt = None
                            logger.error("SRT객체생성시도")
                            srt = SRT(sid, spw, verbose=False) #로그인까지 새롭게
                            set_current_srt(srt)
                            wait_or_stop(0.5)
                            # trains = srt.search_train(dep_station, arr_station, date, time_start, time_end, available_only=False)#expecting에서 trains 바로 하면 또 expecting
                            continue
                            
                        if enable_telegram and should_send_error_telegram(error_message):
                            send_telegram_message(bot_token, chat_id, error_message)
                        wait_or_stop(5)
                        srt = SRT(sid, spw, verbose=False)
                        set_current_srt(srt)
        
            except StopReservation:
                raise
            except Exception as main_e:
                er_cnt += 1
                critical_error = f"{er_cnt}번째 심각한 오류 발생: {main_e}"
                logger.critical(critical_error)
                output_queue.put(critical_error)
                messages.append(critical_error)
                if enable_telegram and should_send_error_telegram(critical_error):
                    send_telegram_message(bot_token, chat_id, critical_error)
                if is_connection_error(str(main_e)):
                    backoff = calculate_backoff(er_cnt)
                    logger.warning(f"심각한 연결 오류 감지: {main_e} - {backoff}초 대기 후 재시도합니다.")
                    if 'srt' in locals() and srt is not None:
                        srt.logout()
                        del srt
                    clear_current_srt()
                    wait_or_stop(backoff)
                    continue
                if 'IP Address Blocked' in str(main_e):
                    message = 'IP Address Blocked'
                    logger.error(message)
                    delay = 50 + random.randint(1,20) #+ (er_cnt*5) #그냥 delay 60초 + 랜덤으로 고정~
                    wait_or_stop(delay)
                    if 'srt' in locals() and srt is not None: #로그아웃하고 로그인하게 하기
                        srt.logout()
                        logger.error("SRT LOGOUT")
                        del srt
                    clear_current_srt()
                    
                    continue
                    
                wait_or_stop(30)
            finally:
                if 'srt' in locals() and srt is not None:
                    srt.logout()
                    del srt
                clear_current_srt()
                srt = None
            continue
    except StopReservation:
        logger.info("예약 중단 요청이 감지되어 프로세스를 종료합니다.")
    except Exception as shut_e: #attempt 함수 종료되면 알림
        shut_error = f"!!!MACRO 정지!!!확인필요!!!: {shut_e}"
        logger.error(shut_error)
        if enable_telegram:
            send_telegram_message(bot_token, chat_id, shut_error)
    finally:
        global reservation_thread
        reservation_thread = None

reservation_thread = None

@app.route('/', methods=['GET', 'POST'])
def index():
    global reservation_thread
    if request.method == 'POST':
        if reservation_thread and reservation_thread.is_alive():
            return jsonify({'message': '이미 예약 프로세스가 실행 중입니다.'})
        
        stop_event.clear()
        sid = request.form.get('sid', SRT_ID)
        spw = request.form.get('spw', SRT_PASSWORD)
        dep_station = request.form['dep_station']
        arr_station = request.form['arr_station']
        if dep_station == "direct":
            dep_station = request.form['customDepStation']
        if arr_station == "direct":
            arr_station = request.form['customArrStation']
        date = request.form['date'].replace("-", "")
        start_time = f"{request.form['start_hour']}{request.form['start_minute']}00"
        end_time = f"{request.form['end_hour']}{request.form['end_minute']}00"
        phone_number = f"{request.form['phone_part1']}-{request.form['phone_part2']}-{request.form['phone_part3']}"
        enable_telegram = 'enable_telegram' in request.form
        bot_token = request.form.get('bot_token', TELEGRAM_BOT_TOKEN)
        chat_id = request.form.get('chat_id', TELEGRAM_CHAT_ID)
        
        # 새로운 입력 필드 추가
        num_adults = int(request.form.get('num_adults', 1))
        seat_type = request.form.get('seat_type', 'GENERAL_FIRST')

        reservation_thread = threading.Thread(target=attempt_reservation, args=(sid, spw, dep_station, arr_station, date, start_time, end_time, phone_number, enable_telegram, bot_token, chat_id, num_adults, seat_type))
        reservation_thread.start()
        return jsonify({'message': '예약 프로세스가 시작되었습니다.'})

    default_values = {
        'srt_id': SRT_ID,
        'srt_password': SRT_PASSWORD,
        'telegram_bot_token': TELEGRAM_BOT_TOKEN,
        'telegram_chat_id': TELEGRAM_CHAT_ID,
        'phone_number': PHONE_NUMBER
    }
    return render_template('index.html', **default_values)

@app.route('/status', methods=['GET'])
def status():
    is_running = reservation_thread is not None and reservation_thread.is_alive()
    return jsonify({
        'running': is_running,
        'stop_requested': stop_event.is_set()
    })

@app.route('/stop', methods=['POST'])
def stop():
    global reservation_thread
    stop_event.set()
    with current_srt_lock:
        if current_srt is not None:
            try:
                current_srt.logout()
            except Exception as e:
                logger.warning(f"중단 중 로그아웃 실패: {e}")
    if reservation_thread and reservation_thread.is_alive():
        reservation_thread.join(timeout=5)
    if reservation_thread and not reservation_thread.is_alive():
        reservation_thread = None
    return jsonify({'message': '예약 프로세스가 중단되었습니다.'})

@app.route('/stream') #241125 실시간 로깅 필요하긴한데... 그냥 써도 무관할듯~
def stream(): 
    def generate():
        log_stream = io.StringIO()
        handler = logging.StreamHandler(log_stream)
        formatter = logging.Formatter('%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
        handler.setFormatter(formatter)
        logging.getLogger().addHandler(handler)
        last_timestamp = datetime.now()

        while True:
            log_stream.seek(0)
            log_content = log_stream.read()
            log_stream.truncate(0)
            log_stream.seek(0)

            if log_content:
                log_lines = log_content.strip().split('\n')
                new_logs = []
                for line in log_lines:
                    try:
                        timestamp_str = line.split(' - ')[0]
                        timestamp = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S.%f')
                        if timestamp > last_timestamp:
                            new_logs.append(line)
                            last_timestamp = timestamp
                    except (ValueError, IndexError):
                        continue  # 잘못된 형식의 로그 라인은 무시

                if new_logs:
                    new_logs.reverse()
                    newline = '\n'
                    yield f"data: {newline.join(new_logs)}\n\n"
            else:
                time.sleep(0.1)  # 0.1초마다 확인

    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    
    #logger 인스턴스 생성 및 로그레벨 설정
    logger = logging.getLogger('app')
    logger.setLevel(logging.INFO)
    
    # formatter 생성
    logFormatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s : Line %(lineno)s - %(message)s')
    
    # fileHandler, StreamHandler 생성
    file_max_bytes = 10 * 1024 * 1024 # 10 MB 사이즈
    logFileHandler = logging.handlers.RotatingFileHandler(filename=log_path, maxBytes=file_max_bytes, backupCount=20, encoding='utf-8')
    logStreamHandler = logging.StreamHandler()
    
    # handler 에 formatter 설정
    logFileHandler.setFormatter(logFormatter)
    logStreamHandler.setFormatter(logFormatter)
    logFileHandler.suffix = "%Y%m%d"
    
    logger.addHandler(logFileHandler)
    logger.addHandler(logStreamHandler)
    
    try:
        port = int(get_config('PORT', 5000))
        logger.info(f"Starting SRT application ver {__version__} on port {port}")
        app.run(host='0.0.0.0', port=port)
    except Exception as e:
        logger.error(f"Error starting application: {e}")
    while True:
        time.sleep(30)
