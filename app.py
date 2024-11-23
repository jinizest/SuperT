from flask import Flask, render_template, request, jsonify, Response
from SRT import SRT
import requests
from datetime import datetime
import time
import threading
import queue
import os
import logging

app = Flask(__name__)

def get_config(key, default=None):
    return os.environ.get(key, default)

global messages, stop_reservation, output_queue
messages = []
stop_reservation = False
output_queue = queue.Queue()

# 환경 변수에서 설정 값 가져오기
SRT_ID = get_config('SRT_ID', '')
SRT_PASSWORD = get_config('SRT_PASSWORD', '')
TELEGRAM_BOT_TOKEN = get_config('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = get_config('TELEGRAM_CHAT_ID', '')
PHONE_NUMBER = get_config('PHONE_NUMBER', '')

def send_telegram_message(bot_token, chat_id, message):
    if bot_token and chat_id:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": 'SRTrain Rev \n' + message + ' \n@' + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        response = requests.post(url, data=payload)
        if response.status_code == 200:
            print("메시지가 성공적으로 전송되었습니다.")
        else:
            print("메시지 전송에 실패했습니다. 상태 코드:", response.status_code)

def attempt_reservation(sid, spw, dep_station, arr_station, date, time_start, time_end, phone_number, enable_telegram, bot_token, chat_id):
    global messages, stop_reservation
    
    while not stop_reservation:
        try:
            srt = SRT(sid, spw, verbose=False)
            
            while not stop_reservation:
                try:
                    message = '예약시도.....' + ' @' + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    print(message)
                    output_queue.put(message)
                    time.sleep(2)

                    # 기차 검색
                    trains = srt.search_train(dep_station, arr_station, date, time_start, time_end, available_only=False)
                    if 'Expecting value' in str(trains):
                        message = 'Expecting value 오류'
                        print(message)
                        output_queue.put(message)
                        messages.append(message)
                        continue
                    
                    for train in trains:
                        if stop_reservation:
                            break
                        try:
                            # 대기 예약 시도
                            srt.reserve_standby(train)
                            srt.reserve_standby_option_settings(phone_number, True, True)
                            success_message = f"SRT 예약 대기 완료 {train}"
                            messages.append(success_message)
                            output_queue.put(success_message)
                            
                            if enable_telegram:
                                send_telegram_message(bot_token, chat_id, success_message)
                            
                            # 예약 성공 후에도 계속 진행
                            print("예약 성공했지만 계속 진행합니다.")
                            break  # 현재 검색된 열차에 대한 루프만 종료
                        
                        except Exception as e:
                            error_message = f"열차 {train}에 대한 오류 발생: {e}"
                            print(error_message)
                            output_queue.put(error_message)
                            messages.append(error_message)

                except Exception as e:
                    error_message = f"메인 루프에서 오류 발생: {e}"
                    print(error_message)
                    output_queue.put(error_message)
                    messages.append(error_message)
                    
                    if '사용자가 많아 접속이 원활하지 않습니다.' in str(e):
                        time.sleep(5)  # 서버 과부하로 인한 재시도
                        srt = SRT(sid, spw, verbose=False)
                        continue  # while 루프 재시작
                    
                    if enable_telegram:
                        send_telegram_message(bot_token, chat_id, error_message)
                    
                    time.sleep(5)
                    srt = SRT(sid, spw, verbose=False)

        except Exception as main_e:
            # 가장 바깥의 루프에서 예외 발생 시 처리
            critical_error = f"심각한 오류 발생: {main_e}"
            print(critical_error)
            output_queue.put(critical_error)
            messages.append(critical_error)
            
            if enable_telegram:
                send_telegram_message(bot_token, chat_id, critical_error)
            
            time.sleep(30)  # 다시 시도하기 전에 충분히 기다림
            srt = SRT(sid, spw, verbose=True)

    return messages

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        sid = request.form.get('sid', SRT_ID)
        spw = request.form.get('spw', SRT_PASSWORD)
        dep_station = request.form['dep_station']
        arr_station = request.form['arr_station']
      
        # '직접입력'이 선택된 경우 사용자가 입력한 값을 사용
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

        # 스레드로 예약 함수 실행
        thread = threading.Thread(target=attempt_reservation, args=(sid, spw, dep_station, arr_station, date, start_time, end_time, phone_number, enable_telegram, bot_token, chat_id))
        thread.start()

        return jsonify({'message': '예약 프로세스가 시작되었습니다.'})

    # GET 요청 처리
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
    return jsonify({'message': '예약 프로세스가 중단되었습니다.'})

@app.route('/stream')
def stream():
    def generate():
        while True:
            try:
                message = output_queue.get(timeout=1)
                yield f"data: {message}\n\n"
            except queue.Empty:
                pass

    return Response(generate(), mimetype='text/event-stream')

if __name__ == '__main__':
    logging.basicConfig(format='%(levelname)s[%(asctime)s]:%(message)s ', level=logging.DEBUG)
    logger = logging.getLogger(__name__)
    
    try:
        port = int(get_config('PORT', 5000))
        logger.info(f"Starting SRT application on port {port}")
        app.run(host='0.0.0.0', port=port)
    except Exception as e:
        logger.error(f"Error starting application: {e}")
    
    # 애드온이 계속 실행되도록 유지
    while True:
        time.sleep(30)
