import requests
from datetime import datetime

def send_telegram_message(bot_token, chat_id, message):
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