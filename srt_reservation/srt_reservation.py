from SRT import SRT
from simon.telegram_utils import send_telegram_message
from datetime import datetime
import time
import queue

global messages, stop_reservation, output_queue
messages = []
stop_reservation = False
output_queue = queue.Queue()

def attempt_reservation(sid, spw, dep_station, arr_station, date, time_start, time_end, phone_number, enable_telegram, bot_token, chat_id):
    global messages, stop_reservation, output_queue
    
    while not stop_reservation:
        try:
            srt = SRT(sid, spw, verbose=False)
            
            while not stop_reservation:
                try:
                    message = '예약시도.....' + ' @' + datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    print(message)
                    output_queue.put(message)
                    time.sleep(2)

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
                            srt.reserve_standby(train)
                            srt.reserve_standby_option_settings(phone_number, True, True)
                            success_message = f"SRT 예약 대기 완료 {train}"
                            messages.append(success_message)
                            output_queue.put(success_message)
                            
                            if enable_telegram:
                                send_telegram_message(bot_token, chat_id, success_message)
                            
                            print("예약 성공했지만 계속 진행합니다.")
                            break
                        
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
                        time.sleep(5)
                        srt = SRT(sid, spw, verbose=False)
                        continue
                    
                    if enable_telegram:
                        send_telegram_message(bot_token, chat_id, error_message)
                    
                    time.sleep(5)
                    srt = SRT(sid, spw, verbose=False)

        except Exception as main_e:
            critical_error = f"심각한 오류 발생: {main_e}"
            print(critical_error)
            output_queue.put(critical_error)
            messages.append(critical_error)
            
            if enable_telegram:
                send_telegram_message(bot_token, chat_id, critical_error)
            
            time.sleep(30)
            srt = SRT(sid, spw, verbose=True)

    return messages