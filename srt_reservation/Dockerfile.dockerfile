ARG BUILD_FROM
FROM $BUILD_FROM

# 필요한 패키지 설치
RUN apk add --no-cache python3 py3-pip

# 작업 디렉토리 설정
WORKDIR /app

# 필요한 Python 패키지 설치
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# 애플리케이션 파일 복사
COPY . .

# 실행 권한 부여
RUN chmod a+x run.sh

# 실행 명령 설정
CMD [ "/app/run.sh" ]