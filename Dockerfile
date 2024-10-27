FROM python:3.7.3

ENV LANG C.UTF-8

# 작업 디렉토리 설정
WORKDIR /share

# pip 업그레이드
RUN pip3 install --upgrade pip

# 필요한 Python 패키지 설치
COPY requirements.txt .
RUN pip3 install -r requirements.txt

# 애플리케이션 파일 복사
COPY . .

# 실행 권한 부여
RUN chmod a+x run.sh

# 실행 명령 설정
CMD [ "/share/run.sh" ]