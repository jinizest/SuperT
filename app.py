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
import configparser
import io

app = Flask(__name__)

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
        logging.error(f"설정 파일을 찾을 수 없습니다: {config_file}")
        return default

global messages, stop_reservation, output_queue
messages = []
stop_reservation = False
output_queue = queue.Queue()

# 설정 값 가져오기
SRT_ID = get_config('srt_id', '')
SRT_PASSWORD = get_config('srt_password', '')
TELEGRAM_BOT_TOKEN = get_config('telegram_bot_token', '')
TELEGRAM_CHAT_ID = get_config('telegram_chat_id', '')
PHONE_NUMBER = get_config('phone_number', '')
DELAY = int(get_config('time_delay', '1'))

def send_telegram_message(bot_token, chat_id, message):
    if bot_token and chat_id:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": 'SRTrain Rev \n' + message + ' \n@' + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            logging.info("메시지가 성공적으로 전송되었습니다.")
        else:
            logging.error(f"메시지 전송에 실패했습니다. 상태 코드: {response.status_code}")

def attempt_reservation(sid, spw, dep_station, arr_station, date, time_start, time_end, phone_number, enable_telegram, bot_token, chat_id, num_adults, seat_type):
    global messages, stop_reservation
    error_cnt = 0
    while not stop_reservation:
        try:
            srt = SRT(sid, spw, verbose=False)
            trains = srt.search_train(dep_station, arr_station, date, time_start, time_end, available_only=False)
    
            while not stop_reservation:
                try:
                    message = '예약시도.....' + ' @' + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    logging.info(message)
                    output_queue.put(message)
                    time.sleep(DELAY)
    
                    if 'Expecting value' in str(trains):
                        message = 'Expecting value 오류'
                        logging.error(message)
                        output_queue.put(message)
                        messages.append(message)
                        if 'srt' in locals():#그래서 로그아웃 시도
                            srt.logout()
                        time.sleep(10)
                        srt = SRT(sid, spw, verbose=False)
                        trains = srt.search_train(dep_station, arr_station, date, time_start, time_end, available_only=False)
                        continue
    
                    for train in trains:
                        logging.info(str(train))
                        output_queue.put(str(train))
    
                    for train in trains:
                        if stop_reservation:
                            break
                        try:
                            passengers = [Adult() for _ in range(num_adults)] 
                            if "예약대기 가능" in str(train):
                                srt.reserve_standby(train)
                                srt.reserve_standby_option_settings(phone_number, True, True)
                                success_message = f"SRT 예약 대기 완료 {train}"
                            else:
                                srt.reserve(train, passengers=passengers, special_seat=seat_type)
                                success_message = f"SRT 예약 완료, !!결재 필요!! {train}"
                            
                            messages.append(success_message)
                            output_queue.put(success_message)
                            if enable_telegram:
                                send_telegram_message(bot_token, chat_id, success_message)
                            logging.info("예약 성공했지만 계속 진행합니다.")
                            error_cnt = 0 #성공 시 오류 카운트 초기
                            break
                        except Exception as e:
                            error_message = f"열차 {train}에 대한 오류 발생: {e}"
                            logging.error(error_message)
                            output_queue.put(error_message)
                            messages.append(error_message)
                            if '원활하지 않습니다' in str(e):
                                time.sleep(60) #원활하지 않다는 에러 이후, 5초내로 srt = SRT 하면 바로 IP 밴 error 발생
                                if 'srt' in locals(): #그래서 로그아웃 시도
                                    srt.logout()
                                    logging.error("로그아웃")
                                srt = SRT(sid, spw, verbose=False)
                                logging.error("로그인")
                                trains = srt.search_train(dep_station, arr_station, date, time_start, time_end, available_only=False)
                                continue              
                                
                            if 'Expecting value' in str(e):
                                message = 'Expecting value 오류'
                                logging.error(message)
                                output_queue.put(message)
                                messages.append(message)
                                time.sleep(60)
                                if 'srt' in locals():#그래서 로그아웃 시도
                                    srt.logout()
                                    logging.error("로그아웃")
                                srt = SRT(sid, spw, verbose=False)
                                logging.error("로그인")
                                trains = srt.search_train(dep_station, arr_station, date, time_start, time_end, available_only=False)
                                continue
    
                except Exception as e:
                    error_message = f"메인 루프에서 오류 발생: {e}"
                    logging.error(error_message)
                    output_queue.put(error_message)
                    messages.append(error_message)
                    if enable_telegram:
                        send_telegram_message(bot_token, chat_id, error_message)
                        
                except SRTLoginError as login_error:
                    logging.error(f"로그인 오류: {login_error}")
                    # 로그인 오류에 대한 특정 처리
                    if enable_telegram:
                        send_telegram_message(bot_token, chat_id, str(login_error))

            
                except SRTResponseError as response_error:
                    logging.error(f"SRT 응답 오류: {response_error}")
                    # SRT 응답 오류에 대한 특정 처리
                    if enable_telegram:
                        send_telegram_message(bot_token, chat_id, str(response_error))

                finally:            
                    if 'srt' in locals():
                        srt.logout()
                        logging.error("메인에러 로그아웃")
                    time.sleep(60)
                    srt = SRT(sid, spw, verbose=False)
                    logging.error("메인에러러 로그인")

    
        except Exception as main_e:
            critical_error = f"{error_cnt}심각한 오류 발생: {main_e}"
            logging.critical(critical_error)
            output_queue.put(critical_error)
            messages.append(critical_error)
            if enable_telegram:
                send_telegram_message(bot_token, chat_id, critical_error)
            time.sleep(60)            
            error_cnt += 1
            if error_cnt > 200:
                if enable_telegram:
                    send_telegram_message(bot_token, chat_id, "!!!심각한 오류 반복으로 MACRO 정지!!!")
                stop_reservation = True
        finally:            
            if 'srt' in locals():
                srt.logout()       
                logging.error("심각에러 로그아웃")
    return messages

reservation_thread = None

@app.route('/', methods=['GET', 'POST'])
def index():
    global reservation_thread, stop_reservation
    if request.method == 'POST':
        if reservation_thread and reservation_thread.is_alive():
            return jsonify({'message': '이미 예약 프로세스가 실행 중입니다.'})
        
        stop_reservation = False
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
        seat_type = 'GENERAL_FIRST'

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

@app.route('/stop', methods=['POST'])
def stop():
    global stop_reservation
    stop_reservation = True
    if 'srt' in globals():
        srt.logout()
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
    log_level = get_config('LOG_LEVEL', 'INFO').upper()
    logging.basicConfig(
        format='%(asctime)s.%(msecs)03d - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        level=getattr(logging, log_level)
    )
    logger = logging.getLogger(__name__)
    try:
        port = int(get_config('PORT', 5000))
        logger.info(f"Starting SRT application on port {port}")
        app.run(host='0.0.0.0', port=port)
    except Exception as e:
        logger.error(f"Error starting application: {e}")
    while True:
        time.sleep(30)
