from flask import Flask, render_template, request, jsonify, Response
from simon.srt_reservation import attempt_reservation
import threading
import queue
import os

app = Flask(__name__)

def get_config(key, default=None):
    return os.environ.get(key, default)

global messages, stop_reservation, output_queue
messages = []
stop_reservation = False
output_queue = queue.Queue()

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        sid = request.form['sid']
        spw = request.form['spw']
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
        bot_token = request.form.get('bot_token', '')
        chat_id = request.form.get('chat_id', '')

        thread = threading.Thread(target=attempt_reservation, args=(sid, spw, dep_station, arr_station, date, start_time, end_time, phone_number, enable_telegram, bot_token, chat_id))
        thread.start()

        return jsonify({'message': '예약 프로세스가 시작되었습니다.'})

    return render_template('index.html')

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
    port = int(get_config('PORT', 5000))
    app.run(host='0.0.0.0', port=port)